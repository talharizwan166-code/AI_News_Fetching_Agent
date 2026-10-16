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
        label = "PENDING" if verdict is None else "PASS" if verdict["passed"] else "FAIL"
        latency = test["responses"][-1]["latency_ms"] if test["responses"] else 0
        reason = verdict["reason"] if verdict else "No verdict recorded"
        category = test.get("category") or "unspecified"
        severity = test.get("severity") or "unspecified"
        print(f"{label:7} {test['test_key']}  category={category} severity={severity}  {latency:.1f} ms  {reason}")
        if test.get("llm_verdict"):
            llm, combined = test["llm_verdict"], test["combined_verdict"]
            flag = " DISAGREEMENT: human review" if combined["disagreement"] else " REVIEW" if combined["review"] else ""
            print(f"        rule={label.lower()} llm={llm.get('verdict') or 'not judged'} hybrid={combined['verdict']}{flag}; {llm['reason']}")
    summary = result["summary"]
    print(f"{summary['passed']} passed, {summary['failed']} failed, {summary['pending']} pending / {summary['total']} tests")
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
    label = commands.add_parser("label", help="Label raw responses without seeing judge verdicts")
    agreement = commands.add_parser("agreement", help="Compare rule, LLM and hybrid with human labels (JSON)")
    report = commands.add_parser("report", help="Generate a self-contained client HTML report from a saved run")
    report.add_argument("--run", required=True)
    report.add_argument("--out", required=True, help="New .html output file")
    report.add_argument("--pdf", action="store_true", help="Also create a sibling PDF when WeasyPrint is available")
    report.add_argument("--compare", help="Baseline run ID in the same database")
    report.add_argument("--client", default="Client not specified")
    report.add_argument("--suite-name", help="Explicit display name; does not change saved tests")
    report.add_argument("--suite-version", help="Explicit display version; otherwise use saved test-definition hash")
    report.add_argument("--not-tested", action="append", default=[], help="Add a scope exclusion; repeat as needed")
    report.add_argument("--redact-pattern", action="append", default=[], help="Additional secret regex; repeat as needed")
    report.add_argument("--response-limit", type=int, default=2000, help="Maximum response excerpt characters after redaction")
    for command in (label, agreement):
        selection = command.add_mutually_exclusive_group(required=True)
        selection.add_argument("--run")
        selection.add_argument("--sample")
    for command in (run, results, export, imports, sample, label, agreement, report):
        command.add_argument("--db", default="chatcheck.db", help="SQLite path (default: chatcheck.db)")
    return root


def main(argv=None):
    # Preserve useful output when redirected through a legacy Windows code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    args = parser().parse_args(argv)
    try:
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
            if args.command == "report":
                from .report import Redactor, write_report
                run = storage.results(args.run)
                comparison = storage.results(args.compare) if args.compare else None
                print(write_report(run, args.out, pdf=args.pdf, client=args.client, compare=comparison,
                                   suite_name=args.suite_name, suite_version=args.suite_version, not_tested=args.not_tested,
                                   redactor=Redactor.from_environment(args.redact_pattern), response_limit=args.response_limit))
                return 0
            if args.command == "import":
                print("Imported run: " + storage.import_run(read_json(args.input)))
                return 0
            if args.command == "sample":
                sample_id, metadata = build_sample(storage, args.run, size=args.size, seed=args.seed)
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
            else:
                print(payload)
        return 0
    except KeyboardInterrupt:
        print("Run cancelled; partial results were retained.", file=sys.stderr)
        return 130
    except (ValueError, OSError, sqlite3.Error, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Engine error ({type(exc).__name__}). Check target setup; for widgets run: python -m playwright install chromium", file=sys.stderr)
        return 2
