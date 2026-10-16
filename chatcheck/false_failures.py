"""Conservative triage for human review, never semantic judgments or labels."""

import html
import json
from pathlib import Path

from .report import Redactor, outcome


def assess_candidates(runs):
    rows = []
    for run in runs:
        for test in run["tests"]:
            if outcome(test) not in {"fail", "uncertain"}:
                continue
            response = test["responses"][-1] if test["responses"] else {}
            failed = [dict(check=check, reason=detail["reason"])
                      for check, detail in zip(test["checks"], (test.get("verdict") or {}).get("checks", []))
                      if not detail["passed"]]
            kinds = {item["check"]["type"] for item in failed}
            if response.get("error") or not response.get("text"):
                status, reason = "not_indicated", "Transport failure or absent response; no paraphrase to assess."
            elif "not_contains" in kinds:
                status, reason = "not_indicated", "A forbidden-content check failed. Keep leakage and policy failures for direct review."
            elif kinds and kinds <= {"regex", "contains", "equals"}:
                status, reason = "possible_false_failure", "Text matching failed on a nonempty response. Different wording may explain it; correctness of meaning is UNVERIFIED."
            else:
                status, reason = "needs_manual_review", "Formatting, length or uncertain judgment requires manual assessment."
            rows.append({"run_id": run["id"], "test_key": test["test_key"], "category": test.get("category"),
                         "language": test.get("language"), "outcome": outcome(test), "assessment": status,
                         "assessment_reason": reason, "prompt": test["prompt"], "response": response.get("text") or "(no response)",
                         "expected_behavior": test.get("expected_behavior"), "failed_rules": failed,
                         "rule_reason": (test.get("verdict") or {}).get("reason", "No rule verdict")})
    return rows


def write_candidates(runs, directory, *, redactor=None):
    directory = Path(directory)
    redactor = redactor or Redactor.from_environment()
    rows = redactor.tree(assess_candidates(runs))
    lines = ["# Real model: false-failure candidates", "",
             "Every failed or uncertain test is listed. These are heuristic review flags, not human labels or a claim that the response is correct. No checks were changed. Synthetic canaries and configured secrets are redacted.", "",
             f"Items requiring review: {len(rows)}.", ""]
    for row in rows:
        lines.extend([f"## {row['test_key']} ({row['language']}, {row['category']})", "",
                      f"Run: {row['run_id']} | outcome: {row['outcome']} | assessment: {row['assessment']}", "",
                      row["assessment_reason"], ""])
        for title, value in (("Prompt", row["prompt"]), ("Response", row["response"]),
                             ("Expected behavior", row["expected_behavior"] or "Unspecified"),
                             ("Failed rules", json.dumps(row["failed_rules"], ensure_ascii=False, indent=2)),
                             ("Rule reason", row["rule_reason"])):
            lines.extend([f"**{title}**", "", "<pre>" + html.escape(value) + "</pre>", ""])
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "false-failure-candidates.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    (directory / "false-failure-candidates.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, rows
