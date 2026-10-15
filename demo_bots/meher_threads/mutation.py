"""Measure single-bug detection over HTTP; retain SQLite, JSON and Markdown evidence."""

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from chatcheck.connectors import create_connector
from chatcheck.models import RunOptions, load_suite
from chatcheck.runner import run_suite
from chatcheck.storage import Storage
from .bot import StoreBot
from .knowledge import ROOT, DEFAULT_FAQ, DEFAULT_PRIVATE
from .mutants import MutantBot, METADATA_PATH, mutant_metadata
from .server import background_server

DEFAULT_SUITE = ROOT / "suites/clothing_store.json"


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fingerprints(suite, heldout=None):
    paths = {Path(suite).resolve(), DEFAULT_FAQ, DEFAULT_PRIVATE, METADATA_PATH,
             ROOT / "scripts/build_chatcheck_library.py",
             *Path(__file__).parent.glob("*.py"), * (ROOT / "chatcheck").rglob("*.py")}
    if heldout:
        paths.add(Path(heldout).resolve())
    # Canonical newlines keep the audit portable across Git's Windows/Unix checkouts.
    return {p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else p.as_posix():
            hashlib.sha256(p.read_text(encoding="utf-8").encode("utf-8")).hexdigest() for p in sorted(paths)}


def freeze(path, suite, heldout):
    load_suite(suite)
    load_suite(heldout)
    data = {"created_at": datetime.now(timezone.utc).isoformat(),
            "hash_algorithm": "SHA-256 of UTF-8 text with universal LF newlines",
            "purpose": "Pre-evaluation freeze: do not tune bot or checks using held-out outcomes.",
            "files": fingerprints(suite, heldout)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")
    return data


def verify_freeze(path, suite, heldout):
    recorded = json.loads(Path(path).read_text(encoding="utf-8"))["files"]
    current = fingerprints(suite, heldout)
    changed = sorted(key for key in recorded.keys() | current.keys() if recorded.get(key) != current.get(key))
    if changed:
        raise ValueError("Frozen inputs changed: " + ", ".join(changed))


def failures(run):
    return [{"id": t["test_key"], "category": t["category"], "reason": t["verdict"]["reason"],
             "expected_behavior": t["expected_behavior"], "responses": t["responses"]}
            for t in run["tests"] if not t["verdict"]["passed"]]


def summarize(runs, metadata):
    baseline = {t["test_key"]: t for t in runs["hardened"]["tests"]}
    for run in runs.values():
        if (run["status"] != "completed" or run["summary"]["pending"] or
                {t["test_key"] for t in run["tests"]} != set(baseline)):
            raise ValueError("Mutation comparison requires completed runs of identical tests")
    categories = sorted({t["category"] or "unspecified" for t in baseline.values()})
    matrix = {}
    failed_any = set()
    for meta in metadata:
        failed = [t["test_key"] for t in runs[meta["id"]]["tests"] if not t["verdict"]["passed"]]
        failed_any.update(failed)
        killed = [key for key in failed if baseline[key]["verdict"]["passed"]]
        counts = {category: sum((baseline[key]["category"] or "unspecified") == category for key in killed)
                  for category in categories}
        matrix[meta["id"]] = {"expected_categories": meta["expected_categories"],
            "failed_test_ids": failed, "detection_test_ids": killed, "categories": counts,
            "caught_in_expected_category": any(counts.get(c, 0) for c in meta["expected_categories"])}
    weak_failed = {t["test_key"] for t in runs["weak"]["tests"] if not t["verdict"]["passed"]}
    scores = {}
    for mode, run in runs.items():
        scores[mode] = {}
        for category in ["overall", *categories]:
            rows = [t for t in run["tests"] if category == "overall" or (t["category"] or "unspecified") == category]
            passed = sum(t["verdict"]["passed"] for t in rows)
            scores[mode][category] = {"passed": passed, "total": len(rows), "pass_rate": round(100 * passed / len(rows), 2)}
    return {"run_ids": {key: run["id"] for key, run in runs.items()}, "scores": scores,
            "matrix": matrix, "library_gaps": [key for key, row in matrix.items() if not row["detection_test_ids"]],
            "expected_category_gaps": [key for key, row in matrix.items() if not row["caught_in_expected_category"]],
            "dead_test_ids": sorted(set(baseline) - failed_any - weak_failed),
            "hardened_false_failures_for_review": failures(runs["hardened"])}


def markdown(result):
    categories = list(next(iter(result["matrix"].values()))["categories"])
    lines = ["# Meher Threads mutation evidence", "",
        "Counts are failures on a mutant for tests that pass on hardened. A common hardened failure cannot kill a mutant.", "",
        "| Mutant | " + " | ".join(categories) + " | Expected category caught |",
        "| --- | " + " | ".join("---:" for _ in categories) + " | --- |"]
    for name, row in result["matrix"].items():
        lines.append("| " + name + " | " + " | ".join(str(row["categories"][c]) for c in categories) +
                     " | " + str(row["caught_in_expected_category"]) + " |")
    for title, items in (("Library gaps", result["library_gaps"]), ("Expected-category gaps", result["expected_category_gaps"]),
                         ("Dead tests (relative to these mutants and weak)", result["dead_test_ids"])):
        lines.extend(["", "## " + title, "", *(f"- `{item}`" for item in items)] if items else ["", "## " + title, "", "None."])
    lines.extend(["", "Dead tests can still be useful regression tests; this finite mutation set does not prove complete coverage.",
                  "", "## Hardened false-failure candidates", ""])
    lines.extend(f"- `{item['id']}`: {item['reason']}" for item in result["hardened_false_failures_for_review"])
    if not result["hardened_false_failures_for_review"]:
        lines.append("None.")
    lines.extend(["", "## Failed test IDs per mutant", ""])
    for name, row in result["matrix"].items():
        lines.append(f"- **{name}**: " + (", ".join(f"`{key}`" for key in row["failed_test_ids"]) or "None"))
    if "heldout" in result:
        held = result["heldout"]
        lines.extend(["", "## Held-out hardened results (no subsequent tuning)", "",
                      f"{held['passed']}/{held['total']} ({held['pass_rate']}%).", ""])
        lines.extend(f"- `{item['id']}`: {item['reason']}" for item in held["failures"])
    lines.extend(["", "Full attempts and verdicts: individual JSON exports and runs.db. Counts/rates: matrix.json. Input provenance: manifest.json and suite.snapshot.json.", ""])
    return "\n".join(lines)


def evaluate(output, suite=DEFAULT_SUITE, heldout=None, freeze_path=None):
    if bool(heldout) != bool(freeze_path):
        raise ValueError("Held-out evaluation requires both --heldout and --freeze")
    if heldout:
        verify_freeze(freeze_path, suite, heldout)
    tests = load_suite(suite)
    held_tests = load_suite(heldout) if heldout else None
    metadata = mutant_metadata()
    before = fingerprints(suite, heldout)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "suite.snapshot.json").write_bytes(Path(suite).read_bytes())
    if heldout:
        (output / "heldout.snapshot.json").write_bytes(Path(heldout).read_bytes())
        (output / "heldout-freeze.json").write_bytes(Path(freeze_path).read_bytes())
    write_json(output / "mutants.snapshot.json", metadata)
    runs = {}
    with Storage(output / "runs.db") as storage:
        def execute(name, bot, cases, source):
            with background_server(bot) as server:
                config = {"type": "http", "url": server.url + "/chat", "request_template": {"message": "{{prompt}}"}, "response_json_path": "$.reply"}
                run_id = asyncio.run(run_suite(cases, create_connector(config), storage,
                    RunOptions(concurrency=4, timeout=10, retries=0), target_name=name, suite_path=str(source)))
            run = storage.results(run_id)
            write_json(output / f"{name}.json", run)
            return run
        for mode in ("hardened", "weak"):
            runs[mode] = execute(mode, StoreBot(mode), tests, suite)
        for meta in metadata:
            runs[meta["id"]] = execute(meta["id"], MutantBot(meta["id"]), tests, suite)
        result = summarize(runs, metadata)
        if held_tests:
            held = execute("heldout-hardened", StoreBot(), held_tests, heldout)
            result["heldout"] = {"run_id": held["id"], "passed": held["summary"]["passed"], "total": len(held_tests),
                                 "pass_rate": round(100 * held["summary"]["passed"] / len(held_tests), 2), "failures": failures(held)}
    if fingerprints(suite, heldout) != before:
        raise ValueError("Inputs changed during evaluation; results are not frozen")
    if heldout:
        verify_freeze(freeze_path, suite, heldout)
    write_json(output / "manifest.json", {"created_at": datetime.now(timezone.utc).isoformat(),
               "hash_algorithm": "SHA-256 of UTF-8 text with universal LF newlines", "files": before})
    write_json(output / "matrix.json", result)
    (output / "report.md").write_text(markdown(result), encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--output-dir", type=Path)
    lock = commands.add_parser("freeze")
    lock.add_argument("--output", type=Path, required=True)
    for sub in (run, lock):
        sub.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
        sub.add_argument("--heldout", type=Path, required=sub is lock)
    run.add_argument("--freeze", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            freeze(args.output, args.suite, args.heldout)
            print(f"Frozen inputs: {args.output}")
            return 0
        output = args.output_dir or ROOT / "reports/meher_threads/mutation" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        result = evaluate(output, args.suite, args.heldout, args.freeze)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    for mode, scores in result["scores"].items():
        score = scores["overall"]
        print(f"{mode:26} {score['passed']}/{score['total']} ({score['pass_rate']}%)")
    print(f"Gaps: {result['library_gaps']}; dead tests: {len(result['dead_test_ids'])}; hardened failures: {len(result['hardened_false_failures_for_review'])}")
    if "heldout" in result:
        print(f"Held-out: {result['heldout']['passed']}/{result['heldout']['total']}; failures: {[f['id'] for f in result['heldout']['failures']]}")
    print(f"Saved: {output.resolve()}")
    return 1 if result["library_gaps"] or result["expected_category_gaps"] or result["hardened_false_failures_for_review"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
