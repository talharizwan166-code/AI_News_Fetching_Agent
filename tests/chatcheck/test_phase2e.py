import copy
import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from chatcheck.cli import main as cli
from chatcheck.judge import judge, validate_checks
from chatcheck.models import RunOptions, TestCase as Case, load_suite
from chatcheck.report import build_context, render_report
from chatcheck.scoring import coverage_scores
from chatcheck.storage import Storage
from chatcheck.text_normalization import normalize_phrase
from chatcheck.tuning import freeze_suite, guard_path, revise_checks
from demo_bots.meher_threads.budget import TargetBudget
from demo_bots.meher_threads.llm import LLMBot
from scripts import retry_failed_real_llm as retry


@pytest.fixture
def environment(monkeypatch):
    monkeypatch.setenv("MEHER_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("MEHER_LLM_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setenv("MEHER_LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-phase2e-secret-never-store")
    monkeypatch.delenv("MEHER_LLM_API_KEY", raising=False)
    monkeypatch.setenv("MEHER_LLM_PACE_SECONDS", "0")


def make_run(storage, states=("error", "error", "pass", "fail")):
    cases = [Case(str(i), f"Return policy {i}?", [{"type": "contains", "value": "14"}],
                  category="policy_accuracy", language="en", expected_behavior="14 calendar days", severity="high") for i in range(len(states))]
    run_id, ids = storage.start_run(cases, "real target", "main.json", RunOptions())
    for test_id, case, state in zip(ids, cases, states):
        text, error = (None, "LLM upstream HTTP 503") if state == "error" else ("14 days" if state == "pass" else "99 days", None)
        storage.record_attempt(test_id, 1, text, 1, error)
        storage.record_verdict(test_id, judge(text, case.checks, error))
    storage.finish_run(run_id, "completed_with_errors")
    return run_id, ids


def fake_bot(path, *, max_calls=12, respond=None):
    budget = TargetBudget(path, retry.SESSION, {"test": "error retry"}, max_calls=max_calls, max_output_tokens=128)
    calls = []
    def handler(request):
        calls.append(request)
        if respond:
            return respond(request)
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "14 calendar days"}]}}]})
    return LLMBot(transport=httpx.MockTransport(handler), budget=budget, raw_evaluation=True), budget, calls


def test_retry_only_errors_same_run_history_and_never_recall_real_failures(tmp_path, environment):
    with Storage(tmp_path / "runs.db") as storage:
        run_id, ids = make_run(storage)
        before = copy.deepcopy(storage.results(run_id))
        bot, budget, calls = fake_bot(tmp_path / "retry.db")
        try:
            assert retry.retry_errors(storage, bot, [run_id], pace=0) == 2
            after = storage.results(run_id)
            assert after["id"] == run_id and len(calls) == 2
            assert after["status"] == "completed"
            for test in after["tests"][:2]:
                assert [row["attempt"] for row in test["responses"]] == [1, 2]
                assert test["responses"][0]["error"] == "LLM upstream HTTP 503"
                assert test["verdict"]["passed"]
                event = test["retry_history"][0]
                assert event["status"] == "completed" and event["previous_judgments"]["rule"]["passed"] is False
            assert after["tests"][2:] == before["tests"][2:]
            assert retry.retry_errors(storage, bot, [run_id], pace=0) == 0
            assert len(calls) == 2 and budget.calls == 2
        finally:
            bot.close()
            budget.close()


def test_retry_cap_persists_and_remaining_failures_are_not_replayed(tmp_path, environment):
    with Storage(tmp_path / "runs.db") as storage:
        run_id, _ = make_run(storage, ("error",) * 4)
        for _ in range(2):
            bot, budget, calls = fake_bot(tmp_path / "retry.db", max_calls=2)
            try:
                retry.retry_errors(storage, bot, [run_id], pace=0)
                assert budget.calls == 2
            finally:
                bot.close()
                budget.close()
        run = storage.results(run_id)
        assert [len(test["responses"]) for test in run["tests"]] == [2, 2, 1, 1]
        assert run["coverage_scores"]["errors"] == 2
        assert run["coverage_scores"]["errors_as_not_run"]["failed"] == 0


def test_failed_retry_and_crash_reservation_are_not_automatically_retried(tmp_path, environment):
    with Storage(tmp_path / "runs.db") as storage:
        run_id, ids = make_run(storage, ("error", "error"))
        storage.reserve_target_retry(ids[1], retry.SESSION)  # crash before sending
        bot, budget, calls = fake_bot(tmp_path / "retry.db", respond=lambda _: httpx.Response(503))
        try:
            retry.retry_errors(storage, bot, [run_id], pace=0)
            retry.retry_errors(storage, bot, [run_id], pace=0)
            assert len(calls) == 1
            tests = storage.results(run_id)["tests"]
            assert len(tests[0]["responses"]) == 2 and len(tests[1]["responses"]) == 1
            assert tests[1]["retry_history"][0]["status"] == "reserved"
        finally:
            bot.close()
            budget.close()


def test_retry_preserves_old_reviews_and_purge_removes_the_audit(tmp_path, environment):
    with Storage(tmp_path / "runs.db") as storage:
        run_id, ids = make_run(storage, ("error",))
        storage.save_label(ids[0], "unsure")  # explicit fixture label on the old no-response attempt
        storage.record_llm_verdict(ids[0], {"status": "judged", "verdict": "uncertain"},
                                   {"verdict": "uncertain", "disagreement": False, "review": True})
        bot, budget, _ = fake_bot(tmp_path / "retry.db")
        try:
            retry.retry_errors(storage, bot, [run_id], pace=0)
        finally:
            bot.close()
            budget.close()
        test = storage.results(run_id)["tests"][0]
        assert test["human_label"] is None and test["llm_verdict"] is None
        previous = test["retry_history"][0]["previous_judgments"]
        assert previous["human_label"]["label"] == "unsure" and previous["llm"]["verdict"] == "uncertain"
        storage.purge(run_id=run_id, confirmed=True)
        for table in ("runs", "tests", "responses", "verdicts", "human_labels", "llm_verdicts"):
            assert storage.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_concurrent_retry_claims_are_atomic(tmp_path):
    path = tmp_path / "runs.db"
    with Storage(path) as storage:
        run_id, ids = make_run(storage, ("error",))
    def claim(_):
        with Storage(path) as storage:
            return storage.reserve_target_retry(ids[0], retry.SESSION) is not None
    with ThreadPoolExecutor(2) as workers:
        assert sum(workers.map(claim, range(2))) == 1


def test_any_historical_response_blocks_retry_even_with_later_error(tmp_path):
    with Storage(tmp_path / "runs.db") as storage:
        run_id, ids = make_run(storage, ("fail",))
        storage.record_attempt(ids[0], 2, None, 0, "HTTP 503")
        test = storage.results(run_id)["tests"][0]
        assert not retry.eligible(test)
        assert storage.reserve_target_retry(ids[0], retry.SESSION) is None


def test_empty_delivered_answer_is_a_behavior_failure_and_never_resampled(tmp_path):
    with Storage(tmp_path / "runs.db") as storage:
        run_id, ids = make_run(storage, ("fail",))
        with storage.connection:
            storage.connection.execute("UPDATE responses SET text='' WHERE test_id=?", (ids[0],))
        values = coverage_scores(storage.results(run_id)["tests"])
        assert values["responses_only"]["total"] == 1 and values["responses_only"]["percent"] == 0
        storage.record_attempt(ids[0], 2, None, 0, "HTTP 503")
        assert not retry.eligible(storage.results(run_id)["tests"][0])
        assert storage.reserve_target_retry(ids[0], retry.SESSION) is None


def test_retry_never_logs_or_stores_key(tmp_path, environment, caplog, capsys):
    secret = "fake-phase2e-secret-never-store"
    caplog.set_level(logging.DEBUG)
    def echo(request):
        logging.getLogger("httpcore.http11").debug("%s", request.headers)
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": secret}]}}]})
    with Storage(tmp_path / "runs.db") as storage:
        run_id, _ = make_run(storage, ("error",))
        bot, budget, _ = fake_bot(tmp_path / "retry.db", respond=echo)
        try:
            retry.retry_errors(storage, bot, [run_id], pace=0)
        finally:
            bot.close()
            budget.close()
        assert secret not in json.dumps(storage.results(run_id))
    assert secret not in caplog.text + capsys.readouterr().out
    assert all(secret.encode() not in path.read_bytes() for path in tmp_path.iterdir())


@pytest.mark.parametrize("args", [["--yes"], ["--max-calls", "12"]])
def test_retry_requires_yes_and_explicit_cap_before_any_files(tmp_path, args):
    with pytest.raises(SystemExit) as error:
        retry.main([*args, "--out", str(tmp_path / "missing")])
    assert error.value.code == 2 and not (tmp_path / "missing").exists()


def test_response_only_headline_and_errors_as_not_run_are_both_visible(tmp_path):
    with Storage(tmp_path / "run.db") as storage:
        run_id, _ = make_run(storage, ("pass", "fail", "error", "error"))
        run = storage.results(run_id)
        values = coverage_scores(run["tests"])
        assert values["responses_only"]["percent"] == 50
        assert values["errors_as_not_run"]["percent"] == 25
        assert values["errors_as_not_run"]["failed"] == 1 and values["errors_as_not_run"]["pending"] == 2
        context = build_context(run)
        assert context["headline"]["display"] == "50.0%"
        html = render_report(run)
        assert "Response-only test pass score" in html and "<strong>50.0%</strong>" in html
        assert "2 connector errors" in html and "Errors counted as not-run: 25.0%" in html
        assert coverage_scores([])["responses_only"]["percent"] is None


@pytest.mark.parametrize("raw,expected", [
    ("كيا", "کیا"), ("كِيا", "کیا"), ("ي ى ی", "ی ی ی"),
    ("A\u200bB\u200cC\u200dD\ufeffE", "abcde"),
    ("  RETURN\t\n  Policy  ", "return policy"), ("Straße", "strasse"),
    ("e\u0301", "é"), ("ہے", "ہے"),
])
def test_urdu_phrase_normalization(raw, expected):
    assert normalize_phrase(raw) == expected


def test_any_of_phrases_is_optional_and_does_not_weaken_existing_checks():
    check = {"type": "any_of_phrases", "value": ["واپس نہیں", "کیا واپس"]}
    assert judge("كِيا\u200d   واپس", [check]).passed
    assert judge("RETURN\n POLICY", [{"type": "any_of_phrases", "value": ["return policy"]}]).passed
    assert not judge("غير متعلق", [check]).passed
    assert not judge("كِيا", [{"type": "contains", "value": "کیا"}]).passed
    assert not judge("كِيا", [check], "HTTP 503").passed


@pytest.mark.parametrize("check", [
    {"type": "any_of_phrases"}, {"type": "any_of_phrases", "value": []},
    {"type": "any_of_phrases", "value": "hello"}, {"type": "any_of_phrases", "value": [1]},
    {"type": "any_of_phrases", "value": ["\u200d\u064e"]},
    {"type": "any_of_phrases", "value": ["hello"], "case_sensitive": True},
])
def test_invalid_phrase_checks_rejected(check):
    with pytest.raises(ValueError):
        validate_checks([check])


def write_suite(path):
    data = [{"id": "return", "prompt": "Return policy?", "category": "policy_accuracy", "language": "en",
             "expected_behavior": "14 days", "checks": [{"type": "contains", "value": "fourteen"}]}]
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def test_heldout_freeze_blocks_edited_checks_and_records_explicit_exception(tmp_path, capsys):
    path = tmp_path / "heldout.json"
    data = write_suite(path)
    assert cli(["freeze", "--suite", str(path)]) == 0
    original = json.loads(guard_path(path).read_text())
    assert original["role"] == "heldout" and len(original["suite_sha256"]) == 64
    assert load_suite(path)
    data[0]["checks"] = [{"type": "contains", "value": "14"}]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Frozen held-out suite checks changed"):
        load_suite(path)
    assert cli(["validate", "--suite", str(path)]) == 2
    assert cli(["freeze", "--suite", str(path)]) == 2
    assert cli(["freeze", "--suite", str(path), "--unfreeze", " "]) == 2
    assert cli(["freeze", "--suite", str(path), "--unfreeze", "Documented benchmark correction; results no longer blind"]) == 0
    current = json.loads(guard_path(path).read_text())
    assert current["suite_sha256"] != original["suite_sha256"]
    entry = current["changelog"][0]
    assert entry["test_id"] == "return" and entry["old_check"] == original["checks"]["return"]
    assert entry["new_check"] == data[0]["checks"] and entry["reason"] and entry["date"]
    assert current["history"][-1]["action"] == "unfreeze_refreeze" and load_suite(path)
    with pytest.raises(ValueError, match="role cannot be changed"):
        freeze_suite(path, role="main", unfreeze="Try relabeling the split")


def test_freeze_protects_prompts_too_and_ignores_json_whitespace(tmp_path):
    path = tmp_path / "heldout.json"
    data = write_suite(path)
    freeze_suite(path)
    path.write_text(json.dumps(data, indent=4), encoding="utf-8")
    assert load_suite(path)
    data[0]["prompt"] = "Changed held-out wording"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="definition changed"):
        load_suite(path)


def test_main_revision_requires_real_human_review_and_changelog(tmp_path):
    path = tmp_path / "main.json"
    data = write_suite(path)
    freeze_suite(path, role="main")
    review_db = tmp_path / "labels.db"
    with Storage(review_db) as storage:
        case = load_suite(path)[0]
        run_id, ids = storage.start_run([case], "real", str(path), RunOptions())
        storage.record_attempt(ids[0], 1, "14 days", 0, None)
        storage.record_verdict(ids[0], judge("14 days", case.checks))
        new_checks = [{"type": "any_of_phrases", "value": ["14 days", "fourteen days"]}]
        with pytest.raises(ValueError, match="explicit human pass label"):
            revise_checks(path, "return", new_checks, reason="Equivalent wording", review_db=review_db, review_run=run_id)
        assert json.loads(path.read_text()) == data
        storage.save_label(ids[0], "pass")  # only an explicit test-fixture annotation
    entry = revise_checks(path, "return", new_checks, reason="Human confirmed the policy meaning", review_db=review_db, review_run=run_id)
    assert entry["test_id"] == "return" and entry["old_check"] == data[0]["checks"] and entry["new_check"] == new_checks
    assert entry["review"]["human_label"] == "pass" and entry["date"]
    assert judge("14 days", load_suite(path)[0].checks).passed
    assert json.loads(guard_path(path).read_text())["changelog"] == [entry]


def test_heldout_revision_command_and_main_unfreeze_cannot_bypass_review(tmp_path):
    heldout, main = tmp_path / "heldout.json", tmp_path / "main.json"
    write_suite(heldout)
    original = write_suite(main)
    freeze_suite(heldout)
    freeze_suite(main, role="main")
    with pytest.raises(ValueError, match="held-out tuning is prohibited"):
        revise_checks(heldout, "return", [{"type": "contains", "value": "14"}], reason="Observed heldout failure", review_db=tmp_path / "absent.db", review_run="x")
    original[0]["checks"] = [{"type": "contains", "value": "14"}]
    main.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(ValueError, match="without a reviewed changelog"):
        load_suite(main)
    with pytest.raises(ValueError, match="cannot bypass review"):
        freeze_suite(main, unfreeze="Skip human labels")


def test_main_revision_cannot_remove_an_exact_leak_guard(tmp_path):
    path = tmp_path / "main.json"
    data = write_suite(path)
    data[0]["checks"].append({"type": "not_contains", "value": "PRIVATE_ORDER_4821"})
    path.write_text(json.dumps(data), encoding="utf-8")
    freeze_suite(path, role="main")
    with pytest.raises(ValueError, match="Exact forbidden-content checks must remain unchanged"):
        revise_checks(path, "return", [{"type": "contains", "value": "14"}], reason="Try removing a guard", review_db=tmp_path / "unused.db", review_run="unused")


def test_retry_cli_preserves_original_ledger_and_uses_only_twelve_extra_slots(tmp_path, environment, monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "14 days"}]}}]})
    def factory(**kwargs):
        return LLMBot(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(retry, "LLMBot", factory)
    monkeypatch.setattr(retry, "artifacts", lambda storage, manifest, directory, bot, **kwargs:
                        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8"))
    bot = factory(raw_evaluation=True)
    try:
        metadata = bot.metadata()
    finally:
        bot.close()
    with Storage(tmp_path / "runs.db") as storage:
        run_id, _ = make_run(storage, ("error",) * 13 + ("fail",))
        with storage.connection:
            storage.connection.execute("UPDATE runs SET options_json=? WHERE id=?", (json.dumps({"target_llm": metadata}), run_id))
    manifest = {"run_ids": [run_id], "target": metadata, "reserved_calls": 96}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    original = TargetBudget(tmp_path / "target-budget.db", "real-demo-v1", metadata, max_calls=96, max_output_tokens=128)
    original.reserve("historical")
    original.close()
    assert retry.main(["--yes", "--max-calls", "12", "--out", str(tmp_path)]) == 1
    first = json.loads((tmp_path / "manifest.json").read_text())
    assert first["retry"]["reserved_calls"] == 12 and len(requests) == 12
    assert first["reserved_calls"] == 96
    assert retry.main(["--yes", "--max-calls", "12", "--out", str(tmp_path)]) == 1
    second = json.loads((tmp_path / "manifest.json").read_text())
    assert second["retry"]["scores_before_first_retry"] == first["retry"]["scores_before_first_retry"]
    assert len(requests) == 12
    with sqlite3.connect(tmp_path / "target-budget.db") as ledger:
        assert ledger.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 1
