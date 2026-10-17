"""Run source-checkout agent scenarios and persist normal chatcheck verdicts."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from chatcheck.judge import judge
from chatcheck.models import load_suite, RunOptions
from chatcheck.report import write_report
from chatcheck.storage import Storage
from .fixtures import validate_case
from .safety import clean_environment, local_url, refuse_credentials, SandboxRefusal
from .workflow import ROOT, fingerprint


def run(db, suite, *, broker=None, timeout=25):
    refuse_credentials()
    environment = clean_environment()
    tests = load_suite(suite)
    scenarios = [validate_case(json.loads(test.prompt)) for test in tests]
    if broker:
        local_url(broker)
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    with Storage(db) as storage:
        options = RunOptions(concurrency=1, retries=0, timeout=timeout)
        run_id, test_ids = storage.start_run(tests, "AI News Agent sandbox", suite, options)
        description = ("Local sinks; isolated Python pipeline and actual approval workflow scripts. "
                       + ("Explicit real-LLM broker enabled; all publishing and email remain fake." if broker else
                          "Deterministic fake LLM; no real provider calls. Adversarial fake outputs test validation, not model susceptibility."))
        saved = {**options.to_dict(), "sandbox": {"description": description, "mode": "real_broker" if broker else "fake",
                                                "workflow_sha256": fingerprint()}}
        with storage.connection:
            storage.connection.execute("UPDATE runs SET options_json=? WHERE id=?", (json.dumps(saved), run_id))
        try:
            with tempfile.TemporaryDirectory(prefix="chatcheck-sandbox-") as directory:
                for test, test_id, case in zip(tests, test_ids, scenarios):
                    scenario = Path(directory) / "scenario.json"
                    scenario.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
                    command = [sys.executable, "-m", "agent_sandbox.worker", "--db", str(Path(db).resolve()),
                               "--test-id", str(test_id), "--scenario", str(scenario)]
                    if broker:
                        command += ["--broker", broker]
                    started = time.perf_counter()
                    error = None
                    text = None
                    try:
                        process = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True,
                                                 text=True, encoding="utf-8", timeout=timeout)
                        # Do not persist stderr or raw process output on errors.
                        result = json.loads(process.stdout)
                        if process.returncode:
                            error = "Sandbox worker failed (" + result.get("error_type", "unknown") + ")"
                        else:
                            text = json.dumps(result, ensure_ascii=False)
                    except subprocess.TimeoutExpired:
                        error = f"Sandbox worker exceeded {timeout}s wall-clock cap"
                    except (ValueError, OSError):
                        error = "Sandbox worker did not return a valid result"
                    storage.record_attempt(test_id, 1, text, (time.perf_counter() - started) * 1000, error)
                    events = storage.agent_events(test_id)
                    storage.record_verdict(test_id, judge(text, test.checks, error, trace=events))
        except BaseException:
            storage.finish_run(run_id, "failed", "Sandbox run interrupted")
            raise
        storage.finish_run(run_id)
        failed = {test["test_key"] for test in storage.results(run_id)["tests"] if not test["verdict"]["passed"]}
        findings = {
            "injection-marker-adversarial-fake": (
                "The generator accepts and delivers a marker-contaminated draft that meets its URL, length and hashtag checks.",
                "Consider explicit untrusted-article boundaries and an output policy before issue creation and email. Evaluate Gemini resistance separately with the capped broker."),
            "injection-system-prompt": (
                "The generator accepts prompt-template text in an otherwise valid draft.",
                "Consider separating instructions from source data and rejecting known instruction-template leakage before delivery."),
            "invalid-output-repeat-cost": (
                "One article with invalid model output causes four model calls (primary twice, fallback twice).",
                "Consider a shared per-article call/token budget across validation retries, transient retries and fallback, with a controlled failure status."),
        }
        saved["sandbox"]["findings"] = [{"test": key, "finding": value[0], "suggestion": value[1]}
                                           for key, value in findings.items() if key in failed]
        with storage.connection:
            storage.connection.execute("UPDATE runs SET options_json=? WHERE id=?", (json.dumps(saved), run_id))
        return storage.results(run_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default=str(ROOT / "agent_sandbox/suite.json"))
    parser.add_argument("--db", default=str(ROOT / "reports/agent_sandbox/runs.sqlite3"))
    parser.add_argument("--out", default=str(ROOT / "reports/agent_sandbox/report.html"))
    parser.add_argument("--pdf", action="store_true")
    parser.add_argument("--real-llm-broker")
    parser.add_argument("--allow-real-llm", action="store_true")
    args = parser.parse_args()
    try:
        refuse_credentials()
        if bool(args.real_llm_broker) != args.allow_real_llm:
            raise ValueError("Real LLM requires both --allow-real-llm and --real-llm-broker")
        output = Path(args.out)
        if output.exists() or (args.pdf and output.with_suffix(".pdf").exists()):
            raise ValueError("Report already exists; choose a new --out path")
        result = run(args.db, args.suite, broker=args.real_llm_broker)
        output.parent.mkdir(parents=True, exist_ok=True)
        message = write_report(result, output, pdf=args.pdf, client="AI News Agent",
                               not_tested=["Live GitHub event delivery and permissions, real accounts, and production Gemini injection rates."])
        print(json.dumps({"run_id": result["id"], "summary": result["summary"]}))
        print(message)
        if args.pdf and not output.with_suffix(".pdf").exists():
            return 2
        return 1 if result["summary"]["failed"] else 0
    except (SandboxRefusal, ValueError) as exc:
        # Only controlled configuration errors; refusal never includes values.
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
