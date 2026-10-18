"""One bounded, durably claimed monitoring cycle; scheduling is external."""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import uuid

from .connectors import create_connector, ConnectorError
from .models import load_suite, read_json, RunOptions
from .monitor_store import MonitorStorage, register_artifact, target_redactor
from .report import compare_runs, write_report
from .runner import run_suite, RunBudgetExceeded
from .scoring import coverage_scores, has_response, outcome


def load_config(path):
    path = Path(path).resolve()
    config = read_json(path)
    required = {"client_id", "target_id", "target", "suites", "schedule", "score_drop_threshold",
                "error_rate_threshold", "recipients", "call_budget", "reports_dir"}
    optional = {"channels", "max_cost", "cost_per_call", "pdf"}
    if not isinstance(config, dict) or not required <= config.keys() or config.keys() - required - optional:
        raise ValueError("Invalid monitoring config fields; see the monitoring example")
    for name in ("client_id", "target_id"):
        if not isinstance(config[name], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", config[name]):
            raise ValueError("Client and target IDs must be short letters, digits, hyphens or underscores")
    schedule = config["schedule"]
    if (not isinstance(schedule, dict) or set(schedule) != {"description", "interval_minutes"}
            or not isinstance(schedule["description"], str) or not schedule["description"].strip()
            or type(schedule["interval_minutes"]) is not int or not 1 <= schedule["interval_minutes"] <= 525600):
        raise ValueError("Schedule needs a description and interval_minutes between 1 and 525600")
    for name in ("score_drop_threshold", "error_rate_threshold"):
        value = config[name]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError("Monitoring thresholds must be percentages between 0 and 100")
    if type(config["call_budget"]) is not int or config["call_budget"] < 0:
        raise ValueError("call_budget must be a nonnegative integer")
    if (not isinstance(config["recipients"], list) or any(not isinstance(v, str) or
            not re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", v) for v in config["recipients"])):
        raise ValueError("Recipients must be explicit email addresses")
    config.setdefault("channels", ["email"])
    if (not isinstance(config["channels"], list) or set(config["channels"]) - {"email", "slack"}
            or len(config["channels"]) != len(set(config["channels"]))):
        raise ValueError("Channels must contain email and/or slack without duplicates")
    if "email" in config["channels"] and not config["recipients"]:
        raise ValueError("Email alerts require recipients")
    config.setdefault("pdf", False)
    if type(config["pdf"]) is not bool:
        raise ValueError("pdf must be boolean")
    if ("max_cost" in config) != ("cost_per_call" in config):
        raise ValueError("Set both max_cost and cost_per_call to enforce a monetary reservation cap")
    for name in ("max_cost", "cost_per_call"):
        if name in config and (type(config[name]) not in (int, float) or not math.isfinite(config[name]) or config[name] < 0):
            raise ValueError("Cost reservations must be finite nonnegative numbers")
    if "cost_per_call" in config and config["cost_per_call"] == 0:
        raise ValueError("A monetary cap requires a positive conservative cost_per_call")
    if not isinstance(config["suites"], list) or not config["suites"]:
        raise ValueError("At least one suite is required")
    for name in ("target", "reports_dir"):
        if not isinstance(config[name], str) or not config[name]:
            raise ValueError("Target and reports_dir must be paths")
        config[name] = str((path.parent / config[name]).resolve())
    if any(not isinstance(p, str) or not p for p in config["suites"]):
        raise ValueError("Suites must be paths")
    config["suites"] = [str((path.parent / p).resolve()) for p in config["suites"]]
    return config


def metrics(run):
    coverage = coverage_scores(run["tests"])
    attempted = sum(bool(t["responses"]) for t in run["tests"])
    return {"score": coverage["responses_only"]["percent"], "passed": coverage["responses_only"]["passed"],
            "received": coverage["received"], "planned": coverage["planned"], "attempted": attempted,
            "errors": coverage["errors"], "not_attempted": coverage["planned"] - attempted,
            "error_rate": 100 * coverage["errors"] / attempted if attempted else None,
            "availability": 100 * coverage["received"] / attempted if attempted else None}


def detect(current, previous, *, score_drop_threshold, error_rate_threshold):
    current_metrics = metrics(current)
    comparison = compare_runs(current, previous) if previous else None
    # Only unchanged definitions with real responses on BOTH sides can newly
    # fail/fix. A transport failure can never become a model-regression alert.
    newly_failing = comparison["newly_failing"] if comparison else []
    fixed = comparison["fixed"] if comparison else []
    critical = [t["test_key"] for t in current["tests"] if t["test_key"] in newly_failing and t.get("severity") == "critical"]
    comparable = bool(comparison and not any(comparison[k] for k in ("added", "removed", "modified")))
    old_score = metrics(previous)["score"] if previous else None
    score_drop = (old_score - current_metrics["score"] if comparable and old_score is not None
                  and current_metrics["score"] is not None else None)
    reasons = []
    if score_drop is not None and score_drop > score_drop_threshold:
        reasons.append("response_score_drop")
    if critical:
        reasons.append("new_critical_failure")
    if current_metrics["error_rate"] is not None and current_metrics["error_rate"] > error_rate_threshold:
        reasons.append("availability")
    return {"metrics": current_metrics, "reasons": reasons, "score_drop": score_drop,
            "newly_failing": newly_failing, "newly_fixed": fixed, "critical": critical,
            "baseline_run": previous["id"] if previous else None, "comparable": comparable,
            "definition_changes": bool(comparison and not comparable)}


def alert_text(client, target, decision, report_path):
    data = decision["metrics"]
    lines = [f"Chatcheck monitoring: {client} / {target}"]
    if "response_score_drop" in decision["reasons"]:
        lines.append(f"Response-only score dropped by {decision['score_drop']:.1f} percentage points.")
    if "new_critical_failure" in decision["reasons"]:
        lines.append(f"{len(decision['critical'])} critical test(s) newly failed on received responses.")
    if "availability" in decision["reasons"]:
        lines.append(f"Availability problem: {data['errors']} of {data['attempted']} attempted tests ended in connector errors ({data['error_rate']:.1f}%).")
    score = "not available" if data["score"] is None else f"{data['score']:.1f}%"
    lines += [f"Response-only score: {score}. Connector errors are excluded from model scores.",
              f"Coverage: {data['received']}/{data['planned']} usable responses; {data['not_attempted']} tests not attempted.",
              f"Report: {report_path}"]
    return "\n".join(lines)


def previous_runs(storage, client, target):
    rows = storage.connection.execute(
        "SELECT run_id FROM monitor_cycles WHERE client_id=? AND target_id=? AND status='completed' AND run_id IS NOT NULL ORDER BY created_at, id",
        (client, target))
    return [storage.results(row[0]) for row in rows]


async def cycle(config, db, *, dry_run=False, clock=None, connector_factory=create_connector):
    timestamp = (clock or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc)
    target = read_json(config["target"])
    redactor = target_redactor(target)
    tests = []
    for index, suite in enumerate(config["suites"]):
        # Stable namespaces let different suites reuse a test ID without collisions.
        tests.extend(replace(t, id=f"s{index + 1}:{t.id}") for t in load_suite(suite))
    options = RunOptions(**target.get("runner", {}))
    interval = config["schedule"]["interval_minutes"] * 60
    slot = int(timestamp.timestamp()) // interval
    signature = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    with MonitorStorage(db, redactor) as storage:
        with storage.connection:
            storage.connection.execute("BEGIN IMMEDIATE")
            existing = storage.connection.execute(
                "SELECT * FROM monitor_cycles WHERE client_id=? AND target_id=? AND (slot=? OR status='running') ORDER BY created_at LIMIT 1",
                (config["client_id"], config["target_id"], slot)).fetchone()
            if existing:
                return {"status": "already_claimed", "cycle_id": existing["id"], "run_id": existing["run_id"],
                        "previous_status": existing["status"]}
            cycle_id = str(uuid.uuid4())
            storage.connection.execute(
                "INSERT INTO monitor_cycles (id, client_id, target_id, slot, created_at, status, config_hash, schedule, report_root) VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?)",
                (cycle_id, config["client_id"], config["target_id"], slot, timestamp.isoformat(), signature,
                 redactor.text(config["schedule"]["description"]), redactor.text(config["reports_dir"])))
        history = previous_runs(storage, config["client_id"], config["target_id"])
        baseline = history[-1] if history else None

        def attach(run_id):
            with storage.connection:
                storage.connection.execute("UPDATE monitor_cycles SET run_id=? WHERE id=?", (run_id, cycle_id))
                storage.connection.execute("UPDATE runs SET started_at=? WHERE id=?", (timestamp.isoformat(), run_id))

        exhausted = False
        def reserve(*_):
            nonlocal exhausted
            with storage.connection:
                storage.connection.execute("BEGIN IMMEDIATE")
                row = storage.connection.execute("SELECT calls FROM monitor_cycles WHERE id=?", (cycle_id,)).fetchone()
                estimate = Decimal(str(config.get("cost_per_call", 0))) * (row[0] + 1)
                if row[0] >= config["call_budget"] or ("max_cost" in config and estimate > Decimal(str(config["max_cost"]))):
                    exhausted = True
                    raise RunBudgetExceeded()
                storage.connection.execute("UPDATE monitor_cycles SET calls=calls+1, reserved_cost=? WHERE id=?", (float(estimate), cycle_id))

        try:
            connector = LazyConnector(connector_factory(target))
            run_id = await run_suite(tests, connector, storage, options, target_name=config["target_id"],
                                     suite_path="monitor suites", before_attempt=reserve, on_run_started=attach)
            run = storage.results(run_id)
            decision = detect(run, baseline, score_drop_threshold=config["score_drop_threshold"],
                              error_rate_threshold=config["error_rate_threshold"])
            directory = Path(config["reports_dir"]) / config["client_id"] / config["target_id"]
            directory.mkdir(parents=True, exist_ok=True)
            report = directory / (run_id + ".html")
            write_report(run, report, compare=baseline, client=config["client_id"], redactor=redactor, pdf=config["pdf"])
            for path in ([report, report.with_suffix(".pdf")] if config["pdf"] else [report]):
                if path.exists():
                    register_artifact(storage, path, run_id=run_id, kind="report")
            from .monitor_alerts import deliver
            message = redactor.text(alert_text(config["client_id"], config["target_id"], decision, report))
            statuses = deliver(storage, cycle_id, config, message, dry_run=dry_run) if decision["reasons"] else {}
            decision.update(alerts=statuses, report=redactor.text(report), run_id=run_id,
                            budget_stopped=exhausted, pdf_created=report.with_suffix(".pdf").exists(),
                            report_error=config["pdf"] and not report.with_suffix(".pdf").exists())
            usage = storage.connection.execute("SELECT calls, reserved_cost FROM monitor_cycles WHERE id=?", (cycle_id,)).fetchone()
            decision["budget"] = {"reserved_calls": usage[0], "max_calls": config["call_budget"],
                                  "reserved_cost": usage[1] if "max_cost" in config else None,
                                  "max_cost": config.get("max_cost"), "basis": "Configured conservative per-call estimate; not provider billing"}
            with storage.connection:
                storage.connection.execute("UPDATE monitor_cycles SET status='completed', finished_at=?, summary_json=? WHERE id=?",
                                           (datetime.now(timezone.utc).isoformat(), json.dumps(redactor.tree(decision)), cycle_id))
            return {"status": "completed", "cycle_id": cycle_id, **decision}
        except BaseException:
            with storage.connection:
                storage.connection.execute("UPDATE monitor_cycles SET status='failed', finished_at=? WHERE id=?",
                                           (datetime.now(timezone.utc).isoformat(), cycle_id))
            raise


class LazyConnector:
    """Reserve before startup/network; startup failures are availability evidence."""
    def __init__(self, connector):
        self.connector = connector
        self.lock = asyncio.Lock()
        self.entered = self.failed = False

    async def __aenter__(self):
        return self

    async def send(self, prompt):
        async with self.lock:
            if not self.entered and not self.failed:
                try:
                    await self.connector.__aenter__()
                    self.entered = True
                except Exception:
                    self.failed = True
        if self.failed:
            raise ConnectorError("Connector startup unavailable")
        return await self.connector.send(prompt)

    async def __aexit__(self, *args):
        if self.entered:
            await self.connector.__aexit__(*args)
