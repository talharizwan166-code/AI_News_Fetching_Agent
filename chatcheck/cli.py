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
    summary = result["summary"]
    print(f"{summary['passed']} passed, {summary['failed']} failed, {summary['pending']} pending / {summary['total']} tests")


def print_validation(tests):
    print(f"Valid suite: {len(tests)} tests")
    for name, allowed in (("category", CATEGORIES), ("language", LANGUAGES), ("severity", SEVERITIES)):
        counts = Counter(getattr(test, name) or "unspecified" for test in tests)
        print(f"{name.capitalize()}:")
        for value in (*allowed, "unspecified"):
            print(f"  {value}: {counts[value]}")


def parser():
    root = argparse.ArgumentParser(prog="chatcheck", description="Run deterministic chatbot checks and store results in SQLite.")
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
    export = commands.add_parser("export", help="Export the run, attempts and verdicts as JSON")
    export.add_argument("--run", required=True)
    export.add_argument("--format", choices=["json"], required=True)
    export.add_argument("--output", help="Write UTF-8 JSON to a file instead of stdout")
    for command in (run, results, export):
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
                run_id = asyncio.run(run_suite(tests, connector, storage, options, target_name=config.get("name", config["type"]), suite_path=args.suite))
                result = storage.results(run_id)
            print_results(result)
            return 1 if result["summary"]["failed"] else 0
        if not Path(args.db).is_file():
            raise ValueError(f"Database not found: {args.db}")
        with Storage(args.db) as storage:
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
