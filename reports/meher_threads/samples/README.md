# Client report samples

Open [weak.html](weak.html) and [hardened.html](hardened.html) in a browser. Both
are standalone UTF-8 HTML, with inline styles and SVG charts, redacted evidence,
Urdu/Roman Urdu support, static remediation guidance and all 76 tests in the
appendix. No external assets or provider calls are required.

| Target | Passed | Test pass score |
| --- | ---: | ---: |
| Weak | 15 / 76 | 19.7% |
| Hardened | 76 / 76 | 100.0% |

The hardened report compares against weak: 61 fixes, zero newly failing tests,
and +80.3 percentage points. The baseline timestamp is later because the source
evaluation loop ran hardened before weak; the report makes this scenario-comparison
limitation explicit. Imported runs have rule verdicts only and no human labels.
The score uses the standard hybrid rule fallback and does not claim complete safety.

`manifest.json` records source/run identities and scores. `runs.db` contains the
local imported snapshots and is ignored by Git. Recreate the reports and database
in a fresh directory:

```powershell
python -m scripts.demo_chatcheck_report --out-dir reports/meher_threads/samples-local
```

See the [report guide](../../../docs/chatcheck-reports.md) for exact report/PDF
commands, redaction settings, scoring definitions and the verification checklist.
