"""Monthly aggregation over saved monitoring runs; never calls a target."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

from .monitor import detect, metrics, previous_runs
from .monitor_store import register_artifact, secret_redactor
from .report import write_report
from .storage import Storage


def month_bounds(month=None, clock=None):
    date = (clock or (lambda: datetime.now(timezone.utc)))()
    if month is None:
        month = (date.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("Month must be YYYY-MM")
    start = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return month, start, end


def trend(history, month=None, clock=None):
    month, start, end = month_bounds(month, clock)
    selected = [r for r in history if start <= datetime.fromisoformat(r["started_at"]) < end]
    weeks = defaultdict(list)
    week_start = start - timedelta(days=start.weekday())
    while week_start < end:
        weeks[week_start.strftime("%Y-%m-%d")] = []
        week_start += timedelta(days=7)
    failures, fixes = [], []
    for index, run in enumerate(history):
        if run not in selected:
            continue
        date = datetime.fromisoformat(run["started_at"])
        week = (date - timedelta(days=date.weekday())).strftime("%Y-%m-%d")
        weeks[week].append(metrics(run))
        previous = history[index - 1] if index else None
        changes = detect(run, previous, score_drop_threshold=100, error_rate_threshold=100)
        failures.extend(changes["newly_failing"])
        fixes.extend(changes["newly_fixed"])
    def aggregate(rows):
        counts = {k: sum(r[k] for r in rows) for k in ("passed", "received", "attempted", "errors", "not_attempted", "planned")}
        return {**counts, "score": round(100 * counts["passed"] / counts["received"], 1) if counts["received"] else None,
                "availability": round(100 * counts["received"] / counts["attempted"], 1) if counts["attempted"] else None}
    weekly = [{"week": key, "runs": len(rows), **aggregate(rows)} for key, rows in sorted(weeks.items())]
    return {"month": month, "weeks": weekly, "newly_failing": sorted(set(failures)), "newly_fixed": sorted(set(fixes)),
            "failure_transitions": len(failures), "fix_transitions": len(fixes), "runs": len(selected),
            **aggregate([metrics(r) for r in selected])}, selected


def monthly(config, db, *, month=None):
    redactor = secret_redactor()
    with Storage(db) as storage:
        history = previous_runs(storage, config["client_id"], config["target_id"])
        summary, selected = trend(history, month)
        if not selected:
            return {"status": "no_runs", "month": summary["month"]}
        summary = redactor.tree(summary)
        signature = hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest()[:12]
        directory = Path(config["reports_dir"]) / config["client_id"] / config["target_id"]
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / f"monthly-{summary['month']}-{signature}.html"
        if output.exists():
            return {"status": "already_created", "report": str(output),
                    "report_error": config["pdf"] and not output.with_suffix(".pdf").exists()}
        write_report(selected[-1], output, summary=True, pdf=config["pdf"], redactor=redactor,
                     client=config["client_id"], monthly=summary,
                     not_tested=["Cover score describes the latest run; the monthly page aggregates received responses. Weeks start Monday (UTC)."])
        for path in ([output, output.with_suffix(".pdf")] if config["pdf"] else [output]):
            if path.exists():
                register_artifact(storage, path, run_id=selected[-1]["id"], kind="monthly")
        export = output.with_suffix(".json")
        with export.open("x", encoding="utf-8") as stream:
            json.dump(summary, stream, indent=2)
        register_artifact(storage, export, run_id=selected[-1]["id"], kind="export")
        return {"status": "created", "report": str(output), "monthly": summary,
                "report_error": config["pdf"] and not output.with_suffix(".pdf").exists()}
