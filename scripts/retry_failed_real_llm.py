"""Explicitly capped, error-only retries in the original saved real-target runs."""

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chatcheck.models import load_suite, read_json
from chatcheck.scoring import has_response
from chatcheck.storage import Storage
from demo_bots.meher_threads.budget import BudgetStop, TargetBudget
from demo_bots.meher_threads.llm import LLMBot, UpstreamError
from scripts.run_real_llm_demo import SUITES, artifacts

SESSION = "connection-retry-v1"


def eligible(test):
    responses = test.get("responses", [])
    return bool(responses and responses[-1].get("error")
                and not any(isinstance(row.get("text"), str) and (not row.get("error") or row["text"].strip()) for row in responses))


def retry_errors(storage, bot, run_ids, *, session=SESSION, pace=4, sleep=time.sleep, write=print):
    completed = 0
    stop = None
    consecutive_errors = 0
    for run_id in run_ids:
        for test in storage.results(run_id)["tests"]:
            if stop or not eligible(test):
                continue
            if bot.budget.calls >= bot.budget.max_calls:
                stop = "Retry call budget exhausted; remaining errors retain their original attempts"
                break
            event = storage.reserve_target_retry(test["id"], session)
            if event is None:
                continue
            start = time.monotonic()
            text, error = None, None
            try:
                text = bot.reply(event["prompt"], request_id="retry:" + event["id"])
                consecutive_errors = 0
            except BudgetStop as exc:
                storage.finish_target_retry(run_id, event["id"], None, 0, str(exc), sent=False)
                stop = str(exc)
                continue
            except UpstreamError as exc:
                error = str(exc)
                consecutive_errors += 1
                if exc.status in {400, 401, 403, 404, 429} or consecutive_errors >= 3:
                    stop = error + "; no further retry calls sent"
            storage.finish_target_retry(run_id, event["id"], text, (time.monotonic() - start) * 1000, error)
            completed += 1
            write(f"Retry reservations: {bot.budget.calls}/{bot.budget.max_calls}; saved attempt {event['attempt']}")
            if pace and stop is None:
                sleep(pace)
        result = storage.results(run_id)
        errors = result["coverage_scores"]["errors"]
        pending = result["summary"]["pending"]
        storage.finish_run(run_id, "partial" if pending else "completed_with_errors" if errors else "completed",
                           "Remaining connector/provider errors" if errors else None)
    if stop:
        write(stop)
    return completed


def refresh_sample(storage, manifest):
    if "sample_id" not in manifest:
        return
    tests = storage.sample_tests(manifest["sample_id"])
    row = storage.connection.execute("SELECT metadata_json FROM label_samples WHERE id=?", (manifest["sample_id"],)).fetchone()
    metadata = json.loads(row[0])
    metadata["real_items"] = sum(test["run_id"] in manifest["run_ids"] and has_response(test) for test in tests)
    with storage.connection:
        storage.connection.execute("UPDATE label_samples SET metadata_json=? WHERE id=?", (json.dumps(metadata), manifest["sample_id"]))
    manifest["sample_metadata"] = metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="Authorize additional real target calls")
    parser.add_argument("--max-calls", type=int, required=True, default=12,
                        help="Explicit cumulative retry cap across reruns; suggested/default value: 12")
    parser.add_argument("--out", type=Path, default=ROOT / "reports/real_llm", help="Existing real-demo directory")
    parser.add_argument("--run", action="append", help="Limit to a manifest run; repeat to select both")
    args = parser.parse_args(argv)
    print(f"Maximum additional target calls: {args.max_calls} across this retry batch and all its reruns.")
    if not args.yes:
        parser.error("Retries require --yes and an explicit --max-calls; no calls or files were created")
    if args.max_calls < 0:
        parser.error("--max-calls must be nonnegative")
    pace = float(os.environ.get("MEHER_LLM_PACE_SECONDS", "4"))
    if not math.isfinite(pace) or pace < 0:
        parser.error("MEHER_LLM_PACE_SECONDS must be finite and nonnegative")
    directory = args.out.resolve()
    manifest = read_json(directory / "manifest.json")
    run_ids = list(dict.fromkeys(args.run or manifest["run_ids"]))
    if not set(run_ids) <= set(manifest["run_ids"]):
        raise ValueError("Retry selection must belong to the saved real-target manifest")
    if not (directory / "runs.db").is_file() or not (directory / "target-budget.db").is_file():
        raise ValueError("Original real-run database and call ledger are required")
    for suite in SUITES:
        load_suite(suite)  # enforce the held-out freeze before any target calls
    with sqlite3.connect((directory / "target-budget.db").as_uri() + "?mode=ro", uri=True) as original:
        original_cap = original.execute("SELECT max_output_tokens, signature FROM budgets WHERE session='real-demo-v1'").fetchone()
        if original_cap is None:
            raise ValueError("Original target budget not found")
        if original_cap[1] != hashlib.sha256(json.dumps(manifest["target"], sort_keys=True).encode()).hexdigest():
            raise ValueError("Manifest target differs from the original immutable call ledger")
    metadata = {"target": manifest["target"], "run_ids": manifest["run_ids"], "purpose": "error-only-retry-v1"}
    budget = TargetBudget(directory / "retry-budget.db", SESSION, metadata,
                          max_calls=args.max_calls, max_output_tokens=original_cap[0])
    bot = None
    try:
        bot = LLMBot(budget=budget, raw_evaluation=True)
        if bot.metadata() != manifest["target"]:
            raise ValueError("Retry target differs from the original provider/model/system prompt")
        print(f"Previously reserved retry calls: {budget.calls}/{budget.max_calls}; output cap: {budget.max_output_tokens}. Original ledger unchanged.")
        with Storage(directory / "runs.db") as storage:
            for key in run_ids:
                if storage.results(key)["options"].get("target_llm") != manifest["target"]:
                    raise ValueError("Saved run target provenance does not match the manifest")
            before = {key: storage.results(key)["coverage_scores"] for key in run_ids}
            retry_errors(storage, bot, run_ids, pace=pace)
            after = {key: storage.results(key)["coverage_scores"] for key in run_ids}
            retry_state = manifest.setdefault("retry", {})
            retry_state.setdefault("scores_before_first_retry", before)
            retry_state.update(session=SESSION, max_calls=budget.max_calls, reserved_calls=budget.calls,
                               scores_before_latest_invocation=before, scores_after=after)
            refresh_sample(storage, manifest)
            artifacts(storage, manifest, directory, bot, update_budget=False)
            return 1 if any(storage.results(key)["coverage_scores"]["errors"] for key in run_ids) else 0
    finally:
        if bot is not None:
            bot.close()
        budget.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Retry interrupted; saved attempts and reservations remain. No automatic replay.", file=sys.stderr)
        raise SystemExit(130)
    except (ValueError, OSError, sqlite3.Error, UpstreamError):
        print("Retry stopped: check the original manifest, environment, frozen suites and persistent cap. No automatic replay was made.", file=sys.stderr)
        raise SystemExit(2)
