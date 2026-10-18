"""Verify saved v2 comparison evidence, frozen inputs and report artifacts."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_sandbox.compare_v2 import frozen_hashes, verification
from chatcheck.judge import judge
from chatcheck.storage import Storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    saved = json.loads((directory / "verification.json").read_text(encoding="utf-8"))
    provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
    assert frozen_hashes() == provenance["frozen"]
    assert hashlib.sha256((ROOT / "agent_sandbox/suite_v2.json").read_bytes()).hexdigest() == provenance["suite_sha256"]
    assert provenance["before"]["harness_sha256"] == provenance["after"]["harness_sha256"]
    for name, digest in provenance["after"]["harness_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    old_source, new_source = (provenance[key]["source_sha256"] for key in ("before", "after"))
    changed_sources = sorted(key for key in old_source.keys() | new_source.keys() if old_source.get(key) != new_source.get(key))
    assert changed_sources == ["src/config.py", "src/generator.py"]
    with Storage(directory / "runs.sqlite3") as storage:
        before, after = (storage.results(saved[key]) for key in ("before_run", "after_run"))
    actual = verification(before, after)
    assert all(saved[key] == value for key, value in actual.items())
    assert actual["identical_test_snapshots"] and actual["comparison"]["matched"] == 30
    assert not actual["worker_errors"]
    for run in (before, after):
        assert run["status"] == "completed"
        for test in run["tests"]:
            response = test["responses"][-1]
            reproduced = judge(response["text"], test["checks"], response["error"],
                               trace=test["agent_behavior"]).to_dict()
            assert all(test["verdict"][key] == value for key, value in reproduced.items())
    from pypdf import PdfReader
    pages = {}
    for name in ("before", "after", "comparison", "summary"):
        html = (directory / (name + ".html")).read_text(encoding="utf-8")
        assert "not an independent benchmark" in html
        reader = PdfReader(directory / (name + ".pdf"))
        pages[name] = len(reader.pages)
        pdf_text = " ".join(page.extract_text() for page in reader.pages)
        assert "not an independent benchmark" in pdf_text
    assert 1 <= pages["summary"] <= 5
    audit = {"frozen_inputs_unchanged": True, "source_changes": changed_sources,
             "same_harness_and_suite": True, "saved_verdicts_reproduced": True,
             "before_run": before["id"], "after_run": after["id"], "pdf_pages": pages,
             "before": actual["comparison"]["before"], "after": actual["comparison"]["after"],
             "fixed": actual["comparison"]["fixed"], "newly_failing": actual["comparison"]["newly_failing"],
             "benign_failures": actual["benign_failures"], "worker_errors": actual["worker_errors"]}
    output = directory / "audit.json"
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
