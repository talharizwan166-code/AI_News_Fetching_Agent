# Chatcheck: core chatbot test engine

Chatcheck is a separate Python 3.12+ package in this workspace. It runs a JSON
suite against either an HTTP chatbot API or a Playwright web widget, evaluates
deterministic rules, and retains runs, test definitions, every response attempt,
and final verdicts in SQLite. It does not require the news agent's credentials.

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

The [first library](../suites/README.md) contains **64 tests, eight per category**,
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
