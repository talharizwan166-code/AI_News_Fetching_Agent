# Phase 6 synthetic monitoring evidence

Five historical cycles use a deterministic fake target; alert delivery is dry-run only. No real accounts or provider calls.

- [Monthly HTML](reports/demo-client/fake-bot/monthly-2026-09-8775de9c2e52.html) and [PDF](reports/demo-client/fake-bot/monthly-2026-09-8775de9c2e52.pdf) (4 pages).
- [Client retention inventory](client-retention.html) (dry-run; no data deleted).
- [Verification](verification.json) records scores, availability, regressions/fixes, duplicate suppression and budget stops.
- `monitor.sqlite3` retains all runs locally (ignored by Git).

The failing week has one real response failing a critical check and one synthetic connector error. Only the first is a model-check failure. The following week records recovery; the final week stops at one call with the remaining test not attempted.

Final verification: **855 pytest tests passed, 2 skipped**, including 42 new Phase 6
tests. An initial full run had a wheel-build timeout and a PDF-renderer failure;
both passed separately and in the final full run. No existing assertions were
weakened. The old-schema migration fixture now drops the new monitoring tables
before simulating schema v3.

Reproduce from the repository root, using a new directory:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe scripts/demo_monitor.py --out-dir reports/monitor-phase6-next
.\.venv\Scripts\python.exe -m chatcheck retention --db reports/monitor-phase6-next/monitor.sqlite3 --policy reports/monitor-phase6-next/retention-policy.json --out reports/monitor-phase6-next/client-retention.html
```

The [monitoring guide](../../docs/chatcheck-monitoring.md) includes actual target
configuration, dry-run semantics, SMTP/Slack settings, monthly commands, optional
dashboard setup, scheduler templates and retention limits. Monetary limits reserve
the configured per-call estimate; they do not read provider bills. Live transport
credentials, Streamlit deployment and schedule activation are not part of this demo.
