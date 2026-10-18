"""Retest two immutable source revisions with one retrospective v2 harness."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

from chatcheck.judge import judge
from chatcheck.models import load_suite, RunOptions
from chatcheck.report import compare_runs, suite_snapshot, write_report
from chatcheck.storage import Storage
from .fixtures import validate_case
from .safety import clean_environment, refuse_credentials, SandboxRefusal

ROOT = Path(__file__).resolve().parents[1]
DISCLOSURE = "V2 was written AFTER seeing frozen-suite results. It is not an independent benchmark."


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_hashes():
    manifest = json.loads((ROOT / "reports/agent_sandbox/phase5b-frozen-inputs.json").read_text())
    for name, expected in manifest.items():
        if digest(ROOT / name.replace("\\", "/")) != expected:
            raise ValueError("Frozen Phase 5 input changed; comparison refused")
    return manifest


def git(*args):
    result = subprocess.run(["git", "-c", "safe.directory=" + ROOT.as_posix(), *args],
                            cwd=ROOT, env=clean_environment(), capture_output=True)
    if result.returncode:
        raise ValueError("Could not read the requested local Git revision")
    return result.stdout


def export_target(revision, destination):
    """Export only tracked target code; never copy dotenv, accounts or Git config."""
    commit = git("rev-parse", "--verify", revision + "^{commit}").decode().strip()
    archive = git("archive", "--format=tar", commit, "src", ".github/workflows/linkedin_approve.yml")
    destination.mkdir()
    source_hashes = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as source:
        for member in source.getmembers():
            if member.isdir():
                continue
            relative = Path(member.name)
            if (not member.isfile() or relative.is_absolute() or ".." in relative.parts
                    or not (relative.parts[0] == "src" or member.name == ".github/workflows/linkedin_approve.yml")):
                raise ValueError("Unexpected target archive entry")
            output = destination / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(source.extractfile(member).read())
            source_hashes[member.name] = digest(output)
    harness_hashes = {}
    for package in ("agent_sandbox", "chatcheck"):
        for path in sorted((ROOT / package).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix not in {".py", ".json", ".html", ".css"}:
                continue
            relative = path.relative_to(ROOT)
            output = destination / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, output)
            harness_hashes[relative.as_posix()] = digest(output)
    return {"revision": commit, "source_sha256": source_hashes, "harness_sha256": harness_hashes}


def run_target(db, suite, target_root, provenance, timeout=25):
    refuse_credentials()
    tests = load_suite(suite)
    scenarios = [validate_case(json.loads(test.prompt)) for test in tests]
    environment = clean_environment()
    with Storage(db) as storage:
        options = RunOptions(concurrency=1, retries=0, timeout=timeout)
        run_id, test_ids = storage.start_run(tests, "AI News Agent v2 sandbox", str(suite), options)
        saved = {**options.to_dict(), "sandbox": {
            "description": DISCLOSURE + " Same deterministic fake LLM and local sinks for both Git source exports. "
                           "Target revision: " + provenance["revision"],
            "mode": "fake", "retrospective": True, "independent_benchmark": False,
            "suite_sha256": digest(suite), **provenance}}
        with storage.connection:
            storage.connection.execute("UPDATE runs SET options_json=? WHERE id=?", (json.dumps(saved), run_id))
        try:
            with tempfile.TemporaryDirectory(prefix="v2-cases-") as directory:
                for test, test_id, case in zip(tests, test_ids, scenarios):
                    scenario = Path(directory) / "scenario.json"
                    scenario.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
                    started = time.perf_counter()
                    response = error = None
                    try:
                        process = subprocess.run(
                            [sys.executable, "-m", "agent_sandbox.worker_v2", "--db", str(db),
                             "--test-id", str(test_id), "--scenario", str(scenario)],
                            cwd=target_root, env=environment, capture_output=True, text=True,
                            encoding="utf-8", timeout=timeout)
                        result = json.loads(process.stdout)
                        if process.returncode:
                            error = "V2 worker failed; raw output withheld"
                        else:
                            response = json.dumps(result, ensure_ascii=False)
                    except subprocess.TimeoutExpired:
                        error = "V2 worker exceeded wall-clock cap"
                    except (ValueError, OSError):
                        error = "V2 worker did not return a valid result"
                    storage.record_attempt(test_id, 1, response, (time.perf_counter() - started) * 1000, error)
                    verdict = judge(response, test.checks, error, trace=storage.agent_events(test_id))
                    storage.record_verdict(test_id, verdict)
                    print(json.dumps({"revision": provenance["revision"][:7], "case": test.id,
                                      "passed": verdict.passed}), flush=True)
        except BaseException:
            storage.finish_run(run_id, "failed", "V2 comparison interrupted")
            raise
        storage.finish_run(run_id)
        return storage.results(run_id)


def verification(before, after):
    comparison = compare_runs(after, before)
    rows = []
    for old, new in zip(before["tests"], after["tests"]):
        def counts(test):
            events = test["agent_behavior"]
            return {"llm_calls": sum(e["action"] == "llm_call" and e["status"] != "blocked" for e in events),
                    "deliveries": sum(e["action"] in {"issue_created", "email_sent", "post_published"} for e in events),
                    "rejections": [e["arguments"]["reason"] for e in events if e["action"] == "draft_rejected"],
                    "passed": test["verdict"]["passed"], "reason": test["verdict"]["reason"]}
        rows.append({"case": new["test_key"], "before": counts(old), "after": counts(new)})
    return {"disclosure": DISCLOSURE, "before_run": before["id"], "after_run": after["id"],
            "comparison": comparison, "identical_test_snapshots": suite_snapshot(before) == suite_snapshot(after),
            "worker_errors": sum(bool(t["responses"][-1]["error"]) for run in (before, after) for t in run["tests"]),
            "benign_failures": [t["test_key"] for t in after["tests"] if not t["verdict"]["passed"]
                                and any(c["type"] == "must_deliver" for c in t["checks"])], "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", default="0bfb2f1")
    parser.add_argument("--after", default="e7726b0")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--pdf", action="store_true")
    args = parser.parse_args()
    refuse_credentials()
    frozen = frozen_hashes()
    output = Path(args.out_dir).resolve()
    if output.exists():
        raise ValueError("Output directory already exists; choose a new directory")
    output.mkdir(parents=True)
    suite = ROOT / "agent_sandbox/suite_v2.json"
    with tempfile.TemporaryDirectory(prefix="v2-source-") as directory:
        targets = [Path(directory) / name for name in ("before", "after")]
        provenance = [export_target(rev, dest) for rev, dest in zip((args.before, args.after), targets)]
        if provenance[0]["harness_sha256"] != provenance[1]["harness_sha256"]:
            raise ValueError("Harness changed during export")
        (output / "provenance.json").write_text(json.dumps({"disclosure": DISCLOSURE, "frozen": frozen,
            "suite_sha256": digest(suite), "before": provenance[0], "after": provenance[1]}, indent=2) + "\n")
        before, after = [run_target(output / "runs.sqlite3", suite, target, prov)
                         for target, prov in zip(targets, provenance)]
    evidence = verification(before, after)
    evidence["frozen_inputs_unchanged"] = frozen_hashes() == frozen
    (output / "verification.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    for name, run, baseline, summary in (("before", before, None, False), ("after", after, None, False),
                                         ("comparison", after, before, False), ("summary", after, before, True)):
        print(write_report(run, output / (name + ".html"), pdf=args.pdf, summary=summary, compare=baseline,
                           client="AI News Agent", suite_name="Retrospective delivery checks v2", suite_version="2.0",
                           not_tested=[DISCLOSURE, "Live Gemini susceptibility and real accounts; no added attack scenarios."]), flush=True)
        if args.pdf and not (output / (name + ".pdf")).exists():
            raise ValueError("PDF generation failed; HTML and saved runs remain available")
    print(json.dumps({"before_run": before["id"], "after_run": after["id"], "comparison": evidence["comparison"]}))
    return 0 if not evidence["worker_errors"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SandboxRefusal, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
