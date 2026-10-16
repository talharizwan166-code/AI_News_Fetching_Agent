# Chatcheck Phase 2A: judging and human review

LLM judging is **off by default**, even when credentials exist. All deterministic
checks still run and their original verdicts remain stored. No new dependencies
are needed beyond `requirements-chatcheck.txt`. Commands below use PowerShell
from the repository root with the virtual environment activated:

```powershell
.\.venv\Scripts\Activate.ps1
```

## Offline demonstration

The recorded demonstration is in `reports/meher_threads/phase2a/`. It imported
15 existing exports: weak, hardened, 12 mutants, and held-out hardened, totaling
1,084 saved responses. Five additional scripted smoke cases demonstrate:

| Case | Rule | Scripted LLM | Hybrid |
| --- | --- | --- | --- |
| Correct paraphrase | fail | pass | uncertain; human review |
| Hostile wording missed by a simple check | pass | fail | uncertain; human review |
| Exact private canary | fail | deliberately wrong pass | **fail, final** |
| English greeting | pass | pass | pass |
| Fifth item after four-call cap | pass | not judged | rule fallback |

The fake provider exercises storage, control flow and review; it does not measure
semantic quality. Unscripted responses always return `uncertain`. The saved
agreement report has zero human labels and null quality scores. Nothing has been
automatically labeled. The database is local and ignored by Git; JSON evidence
is retained in the report directory.

To create your own fresh offline database, run:

```powershell
python -m scripts.demo_chatcheck_judge --output reports/meher_threads/phase2a-local
$demo = Get-Content reports/meher_threads/phase2a-local/demo-summary.json -Raw | ConvertFrom-Json
python -m chatcheck results --run $demo.smoke_run --db $demo.database
python -m chatcheck label --sample $demo.sample --db $demo.database
python -m chatcheck agreement --sample $demo.sample --db $demo.database
```

Choose another output directory if that database already exists. The demo refuses
to overwrite a previous labeling session. It uses its own fixed budgets and fake
providers, regardless of credential or provider environment settings.

The existing local demonstration can be labeled immediately:

```powershell
$demo = Get-Content reports/meher_threads/phase2a/demo-summary.json -Raw | ConvertFrom-Json
python -m chatcheck label --sample $demo.sample --db $demo.database
python -m chatcheck agreement --sample $demo.sample --db $demo.database
```

## Normal runs and saved responses

```powershell
# Existing deterministic behavior; no external judge calls.
python -m chatcheck run --target examples/chatcheck/target.meher.hardened.json --suite suites/clothing_store.json

# Same target, explicitly opt in to the offline fake.
python -m chatcheck run --target examples/chatcheck/target.meher.hardened.json --suite suites/clothing_store.json --judge fake

# Read results without making judge calls.
python -m chatcheck results --run <id>

# Judge the saved final responses, without calling the chatbot again.
python -m chatcheck results --run <id> --judge llm
```

The target server must be running for `run`; see the [demo instructions](chatcheck.md).
`results --judge off` still displays previously saved judge verdicts. It never
deletes them. `run --judge` exits 1 if any hybrid result is fail or uncertain;
the default run exit behavior is unchanged. Successful `results` commands exit 0,
including when budget exhaustion leaves items not judged. Configuration errors
exit 2. All data commands accept `--db`; use the same database for review.

Exports contain `verdict` (the original rule object), `rule_verdict` (an explicit
alias), `llm_verdict`, `combined_verdict`, and `human_label`. The old `summary`
continues to count rules; `judge_summary` shows calls, estimated cost, disagreements,
review flags and unjudged items. Judge metadata includes provider, model, rubric
version and cache key. The CLI shows both judges and the hybrid beside each item.

For groundedness, language, tone and policy accuracy, definite agreement yields
that verdict. Definite disagreement or LLM uncertainty yields hybrid `uncertain`
and a human-review flag. A missing/unavailable LLM verdict falls back to the rule,
with an explicit `not_judged` LLM status. Other categories keep the rule as the
hybrid verdict while still recording LLM opinions and disagreements. Human labels
remain independent reference data; they do not silently rewrite either judge.

Failed exact `not_contains` checks stay final when the test is in prompt injection
or data leakage, has critical severity, or carries the `canary` tag. Connector
failures stay final. An LLM pass can never lift these failures. Existing rules and
suite definitions have not been changed.

## Small real-provider run: eight calls maximum

This example evaluates **saved synthetic demo responses**, so no chatbot server
is necessary. It uses GPT-4.1 nano, whose documented standard rates are $0.10 input
and $0.40 output per million tokens. See the
[official model page](https://developers.openai.com/api/docs/models/gpt-4.1-nano)
and [Chat Completions request reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).
Check model access and current prices before use. No live provider call was made
while implementing or verifying this phase.

```powershell
$env:CHATCHECK_JUDGE_PROVIDER = 'openai'
$env:CHATCHECK_JUDGE_MODEL = 'gpt-4.1-nano'
$env:CHATCHECK_JUDGE_API_KEY = '<your-api-key>'
$env:CHATCHECK_JUDGE_MAX_CALLS = '8'
$env:CHATCHECK_JUDGE_MAX_COST = '0.02'
$env:CHATCHECK_JUDGE_MAX_OUTPUT_TOKENS = '300'
$env:CHATCHECK_JUDGE_INPUT_PER_MILLION = '0.10'
$env:CHATCHECK_JUDGE_OUTPUT_PER_MILLION = '0.40'
$env:CHATCHECK_JUDGE_RETRIES = '1'
$env:CHATCHECK_JUDGE_TIMEOUT = '30'

python -m chatcheck import --input reports/meher_threads/mutation/final/hardened.json --db phase2a-real.db
$saved = python -m chatcheck export --run 78cd767d-5c2e-4c16-b3ee-e3ec354f2a09 --format json --db phase2a-real.db | ConvertFrom-Json
python -m chatcheck results --run $saved.id --judge llm --db phase2a-real.db
python -m chatcheck label --run $saved.id --db phase2a-real.db
python -m chatcheck agreement --run $saved.id --db phase2a-real.db
```

The cap counts actual provider attempts, including retries, across repeated
invocations for this run. Cached results consume neither calls nor cost. After
the cap, uncached items receive `not_judged`; deterministic results are retained.
This small probe is a connectivity and workflow check. It is too small to establish
judge quality, and the first eight suite items do not cover all categories.

To use Gemini, keep the caps and change the provider/model/key before judging a
freshly imported run in a separate database:

```powershell
$env:CHATCHECK_JUDGE_PROVIDER = 'gemini'
$env:CHATCHECK_JUDGE_MODEL = 'gemini-2.5-flash-lite'
$env:CHATCHECK_JUDGE_API_KEY = '<your-gemini-api-key>'
```

The Gemini adapter uses the
[official structured-output API](https://ai.google.dev/gemini-api/docs/structured-output),
with thinking disabled for this model. Check
[Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) and update the
two configured rates. Both adapters send temperature 0, a strict JSON schema and
the configured output-token limit. Models that do not support these settings
return an explicit unjudged error instead of silently dropping the settings.

The dedicated judge key falls back to `OPENAI_API_KEY` or `GEMINI_API_KEY` if empty.
All options are documented in [.env.example](../.env.example). Chatcheck reads
the process environment and does not automatically load `.env`.

Estimated cost reserves UTF-8 input bytes, schema and framing allowance, plus the
full output cap on every attempted request. It deliberately overestimates common
tokenizations, including Urdu. It is an estimated-cost guard, not a provider
billing guarantee. Update configured rates when changing models or prices. Limits
apply to a run, not globally across different run UUIDs. Raising a configured cap
explicitly allows more attempts against the cumulative usage already recorded.

## Blinded labels and sampling

```powershell
python -m chatcheck label --run <id> --db chatcheck.db
python -m chatcheck sample --size 100 --seed 42 --db chatcheck.db
# Use the sample UUID printed by the previous command.
python -m chatcheck label --sample <sample-id> --db chatcheck.db
python -m chatcheck agreement --sample <sample-id> --db chatcheck.db
```

`label` shows only prompt, final response, expected behavior, original checks,
category and language. It hides rule/LLM/hybrid verdicts, check outcomes, judge
reasons, target names and sampler inclusion reasons. Terminal control characters
are rendered literally. Enter `pass`, `fail` or `unsure`; `s` or blank skips, `q`
quits, and EOF stops cleanly. Every explicit label is committed immediately.
Rerunning resumes with unlabeled items. There is no automatic/default label and
no bulk label import. Labels are keyed to the saved test/response, with timestamps,
in the migrated SQLite `human_labels` table.

The sampler defaults to every saved run in the selected database. Repeat `--run`
to restrict its input. It includes all held-out failures and definite rule/LLM
disagreements, then covers available category/language cells and fills random
target strata using the fixed seed. If mandatory items exceed 100, it keeps all
of them. If fewer than 100 exist, it returns the whole available pool. Pending
tests without rule results are excluded. Sampling never creates labels. Selection,
seed, mandatory-item reasons and exact membership are persisted for reproducibility;
the label view hides those reasons. Create a new sample after adding new runs or
judge results.

To import other saved runs, with response/check snapshots preserved and SQLite row
IDs remapped:

```powershell
python -m chatcheck import --input reports/meher_threads/mutation/final/weak.json --db review.db
python -m chatcheck import --input reports/meher_threads/mutation/final/heldout-hardened.json --db review.db
python -m chatcheck sample --size 100 --seed 42 --db review.db
```

Importing the same UUID twice leaves the existing run untouched. Imports retain
original rule results; they never import human labels or external judge opinions.
Use `results --judge llm` to compute judge opinions in the new database. Relabeling
the same saved item via the storage API updates its label, preserving creation time;
the CLI deliberately skips existing labels during normal resume.

## Agreement and interpretation

`agreement` returns JSON for rule-only, LLM-only and hybrid: accuracy, precision,
recall, F1, Cohen's kappa, confusion matrices, per-category/per-language breakdowns,
judge provenance and item IDs where predictions differ from your label.

Failure is the positive class. Human `unsure` labels and unlabeled items are
excluded from binary scoring. Definite predictions are scored on their covered
subset; `coverage`, `abstained`, `accuracy_with_abstentions_wrong` and a shared
`common_subset` make abstentions visible. Confusion-matrix rows are human
pass/fail; columns are predicted pass/fail/uncertain/not_judged. Undefined scores,
including kappa for single-class perfect agreement, are null. No labels means
null accuracy, never a fabricated quality percentage.

The sample intentionally oversamples failures and disagreement. Its metrics
describe the reviewed sample, not population accuracy. Keep a separately sampled
evaluation set for population estimates. Model/rubric changes require a new report;
the existing human labels stay attached to the unchanged saved responses.

## Injection, caching and retries

Each category has a versioned rubric in `chatcheck/llm_judge.py`. The response and
other test data appear only in a JSON record between digest-specific delimiters.
Embedded newlines and quote characters are escaped. System instructions explicitly
forbid obeying commands, role claims or fake delimiters in that record. Only the
rubric is in the provider's system message. Judge output is validated locally:
exact keys/enums, bounded short reason/evidence, duplicate-key rejection, severity
consistency and an evidence quote that actually occurs in the response. Invalid,
refused or truncated output is unjudged and never cached. These controls and mock
injection tests verify the boundary; they do not prove that a real model can never
be manipulated. Assess real injection cases with blinded labels as well.

SQLite caches hashes of rubric version, system rubric, prompt, response, expected
behavior, checks, category, language, severity, schema, provider/model namespace and
output cap. Fake scripts have their own namespace and cannot pollute real-provider
results. Changing rubric contents also invalidates the cache. A run's call/cost
reservations are transactional and persist before sending requests, including on
timeouts or process interruption. Duplicate evaluations within one evaluator share
cache results. Separate processes still share the run's budget safely.

Retries use bounded backoff and occur only for timeouts, network errors and HTTP
408/429/500/502/503/504. Authentication/configuration errors, invalid JSON/evidence,
refusals and truncation are not retried. Provider error messages exclude response
bodies and credentials. Judge verdicts are saved after each item, preserving
partial work on interruption.

## Verification checklist

```powershell
python -m pytest -q -p no:cacheprovider
python -m chatcheck validate --suite suites/clothing_store.json
python -m chatcheck validate --suite suites/clothing_store_heldout.json
```

- Existing rule checks, demo behavior and 76/20-test suites remain unchanged.
- Default runs do not make judge API calls; mock transports test both provider payloads.
- Schema, cache invalidation/persistence, cumulative call/cost limits, retries and injection boundaries pass.
- Exact critical leakage remains fail even with an LLM pass; disagreement requires review.
- Labels are blinded, explicitly entered, persisted and resumable; sampling creates none.
- Kappa fixtures cover 1, 0.5, 0 and -1; abstentions and undefined metrics are explicit.
- The mutation regression preserves the historical freeze, checks its unchanged bot,
  suite and deterministic-judge inputs, then freezes the current engine in a temporary
  audit before running it. Historical evidence is not rewritten. Held-out hardened
  results remain 15/20 with the same documented five failures.
- Review real quality only after entering human labels; no live quality claim is
  made from the offline fake demonstration.
