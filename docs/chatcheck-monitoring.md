# Phase 6: monitoring, alerts, dashboard and retention

`chatcheck monitor` performs one cycle. GitHub Actions or Task Scheduler decides
when to invoke it. The command runs all configured suites as one saved run, compares
with the previous completed monitoring run for the same client/target IDs, generates
a report, and optionally sends a short alert. Normal `chatcheck run` behavior remains
unchanged. Monitoring uses deterministic rule judging; it does not enable LLM judging.

## Configuration and execution

Copy [the per-target example](../examples/monitor/client.json) and its target/suite
files. Paths are relative to the monitor config. Use a persistent database and reports
directory, and obtain the bot owner's permission before pointing at a real target.
The example is local-only and has synthetic recipients; edit it before deployment.

```powershell
.\.venv\Scripts\python.exe -m chatcheck.mock_server --port 8765
```

In another terminal, run one cycle with alert delivery disabled:

```powershell
.\.venv\Scripts\python.exe -m chatcheck monitor --config examples/monitor/client.json --db reports/monitor/monitor.sqlite3 --dry-run
```

`--dry-run` **runs the tests** and prints proposed alerts instead of contacting
SMTP/Slack. It consumes that scheduled cycle. Repeating it, or switching to live
delivery in the same cycle, does not rerun tests or send the previewed alerts.
Remove `--dry-run` for a future scheduled cycle when ready to send alerts.

Configuration fields:

| Field | Meaning |
| --- | --- |
| `client_id`, `target_id` | Stable, non-secret IDs; they define ownership and baseline selection. |
| `target`, `suites` | Existing HTTP/widget target config and one or more existing suite files. |
| `schedule` | Human-readable `description` plus positive `interval_minutes`; scheduling remains external. |
| `score_drop_threshold` | Alert when response-only score falls by **more than** this many percentage points. |
| `error_rate_threshold` | Alert when final connector errors exceed this percentage of attempted tests. |
| `recipients` | Explicit email recipients; no newline/display-name/header injection. |
| `channels` | `email`, `slack`, both, or an empty list. Default: email. |
| `call_budget` | Maximum request attempts across all suites, including errors and retries. Required. |
| `max_cost`, `cost_per_call` | Optional paired settings: monetary cap and a positive conservative per-request reservation. |
| `reports_dir`, `pdf` | Report root and optional PDF creation; HTML always remains available. |

The existing target's timeout, concurrency, retry and rate-limit settings still apply.
Monitoring adds a pre-request reservation; it never bypasses target-side limits. A
budget refusal makes no new request and records uncalled tests as **not attempted**,
not connector errors or failed model answers. A retry stopped after a connector error
retains that availability evidence. Startup failure becomes availability evidence too.

Cost reservations are **not provider billing**. For an HTTP/widget target, chatcheck
cannot see the target's internal LLM calls or token usage. Set `cost_per_call` to a
conservative upper bound and retain provider/target-side spending controls. The cap
enforces the configured estimate, including failed attempts; no price is guessed.

## Duplicate invocations and interruption

Cycles use UTC epoch-aligned intervals, not a cron parser. For example, 1440 minutes
means one UTC calendar-day bucket; a seven-day interval is epoch-aligned rather than
automatically Monday-aligned. The scheduler description is recorded but not executed.

SQLite claims `(client_id, target_id, interval slot)` transactionally before any target
calls. An active cycle also blocks overlapping cycles for that target. Calls reserve
their budget before execution. Repeated invocations return `already_claimed`; they do
not spend again, even if the preceding cycle failed. Keep the same durable database
and cadence; deleting state or changing IDs removes this protection.

Alert attempts are recorded before sending. This is **at-most-once**, not guaranteed
delivery: a crash after reservation or an ambiguous SMTP timeout can lose an alert,
but rerunning the command will not duplicate it. Alert statuses are `sent`, `failed`,
`attempted`, or `dry_run`. Failed delivery and requested-but-missing PDFs return exit
code 2. Behavioral regressions themselves return 0 after saving/reporting/alerting.

A hard-killed process can leave a `running` claim. It intentionally blocks automatic
re-execution. Inspect the saved run and confirm the process has stopped before an
operator changes that claim to `failed` in `monitor_cycles`. The next interval can
then run; the interrupted interval remains consumed. There is no automatic retry of
partially executed monitoring cycles and no automatic resend of uncertain alerts.

## Regression versus availability

Alerts trigger on a score drop exceeding its threshold, any **newly failing critical
test**, or an excessive connector error rate. Newly failing/fixed lists require an
unchanged test definition and usable responses on both sides. First-run critical
failures appear in the report but have no prior pass from which to claim regression.
If suites/definitions change, aggregate score-drop alerting is suppressed; unchanged
critical tests and availability are still evaluated. Changing coverage is displayed.

Connector errors never enter response-only scores or newly failing/fixed model lists.
Availability is usable responses divided by attempted tests, based on each test's
final attempt. Budget-skipped tests are excluded from this availability denominator
and shown separately as missing coverage. Zero attempts means no availability data.

## SMTP, Slack and secret handling

Environment variables only:

- `CHATCHECK_SMTP_HOST`, `CHATCHECK_SMTP_FROM`.
- `CHATCHECK_SMTP_PORT` (587 with STARTTLS, or 465 with implicit TLS).
- `CHATCHECK_SMTP_USER`, `CHATCHECK_SMTP_PASSWORD` for authentication.
- `CHATCHECK_SMTP_SSL=true` to use implicit TLS; otherwise STARTTLS is required.
- `CHATCHECK_SLACK_WEBHOOK` for the optional HTTPS webhook.

For target authentication use the existing header substitution, for example
`"Authorization": "Bearer ${TARGET_API_TOKEN}"`. Do not put literal credentials in
configs, prompts, command arguments or tracked files. No provider exception body or
webhook URL is stored in alert status records. Slack redirects are not followed.
Monitoring refuses inline authentication headers, credential-bearing URLs and
credential fields in request templates. Environment values referenced by target
headers are redacted even when their variable names are not recognized as secret.

Alert text contains counts, plain-language reasons and a report path. It contains no
raw response, prompt, test failure excerpt or copied provider diagnostic. Monitoring
applies the existing redaction patterns and replaces known secret environment values
**before SQLite writes**, including encoded forms. Secret variables are recognized by
names containing KEY, TOKEN, SECRET, PASSWORD, PASSWD, CREDENTIAL, AUTH, COOKIE,
WEBHOOK or CONNECTION_STRING. `CHATCHECK_SECRET_ENV_NAMES` can list additional names,
comma-separated. `CHATCHECK_REPORT_REDACT_PATTERNS` still supports client-specific
patterns. Redaction cannot infer unknown secrets or all personal data; use authorized
synthetic test data and configure additional patterns for client-specific evidence.

## Monthly summary

```powershell
.\.venv\Scripts\python.exe -m chatcheck monitor --config examples/monitor/client.json --db reports/monitor/monitor.sqlite3 --monthly --month 2026-09
```

Without `--month`, the command selects the previous complete UTC calendar month.
It reads saved runs and makes no target calls or alert deliveries. It uses the existing
summary renderer, adds a monthly page with weekly response scores and availability,
and retains the five-page PDF limit. Weeks begin Monday, including partial weeks;
weeks without runs display no data. Scores weight responses rather than averaging
percentages. The cover and issue pages describe the latest run, clearly distinguished
from monthly aggregates. Newly failing/fixed transitions include comparison with the
last run before the month. Lists are condensed to six names each in the PDF; the JSON
companion retains the complete lists/counts. A test may fail and recover in one month.

Outputs use a content-derived monthly filename and are never overwritten. Repeat
invocation with unchanged evidence returns the existing report. No appendix is added.

## Read-only dashboard

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-chatcheck-dashboard.txt
$env:CHATCHECK_DASHBOARD_DB = 'reports/monitor/monitor.sqlite3'
$env:CHATCHECK_DASHBOARD_PASSWORD = [System.Net.NetworkCredential]::new('', (Read-Host 'Dashboard password' -AsSecureString)).Password
.\.venv\Scripts\python.exe -m chatcheck dashboard
```

The launcher checks the password before starting Streamlit. The app authenticates
before reading data, compares passwords with `hmac.compare_digest`, and removes the
submitted password from widget session state. Password rotation invalidates existing
session tokens. It binds to loopback and disables usage telemetry. This is a shared
administrator view of all monitored clients, not a multi-tenant client portal.

SQLite is opened with `mode=ro` and `query_only=ON`. The UI has target selection, score
and availability trends, newly failing/fixed tests and redacted failure evidence. It
has no run, edit, label or purge actions. It uses no mutable data cache.
The Streamlit dependency is optional and does not affect ordinary CLI installation.
The implementation follows Streamlit's official [password input](https://docs.streamlit.io/develop/api-reference/widgets/st.text_input),
[session-state](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state)
and [server configuration](https://docs.streamlit.io/develop/api-reference/configuration/config.toml) APIs.

## Client retention and deletion receipt

Copy [the retention policy](../examples/monitor/retention.json). Each client has its
own number of days and reports root; policy paths are relative to the policy file.

```powershell
.\.venv\Scripts\python.exe -m chatcheck retention --db reports/monitor/monitor.sqlite3 --policy examples/monitor/retention.json --out reports/monitor/retention-preview.html
# Only after reviewing the inventory:
.\.venv\Scripts\python.exe -m chatcheck retention --db reports/monitor/monitor.sqlite3 --policy examples/monitor/retention.json --yes --out reports/monitor/retention-receipt.html
```

Default inventory uses a read-only database connection. Old, finished runs are selected
by explicit monitoring client ownership and finish timestamp. Artifact age uses its
registered creation time, independently of the run's age. Reports from monitoring,
monthly summaries, and subsequent `chatcheck report` / `chatcheck export --output`
files for owned runs are registered automatically. Other clients' runs, running runs,
recent files and unregistered copies are preserved. There is no filename/glob guessing
and no automatic attribution of historical runs that lack client ownership.

`--yes` uses the existing transactional run purge, including dependent responses,
judgments, labels, samples and cache references. Registered HTML/PDF/JSON files must
be beneath the configured reports root, with no symlink/junction ancestors and an
unchanged content hash. Outside/replaced files are listed as blocked, not deleted.
Only individual files are removed; no recursive directory deletion occurs. Missing
files are safely deregistered. Filesystem and database deletion are not one atomic
transaction; rerunning after an interruption safely finishes eligible remaining work.

Minimal cycle IDs/client IDs/target IDs/timing/status/budget counters and alert status
remain to preserve duplicate protection. Purging a run clears its stored monitoring
summary, schedule and report-root metadata. Fresh/or blocked artifacts keep the
registration needed for a later inventory. Backups, remote provider logs, other file
copies and operating-system recoverability are outside this command's deletion scope.
This is an operational retention receipt, not a legal compliance certification.

## Scheduler templates and verification

- [GitHub Actions cron template](../examples/monitor/github-monitor.yml): deliberately
  not installed as an active workflow. Uses a self-hosted Windows runner, durable
  state outside checkout, a concurrency group and environment-provided secrets.
- [Windows Task Scheduler example](../examples/monitor/windows-task.ps1): ignores
  overlapping instances, uses the task account's environment and stores no passwords
  in task arguments. Example local time corresponds to Asia/Karachi; adjust locally.

Do not use a fresh ephemeral SQLite file for each Actions run: that defeats baselines,
budgets and duplicate protection. Back up the durable database according to the same
client retention policy. The command does not install or enable either schedule.

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe scripts/demo_monitor.py --out-dir reports/monitor-phase6-next
```

The demo uses only in-process fake targets and dry-run alerts; it generates five
synthetic historical cycles, a monthly HTML/PDF, a read-only dashboard snapshot and
a retention inventory. Choose a new output directory. [Saved demo artifacts](../reports/monitor-phase6/README.md)
are available for review.

Verification checklist: thresholds and first-run behavior; matched definitions;
connector-error separation; concurrent duplicate claims; shared call/cost caps with
retries; fake SMTP/Slack; dry-run suppression; no secrets in database/report/alerts;
monthly aggregation and PDF page cap; password refusal and SQLite read-only mode;
retention preview, real synthetic purge, client isolation and path/hash guards.

Verified in this workspace: **855 tests passed, 2 skipped** (42 new Phase 6 tests).
The saved synthetic monthly PDF has four pages. Live alerts and schedules were not
activated; real deletion tests used only temporary synthetic client data.
