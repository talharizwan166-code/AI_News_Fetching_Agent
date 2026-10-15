"""Run both offline modes over real HTTP and retain every result and shared outcome."""

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from chatcheck.connectors import create_connector
from chatcheck.models import RunOptions, load_suite, read_json
from chatcheck.runner import run_suite
from chatcheck.storage import Storage

from .bot import StoreBot
from .knowledge import DEFAULT_FAQ, DEFAULT_PRIVATE, ROOT
from .server import background_server


def summarize(weak, hardened):
    runs = {"weak": weak, "hardened": hardened}
    ids = [{t["test_key"] for t in run["tests"]} for run in runs.values()]
    if ids[0] != ids[1] or any(run["summary"]["pending"] or run["status"] != "completed" for run in runs.values()):
        raise ValueError("Comparison requires completed runs of the same tests")
    categories = sorted({t["category"] or "unspecified" for t in weak["tests"]})
    scores = {}
    for mode, run in runs.items():
        scores[mode] = {}
        for category in ("overall", *categories):
            tests = [t for t in run["tests"] if category == "overall" or (t["category"] or "unspecified") == category]
            passed = sum(t["verdict"]["passed"] for t in tests)
            scores[mode][category] = {"passed": passed, "total": len(tests), "pass_rate": round(100 * passed / len(tests), 2)}
    hardened_tests = {t["test_key"]: t for t in hardened["tests"]}
    shared = []
    for test in weak["tests"]:
        other = hardened_tests[test["test_key"]]
        if test["verdict"]["passed"] == other["verdict"]["passed"]:
            shared.append({"id": test["test_key"], "category": test["category"],
                           "outcome": "pass" if test["verdict"]["passed"] else "fail",
                           "review": "Possible weak test: same outcome in both modes; review discrimination, not automatically a defective check.",
                           "weak_reason": test["verdict"]["reason"], "hardened_reason": other["verdict"]["reason"]})
    failures = [{"id": t["test_key"], "reason": t["verdict"]["reason"],
                 "expected_behavior": t["expected_behavior"], "response": t["responses"][-1]["text"]}
                for t in hardened["tests"] if not t["verdict"]["passed"]]
    return {"run_ids": {mode: run["id"] for mode, run in runs.items()}, "scores": scores,
            "possible_weak_tests": shared, "hardened_failures_for_review": failures}


def markdown_report(comparison):
    lines = ["# Meher Threads offline comparison", "",
             "These are deterministic demonstration targets, not measurements of a production LLM's security.", "",
             "| Category | Weak | Hardened |", "| --- | ---: | ---: |"]
    for category in comparison["scores"]["weak"]:
        values = [comparison["scores"][mode][category] for mode in ("weak", "hardened")]
        cells = [f"{v['passed']}/{v['total']} ({v['pass_rate']:.1f}%)" for v in values]
        lines.append(f"| {category} | {cells[0]} | {cells[1]} |")
    lines.extend(["", "## Shared outcomes: possible weak tests", "",
                  "Every identical pass/fail outcome is listed below. A shared pass may simply cover a basic policy both bots know; it does not by itself prove that the check is weak.", ""])
    for shared in comparison["possible_weak_tests"]:
        lines.append(f"- `{shared['id']}` — both **{shared['outcome']}**; possible weak test, review discrimination.")
    if not comparison["possible_weak_tests"]:
        lines.append("None.")
    lines.extend(["", "## Hardened failures requiring review", ""])
    for failure in comparison["hardened_failures_for_review"]:
        lines.append(f"- `{failure['id']}`: {failure['reason']}")
    if not comparison["hardened_failures_for_review"]:
        lines.append("None. This describes the executable checks, not a guarantee of unrestricted language understanding.")
    lines.extend(["", "## Artifacts", "", "- `weak.json` and `hardened.json`: full prompts, attempts, responses and verdicts.",
                  "- `runs.db`: both runs in SQLite (local artifact; ignored by Git).",
                  "- `comparison.json`: all category scores, run IDs and shared outcomes.",
                  "- `manifest.json`: SHA-256 hashes of the inputs and implementation used.", ""])
    return "\n".join(lines)


def compare(output_dir, suite_path=ROOT / "suites/clothing_store.json"):
    tests = load_suite(suite_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    runs = {}
    with Storage(output_dir / "runs.db") as storage:
        for mode in ("weak", "hardened"):
            config = read_json(ROOT / f"examples/chatcheck/target.meher.{mode}.json")
            with background_server(StoreBot(mode)) as server:
                # Use the checked-in config, replacing only its port for isolation.
                config["url"] = server.url + "/chat"
                run_id = asyncio.run(run_suite(tests, create_connector(config), storage,
                    RunOptions(**config["runner"]), target_name=config["name"], suite_path=str(suite_path)))
                runs[mode] = storage.results(run_id)
                (output_dir / f"{mode}.json").write_text(json.dumps(runs[mode], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    comparison = summarize(runs["weak"], runs["hardened"])
    (output_dir / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    report = markdown_report(comparison)
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    sources = [Path(suite_path), DEFAULT_FAQ, DEFAULT_PRIVATE,
               *sorted(Path(__file__).parent.glob("*.py")),
               ROOT / "chatcheck/judge.py", ROOT / "chatcheck/runner.py",
               *sorted((ROOT / "examples/chatcheck").glob("target.meher.*.json"))]
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "mode": "offline",
                "files": {str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path):
                          hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}}
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return comparison


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="New directory for artifacts; existing directories are never overwritten")
    parser.add_argument("--suite", type=Path, default=ROOT / "suites/clothing_store.json")
    args = parser.parse_args(argv)
    output = args.output_dir or ROOT / "reports/meher_threads" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    try:
        result = compare(output, args.suite.resolve())
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Error: {exc}\n")
    print("Category             Weak             Hardened")
    for category in result["scores"]["weak"]:
        values = [result["scores"][mode][category] for mode in ("weak", "hardened")]
        cells = [f"{v['passed']}/{v['total']} ({v['pass_rate']:.1f}%)" for v in values]
        print(f"{category:20} {cells[0]:16} {cells[1]}")
    print(f"\n{len(result['possible_weak_tests'])} identical outcomes flagged as possible weak tests in report.md.")
    print(f"{len(result['hardened_failures_for_review'])} hardened failures to review.")
    print(f"Saved results: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
