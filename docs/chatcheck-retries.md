# Phase 2E: error-only retry and response coverage

Use the source checkout and the existing `reports/real_llm` experiment. A retry
adds a new response attempt to the **same run and test**, keeping the original
failed attempt, its error and its prior judgments. No new benchmark run is made.

## Exact commands

With target credentials securely supplied in the environment:

```powershell
.\.venv\Scripts\Activate.ps1
$env:MEHER_LLM_PROVIDER = 'gemini'
$env:MEHER_LLM_MODEL = 'gemini-3.5-flash-lite'
$env:MEHER_LLM_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'
$env:MEHER_LLM_PACE_SECONDS = '4'
python scripts/retry_failed_real_llm.py --yes --max-calls 12
```

If the key is already in the ignored local `.env`, this launcher loads it only
inside Python. Export the nonsecret target configuration above first:

```powershell
python -c "from dotenv import load_dotenv; load_dotenv('.env'); from scripts.retry_failed_real_llm import main; raise SystemExit(main(['--yes','--max-calls','12']))"
```

`--yes` and an explicitly supplied `--max-calls` are both required. The suggested
default allowance is **12 additional calls**; omission of the cap refuses paid
work. A smaller explicit cap is supported. `--out <existing-directory>` selects
another saved real experiment; repeat `--run <manifest-run-id>` to select runs.
Archived demo runs outside the real manifest cannot be retried by this tool.

The original `target-budget.db` stays unchanged. `retry-budget.db` has a separate
immutable cap, shared across both suites and all reruns of this retry batch.
The output-token cap is copied from the original ledger (512 in this experiment).
The configured provider, model, base URL and system-prompt hash must match the
original target and ledger. Keys remain environment-only, never metadata or logs.

A case is eligible only if its latest attempt has an error and no historical
attempt contains a delivered response. Failed real answers, passes, uncertain
answers and empty delivered answers are never sampled again. A reservation is
journaled atomically before calling the target; concurrent retry processes
cannot claim the same test. Failed or interrupted calls consume the budget.
Each test gets at most one additional attempt in this batch. Rerunning resumes
unclaimed errors, never repeats completed/unknown reservations, and never resets
or increases the cap. There is no hidden retry loop or model fallback.

Authentication, invalid-request, model-access and rate-limit errors stop the
batch; three consecutive other errors also stop it. The untouched cases keep
their original error attempts. The script returns 0 if selected runs have no
remaining errors, 1 if errors remain and 2 for invalid configuration. Do not
delete the retry ledger/audit to obtain a fresh allowance.

## Scores and reports

The headline is **passed tests / tests that received a response**. Connection or
provider errors are excluded from that denominator and stated next to the
headline. An empty delivered answer is a response and can fail its rules. A
provider error with no answer is not a behavior failure.

The second number treats errors/unattempted tests as **not-run** and uses all
planned tests as the denominator; these cases receive no pass credit. Thus the
main Phase 2D baseline is 52/68 = **76.5% response-only**, with eight errors;
52/76 = **68.4%** across all planned tests. Held-out is 7/16 = **43.8%**, with four
errors; 7/20 = **35.0%** across all planned tests. These are arithmetic corrections,
not a change to any rule verdict or a claim of improved model quality.

The existing `summary` field/raw rule verdicts remain available for compatibility
and audit. The new `coverage_scores` field has `responses_only`,
`errors_as_not_run`, response count, error count and planned count. Reports,
category/language bars and the real-demo summary explicitly use response-only
scores. Coverage differences are called out in report comparisons.

The retry tool refreshes the existing redacted HTML/PDF reports and candidate
files. Attempt history appears in each retried item's appendix details and in
`chatcheck results` / JSON exports. The run's `options.target_retries` contains
the reservation, source response ID, attempt number, completion status and
complete prior rule/LLM/human judgments. Earlier human labels and LLM verdicts
are archived and removed from current evaluation when the response changes;
no new labels are created. Other tests' labels and verdicts remain unchanged.
This journal is deleted with its run by the existing purge procedure.

The 100-item sample keeps the same membership and ID. Its real-response count is
refreshed; a newly received response needs a fresh human label. Original
no-response labels remain in the audit. Blind labeling still hides both judges.

```powershell
$m = Get-Content reports/real_llm/manifest.json -Raw | ConvertFrom-Json
python -m chatcheck results --run $m.run_ids[0] --db reports/real_llm/runs.db
python -m chatcheck label --sample $m.sample_id --db reports/real_llm/runs.db
python -m chatcheck agreement --sample $m.sample_id --db reports/real_llm/runs.db
# A separate output filename for an additional client report:
python -m chatcheck report --run $m.run_ids[0] --db reports/real_llm/runs.db --out reports/real_llm/retry-review.html --pdf --client 'Meher Threads'
```

See the [tuning protocol](../tuning-protocol.md) for the frozen held-out controls,
reviewed MAIN revisions and the optional `any_of_phrases` check. Do not revise
checks while interpreting these retries; the saved test snapshots remain fixed.

## Verification checklist

```powershell
python -m pytest tests/chatcheck/test_phase2e.py -q -p no:cacheprovider
python -m pytest -q -p no:cacheprovider
```

- Original responses, failed attempts and prior judgments remain visible under
  the same run/test IDs; only error-only cases get a new attempt.
- The original ledger is unchanged, the additional cap survives reruns, and
  a rerun cannot re-call a successful or failed model answer.
- Both score denominators and remaining-error counts are printed and rendered.
- Held-out edits fail loading; an explicit reason creates an exception record.
- MAIN revisions require an existing human-reviewed false failure and record
  test ID, old/new checks, reason, date and review provenance.
- Unicode/Urdu phrase tests pass without changing existing check behavior.
- Reports remain escaped/redacted and PDFs remain offline and multipage.
- No API keys appear in console output, artifacts, run metadata or either ledger.
