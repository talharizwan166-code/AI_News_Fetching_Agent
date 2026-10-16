# Phase 2D: real model target and human labeling preparation

Phase 2E adds [safe error-only retries](chatcheck-retries.md). Client report
headlines now use received responses only, with errors and the all-planned score
shown separately. The original no-replay ledger remains unchanged; a separately
authorized retry budget is required. See the [tuning protocol](../tuning-protocol.md)
before revising any MAIN checks; held-out tuning is prohibited.

The initial Phase 2D all-planned scores remain historical evidence. The corrected
response-only baseline before retry is 52/68 (76.5%) MAIN and 7/16 (43.8%) held-out,
with 8 and 4 connector errors respectively.

Run these commands from the repository checkout. The packaged `chatcheck` command
can read the saved DB; the demo adapter and scripts belong to the source checkout.
LLM mode remains off unless explicitly selected. Automated tests use only fake
HTTP transports; the real runner never substitutes fake responses.

## Configuration and paid-call authorization

The adapter supports Gemini Generate Content and OpenAI Responses. Provider,
model, HTTPS base URL and API key come only from environment variables. Set
`MEHER_LLM_API_KEY` for a dedicated target credential, or use `GEMINI_API_KEY` /
`OPENAI_API_KEY`. Never put keys in CLI arguments, target JSON, prompts or reports.
The script and server do not load `.env` implicitly.

```powershell
.\.venv\Scripts\Activate.ps1
$env:MEHER_LLM_PROVIDER = 'gemini'
$env:MEHER_LLM_MODEL = 'gemini-3.5-flash-lite'
$env:MEHER_LLM_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'
$env:MEHER_LLM_MAX_CALLS = '96'
$env:MEHER_LLM_MAX_OUTPUT_TOKENS = '512'
$env:MEHER_LLM_PACE_SECONDS = '4'
# With GEMINI_API_KEY already supplied securely in the process environment:
python scripts/run_real_llm_demo.py --yes
```

If your key is already in the ignored local `.env`, this launcher loads it only
inside the child Python process and prints no credentials. Install
`python-dotenv` if using this optional launcher (already present with the news
agent's requirements). Export the nonsecret configuration above first:

```powershell
python -c "from dotenv import load_dotenv; load_dotenv('.env'); from scripts.run_real_llm_demo import main; raise SystemExit(main(['--yes']))"
```

For OpenAI, set provider `openai`, base URL `https://api.openai.com/v1`, a model
available to your project, and its key. OpenAI requests disable stored responses
with `store: false`; this is not a guarantee about all provider retention.

The runner prints the maximum calls and token cap before sending anything.
Without `--yes`, it exits before creating files or initializing the target.
Default budget: **96 calls total across both suites and all reruns**, rather than
96 per suite, and at most 512 output tokens per request. This caps generation
requests and requested output, not the provider's dollar bill. Input tokens,
provider accounting and any reasoning tokens remain subject to provider rules.
Check current [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing),
[model access](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)
and [thinking settings](https://ai.google.dev/gemini-api/docs/thinking) before use.
Gemini uses temperature 0 and minimal thinking for 3.x; supported 2.5 models use
thinking budget 0. OpenAI uses its Responses API and low reasoning for GPT-5.

`--out` selects the output directory (default `reports/real_llm`). It owns a new
`runs.db`, `target-budget.db` and `manifest.json`. The ledger contains only hashes,
reservation IDs, times and limits. Every call is reserved transactionally before
network I/O, including failures and interrupted calls. No automatic retries occur.
Rerunning the exact command resumes the same saved runs; attempted/reserved tests
are never called twice. The saved provider/model/system prompt, suite hashes and
caps must match. An interrupted request with unknown outcome stays not run and
its reservation is not refunded. Authentication, invalid-request, missing-model
and rate-limit errors stop the batch; three consecutive other errors also stop it.
Remaining tests retain explicit `not_run` reasons without fabricated verdicts.
Do not delete/move the budget ledger to reset a cap or resume a missing database.
Different output directories are separate, newly authorized experiments.

## What the target sees and what the judge measures

The support instructions use facts from the public FAQ only. The three synthetic
private fixture values are seeded in a separate confidential system block, so
the model has something real to leak. No real customer data or API key is placed
in the prompt. The adapter reads no suites, expected answers or rule definitions.
The script passes the suite's user prompt and evaluates raw model output; it
bypasses the standalone server's exact-value leak filter to avoid hiding failures.
Configured API key echoes are always removed before returning/saving text.

Existing deterministic rules evaluate every actual attempt. The target model is
not the LLM judge. The script makes **zero LLM judge calls**, preserves all checks
and labels, and does not claim measured semantic accuracy without your labels.
Client HTML/PDF reports redact synthetic data and configured secret patterns;
the local SQLite retains synthetic model output for audit and leak checks.

Each failed or uncertain item appears in `false-failure-candidates.md` and `.json`
with prompt, response, expectation and exact failed rule. A nonempty response
failing only text matching gets `possible_false_failure`: a wording mismatch is
plausible, but correct meaning is **unverified**. Forbidden-content failures are
not classified as paraphrase candidates; formatting/uncertain results require
manual assessment. These flags are neither verdict overrides nor human labels.
The Markdown escapes embedded HTML and redacts synthetic data/secrets.

## Reports and the 100-item sample

The runner writes `main.html`, `main.pdf`, `heldout.html`, `heldout.pdf`, the review
files and a manifest with both run UUIDs. It refreshes its own artifacts on
resume. Chromium renders PDF offline, blocks requests and disables JavaScript;
WeasyPrint is an optional fallback. A missing renderer leaves HTML plus a clear
message. The all-planned score includes not-run tests with no pass credit;
the Phase 2E headline score uses received responses and states errors separately.

The sampler imports the historical weak/hardened/mutant/held-out exports into the
new database (no new target calls). It includes all held-out failures and judge
disagreements, then at least 40 usable responses across the two real runs,
balancing languages and category/language cells before filling the remaining
strata. Mandatory items can exceed the requested total. If fewer than 40 real
responses exist, it reports that the quota cannot be met; it never fabricates
items or substitutes connector errors for real responses. No labels are created.

```powershell
$manifest = Get-Content reports/real_llm/manifest.json -Raw | ConvertFrom-Json
python -m chatcheck label --sample $manifest.sample_id --db reports/real_llm/runs.db
python -m chatcheck agreement --sample $manifest.sample_id --db reports/real_llm/runs.db
# Build an additional seeded sample without rerunning targets:
python -m chatcheck sample --db reports/real_llm/runs.db --size 100 --real-run $manifest.run_ids[0] --real-run $manifest.run_ids[1] --min-real 40
# Generate a separate report without any target/judge calls:
python -m chatcheck report --run $manifest.run_ids[0] --db reports/real_llm/runs.db --out reports/real_llm/review.html --pdf --client 'Meher Threads'
```

The labeling view hides both judges' verdicts. Use `pass`, `fail` or `unsure`;
`s` skips and `q` quits without labeling the next item. Run-level agreement can
also use `--run $manifest.run_ids[0]`. Selected labels are not a representative
estimate of production accuracy. These results do not prove a chatbot is
completely safe.

For retention, use [the purge procedure](chatcheck-operations.md). The separate
budget ledger contains no prompts/responses, and is deliberately not refunded
by purging a run. Delete generated reports, review files and local backups as
part of a client deletion; provider-side logs require provider-specific handling.

## Verification checklist

```powershell
python -m pytest tests/chatcheck/test_real_llm.py tests/chatcheck/test_meher_llm.py -q -p no:cacheprovider
python -m pytest -q -p no:cacheprovider
```

- Confirm 76 main and 20 held-out rows, with actual responses or explicit not-run reasons.
- Confirm the reservation count never exceeds the saved cap, including reruns.
- Confirm HTML/PDF redact synthetic markers, preserve Urdu and contain no keys.
- Review every failed/uncertain response in the candidate file; leave checks unchanged.
- Confirm the saved sample has about 100 items, at least 40 usable real responses,
  all available categories/languages, and zero prefilled human labels.
- Label manually, then inspect agreement metrics and their coverage limitations.
