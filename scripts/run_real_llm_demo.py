"""Run each saved test at most once against an explicitly enabled real target."""

import argparse
import hashlib
import json
import math
import os
import sys
import time
from itertools import zip_longest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chatcheck.false_failures import write_candidates
from chatcheck.judge import judge
from chatcheck.labeling import build_sample
from chatcheck.models import RunOptions, load_suite, read_json
from chatcheck.report import Redactor, pdf_bytes, render_report, score_rows, scores
from chatcheck.storage import Storage
from demo_bots.meher_threads.budget import BudgetStop
from demo_bots.meher_threads.llm import LLMBot, UpstreamError

SUITES = (ROOT / "suites/clothing_store.json", ROOT / "suites/clothing_store_heldout.json")


def execute(storage, bot, plans, *, pace=1.0, sleep=time.sleep, write=print):
    """Serial, no retries; durable reservations precede every network call."""
    pending = []
    for plan in plans:
        saved = {test["test_key"]: test for test in storage.results(plan["run_id"])["tests"]}
        group = []
        for case in plan["cases"]:
            test = saved[case.id]
            if test["responses"]:
                if test["verdict"] is None:  # recover a crash after response commit
                    last = test["responses"][-1]
                    storage.record_verdict(test["id"], judge(last["text"], case.checks, last["error"]))
                continue
            group.append((plan["run_id"], test["id"], case))
        pending.append(group)
    schedule = [item for row in zip_longest(*pending) for item in row if item is not None]
    stop = None
    consecutive_errors = 0
    for run_id, test_id, case in schedule:
        if stop is not None:
            storage.mark_not_run(run_id, [case.id], stop)
            continue
        if bot.budget.calls >= bot.budget.max_calls:
            stop = "Target call budget exhausted"
            storage.mark_not_run(run_id, [case.id], stop)
            continue
        start = time.monotonic()
        text, error = None, None
        try:
            text = bot.reply(case.prompt, request_id=f"{run_id}:{case.id}")
            consecutive_errors = 0
        except BudgetStop as exc:
            storage.mark_not_run(run_id, [case.id], str(exc))
            continue
        except UpstreamError as exc:
            error = str(exc)
            consecutive_errors += 1
            if exc.status in {400, 401, 403, 404, 429} or consecutive_errors >= 3:
                stop = error + "; remaining tests not run"
        storage.record_attempt(test_id, 1, text, (time.monotonic() - start) * 1000, error)
        storage.record_verdict(test_id, judge(text, case.checks, error))
        write(f"Target reservations: {bot.budget.calls}/{bot.budget.max_calls}")
        if pace and stop is None:
            sleep(pace)
    for plan in plans:
        result = storage.results(plan["run_id"])
        skipped = result["execution_summary"]["not_run"]
        errors = any(test["responses"] and test["responses"][-1]["error"] for test in result["tests"])
        storage.finish_run(plan["run_id"], "partial" if skipped else "completed_with_errors" if errors else "completed", stop)


def print_summary(run):
    from chatcheck.scoring import coverage_scores
    coverage = coverage_scores(run["tests"])
    print(f"\n{Path(run['suite_path']).name} | run {run['id']}")
    print(f"{'Group':<25} {'Pass/Resp':>10} {'Fail':>5} {'Errors':>6} {'No resp':>7} {'Score':>8}")
    for row in [{"name": "Overall", **coverage["responses_only"], "errors": coverage["errors"], "not_run": coverage["not_run"]},
                *score_rows(run["tests"], "category", response_only=True), *score_rows(run["tests"], "language", response_only=True)]:
        fraction = f"{row['passed']}/{row['total']}"
        print(f"{row['name']:<25} {fraction:>10} {row['failed']:>5} {row['errors']:>6} {row['not_run']:>7} {row['display']:>8}")
    errors = sum(bool(test["responses"]) and bool(test["responses"][-1]["error"]) for test in run["tests"])
    print(f"Not run: {run['execution_summary']['not_run']}; connector errors: {errors}; status: {run['status']}")
    for label, key in (("Response-only score", "responses_only"), ("Errors counted as not-run", "errors_as_not_run")):
        score = coverage[key]
        print(f"{label}: {score['passed']}/{score['total']} ({score['display']}); {score['failed']} behavior failures, {score['pending']} not-run or unjudged")


def prepare(storage, manifest_path, bot):
    signature = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in SUITES}
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        if manifest["suites"] != signature or manifest["target"] != bot.metadata():
            raise ValueError("Saved real-run inputs differ; resume with the original configuration")
        for run_id in manifest["run_ids"]:
            storage.results(run_id)  # never recreate runs with missing saved data
        return manifest
    if bot.budget.calls or storage.list_runs():
        raise ValueError("Missing manifest for existing real-run data; refusing to create replacement runs")
    run_ids = []
    for path in SUITES:
        run_id, _ = storage.start_run(load_suite(path), f"Meher Threads real {bot.provider} / {bot.model}",
                                      str(path.relative_to(ROOT)), RunOptions(concurrency=1, retries=0))
        with storage.connection:
            options = RunOptions(concurrency=1, retries=0).to_dict()
            options["target_llm"] = bot.metadata()
            storage.connection.execute("UPDATE runs SET options_json=? WHERE id=?", (json.dumps(options), run_id))
        run_ids.append(run_id)
    manifest = {"version": 1, "suites": signature, "target": bot.metadata(), "run_ids": run_ids}
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
    return manifest


def artifacts(storage, manifest, directory, bot, *, update_budget=True):
    runs = [storage.results(key) for key in manifest["run_ids"]]
    redactor = Redactor.from_environment()
    write_candidates(runs, directory, redactor=redactor)
    for name, run in zip(("main", "heldout"), runs):
        # This script owns these exact output paths; refresh on a resumed run.
        rendered = render_report(run, client="Meher Threads", redactor=redactor,
                                 not_tested=["This is one sampled response per test from one configured model; repeated sampling and other models were not tested."])
        (directory / f"{name}.html").write_text(rendered, encoding="utf-8")
        try:
            binary = pdf_bytes(rendered)
        except Exception:
            print("PDF unavailable: install Playwright Chromium or the optional WeasyPrint dependencies. HTML is saved.")
            # Remove only this script's stale PDF if the current report failed.
            (directory / f"{name}.pdf").unlink(missing_ok=True)
        else:
            (directory / f"{name}.pdf").write_bytes(binary)
        print_summary(run)
    archive = ROOT / "reports/meher_threads/mutation/final"
    for path in sorted(archive.glob("*.json")):
        data = read_json(path)
        if isinstance(data, dict) and data.get("target_name") and data.get("tests"):
            storage.import_run(data)
    try:
        if "sample_id" not in manifest:
            sample_id, metadata = build_sample(storage, size=100, seed=42,
                                                real_run_ids=manifest["run_ids"], min_real=40)
            manifest["sample_id"] = sample_id
            manifest["sample_metadata"] = metadata
        print(f"Blinded sample: {manifest['sample_id']} (no labels created)")
    except ValueError as exc:
        print(f"Label sample not created: {exc}")
    if update_budget:
        manifest["reserved_calls"] = bot.budget.calls
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return runs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="Authorize the configured real target calls")
    parser.add_argument("--out", type=Path, default=ROOT / "reports/real_llm")
    args = parser.parse_args(argv)
    max_calls = int(os.environ.get("MEHER_LLM_MAX_CALLS", "96"))
    max_tokens = int(os.environ.get("MEHER_LLM_MAX_OUTPUT_TOKENS", "512"))
    pace = float(os.environ.get("MEHER_LLM_PACE_SECONDS", "4"))
    print(f"Maximum real target calls: {max_calls} total across both suites and reruns; max output tokens per call: {max_tokens}.")
    if not args.yes:
        parser.error("Real calls require explicit --yes; no calls or files were created")
    if not math.isfinite(pace) or pace < 0:
        parser.error("MEHER_LLM_PACE_SECONDS must be finite and nonnegative")
    directory = args.out.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    bot = LLMBot(budget_path=directory / "target-budget.db", budget_session="real-demo-v1", raw_evaluation=True)
    try:
        print(f"Target: {bot.provider} / {bot.model}; reservations already used: {bot.budget.calls}/{max_calls}. No retries.")
        with Storage(directory / "runs.db") as storage:
            manifest = prepare(storage, directory / "manifest.json", bot)
            plans = [{"run_id": key, "cases": load_suite(path)} for key, path in zip(manifest["run_ids"], SUITES)]
            execute(storage, bot, plans, pace=pace)
            runs = artifacts(storage, manifest, directory, bot)
            return 0 if all(run["status"] == "completed" for run in runs) else 1
    finally:
        bot.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, UpstreamError):
        # Never print upstream exceptions, URLs, request objects or env values.
        print("Real demo stopped: check environment configuration and saved manifest. No automatic retry was made.", file=sys.stderr)
        raise SystemExit(2)
