"""Generate client reports from archived weak/hardened demo responses, offline."""

import argparse
import json
from pathlib import Path

from chatcheck.report import scores, write_report
from chatcheck.storage import Storage


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="reports/meher_threads/samples")
    args = parser.parse_args(argv)
    folder = Path(args.out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    if any((folder / name).exists() for name in ("weak.html", "hardened.html", "manifest.json")):
        parser.error("Sample reports already exist; choose a fresh --out-dir")
    source = Path("reports/meher_threads/mutation/final")
    with Storage(folder / "runs.db") as storage:
        runs = {}
        for name in ("weak", "hardened"):
            exported = json.loads((source / f"{name}.json").read_text(encoding="utf-8"))
            run_id = storage.import_run(exported)
            runs[name] = storage.results(run_id)
        for name, run in runs.items():
            # Legacy exports did not snapshot a declared suite name/version;
            # the report shows the saved filename and immutable definition hash.
            print(write_report(run, folder / f"{name}.html", client="Meher Threads (fictional demo)",
                               compare=runs["weak"] if name == "hardened" else None))
        manifest = {"database": (folder / "runs.db").as_posix(), "external_calls": 0,
                    "source": source.as_posix(), "score_basis": "hybrid with rule fallback; imported rule-only runs",
                    "human_labels": 0, "reports": {name: {"run_id": run["id"], "html": (folder / f"{name}.html").as_posix(),
                                                           "score": scores(run["tests"])} for name, run in runs.items()}}
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
