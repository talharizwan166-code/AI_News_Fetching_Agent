import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from unittest.mock import Mock

import pytest

from chatcheck.cli import main
from chatcheck.connectors import Connector, ConnectorError
from chatcheck.monitor import cycle, detect, load_config, metrics
from chatcheck.monitor_alerts import deliver, send_email, send_slack
from chatcheck.monitor_monthly import monthly, trend
from chatcheck.monitor_store import readonly_storage, register_artifact
from chatcheck.storage import Storage

DATE = datetime(2026, 9, 1, 0, 15, tzinfo=timezone.utc)


class FakeConnector(Connector):
    def __init__(self, replies, *, startup_error=False):
        self.replies = iter(replies)
        self.calls = self.starts = 0
        self.startup_error = startup_error

    async def __aenter__(self):
        self.starts += 1
        if self.startup_error:
            raise RuntimeError("provider diagnostic must not be stored")
        return self

    async def send(self, prompt):
        self.calls += 1
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def settings(tmp_path):
    (tmp_path / "suite.json").write_text(json.dumps({"tests": [
        {"id": "critical", "prompt": "hi", "checks": [{"type": "equals", "value": "safe"}], "severity": "critical"},
        {"id": "normal", "prompt": "hello", "checks": [{"type": "equals", "value": "safe"}], "severity": "low"}
    ]}))
    (tmp_path / "target.json").write_text(json.dumps({"type": "http", "url": "http://127.0.0.1:1/chat",
                                                   "runner": {"concurrency": 1, "retries": 0, "retry_backoff": 0}}))
    config = {"client_id": "client", "target_id": "bot", "target": "target.json", "suites": ["suite.json"],
              "schedule": {"description": "Daily", "interval_minutes": 1440}, "score_drop_threshold": 5,
              "error_rate_threshold": 10, "recipients": ["owner@example.invalid"], "channels": [],
              "call_budget": 10, "reports_dir": "reports"}
    path = tmp_path / "monitor.json"
    path.write_text(json.dumps(config))
    return load_config(path), tmp_path / "monitor.db", path


def run(settings, replies, day=0, **kwargs):
    config, db, _ = settings
    connector = FakeConnector(replies)
    result = asyncio.run(cycle(config, db, clock=lambda: DATE + timedelta(days=day),
                               connector_factory=lambda target: connector, **kwargs))
    with Storage(db) as storage:
        saved = storage.results(result["run_id"])
    return result, saved, connector


def test_score_critical_and_idempotence(settings):
    before, old, _ = run(settings, ["safe", "safe"])
    result, new, connector = run(settings, ["unsafe", "safe"], 1)
    assert set(result["reasons"]) == {"response_score_drop", "new_critical_failure"}
    assert result["score_drop"] == 50 and result["critical"] == ["s1:critical"]
    config, db, _ = settings
    again = asyncio.run(cycle(config, db, clock=lambda: DATE + timedelta(days=1),
                              connector_factory=lambda _: pytest.fail("duplicate cycle called target")))
    assert again["status"] == "already_claimed" and again["run_id"] == result["run_id"]
    assert connector.calls == 2
    decision = detect(new, old, score_drop_threshold=50, error_rate_threshold=100)
    assert "response_score_drop" not in decision["reasons"]  # strictly more than


def test_availability_is_never_new_critical_model_failure(settings):
    run(settings, ["safe", "safe"])
    result, saved, _ = run(settings, [ConnectorError("offline"), "safe"], 1)
    assert result["reasons"] == ["availability"]
    assert result["metrics"]["score"] == 100
    assert result["metrics"]["availability"] == 50
    assert not result["newly_failing"] and not result["critical"]
    recovered, _, _ = run(settings, ["unsafe", "safe"], 2)
    assert not recovered["critical"]  # Previous error was not a passing model answer.


def test_all_errors_have_no_model_score(settings):
    result, saved, _ = run(settings, [ConnectorError("down"), ConnectorError("down")])
    assert result["metrics"]["score"] is None
    assert result["metrics"]["availability"] == 0
    assert result["reasons"] == ["availability"]


@pytest.mark.parametrize("budget", [0, 1])
def test_budget_stops_cleanly_without_false_errors(settings, budget):
    config, db, _ = settings
    config["call_budget"] = budget
    result, saved, connector = run(settings, ["safe", "safe"])
    assert connector.calls == budget
    assert connector.starts == bool(budget)
    assert result["budget_stopped"] and result["metrics"]["errors"] == 0
    assert saved["summary"]["failed"] == 0
    assert result["metrics"]["not_attempted"] == 2 - budget


def test_cost_reservation_includes_failed_attempts_and_retries(settings):
    config, db, _ = settings
    target = json.loads(Path(config["target"]).read_text())
    target["runner"]["retries"] = 3
    Path(config["target"]).write_text(json.dumps(target))
    config.update(cost_per_call=0.1, max_cost=0.2)
    result, saved, connector = run(settings, [ConnectorError("down", retryable=True)] * 4)
    assert connector.calls == 2 and result["budget_stopped"]
    assert result["metrics"]["errors"] == 1 and result["metrics"]["not_attempted"] == 1
    with Storage(db) as storage:
        row = storage.connection.execute("SELECT calls, reserved_cost FROM monitor_cycles").fetchone()
        assert tuple(row) == (2, 0.2)


def test_changed_definitions_do_not_create_score_drop_or_critical_alert(settings):
    run(settings, ["safe", "safe"])
    path = Path(settings[0]["suites"][0])
    data = json.loads(path.read_text())
    for test in data["tests"]:
        test["checks"] = [{"type": "equals", "value": "different"}]
    path.write_text(json.dumps(data))
    result, _, _ = run(settings, ["safe", "safe"], 1)
    assert result["definition_changes"] and not result["reasons"]


def test_startup_error_is_availability_without_diagnostics(settings):
    config, db, _ = settings
    fake = FakeConnector([], startup_error=True)
    result = asyncio.run(cycle(config, db, clock=lambda: DATE, connector_factory=lambda _: fake))
    assert result["reasons"] == ["availability"] and result["metrics"]["score"] is None
    assert b"provider diagnostic" not in db.read_bytes()


def test_concurrent_duplicate_claim(settings):
    config, db, _ = settings
    fake = FakeConnector(["safe", "safe"])
    async def both():
        return await asyncio.gather(*(cycle(config, db, clock=lambda: DATE, connector_factory=lambda _: fake) for _ in range(2)))
    results = asyncio.run(both())
    assert sorted(r["status"] for r in results) == ["already_claimed", "completed"]
    assert fake.calls == 2


def test_running_cycle_blocks_later_slot(settings):
    result, _, _ = run(settings, ["safe", "safe"])
    config, db, _ = settings
    with Storage(db) as storage, storage.connection:
        storage.connection.execute("UPDATE monitor_cycles SET status='running'")
    blocked = asyncio.run(cycle(config, db, clock=lambda: DATE + timedelta(days=1),
                                connector_factory=lambda _: pytest.fail("overlapping run")))
    assert blocked["status"] == "already_claimed"


def test_secrets_redacted_before_database_report_and_alert(settings, monkeypatch, capsys):
    secret = "synthetic-private-value-123"
    monkeypatch.setenv("CLIENT_SECRET", secret)
    config, db, _ = settings
    config["channels"] = ["email", "slack"]
    run(settings, ["safe", "safe"], dry_run=True)
    result, _, _ = run(settings, [secret, "safe"], 1, dry_run=True)
    output = capsys.readouterr().out
    assert "DRY RUN" in output and secret not in output
    assert "unsafe" not in output  # no response snippets
    assert secret.encode() not in db.read_bytes()
    html = Path(result["report"]).read_text(encoding="utf-8")
    assert secret not in html and "REDACTED" in html
    assert result["alerts"] == {"email": "dry_run", "slack": "dry_run"}


def test_fake_smtp_transport(monkeypatch):
    monkeypatch.setenv("CHATCHECK_SMTP_HOST", "smtp.example.invalid")
    monkeypatch.setenv("CHATCHECK_SMTP_FROM", "sender@example.invalid")
    monkeypatch.setenv("CHATCHECK_SMTP_USER", "synthetic-user")
    monkeypatch.setenv("CHATCHECK_SMTP_PASSWORD", "synthetic-password")
    smtp = Mock()
    context = Mock()
    context.__enter__ = Mock(return_value=smtp)
    context.__exit__ = Mock(return_value=None)
    factory = Mock(return_value=context)
    monkeypatch.setattr("chatcheck.monitor_alerts.smtplib.SMTP", factory)
    send_email(["owner@example.invalid"], "Short alert, no responses")
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("synthetic-user", "synthetic-password")
    message = smtp.send_message.call_args.args[0]
    assert "synthetic-password" not in message.as_string()
    assert smtp.send_message.call_args.kwargs["to_addrs"] == ["owner@example.invalid"]


def test_fake_slack_transport(monkeypatch):
    import httpx
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200)
    original = httpx.Client
    monkeypatch.setenv("CHATCHECK_SLACK_WEBHOOK", "https://hooks.example.invalid/synthetic")
    monkeypatch.setattr("chatcheck.monitor_alerts.httpx.Client", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    send_slack("Short alert")
    assert requests == [{"text": "Short alert"}]


def test_alert_attempt_is_not_repeated_after_uncertain_delivery(settings, monkeypatch):
    result, _, _ = run(settings, ["safe", "safe"])
    config, db, _ = settings
    config["channels"] = ["email", "slack"]
    sender = Mock(side_effect=RuntimeError("synthetic confidential provider diagnostic"))
    monkeypatch.setattr("chatcheck.monitor_alerts.send_email", sender)
    monkeypatch.setattr("chatcheck.monitor_alerts.send_slack", lambda _: None)
    with Storage(db) as storage:
        assert deliver(storage, result["cycle_id"], config, "summary") == {"email": "failed", "slack": "sent"}
        assert deliver(storage, result["cycle_id"], config, "summary") == {"email": "already_attempted", "slack": "already_attempted"}
    assert sender.call_count == 1 and b"confidential provider" not in db.read_bytes()


def test_monthly_content_and_idempotence(settings):
    first, _, _ = run(settings, ["safe", "safe"])
    run(settings, ["wrong", ConnectorError("down")], 8)
    last, _, _ = run(settings, ["safe", "safe"], 15)
    config, db, _ = settings
    result = monthly(config, db, month="2026-09")
    summary = result["monthly"]
    assert summary["runs"] == 3 and len(summary["weeks"]) == 5
    assert summary["weeks"][-1]["score"] is None
    assert summary["newly_failing"] == summary["newly_fixed"] == ["s1:critical"]
    assert summary["score"] == 80 and summary["availability"] == 83.3
    html = Path(result["report"]).read_text(encoding="utf-8")
    assert "MONTHLY MONITORING" in html and "Newly fixed tests" in html and "2026-09-07" in html
    assert "Full appendix" not in html
    assert monthly(config, db, month="2026-09")["status"] == "already_created"
    assert monthly(config, db, month="2025-01")["status"] == "no_runs"


def test_readonly_dashboard_and_password_refusal(settings, monkeypatch):
    from chatcheck.dashboard import require_password, password_matches, snapshot, launch
    monkeypatch.delenv("CHATCHECK_DASHBOARD_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="refused"):
        launch()
    assert not password_matches("wrong", "correct") and password_matches("اردو", "اردو")
    run(settings, ["wrong", ConnectorError("unavailable")])
    db = settings[1]
    original = db.read_bytes()
    data = snapshot(db)
    assert data[0]["details"][0]["kind"] == "model check failure"
    assert data[0]["details"][1]["kind"] == "availability / not run"
    assert db.read_bytes() == original
    with readonly_storage(db) as storage, pytest.raises(sqlite3.OperationalError):
        storage.connection.execute("DELETE FROM runs")


def test_cli_monitor_real_http_fake_target(settings, mock_chatbot, capsys):
    config, db, path = settings
    target = Path(config["target"])
    data = json.loads(target.read_text())
    data["url"] = mock_chatbot.url + "/chat"
    target.write_text(json.dumps(data))
    assert main(["monitor", "--config", str(path), "--db", str(db), "--dry-run"]) == 0
    assert main(["monitor", "--config", str(path), "--db", str(db), "--dry-run"]) == 0
    assert "already_claimed" in capsys.readouterr().out


@pytest.mark.parametrize("field,value", [("call_budget", True), ("call_budget", -1), ("score_drop_threshold", float("nan")),
                                         ("error_rate_threshold", 101), ("channels", ["other"]),
                                         ("recipients", ["bad\r\nBcc: victim@example.invalid"]), ("pdf", "yes")])
def test_invalid_monitor_configuration(settings, field, value):
    path = settings[2]
    config = json.loads(path.read_text())
    config[field] = value
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        load_config(path)


def test_budget_shared_across_suites(settings):
    config, db, _ = settings
    config["suites"].append(config["suites"][0])
    config["call_budget"] = 3
    result, saved, fake = run(settings, ["safe"] * 4)
    assert fake.calls == 3 and len(saved["tests"]) == 4
    assert len({t["test_key"] for t in saved["tests"]}) == 4
    assert result["metrics"]["not_attempted"] == 1


def test_error_threshold_is_strict(settings):
    result, saved, _ = run(settings, [ConnectorError("down"), "safe"])
    assert detect(saved, None, score_drop_threshold=0, error_rate_threshold=50)["reasons"] == []


def test_alert_dry_run_does_not_send(settings, monkeypatch, capsys):
    result, _, _ = run(settings, ["safe", "safe"])
    config, db, _ = settings
    config["channels"] = ["email", "slack"]
    monkeypatch.setattr("chatcheck.monitor_alerts.send_email", lambda *_: pytest.fail("SMTP used in dry run"))
    monkeypatch.setattr("chatcheck.monitor_alerts.send_slack", lambda *_: pytest.fail("Slack used in dry run"))
    with Storage(db) as storage:
        assert deliver(storage, result["cycle_id"], config, "Summary only", dry_run=True) == {"email": "dry_run", "slack": "dry_run"}
    assert "Summary only" in capsys.readouterr().out


def test_monthly_compares_to_previous_month(settings):
    run(settings, ["safe", "safe"], -1)
    run(settings, ["bad", "safe"], 0)
    result = monthly(settings[0], settings[1], month="2026-09")
    assert result["monthly"]["runs"] == 1
    assert result["monthly"]["newly_failing"] == ["s1:critical"]


def test_dashboard_blocks_unauthenticated_database_access(monkeypatch):
    import sys
    from chatcheck.dashboard import app
    class Stopped(Exception):
        pass
    st = Mock()
    st.session_state = {}
    st.stop.side_effect = Stopped
    monkeypatch.setitem(sys.modules, "streamlit", st)
    monkeypatch.setenv("CHATCHECK_DASHBOARD_PASSWORD", "synthetic-dashboard-password")
    monkeypatch.setattr("chatcheck.dashboard.snapshot", lambda _: pytest.fail("Unauthenticated data read"))
    with pytest.raises(Stopped):
        app()
    assert st.text_input.call_args.kwargs["type"] == "password"
    assert "synthetic-dashboard-password" not in str(st.mock_calls)


def retention_fixture(settings, tmp_path):
    result, _, _ = run(settings, ["safe", "safe"])
    config, db, _ = settings
    policy = {"clients": [{"client_id": "client", "days": 30, "reports_dir": config["reports_dir"]}]}
    with Storage(db) as storage, storage.connection:
        storage.connection.execute("UPDATE runs SET finished_at=?", (DATE.isoformat(),))
        storage.connection.execute("UPDATE monitor_artifacts SET created_at=?", (DATE.isoformat(),))
    return result, policy, lambda: DATE + timedelta(days=60)


def test_retention_dry_run_and_real_purge(settings, tmp_path):
    from chatcheck.retention import retain
    result, policy, clock = retention_fixture(settings, tmp_path)
    config, db, _ = settings
    export = Path(config["reports_dir"]) / "old-export.json"
    export.write_text('{"synthetic": true}')
    with Storage(db) as storage:
        register_artifact(storage, export, run_id=result["run_id"], kind="export", created_at=DATE.isoformat())
    original = db.read_bytes()
    inventory = retain(policy, db, clock=clock)
    assert inventory["dry_run"] and len(inventory["clients"][0]["runs"]) == 1
    assert len(inventory["clients"][0]["files"]) == 2
    assert export.exists() and db.read_bytes() == original
    receipt = retain(policy, db, clock=clock, yes=True)
    assert receipt["deleted_runs"] == [result["run_id"]]
    assert not export.exists() and not Path(result["report"]).exists()
    with Storage(db) as storage:
        assert not storage.connection.execute("SELECT * FROM responses").fetchall()
        assert not storage.connection.execute("SELECT * FROM runs").fetchall()
        tombstone = storage.connection.execute("SELECT run_id, summary_json, status FROM monitor_cycles").fetchone()
        assert tuple(tombstone) == (None, None, "completed")
        assert not storage.connection.execute("PRAGMA foreign_key_check").fetchall()
    assert retain(policy, db, clock=clock, yes=True)["deleted_runs"] == []


def test_retention_preserves_other_clients_fresh_files_and_unregistered_files(settings, tmp_path):
    from chatcheck.retention import retain
    result, policy, clock = retention_fixture(settings, tmp_path)
    config, db, _ = settings
    config["client_id"] = "other"
    other, _, _ = run(settings, ["safe", "safe"])
    fresh = Path(config["reports_dir"]) / "fresh.json"
    unregistered = Path(config["reports_dir"]) / "unregistered.json"
    fresh.write_text("{}")
    unregistered.write_text("{}")
    with Storage(db) as storage:
        register_artifact(storage, fresh, run_id=result["run_id"], kind="export", created_at=clock().isoformat())
    receipt = retain(policy, db, clock=clock, yes=True)
    assert receipt["deleted_runs"] == [result["run_id"]]
    assert fresh.exists() and unregistered.exists() and Path(other["report"]).exists()
    with Storage(db) as storage:
        assert storage.results(other["run_id"])


@pytest.mark.parametrize("outside", [True, False])
def test_retention_refuses_outside_or_changed_files(settings, tmp_path, outside):
    from chatcheck.retention import retain
    result, policy, clock = retention_fixture(settings, tmp_path)
    config, db, _ = settings
    path = tmp_path / "external.json" if outside else Path(config["reports_dir"]) / "changed.json"
    path.write_text("original")
    with Storage(db) as storage:
        register_artifact(storage, path, run_id=result["run_id"], kind="export", created_at=DATE.isoformat())
    if not outside:
        path.write_text("replacement")
    receipt = retain(policy, db, clock=clock, yes=True)
    assert path.exists()
    item = next(row for row in receipt["clients"][0]["files"] if row["path"] == str(path))
    assert not item["eligible"]


def test_retention_rejects_symlink_ancestor(tmp_path, monkeypatch):
    from chatcheck.retention import permitted_file
    root = tmp_path / "reports"
    root.mkdir()
    path = root / "linked" / "report.json"
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == path.parent or original(self))
    assert permitted_file(path, root, "unused") == (False, "symlink or junction")


def test_retention_cli_inventory_and_export_registration(settings, tmp_path, capsys):
    from chatcheck.retention import load_policy
    result, policy, clock = retention_fixture(settings, tmp_path)
    config, db, _ = settings
    exported = Path(config["reports_dir"]) / "cli-export.json"
    assert main(["export", "--db", str(db), "--run", result["run_id"], "--format", "json", "--output", str(exported)]) == 0
    with Storage(db) as storage:
        assert storage.connection.execute("SELECT kind FROM monitor_artifacts WHERE path=?", (str(exported),)).fetchone()[0] == "export"
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy))
    receipt = tmp_path / "inventory.html"
    assert main(["retention", "--db", str(db), "--policy", str(policy_path), "--out", str(receipt)]) == 0
    assert "Client data-retention report" in receipt.read_text()
    assert Path(result["report"]).exists()


def test_retention_running_and_recent_finished_runs_preserved(settings, tmp_path):
    from chatcheck.retention import retain
    result, policy, clock = retention_fixture(settings, tmp_path)
    db = settings[1]
    with Storage(db) as storage, storage.connection:
        storage.connection.execute("UPDATE runs SET status='running'")
    assert retain(policy, db, clock=clock)["clients"][0]["runs"] == []
    with Storage(db) as storage, storage.connection:
        storage.connection.execute("UPDATE runs SET status='completed', finished_at=?", (clock().isoformat(),))
    assert retain(policy, db, clock=clock)["clients"][0]["runs"] == []


def test_monthly_summary_real_pdf_fits_five_pages(tmp_path):
    import io
    from pypdf import PdfReader
    from chatcheck.report import render_report, pdf_bytes
    from tests.chatcheck.test_report import make_run
    with Storage(tmp_path / "run.db") as storage:
        saved = make_run(storage, [{"key": str(n), "category": category, "response": "wrong", "severity": "critical"}
                                  for n, category in enumerate(["language", "tone", "data_leakage", "robustness", "prompt_injection"])])
    month = {"month": "2026-08", "runs": 31, "score": 50, "availability": 90,
             "newly_failing": ["long-case-" + "a" * 100] * 20, "newly_fixed": ["b" * 100] * 20,
             "failure_transitions": 20, "fix_transitions": 20, "errors": 5, "not_attempted": 4,
             "weeks": [{"week": "2026-08-01", "runs": 5, "score": 50, "availability": 90}] * 6}
    pdf = pdf_bytes(render_report(saved, summary=True, monthly=month))
    assert 1 <= len(PdfReader(io.BytesIO(pdf)).pages) <= 5


def test_header_environment_value_redacted_even_with_nonsecret_variable_name(settings, monkeypatch):
    config, db, _ = settings
    target = json.loads(Path(config["target"]).read_text())
    target["headers"] = {"Authorization": "Bearer ${CUSTOM_HEADER_VALUE}"}
    Path(config["target"]).write_text(json.dumps(target))
    monkeypatch.setenv("CUSTOM_HEADER_VALUE", "synthetic-private-header")
    result, _, _ = run(settings, ["synthetic-private-header", "safe"])
    assert b"synthetic-private-header" not in db.read_bytes()
    assert "synthetic-private-header" not in Path(result["report"]).read_text(encoding="utf-8")


@pytest.mark.parametrize("change", [
    {"headers": {"Authorization": "Bearer synthetic-inline-secret"}},
    {"url": "https://example.invalid/chat?api_key=synthetic-inline-secret"},
    {"request_template": {"api_key": "synthetic-inline-secret", "message": "{{prompt}}"}},
])
def test_inline_authentication_rejected_without_persistence(settings, change):
    config, db, _ = settings
    target = json.loads(Path(config["target"]).read_text())
    target.update(change)
    Path(config["target"]).write_text(json.dumps(target))
    with pytest.raises(ValueError) as error:
        run(settings, ["safe", "safe"])
    assert "synthetic-inline-secret" not in str(error.value)
    assert not db.exists()


def test_html_report_does_not_claim_an_unrelated_existing_pdf(settings, tmp_path):
    result, _, _ = run(settings, ["safe", "safe"])
    config, db, _ = settings
    report = Path(config["reports_dir"]) / "new.html"
    sibling = report.with_suffix(".pdf")
    sibling.write_bytes(b"unrelated private file")
    assert main(["report", "--db", str(db), "--run", result["run_id"], "--out", str(report)]) == 0
    with Storage(db) as storage:
        assert storage.connection.execute("SELECT 1 FROM monitor_artifacts WHERE path=?", (str(sibling),)).fetchone() is None
    assert sibling.read_bytes() == b"unrelated private file"
