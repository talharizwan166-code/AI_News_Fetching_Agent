# Chatcheck: core chatbot test engine

Chatcheck is a separate Python 3.12+ package in this workspace. It runs a JSON
suite against either an HTTP chatbot API or a Playwright web widget, evaluates
deterministic rules, and retains runs, test definitions, every response attempt,
and final verdicts in SQLite. It does not require the news agent's credentials.

Phase 2A adds opt-in Gemini/OpenAI rubric judging, persistent call/cost budgets,
blinded human labels, stratified sampling and agreement reports. See
[judging and human review](chatcheck-judging.md) for exact offline and capped
real-provider commands. Existing rule checks remain enabled; judging defaults off.

Phase 2B adds [client-ready HTML reports and optional PDF export](chatcheck-reports.md),
including redacted evidence, inline charts, a full appendix and before/after comparisons.

Phase 2C adds [installation, reliable PDF export, workspace setup and client data retention](chatcheck-operations.md).
Install the package for a `chatcheck` console command; `python -m chatcheck` remains supported.

## Quick start

From the repository root, activate the virtual environment and install the engine:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-chatcheck.txt
python -m chatcheck.mock_server
```

The mock server listens on `http://127.0.0.1:8765`. Leave it running. In a second
terminal, activate the same environment and run:

```powershell
python -m chatcheck run --target examples/chatcheck/target.http.json --suite examples/chatcheck/suite.json
```

The six example tests should pass. Copy the UUID printed after `Run:` and inspect
or export the stored results:

```powershell
python -m chatcheck results --run <id>
python -m chatcheck export --run <id> --format json
python -m chatcheck export --run <id> --format json --output results.json
```

`<id>` is a placeholder for that UUID. `--output` creates a new file and refuses
to overwrite an existing file. Without it, export writes only JSON to stdout.
The `run`, `results` and `export` commands accept `--db path/to/results.db`; the default is `chatcheck.db` in
the current directory. The parent directory must exist. Use the same database
path for run, results and export.

To see both passing and failing verdicts, including a recovered transient error:

```powershell
python -m chatcheck run --target examples/chatcheck/target.http.json --suite examples/chatcheck/suite.failures.json
```

This deliberately reports one passing and two failing tests. Exit codes are `0`
for a passing run or successful results/export, `1` for a completed run with
failing tests, `2` for configuration/engine errors, and `130` for Ctrl+C.
The `validate` command also returns `0` on success and `2` for invalid input.

## HTTP target configuration

```json
{
  "name": "My API",
  "type": "http",
  "url": "https://example.com/chat",
  "method": "POST",
  "headers": {"Authorization": "Bearer ${CHATBOT_API_KEY}"},
  "request_template": {
    "messages": [{"role": "user", "content": "{{prompt}}"}],
    "temperature": 0
  },
  "response_json_path": "$.choices[0].message.content",
  "runner": {
    "concurrency": 4,
    "timeout": 30,
    "retries": 2,
    "rate_limit": 5,
    "retry_backoff": 0.25
  }
}
```

Headers support `${ENVIRONMENT_VARIABLE}` substitutions; missing variables fail
before requests start. The CLI does not load `.env`. `{{prompt}}` is replaced in
every JSON string value, safely preserving quotes, newlines and Unicode.
The JSONPath must select exactly one string. Missing paths, multiple results,
non-string selections and malformed JSON become failed test verdicts.

Defaults are POST, `{"message":"{{prompt}}"}`, and `$.reply`. POST, PUT and PATCH
are supported with a JSON body. Non-2xx responses fail; redirects are not followed.
HTTP uses [HTTPX's async client](https://www.python-httpx.org/async/).
Each prompt should represent an independent conversation; include any required
model or system-message fields in the template.

The repository's [`.env.example`](../.env.example) includes an optional
`CHATBOT_API_KEY` placeholder and commented browser-test settings. Set variables
in the process environment when using them; copying the file alone does not
load them into Chatcheck. The local mock and `validate` need no credentials.

## Widget configuration

Install Chromium once:

```powershell
python -m playwright install chromium
python -m chatcheck run --target examples/chatcheck/target.widget.json --suite examples/chatcheck/suite.json
```

For a browser installed inside this workspace, set the same environment variable
before installing and running:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) '.tools/playwright'
python -m playwright install chromium
```

Widget targets use `type: "widget"`, `url`, `input_selector`, and `reply_selector`.
Optional `submit_selector` clicks a button; when omitted, the connector presses
Enter in the input. `headless` defaults to true. Each attempt gets a new isolated
[Playwright browser context](https://playwright.dev/python/docs/api/class-browser#browser-new-context),
which is closed after completion or timeout.

The connector ignores existing greetings, waits for a new or changed last reply,
then requires its text to remain stable for 500 ms. For streaming widgets, use
a reply selector that matches only completed messages, such as the mock's
`.reply[data-complete='true']`. Stability alone cannot distinguish a completed
reply from a long pause between streamed tokens. Selectors must target the input
and bot messages in the main document; login flows, iframes, and multi-turn
conversations are outside this phase.

## Suite and checks

A suite is either an array of tests or an object with a `tests` array:

```json
{
  "tests": [
    {
      "id": "greeting",
      "prompt": "hello",
      "checks": [
        {"type": "contains", "value": "hello", "case_sensitive": false},
        {"type": "not_contains", "value": "error"},
        {"type": "max_length", "value": 200}
      ]
    }
  ]
}
```

IDs are unique nonempty strings; omitted IDs default to the 1-based position.
Prompts and check lists must be nonempty. All checks must pass. A connector error
always fails the test. Invalid/unknown checks and malformed regexes fail suite
validation before any target requests or run records are created.

| Check type | Value | Meaning |
| --- | --- | --- |
| `contains` | Nonempty string | Response includes the substring |
| `not_contains` | Nonempty string | Response excludes the substring |
| `equals` | String | Exact equality, including whitespace |
| `regex` | Nonempty Python regex | At least one match anywhere in the response |
| `min_length` | Nonnegative integer | Minimum number of Unicode characters |
| `max_length` | Nonnegative integer | Maximum number of Unicode characters |
| `json_valid` | Omit value | Response parses as JSON; NaN/Infinity rejected |

The four text checks accept `case_sensitive` (default true). Regexes and test
configs are trusted local inputs. Each verdict records a reason and every check's
result, so failed checks remain visible in the JSON export.

## Optional test metadata (Phase 1A)

Existing suites with only `id`, `prompt` and `checks` continue to work. New suites
may add any of these optional fields:

| Field | Allowed values / default |
| --- | --- |
| `category` | `groundedness`, `prompt_injection`, `data_leakage`, `scope`, `policy_accuracy`, `language`, `tone`, `robustness`; default `null` |
| `language` | `ur` (Urdu script), `roman_ur` (Roman Urdu), `en` (English); default `null` |
| `expected_behavior` | Nonempty plain-language string, or `null`; default `null` |
| `severity` | `critical`, `high`, `medium`, `low`; default `null` |
| `tags` | List of nonempty strings; default `[]`; explicit `null` is invalid |

Enum values are case-sensitive. Error messages identify the test and field and
list allowed enum values. Empty strings are invalid metadata values. Tags are
free-form labels, not an enum. The same metadata validation applies to direct
Python `TestCase` construction.

```json
{
  "id": "returns-ur",
  "category": "language",
  "language": "ur",
  "expected_behavior": "Answer in Urdu and state the 14-day return window.",
  "severity": "high",
  "tags": ["returns", "urdu-script"],
  "prompt": "واپسی کی مدت کتنے دن ہے؟ اردو میں بتائیں۔",
  "checks": [
    {"type": "regex", "value": "(?:14|۱۴|چودہ)\\s*(?:دن|روز)"},
    {"type": "regex", "value": "واپس|واپسی"}
  ]
}
```

Metadata does not change the judge: only `checks` decide pass/fail.
`expected_behavior` documents the intended outcome for human review; severity
does not weight results. `run` and `results` show `category=... severity=...` on
each test row. Missing values display as `unspecified`. JSON export includes all
five fields, including their defaults for legacy tests.

## Local suite validation and first library

Validation loads the same suite model and checks as the runner, without creating
a connector, contacting a target, or opening a database:

```powershell
.\.venv\Scripts\python.exe -m chatcheck validate --suite examples/chatcheck/suite.json
.\.venv\Scripts\python.exe -m chatcheck validate --suite suites/clothing_store.json
```

The output reports the total and separate counts for every category, language
and severity, including zero counts and an `unspecified` bucket for old suites.
`--suite` takes a JSON file, not a directory. Invalid JSON, missing files,
duplicate IDs, invalid checks or invalid metadata produce an error and exit 2.

The [library](../suites/README.md) contains **76 tests**: the original 64 (eight
per category) unchanged, plus 12 multilingual mutation-gap probes,
with English, Urdu and Roman Urdu questions, spelling mistakes, benign attack
prompts, policy boundaries, tone and robustness cases. Its fixed ground truth is
the fictional clothing store [FAQ](../examples/chatcheck/kb/faq.md). Seed the
[synthetic private fixture](../examples/chatcheck/private-fixture.md) in the
target's private test context before using the leakage probes. Both documents
are local fixtures; Chatcheck does not inject them automatically.

Configure a real or test store chatbot with these fixtures, then use your own
target config:

```powershell
.\.venv\Scripts\python.exe -m chatcheck run --target target.store.json --suite suites/clothing_store.json --db store-results.db
.\.venv\Scripts\python.exe -m chatcheck results --run <id> --db store-results.db
.\.venv\Scripts\python.exe -m chatcheck export --run <id> --format json --db store-results.db
```

`target.store.json` must be created for your endpoint using the HTTP or widget
format above. The original mock is an engine smoke test and has no clothing-store
knowledge; this library is expected to fail against it. Text rules are limited
probes, not a semantic guarantee: check actual responses against the documented
expected behavior, especially for paraphrases, contradictions and language quality.

## Meher Threads demo target (Phase 1C)

The [demo server](../demo_bots/meher_threads/README.md) makes this library runnable
offline without a key or model. It loads the public FAQ and seeds the synthetic
private fixture automatically. The FAQ is its only source of factual store
knowledge; private values are stored separately. The server reads neither test
IDs nor authored sample responses. It uses deterministic intent rules and response
templates, so its language coverage is finite.

The easiest way to reproduce the comparison is:

```powershell
.\.venv\Scripts\python.exe -m demo_bots.meher_threads.compare
```

This starts weak and hardened servers on available loopback ports, runs all 76
tests through the real HTTP connector, saves `runs.db`, `weak.json`, `hardened.json`,
`comparison.json`, `manifest.json` and `report.md` under a new timestamped folder
in `reports/meher_threads/`, and shuts down the servers. Use `--output-dir` with
a **new** directory to choose another destination. Existing reports are never
overwritten. JSON exports are portable; SQLite files are retained locally and
ignored by Git. Hashes in the manifest identify the exact suite, FAQ, fixture,
target configs and implementation used.

To run the servers and Chatcheck CLI separately, use two terminals:

```powershell
# Terminal 1: weak target, intentionally vulnerable, port 8766
.\.venv\Scripts\python.exe -m demo_bots.meher_threads --mode weak
```

```powershell
# Terminal 2: hardened target, port 8767
.\.venv\Scripts\python.exe -m demo_bots.meher_threads --mode hardened
```

Then in a third terminal:

```powershell
.\.venv\Scripts\python.exe -m chatcheck run --target examples/chatcheck/target.meher.weak.json --suite suites/clothing_store.json --db meher-demo.db
.\.venv\Scripts\python.exe -m chatcheck run --target examples/chatcheck/target.meher.hardened.json --suite suites/clothing_store.json --db meher-demo.db
.\.venv\Scripts\python.exe -m chatcheck results --run <id> --db meher-demo.db
.\.venv\Scripts\python.exe -m chatcheck export --run <id> --format json --db meher-demo.db
```

Use the run IDs printed by `run`. Weak intentionally exits 1 because checks fail;
execute the hardened command separately rather than chaining with `&&`. Both
servers bind only to `127.0.0.1`. POST `/chat` accepts only a nonempty string
`message` in a JSON object and responds with `reply` plus the compatible
`choices[0].message.content` path. GET `/health` reports status and mode.
No mode can be selected by the request body. Stop each server with Ctrl+C.

Default mode is hardened. Weak accepts role/policy overrides, guesses absent
facts, discloses only the seeded synthetic records, handles unrelated requests,
and responds in English. Hardened ignores policy overrides, declines private
requests, acknowledges missing knowledge, stays on topic, and uses English,
Urdu or Roman Urdu. Known private fixture values are blocked at the output
boundary. Numeric policies come from the FAQ at startup; `--faq` and
`--private-fixture` can select compatible fixture files for experiments.

### Saved comparison and check review

The [saved baseline](../reports/meher_threads/baseline/report.md) has:

| Category | Weak | Hardened |
| --- | ---: | ---: |
| Overall | 14/64 (21.9%) | 64/64 (100%) |
| Groundedness | 0/8 (0%) | 8/8 (100%) |
| Prompt injection | 0/8 (0%) | 8/8 (100%) |
| Data leakage | 0/8 (0%) | 8/8 (100%) |
| Scope | 0/8 (0%) | 8/8 (100%) |
| Policy accuracy | 5/8 (62.5%) | 8/8 (100%) |
| Language | 2/8 (25%) | 8/8 (100%) |
| Tone | 3/8 (37.5%) | 8/8 (100%) |
| Robustness | 4/8 (50%) | 8/8 (100%) |

All eight critical leakage cases fail on weak and pass on hardened. All **14
shared outcomes** are listed as possible weak tests in the report. A shared
pass can mean the weak bot also knows that basic policy; it is a review signal,
not automatic proof that a test is defective.

[The check review](../reports/meher_threads/check-review.md) documents seven
initial hardened false failures: six uncertainty responses and one valid JSON
delivery paraphrase. The corresponding regexes now accept equivalent wording
while retaining bad-answer regression cases. The offline 100% score is a demo
result, not a claim of general model security, semantic correctness or fluency.

### Optional LLM mode (off by default)

Set `OPENAI_API_KEY` in the environment of the server process and optionally set
`MEHER_LLM_MODEL`. The default is the low-cost
[`gpt-5-nano`](https://developers.openai.com/api/docs/models/gpt-5-nano). The
[Responses API](https://developers.openai.com/api/docs/guides/text) system
instructions include the public FAQ. Private fixture values stay on the local
server and are excluded from those instructions. The `.env.example` placeholders
are documented but not automatically loaded.

```powershell
# After setting OPENAI_API_KEY in this terminal:
$env:MEHER_LLM_MODEL = 'gpt-5-nano'
.\.venv\Scripts\python.exe -m demo_bots.meher_threads --mode llm
# Another terminal, only when you want to incur model API usage:
.\.venv\Scripts\python.exe -m chatcheck run --target examples/chatcheck/target.meher.llm.json --suite suites/clothing_store.json --db meher-llm.db
```

LLM mode listens on port 8768 and makes paid external requests. It is not part of
the offline comparison and is not deterministic. The adapter uses `store: false`,
a 2,048-token output cap and a 45-second upstream timeout. Its target config uses
one worker and no retries. Missing keys fail startup; unsuccessful or incomplete
upstream replies produce errors rather than fabricated fallback answers. Known
private values are blocked in output, but that exact-value guard is not a general
LLM security guarantee. API tests use a fake transport; no live paid API run was
performed for the saved baseline.

### Rebuild and verify

The authoring script moved to `scripts/build_chatcheck_library.py`. It regenerates
the suite and authored good/bad-response fixtures relative to the repository root,
even when launched from another directory:

```powershell
.\.venv\Scripts\python.exe scripts/build_chatcheck_library.py
.\.venv\Scripts\python.exe -m chatcheck validate --suite suites/clothing_store.json
.\.venv\Scripts\python.exe -m pytest tests/chatcheck/test_meher_demo.py tests/chatcheck/test_meher_llm.py tests/chatcheck/test_library.py -q -o cache_dir=.tools/pytest-cache
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) '.tools/playwright'
$env:CHATCHECK_TEST_WIDGET = '1'
.\.venv\Scripts\python.exe -m pytest tests -q -o cache_dir=.tools/pytest-cache
```

Verification checklist: weak scores below hardened over actual HTTP; all eight
critical leakage probes fail on weak and pass on hardened; every shared outcome
is reported; correct paraphrases pass while incorrect policy values fail; changing
the FAQ changes the bot's answer; offline mode needs no key; API failures are
sanitized; legacy suites, database migrations and browser tests still pass.

## Runner and storage behavior

CLI flags `--concurrency`, `--timeout`, `--retries`, `--rate-limit` and
`--retry-backoff` override the target's `runner` object. Defaults are 4 workers,
30 seconds per attempt, 2 additional retries, unlimited rate (0), and 0.25 seconds
initial backoff. Workers process tests independently and exports retain suite order.

The global rate limit is request starts per second, including retries, with no
initial burst. Timeout covers one connector call, including browser navigation
and reply waiting, but excludes queue/rate-limit wait, backoff and browser startup.
Latency is measured per attempt using a monotonic clock in milliseconds. Cancellation
waits for connector cleanup; a remote server may continue processing a timed-out
request. Retrying a prompt can therefore send it more than once.

Transport failures, timeouts, HTTP 408/429 and 5xx errors retry with exponential
backoff capped at 30 seconds. Other HTTP errors, invalid response mappings,
widget errors and rule failures do not retry. Each attempt is committed immediately;
the final attempt determines the verdict. Ctrl+C retains completed work and marks
the run cancelled. An abrupt process kill may leave the run marked running.

SQLite has `runs`, `tests`, `responses` and `verdicts` tables linked by foreign keys.
`tests` contains a snapshot for each run, so later suite changes cannot alter history.
`chatcheck_migrations` tracks ordered versions from `chatcheck/storage.py`; append
the next migration to `MIGRATIONS` for future schema changes. Migrations execute
transactionally and reject newer schemas. Store engine results in their own DB.
Target headers and request templates are not persisted. Prompts, returned text,
errors, checks and runner settings are persisted.

Migration **2** appends `category`, `language`, `expected_behavior`, `severity`
and `tags_json` columns to the existing `tests` table. Opening an existing v1
database applies it transactionally, retaining old runs, responses and verdicts.
Old rows receive `null` metadata and an empty tag list. Reopening is idempotent.
New runs snapshot metadata with the prompt and checks; export decodes `tags_json`
back to the public `tags` list.

## Mutation testing and held-out split (Phase 1D)

Run the main library against hardened, weak and all 12 single-bug mutants:

```powershell
.\.venv\Scripts\python.exe -m demo_bots.meher_threads.mutation run
```

The command manages temporary loopback servers and writes a new timestamped
directory under `reports/meher_threads/mutation/`. Each has `runs.db`, complete
JSON exports, `matrix.json` (mutant by category plus failed test IDs), `report.md`,
suite/metadata snapshots and a source manifest. Detection counts only failures
on tests that pass on hardened. All hardened failures are reported separately.
`--suite <path>` selects another library; `--output-dir <new-directory>` selects
the destination. Existing results are never overwritten.

The [audit](../reports/meher_threads/mutation/README.md) preserves the original
64-test baseline: 8/12 mutants caught, four gaps, five dead tests, and zero
hardened failures. Twelve narrow additions (one per language for each gap) now
catch 12/12 mutants in expected categories while hardened passes 76/76. The
original 64 tests and hardened bot were not changed. Dead tests are listed even
when retained as regression coverage; no mutation in this set necessarily
exercises every policy.

To repeat the **frozen**, untuned 20-test held-out evaluation as well:

```powershell
.\.venv\Scripts\python.exe -m demo_bots.meher_threads.mutation run --heldout suites/clothing_store_heldout.json --freeze reports/meher_threads/mutation/heldout-freeze.json
.\.venv\Scripts\python.exe -m pytest tests/chatcheck/test_mutation.py -q
```

Held-out hardened scored **15/20 (75%)**. Failures are `heldout.send-back-en`,
`heldout.delivery-misspelling-en`, `heldout.rtrn-spelling-roman`,
`heldout.return-variant-urdu`, and `heldout.inventory-urdu`: generic clarification
replies where a policy answer or explicit uncertainty was required. These remain
failures in exports. Pytest asserts this documented failure set, not a fabricated
100% score. The bot and checks were frozen before the first held-out run and
remain unchanged. This same-author split is not an independent blind benchmark.

The freeze uses SHA-256 of UTF-8 text with normalized LF newlines and is verified
before/after execution. Changed inputs abort the run. For a new experiment use
`mutation freeze --heldout <new-suite> --output <new-freeze>` before running the
new questions; preserve this audit and do not relabel already-seen questions as
unseen. Held-out failures are report-only. The batch command exits 1 for main-suite
gaps, expected-category gaps or hardened failures, and 2 for invalid input or a
freeze mismatch.

For a standalone target:

```powershell
.\.venv\Scripts\python.exe -m demo_bots.meher_threads --mode mutant --mutant wrong_return_window
```

It listens on port 8769 and implements the same POST `/chat` contract. IDs,
triggers and expected categories are declared in
[mutants.json](../demo_bots/meher_threads/mutants.json). Each mutant delegates all
other behavior to hardened and reads no suites or test IDs. The empty-response
mutant uses punctuation/emoji-only input because actual blank messages are
already rejected by the suite and HTTP validators.

Verification checklist:

- Validate both JSON suites: 76 main tests and 20 held-out tests.
- Confirm every mutant has a detection in an expected category, and zero main-suite gaps.
- Confirm hardened passes 76/76 and the original 64 test objects are unchanged.
- Review all five dead tests and the five documented held-out failures.
- Verify freeze hashes, saved SQLite/export parity, and mutation pytest checks.

## Tests

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests/chatcheck -q
$env:CHATCHECK_TEST_WIDGET = '1'
python -m pytest tests/chatcheck -q
python -m pytest tests -q
```

Widget tests require Chromium; they are skipped unless `CHATCHECK_TEST_WIDGET=1`.
Tests create their own mock servers on available loopback ports and temporary
SQLite databases. They cover real HTTP transport, rule outcomes, retries, timeout
recovery, concurrency, rate limits, cancellation, migrations, CLI subprocesses,
JSON export, and the real browser widget. CI installs Chromium and enables widget
tests. Mock controls include `echo:text`, `delay:seconds:text`, `flaky:text` (503
on the first request per exact prompt), `error` (500), `bad-request` (400), and
`invalid-json`. Restarting the mock resets its request counters.
