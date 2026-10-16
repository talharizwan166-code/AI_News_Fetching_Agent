# Phase 2C verification evidence

Three consecutive complete pytest runs passed against unchanged Python source:

| Run | Result | Time |
| --- | --- | ---: |
| 1 | 588 passed, 2 skipped | 83.67 s |
| 2 | 588 passed, 2 skipped | 90.84 s |
| 3 | 588 passed, 2 skipped | 88.69 s |

The two skips are the existing opt-in widget tests. The new real Chromium PDF
test ran in all three suites, including `%PDF`, three parsed pages, A4 dimensions
and numbered footers. Exact output is in [the stability logs](stability/stability.json).
The source fingerprint was rechecked after the final build.

[hardened.pdf](hardened.pdf) is a **nine-page PDF exported through Playwright
Chromium** from the archived hardened run. Its [HTML](hardened.html) uses the
standard escaped/redacted client report. No provider call or human labeling was
needed. [verification.json](verification.json) records artifact and test results.

Editable installation, the console command, and a built wheel installed outside
the source tree were verified. Final distribution files were built locally under
`dist/` (ignored by Git). Wheel tests read bundled suites and render with installed
templates/fixes, and invoke the installed CLI.

Purge tests cover confirmation, all dependent tables, cache ownership, sample
metadata, age cutoffs and preservation of other runs. Only temporary test data
was deleted; no existing client run was purged. Workspace tests confirm that
existing files and directories are retained and the starter suite is empty.

Reproduce in a fresh output directory:

```powershell
python -m scripts.verify_chatcheck_stability --runs 3 --out reports/meher_threads/phase2c/stability-local
```

See [the operations guide](../../../docs/chatcheck-operations.md) for installation,
PDF, workspace and client-retention commands.
