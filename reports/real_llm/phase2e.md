# Phase 2E: error-only retry audit

The original real-target run reserved 96 requests and received 84 model
responses. This retry batch sent **12 additional capped requests**, only for
tests whose original attempts ended without a response. All 12 returned model
responses. No pass, failed answer or uncertain answer was sampled again.

| Suite | Before: response-only | Before: errors as not-run / all planned | Original errors | After: both scores | Remaining errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Main | 52 / 68 (76.5%) | 52 / 76 (68.4%) | 8 | 57 / 76 (75.0%) | 0 |
| Held-out | 7 / 16 (43.8%) | 7 / 20 (35.0%) | 4 | 8 / 20 (40.0%) | 0 |

Response-only scores now equal all-planned scores because coverage is complete.
The changed scores describe newly filled coverage, not a tuned or improved
model. The provider/model/system prompt and all 96 suite cases stayed unchanged.
The optional normalized phrase check was not applied to existing cases.

## Provenance verified

- Same main run: `e4f331e7-4b25-48c7-9fda-842fc6a55298`.
- Same held-out run: `9de5255b-6552-4f91-9090-af7e778f4c41`.
- Original `target-budget.db` is byte-identical to its pre-retry hash: 96 calls.
- New `retry-budget.db`: 12 reservations, maximum 12 across both runs and reruns,
  original 512-token output cap, no automatic retries.
- All 84 pre-existing response-bearing test objects are unchanged, including
  their responses, verdicts and labels. This includes answers that failed checks.
- All 96 original response-attempt rows are unchanged. Twelve new rows use
  attempt 2 on exactly the 12 original error-only test IDs; 108 total attempts.
- Original failed rule judgments and any old review records are retained in
  `options.target_retries[*].previous_judgments`. Current verdicts use attempt 2.
- Both runs are `completed`, with 96 delivered responses and no remaining errors.
- A guarded rerun that would reject any target invocation made zero calls.

Both suites have registered freeze sidecars. The held-out checks and full
definition are enforced on load. MAIN revision requires an explicit human pass
label on an exact original rule failure; both suite changelogs remain empty.
The historical mutation audit allows the authorized `judge.py` and `models.py`
engine changes; all existing suite cases and behavioral assertions remain intact.

## Refreshed artifacts and review

- [Main HTML](main.html) / [PDF](main.pdf), 14 pages.
- [Held-out HTML](heldout.html) / [PDF](heldout.pdf), 9 pages.
- [31 current failed-test review items](false-failure-candidates.md): 30 possible
  phrase mismatches and one other review item, all unverified. No verdict overrides.
- [Before snapshot and hashes](phase2e-before.json).
- [Detailed verification](phase2e-verification.json).
- [Historical Phase 2D verification](verification.json), retained as the pre-retry record.

The same 100-item blinded sample now contains **49 usable real responses**:
22 English, 14 Roman Urdu and 13 Urdu, across all eight categories. Membership
and sample ID are unchanged. No human labels or LLM judge evaluations were added.

```powershell
.\.venv\Scripts\Activate.ps1
$m = Get-Content reports/real_llm/manifest.json -Raw | ConvertFrom-Json
python -m chatcheck label --sample $m.sample_id --db reports/real_llm/runs.db
python -m chatcheck agreement --sample $m.sample_id --db reports/real_llm/runs.db
python -m chatcheck freeze --suite suites/clothing_store_heldout.json
python -m pytest -q -p no:cacheprovider
```

Verification: **640 passed, 2 skipped**. PDFs are valid and multipage; Urdu is
present. Current client reports and review files contain none of the synthetic
private fixture values. All experiment output files, including three databases,
were scanned in memory against the configured target credentials: zero matches.
No API keys were printed. These rule scores do not measure semantic accuracy or
establish complete safety. Follow the [tuning protocol](../../tuning-protocol.md)
before revising MAIN checks; do not tune from held-out observations.
