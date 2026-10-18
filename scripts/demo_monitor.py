"""Generate Phase 6 evidence using only deterministic fake connectors and dry-run alerts."""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chatcheck.connectors import Connector, ConnectorError
from chatcheck.dashboard import snapshot
from chatcheck.monitor import cycle, load_config
from chatcheck.monitor_monthly import monthly
from chatcheck.retention import retain, write_inventory
from chatcheck.storage import Storage


class FakeTarget(Connector):
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = 0

    async def send(self, prompt):
        self.calls += 1
        value = next(self.replies)
        if isinstance(value, Exception):
            raise value
        return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    root = Path(args.out_dir).resolve()
    if root.exists():
        raise ValueError("Choose a new output directory")
    root.mkdir(parents=True)
    target = {"type": "http", "url": "http://127.0.0.1:1/unused", "runner": {"concurrency": 1, "retries": 0}}
    suite = {"tests": [{"id": "critical", "prompt": "Synthetic safety check", "severity": "critical",
                        "checks": [{"type": "equals", "value": "safe"}]},
                       {"id": "normal", "prompt": "Synthetic greeting", "severity": "low",
                        "checks": [{"type": "equals", "value": "safe"}]}]}
    config = {"client_id": "demo-client", "target_id": "fake-bot", "target": "target.json", "suites": ["suite.json"],
              "schedule": {"description": "Synthetic weekly history", "interval_minutes": 10080},
              "score_drop_threshold": 5, "error_rate_threshold": 10, "recipients": ["owner@example.invalid"],
              "channels": ["email", "slack"], "call_budget": 2, "reports_dir": "reports", "pdf": False}
    for name, data in (("target.json", target), ("suite.json", suite), ("config.json", config)):
        (root / name).write_text(json.dumps(data, indent=2) + "\n")
    config = load_config(root / "config.json")
    db = root / "monitor.sqlite3"
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    evidence = []
    for week, replies in enumerate((["safe", "safe"], ["wrong", ConnectorError("Synthetic unavailable target")],
                                    ["safe", "safe"], ["safe", "safe"], ["safe", "safe"])):
        date = start + timedelta(days=7 * week)
        fake = FakeTarget(replies)
        if week == 4:
            config["call_budget"] = 1
        result = asyncio.run(cycle(config, db, dry_run=True, clock=lambda: date, connector_factory=lambda _: fake))
        duplicate = asyncio.run(cycle(config, db, dry_run=True, clock=lambda: date, connector_factory=lambda _: fake))
        assert duplicate["status"] == "already_claimed"
        evidence.append({**result, "target_calls": fake.calls, "duplicate_status": duplicate["status"]})
        # Explicitly synthetic historical finish/artifact dates for the retention demo.
        with Storage(db) as storage, storage.connection:
            storage.connection.execute("UPDATE runs SET finished_at=? WHERE id=?", ((date + timedelta(seconds=1)).isoformat(), result["run_id"]))
            storage.connection.execute("UPDATE monitor_artifacts SET created_at=? WHERE run_id=?", (date.isoformat(), result["run_id"]))
    assert evidence[1]["reasons"] == ["response_score_drop", "new_critical_failure", "availability"]
    assert evidence[2]["newly_fixed"] == ["s1:critical"]
    assert evidence[4]["budget_stopped"] and evidence[4]["target_calls"] == 1
    config["pdf"] = True
    summary = monthly(config, db, month="2026-09")
    if summary["report_error"]:
        raise ValueError("Monthly PDF generation failed; HTML and evidence remain available")
    from pypdf import PdfReader
    pages = len(PdfReader(Path(summary["report"]).with_suffix(".pdf")).pages)
    assert 1 <= pages <= 5
    dashboard = snapshot(db)
    policy = {"clients": [{"client_id": "demo-client", "days": 30, "reports_dir": "reports"}]}
    (root / "retention-policy.json").write_text(json.dumps(policy, indent=2) + "\n")
    policy["clients"][0]["reports_dir"] = str(root / "reports")
    inventory = retain(policy, db, clock=lambda: datetime(2026, 10, 18, tzinfo=timezone.utc))
    write_inventory(inventory, root / "retention.html")
    proof = {"scope": "Synthetic history, deterministic in-process target; all alerts dry-run. No real account/provider calls.",
             "cycles": evidence, "monthly": summary, "summary_pages": pages, "dashboard_targets": len(dashboard),
             "retention_eligible_runs": len(inventory["clients"][0]["runs"])}
    (root / "verification.json").write_text(json.dumps(proof, indent=2) + "\n")
    relative = Path(summary["report"]).relative_to(root).as_posix()
    (root / "README.md").write_text(
        "# Phase 6 synthetic monitoring evidence\n\n"
        "Five historical cycles use a deterministic fake target; alert delivery is dry-run only. No real accounts or provider calls.\n\n"
        f"- [Monthly HTML]({relative}) and [PDF]({Path(relative).with_suffix('.pdf').as_posix()}) ({pages} pages).\n"
        "- [Client retention inventory](retention.html) (dry-run; no data deleted).\n"
        "- [Verification](verification.json) records scores, availability, regressions/fixes, duplicate suppression and budget stops.\n"
        "- `monitor.sqlite3` retains all runs locally (ignored by Git).\n\n"
        "The failing week has one real response failing a critical check and one synthetic connector error. Only the first is a model-check failure. "
        "The following week records recovery; the final week stops at one call with the remaining test not attempted.\n", encoding="utf-8")
    print(json.dumps({"cycles": len(evidence), "summary_pages": pages, "retention_eligible_runs": proof["retention_eligible_runs"]}))


if __name__ == "__main__":
    main()
