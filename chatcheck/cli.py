"""Command-line entry point: python -m chatcheck."""

import argparse
import asyncio
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from .connectors import create_connector
from .models import CATEGORIES, LANGUAGES, SEVERITIES, RunOptions, load_suite, read_json
from .runner import run_suite
from .storage import Storage
from .llm_judge import from_environment, judge_saved_run
from .labeling import build_sample, label_items
from .agreement import agreement_report


def print_results(result):
    print(f"Run: {result['id']} ({result['status']})")
    for test in result["tests"]:
        verdict = test["verdict"]
        label = ("NOT RUN" if test.get("execution_status") == "not_run" else "PENDING") if verdict is None else "PASS" if verdict["passed"] else "FAIL"
        latency = test["responses"][-1]["latency_ms"] if test["responses"] else 0
        reason = verdict["reason"] if verdict else test.get("not_run_reason") or "No verdict recorded"
        category = test.get("category") or "unspecified"
        severity = test.get("severity") or "unspecified"
        print(f"{label:7} {test['test_key']}  category={category} severity={severity}  {latency:.1f} ms  {reason}")
        if test.get("retry_history"):
            for attempt in test["responses"]:
                print(f"        attempt {attempt['attempt']}: {attempt['error'] or 'response received'}")
        if test.get("llm_verdict"):
            llm, combined = test["llm_verdict"], test["combined_verdict"]
            flag = " DISAGREEMENT: human review" if combined["disagreement"] else " REVIEW" if combined["review"] else ""
            print(f"        rule={label.lower()} llm={llm.get('verdict') or 'not judged'} hybrid={combined['verdict']}{flag}; {llm['reason']}")
    summary = result["summary"]
    print(f"{summary['passed']} passed, {summary['failed']} failed, {summary['pending']} pending / {summary['total']} tests")
    from .scoring import coverage_scores
    coverage = coverage_scores(result["tests"])
    response_score, all_score = coverage["responses_only"], coverage["errors_as_not_run"]
    print(f"Response-only score: {response_score['passed']}/{response_score['total']} ({response_score['display']}); {coverage['errors']} connector errors, {coverage['not_run']} without a response")
    print(f"Errors counted as not-run: {all_score['passed']}/{all_score['total']} ({all_score['display']}); {all_score['failed']} behavior failures, {all_score['pending']} not-run or unjudged")
    if any(test.get("llm_verdict") for test in result["tests"]):
        stats = result["judge_summary"]
        print(f"Judge: {stats['calls']} calls, estimated ${stats['estimated_cost']:.6f}; {stats['disagreements']} disagreements, {stats['not_judged']} not judged")


def print_validation(tests):
    print(f"Valid suite: {len(tests)} tests")
    for name, allowed in (("category", CATEGORIES), ("language", LANGUAGES), ("severity", SEVERITIES)):
        counts = Counter(getattr(test, name) or "unspecified" for test in tests)
        print(f"{name.capitalize()}:")
        for value in (*allowed, "unspecified"):
            print(f"  {value}: {counts[value]}")


def parser():
    root = argparse.ArgumentParser(prog="chatcheck", description="Run chatbot checks, optional rubric judging, and blinded human review.")
    commands = root.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate a JSON suite locally and report metadata counts")
    validate.add_argument("--suite", required=True)
    freeze = commands.add_parser("freeze", help="Hash a held-out suite and enforce its freeze on every load")
    freeze.add_argument("--suite", required=True)
    freeze.add_argument("--role", choices=["heldout", "main"], help="Default heldout; main registers a reviewed-revision baseline")
    freeze.add_argument("--unfreeze", metavar="REASON", help="Record an explicit exception and immediately freeze the current version")
    revise = commands.add_parser("revise", help="Revise MAIN checks only with an existing human-reviewed false failure")
    revise.add_argument("--suite", required=True)
    revise.add_argument("--test-id", required=True)
    revise.add_argument("--checks", required=True, help="JSON file containing the proposed new checks array")
    revise.add_argument("--reason", required=True)
    revise.add_argument("--review-db", required=True)
    revise.add_argument("--review-run", required=True)
    run = commands.add_parser("run", help="Run a JSON suite against a target config")
    run.add_argument("--target", required=True)
    run.add_argument("--suite", required=True)
    for flag, kind in (("concurrency", int), ("timeout", float), ("retries", int), ("rate-limit", float), ("retry-backoff", float)):
        run.add_argument(f"--{flag}", type=kind, default=None, help="Override target runner settings")
    results = commands.add_parser("results", help="Show stored verdicts")
    results.add_argument("--run", required=True)
    for command in (run, results):
        command.add_argument("--judge", choices=["off", "fake", "llm"], default="off", help="Opt in to fake or environment-configured LLM judging; default off")
    export = commands.add_parser("export", help="Export the run, attempts and verdicts as JSON")
    export.add_argument("--run", required=True)
    export.add_argument("--format", choices=["json"], required=True)
    export.add_argument("--output", help="Write UTF-8 JSON to a file instead of stdout")
    imports = commands.add_parser("import", help="Import a saved JSON run; never imports human labels")
    imports.add_argument("--input", required=True)
    sample = commands.add_parser("sample", help="Build a stratified blinded label sample from saved runs")
    sample.add_argument("--run", action="append", help="Repeat for multiple runs; default all saved runs")
    sample.add_argument("--size", type=int, default=100)
    sample.add_argument("--seed", type=int, default=42)
    sample.add_argument("--real-run", action="append", help="Real target run to include; repeat for main and heldout")
    sample.add_argument("--min-real", type=int, default=40, help="Minimum usable real responses when --real-run is supplied")
    label = commands.add_parser("label", help="Label raw responses without seeing judge verdicts")
    agreement = commands.add_parser("agreement", help="Compare rule, LLM and hybrid with human labels (JSON)")
    report = commands.add_parser("report", help="Generate a self-contained client HTML report from a saved run")
    report.add_argument("--run", required=True)
    report.add_argument("--out", required=True, help="New .html output file")
    report.add_argument("--pdf", action="store_true", help="Also create a sibling PDF using Chromium, with optional WeasyPrint fallback")
    report.add_argument("--summary", action="store_true", help="Client summary, at most five PDF pages; omit full appendix and trace dump")
    report.add_argument("--compare", help="Baseline run ID in the same database")
    report.add_argument("--client", default="Client not specified")
    report.add_argument("--suite-name", help="Explicit display name; does not change saved tests")
    report.add_argument("--suite-version", help="Explicit display version; otherwise use saved test-definition hash")
    report.add_argument("--not-tested", action="append", default=[], help="Add a scope exclusion; repeat as needed")
    report.add_argument("--redact-pattern", action="append", default=[], help="Additional secret regex; repeat as needed")
    report.add_argument("--response-limit", type=int, default=2000, help="Maximum response excerpt characters after redaction")
    init = commands.add_parser("init", help="Create starter workspace files without overwriting existing files")
    init.add_argument("directory", nargs="?", default=".")
    purge = commands.add_parser("purge", help="Delete saved run data and dependent records; requires --yes")
    selection = purge.add_mutually_exclusive_group(required=True)
    selection.add_argument("--run")
    selection.add_argument("--older-than", type=float, help="Delete finished runs started more than DAYS ago")
    purge.add_argument("--yes", action="store_true", help="Confirm deletion of the selected run data")
    monitor = commands.add_parser("monitor", help="Run one scheduled, idempotent monitoring cycle")
    monitor.add_argument("--config", required=True)
    monitor.add_argument("--dry-run", action="store_true", help="Run tests but print alerts instead of sending")
    monitor.add_argument("--monthly", action="store_true", help="Report saved runs only; no tests or alerts")
    monitor.add_argument("--month", help="YYYY-MM for monthly reporting; default previous UTC month")
    retention = commands.add_parser("retention", help="Inventory old client data; deletion requires --yes")
    retention.add_argument("--policy", required=True)
    retention.add_argument("--yes", action="store_true")
    retention.add_argument("--out", help="New .html or JSON inventory/deletion receipt")
    commands.add_parser("dashboard", help="Launch optional read-only Streamlit dashboard on loopback")
    for command in (label, agreement):
        selection = command.add_mutually_exclusive_group(required=True)
        selection.add_argument("--run")
        selection.add_argument("--sample")
    for command in (run, results, export, imports, sample, label, agreement, report, purge, monitor, retention):
        command.add_argument("--db", default="chatcheck.db", help="SQLite path (default: chatcheck.db)")
    return root


def main(argv=None):
    # Preserve useful output when redirected through a legacy Windows code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    args = parser().parse_args(argv)
    try:
        if args.command in {"monitor", "retention", "dashboard"}:
            from .monitor_store import secret_redactor
            if args.command == "dashboard":
                from .dashboard import launch
                return launch()
            if args.command == "monitor":
                from .monitor import load_config, cycle
                config = load_config(args.config)
                if args.month and not args.monthly:
                    raise ValueError("--month requires --monthly")
                if args.monthly:
                    from .monitor_monthly import monthly
                    if not Path(args.db).is_file():
                        raise ValueError("Monitoring database not found")
                    result = monthly(config, args.db, month=args.month)
                else:
                    result = asyncio.run(cycle(config, args.db, dry_run=args.dry_run))
            else:
                from .retention import load_policy, retain, write_inventory
                if args.out and Path(args.out).exists():
                    raise ValueError("Retention output already exists")
                result = retain(load_policy(args.policy), args.db, yes=args.yes)
                if args.out:
                    write_inventory(result, args.out)
            print(json.dumps(secret_redactor().tree(result), indent=2, ensure_ascii=True))
            return 2 if result.get("report_error") or any(v == "failed" for v in result.get("alerts", {}).values()) else 0
        if args.command == "freeze":
            from .tuning import freeze_suite, guard_path
            guard = freeze_suite(args.suite, role=args.role, unfreeze=args.unfreeze)
            print(f"Frozen {guard['role']} suite: {args.suite}\nSHA-256: {guard['suite_sha256']}\nAudit: {guard_path(args.suite)}")
            return 0
        if args.command == "revise":
            from .tuning import revise_checks, guard_path
            revise_checks(args.suite, args.test_id, read_json(args.checks), reason=args.reason,
                          review_db=args.review_db, review_run=args.review_run)
            print(f"Recorded human-reviewed MAIN revision: {args.test_id}\nChangelog: {guard_path(args.suite)}")
            return 0
        if args.command == "init":
            from .workspace import init_workspace
            result = init_workspace(args.directory)
            print(f"Workspace: {result['directory']}")
            print("Created: " + (", ".join(result["created"]) or "none"))
            print("Skipped existing: " + (", ".join(result["skipped"]) or "none"))
            return 0
        if args.command == "purge" and not args.yes:
            raise ValueError("Purge requires --yes; no run data was deleted")
        if args.command == "validate":
            print_validation(load_suite(args.suite))
            return 0
        if args.command == "run":
            config = read_json(args.target)
            connector = create_connector(config)
            settings = config.get("runner", {})
            if not isinstance(settings, dict) or set(settings) - set(RunOptions.__dataclass_fields__):
                raise ValueError("runner must be an object containing valid RunOptions fields")
            settings = dict(settings)
            for name in RunOptions.__dataclass_fields__:
                value = getattr(args, name)
                if value is not None:
                    settings[name] = value
            options = RunOptions(**settings)
            tests = load_suite(args.suite)
            with Storage(args.db) as storage:
                evaluator = from_environment(args.judge, storage)
                run_id = asyncio.run(run_suite(tests, connector, storage, options, target_name=config.get("name", config["type"]), suite_path=args.suite, llm_judge=evaluator))
                result = storage.results(run_id)
            print_results(result)
            if args.judge != "off":
                return 1 if any(t["combined_verdict"]["verdict"] != "pass" for t in result["tests"]) else 0
            return 1 if result["summary"]["failed"] else 0
        if args.command != "import" and not Path(args.db).is_file():
            raise ValueError(f"Database not found: {args.db}")
        with Storage(args.db) as storage:
            if args.command == "purge":
                result = storage.purge(run_id=args.run, older_than=args.older_than, confirmed=args.yes)
                print("Deleted records:")
                for table, count in result["deleted"].items():
                    print(f"  {table}: {count}")
                print(f"Samples updated: {result['samples_updated']}")
                return 0
            if args.command == "report":
                from .report import Redactor, write_report
                from .monitor_store import register_artifact
                run = storage.results(args.run)
                comparison = storage.results(args.compare) if args.compare else None
                print(write_report(run, args.out, pdf=args.pdf, summary=args.summary, client=args.client, compare=comparison,
                                   suite_name=args.suite_name, suite_version=args.suite_version, not_tested=args.not_tested,
                                   redactor=Redactor.from_environment(args.redact_pattern), response_limit=args.response_limit))
                for path in ([Path(args.out), Path(args.out).with_suffix(".pdf")] if args.pdf else [Path(args.out)]):
                    if path.is_file():
                        register_artifact(storage, path, run_id=args.run, kind="report")
                return 0
            if args.command == "import":
                print("Imported run: " + storage.import_run(read_json(args.input)))
                return 0
            if args.command == "sample":
                sample_id, metadata = build_sample(storage, args.run, size=args.size, seed=args.seed,
                                                   real_run_ids=args.real_run, min_real=args.min_real if args.real_run else 0)
                print(f"Sample: {sample_id} ({metadata['size']} items, {len(metadata['mandatory'])} mandatory)")
                return 0
            if args.command in {"label", "agreement"}:
                tests = storage.sample_tests(args.sample) if args.sample else storage.results(args.run)["tests"]
                if args.command == "label":
                    count = label_items(storage, tests)
                    print(f"Saved {count} human labels. Existing labels are skipped on resume.")
                else:
                    print(json.dumps(agreement_report(tests), ensure_ascii=True, indent=2))
                return 0
            if args.command == "results" and args.judge != "off":
                asyncio.run(judge_saved_run(storage, args.run, from_environment(args.judge, storage)))
            result = storage.results(args.run)
        if args.command == "results":
            print_results(result)
        else:
            payload = json.dumps(result, indent=2)
            if args.output:
                # Avoid truncating a database or an existing export accidentally.
                with Path(args.output).open("x", encoding="utf-8") as stream:
                    stream.write(payload + "\n")
                from .monitor_store import register_artifact
                with Storage(args.db) as storage:
                    register_artifact(storage, args.output, run_id=args.run, kind="export")
            else:
                print(payload)
        return 0
    except KeyboardInterrupt:
        print("Run cancelled; partial results were retained.", file=sys.stderr)
        return 130
    except (ValueError, OSError, sqlite3.Error, TypeError) as exc:
        if args.command in {"monitor", "retention", "dashboard"}:
            from .monitor_store import secret_redactor
            try:
                diagnostic = secret_redactor().text(f"Error: {exc}")
            except Exception:
                diagnostic = "Monitoring configuration invalid; diagnostic values withheld"
            print(diagnostic, file=sys.stderr)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Engine error ({type(exc).__name__}). Check target setup; for widgets run: python -m playwright install chromium", file=sys.stderr)
        return 2
