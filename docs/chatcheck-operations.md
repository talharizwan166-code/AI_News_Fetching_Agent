# Chatcheck Phase 2C: installation, reliability and retention

## Install the CLI

Chatcheck supports Python **3.12+**. From the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
chatcheck --help
python -m chatcheck --help
```

Both commands use the same entry point. The `[dev]` extra includes pytest, wheel
build tools and the PDF test reader. Install `requirements-dev.txt` for the whole
repository's test dependencies, including the existing news-agent project.
The core package installs HTTP/browser connectors and Jinja2. The optional
`[pdf]` extra adds WeasyPrint as a fallback; Chromium export uses core Playwright.

Build and install a distributable wheel:

```powershell
python -m build --wheel
python -m pip install dist/chatcheck-0.2.0-py3-none-any.whl
```

Wheels include the canonical 76-test suite, the 20-test held-out suite, the empty
starter suite, report templates, CSS, `fixes.json` and workspace templates.
They exclude databases, credentials, client reports, the news agent and demo bots.
The source library is mapped into `chatcheck.suites` at build time, avoiding a
second copy of the suite definitions. Installed report templates are resolved
relative to the installed package, independent of the current working directory.

The packaging regression builds a wheel from a clean copy of distribution inputs,
installs it outside the source tree with no network/dependency resolution, asserts
that imports come from that installation, renders a report, reads both suites,
runs `init`, and invokes the installed console command.

## Initialize a client workspace

```powershell
chatcheck init client-workspace
cd client-workspace
```

This creates four files, skipping every existing file or directory:

- `target.json`: an HTTP target config with placeholder endpoint/authentication.
- `suite.json`: an exact-content copy of the library's empty starter template.
- `.env.example`: variable names and conservative optional judge caps, no keys.
- `README.md`: setup, run/report and retention commands.

Initialization never starts a server, calls a provider, writes labels, or creates
a database. It uses exclusive file creation to avoid overwriting user work.
Running `chatcheck init` without a directory initializes the current directory.

Edit the target and add reviewed tests before running. Empty suites are
intentionally rejected; `init` does not silently turn a fictional store library
into client acceptance criteria. To inspect the installed full library:

```powershell
python -c "from chatcheck.workspace import library_directory; print(library_directory())"
```

Chatcheck reads the process environment; it does not automatically load `.env`.

## Chromium PDF export

```powershell
chatcheck report --run <id> --db client.db --out client-report.html --pdf
```

The default renderer is locally installed Playwright Chromium. This source
checkout automatically finds its matching `.tools/playwright` browser revision.
An explicit `PLAYWRIGHT_BROWSERS_PATH` takes precedence. On a fresh machine,
install a browser once:

```powershell
python -m playwright install chromium
```

PDFs use A4, print backgrounds, 17 mm top / 18 mm bottom / 14 mm side margins and
`current / total` footer page numbers. Trusted print CSS prevents duplicate CSS
page counters. Reports keep the existing UTF-8/Urdu font fallbacks. JavaScript is
disabled, service workers are blocked, the browser context is offline, and all
request routes are aborted. No network resources are fetched during rendering.
The browser is closed even when rendering fails. Only redacted, escaped report
HTML reaches either PDF renderer.

WeasyPrint remains the fallback if Chromium cannot export:

```powershell
python -m pip install -e ".[pdf]"
# Or: python -m pip install -r requirements-chatcheck-pdf.txt
```

Its native libraries may also be needed. If neither renderer works, the HTML
remains available and the command prints installation guidance for both backends.
Existing output files are never overwritten. Backend errors are sanitized rather
than printing report contents in diagnostics. See the official
[Playwright PDF API](https://playwright.dev/python/docs/api/class-page#page-pdf)
and [WeasyPrint installation instructions](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html).

The real-PDF regression checks the `%PDF` signature, three parsed pages, A4
dimensions, page-number footers, and disabled response scripts. It skips only
when the matching browser is absent. A separate transport-settings test confirms
that routes are aborted and offline/script/service-worker settings are applied.

## Client data-retention procedure

Close active jobs using the client database. Select the correct database and
either a specific run or the agreed age cutoff. Deletion requires an explicit
`--yes`; omitting it refuses the operation before database initialization/migration.

```powershell
# One run, with its dependent records.
chatcheck purge --run <id> --db client.db --yes

# Finished runs started more than 30 days ago, compared in UTC.
chatcheck purge --older-than 30 --db client.db --yes
```

`--run` and `--older-than` are mutually exclusive. Days may be fractional, finite
and nonnegative; the cutoff is strict (a run exactly at the cutoff is retained).
Age-based deletion excludes running runs and unknown/invalid timestamps. A
specific run selector can delete a running run, so stop its workers first.
An unknown explicit run is an error; no age matches is a successful no-op.

The operation uses a single SQLite write transaction and prints deleted counts
for runs, tests, response attempts, rule verdicts, LLM/hybrid verdicts, human
labels, judge calls, cache ownership links, cached verdicts and sample records.
Foreign-key cascades remove dependent rows. Samples containing other runs keep
their remaining members/labels; deleted source IDs and mandatory-item IDs are
removed from their metadata. Empty affected samples are deleted. Existing sample
membership and pool counts are updated, so create a fresh sample if you need a
new randomized review set after retention.

Judge-cache ownership is tracked for both fresh evaluations and cache hits.
Migration 4 backfills owners from existing saved verdicts. A cache shared by
another retained run survives until its last owner is removed. Unowned legacy
cache entries cannot be safely attributed and are discarded during a nonempty
purge. Other runs' prompts, responses, verdicts and labels remain unchanged.
Schema/migration records remain so the database stays usable.

`secure_delete` is enabled for the purge connection. This is database row deletion,
not a promise of forensic erasure from storage, journal history or backups. Apply
the same agreed retention policy to **HTML/PDF/JSON exports, copied databases,
backups and provider-side logs**: purge does not find or delete those separate
copies. Keep client data on protected storage and out of source control.

For a specific deleted run, verify that it is no longer readable:

```powershell
chatcheck results --run <deleted-id> --db client.db
# Expected: Run not found; exit code 2.
```

The regression tests verify zero remaining data rows when the last run is purged,
that other runs are unchanged, shared-cache cleanup, sample metadata cleanup,
UTC cutoff boundaries, confirmation and migration backfill. Synthetic test labels
exist only in temporary fixtures; retention commands never create labels.

## Deterministic rate limiting and three-run verification

`RateLimiter` accepts injected monotonic-clock and async-sleep functions.
Production still uses `time.monotonic` and `asyncio.sleep`. `run_suite` can accept
a shared limiter for tests. The former flaky test now exercises concurrent
workers and retries against a virtual clock, asserting six exact admission times
at 0.125-second intervals. It does not infer admission timing from server arrival
times, which can vary with scheduling and HTTP buffering.

Run the entire repository suite three times sequentially and retain evidence:

```powershell
python -m pip install -r requirements-dev.txt
python -m scripts.verify_chatcheck_stability --runs 3 --out reports/meher_threads/phase2c/stability-local
```

Choose a fresh output directory. The script records each complete pytest log,
exit status, Python version and a source fingerprint in `stability.json`. It
stops on a failure or a source change. The ordinary single-run command remains:

```powershell
python -m pytest -q -p no:cacheprovider
```

## Verification checklist

- The old rate-limit regression uses virtual time and still verifies shared
  worker/retry admission spacing.
- Real Chromium export yields a multipage A4 PDF with page numbers; resource
  routing is blocked, and missing backends retain HTML with clear guidance.
- Editable and built-wheel console commands work alongside `python -m chatcheck`.
- Installed wheels resolve suites, report templates and the fixes catalog outside
  the source checkout.
- Purge requires `--yes`, reports row counts and removes all selected data,
  cache references and sample references while retaining other runs.
- `init` copies the empty library template and never overwrites existing files.
- Three consecutive complete-suite logs and their source fingerprint are retained
  under `reports/meher_threads/phase2c/stability/` for this implementation.
