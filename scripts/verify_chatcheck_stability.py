"""Run the complete pytest suite repeatedly and retain exact logs and results."""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source_hash():
    paths = [*ROOT.glob("*.py"), ROOT / "pyproject.toml"]
    for directory in ("chatcheck", "tests", "demo_bots", "src", "scripts"):
        paths.extend((ROOT / directory).rglob("*.py"))
    value = hashlib.sha256()
    for path in sorted(set(paths)):
        value.update(path.relative_to(ROOT).as_posix().encode())
        value.update(path.read_text(encoding="utf-8").encode())
    return value.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out", default="reports/meher_threads/phase2c/stability")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be positive")
    folder = Path(args.out).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    report = {"command": command, "python": sys.version, "started_at": datetime.now(timezone.utc).isoformat(),
              "source_sha256": source_hash(), "runs": []}
    for index in range(1, args.runs + 1):
        log = folder / f"pytest-{index}.txt"
        print(f"Starting full suite {index}/{args.runs}", flush=True)
        with log.open("w", encoding="utf-8") as stream:
            completed = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        lines = log.read_text(encoding="utf-8").splitlines()
        result = {"index": index, "exit_code": completed.returncode, "summary": lines[-1] if lines else "No output", "log": log.name}
        report["runs"].append(result)
        report["source_unchanged"] = report["source_sha256"] == source_hash()
        report["all_passed"] = all(run["exit_code"] == 0 for run in report["runs"]) and len(report["runs"]) == args.runs
        (folder / "stability.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(result["summary"], flush=True)
        if completed.returncode or not report["source_unchanged"]:
            return 1
    print(f"All {args.runs} full suite runs passed; evidence: {folder}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
