# Meher Threads: real Gemini experiment

Phase 2E retried only the 12 connection/provider failures, using a separate
12-call cap. All 12 returned responses. The original 84 response-bearing tests,
all 96 original attempts and the original ledger are unchanged. There are now
108 attempts, 96 model responses and zero remaining connector errors in the same
two runs. A rerun invoked the target zero times.

| Suite | Current response-only score | Errors | All-planned score |
| --- | ---: | ---: | ---: |
| Main | 57 / 76 (75.0%) | 0 | 75.0% |
| Held-out | 8 / 20 (40.0%) | 0 | 40.0% |

These scores reflect complete response coverage under unchanged checks. Before
retry, the response-only scores were 76.5% MAIN and 43.8% held-out; the all-planned
scores were 68.4% and 35.0%. Coverage changed, so this is not evidence of a model
improvement. No checks were tuned. See the [Phase 2E audit](phase2e.md),
[machine-readable verification](phase2e-verification.json),
[retry procedure](../../docs/chatcheck-retries.md) and
[tuning protocol](../../tuning-protocol.md).

## Initial Phase 2D record (before retry)

Target: `gemini / gemini-3.5-flash-lite`. This experiment used 96 cumulative
request reservations across the 76 main tests and 20 held-out tests, with a
512-output-token request cap, minimal thinking and no retries. A rerun with the
same manifest and ledger made **zero additional reservations**. Both suites were
attempted once; no tests remain pending or not run.

| Suite | Rule passes | Rule failures | Score | Connector errors included in failures |
| --- | ---: | ---: | ---: | ---: |
| Main | 52 / 76 | 24 | 68.4% | 8 |
| Held-out | 7 / 20 | 13 | 35.0% | 4 |

There were **84 usable model responses and 12 connector/provider errors**: five
connection failures/timeouts and seven HTTP 503 responses. The first three
connection failures came from the restricted sandbox; the experiment resumed
with network access using the same cap, without retrying those tests. These
errors remain visible as failures and are not evidence of incorrect model
answers. Scores use all saved tests in the denominator. The runner exits 1 for
`completed_with_errors`, including a zero-call rerun of these saved results.

The target received public FAQ facts and a separate hidden block with the three
synthetic private fixture values. Raw model output was evaluated so the demo's
standalone output filter could not hide leakage. API key echoes are always
scrubbed. No failed `not_contains` checks were observed; that does not establish
complete safety. No rules, suites or FAQ facts were tuned after this experiment.

There were **zero LLM judge calls and zero human labels**. The real target and
the verdict judge are separate components. These rule scores are not measured
semantic accuracy, language fluency or agreement with human reviewers.

## Artifacts

- [Main client HTML](main.html) and [PDF](main.pdf), 14 pages.
- [Held-out client HTML](heldout.html) and [PDF](heldout.pdf), now 9 pages after Phase 2E.
- [False-failure review file](false-failure-candidates.md) and [structured assessments](false-failure-candidates.json).
- [Manifest with run/sample IDs](manifest.json) and [verification results](verification.json).
- `runs.db`: local saved runs, archived demo imports, responses, verdicts and the
  blinded sample. SQLite files are ignored by Git.
- `target-budget.db`: persistent reservation ledger; keep it with the manifest
  when resuming. It contains no prompts, responses or API keys.
- `retry-budget.db`: the separate Phase 2E allowance, capped at 12. Its rerun
  did not consume any additional calls. It is also ignored by Git.

The refreshed review file covers **all 31 currently failed tests**. It flags
30 possible wording mismatches and one item requiring other manual review.
The original 12 transport-error judgments remain in the retry audit. The flags are heuristic and correctness is
unverified. They do not override verdicts or create human labels.

## Begin human labeling

The saved sample still has **100 items**, now including **49 usable real responses**:
22 English, 14 Roman Urdu and 13 Urdu. Those usable real responses cover all
eight categories. Mandatory held-out failures and archived weak/hardened/mutant
items are also included. There are no prefilled labels. The sample UUID is
`062c36a7-a4f1-4f87-ac42-e1fbee03eae3`.

From the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
$m = Get-Content reports/real_llm/manifest.json -Raw | ConvertFrom-Json
python -m chatcheck label --sample $m.sample_id --db reports/real_llm/runs.db
python -m chatcheck agreement --sample $m.sample_id --db reports/real_llm/runs.db
```

The labeler hides judge verdicts and inclusion reasons. Enter `pass`, `fail`,
`unsure`, `s` to skip, or `q` to quit. Review the candidate file separately after
blind labeling if you want to preserve that blindness.

Main run: `e4f331e7-4b25-48c7-9fda-842fc6a55298`.
Held-out run: `9de5255b-6552-4f91-9090-af7e778f4c41`.

To inspect saved results or create another report without target calls:

```powershell
python -m chatcheck results --run $m.run_ids[0] --db reports/real_llm/runs.db
python -m chatcheck report --run $m.run_ids[0] --db reports/real_llm/runs.db --out reports/real_llm/review.html --pdf --client 'Meher Threads'
```

Report generation refuses existing output names. Use the
[real-run guide](../../docs/chatcheck-real-llm.md) for exact environment setup,
the explicit `--yes` runner command, quota sampling and retention instructions.
The runner refreshes only its own fixed report/review output paths on resume.

## Verification checklist

- [x] Entire repository: **640 passed, 2 optional tests skipped**.
- [x] All 96 original attempts preserved; 12 new attempts belong only to original error cases.
- [x] Original ledger stayed at 96; retry ledger stayed at 12 on a zero-call rerun.
- [x] All failed/uncertain cases are represented in the candidate file.
- [x] Sample contains 100 items and at least 40 usable real responses; all eight
  categories and three languages are represented, with zero automatic labels.
- [x] HTML preserves Urdu, specifies the Urdu font stack and includes scope limits.
- [x] Refreshed PDFs begin with `%PDF` and contain 14 / 9 pages.
- [x] Client reports and review files contain none of the synthetic private values.
- [x] Scanning all output files, including both databases, found no matches for
  the configured target API keys. No keys were printed. The Phase 2E scan
  includes all three databases.

Selected labels will not by themselves estimate production accuracy. Results do
not prove a chatbot is completely safe. Delete exported artifacts and backups
as well as purging the local run when applying a client retention request;
provider-side retention requires separate handling.
