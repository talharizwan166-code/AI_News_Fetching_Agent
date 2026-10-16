# Chatcheck Phase 2B: client reports

Generate a standalone UTF-8 HTML report from a saved SQLite run. No chatbot,
LLM, labeling action or external asset request is needed. Jinja2 is included in
the core Chatcheck requirements. PDF export now defaults to the locally installed
Playwright Chromium; WeasyPrint remains an optional fallback. See the
[Phase 2C operations guide](chatcheck-operations.md) for packaging and data retention.

## Quick start

From the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-chatcheck.txt
python -m chatcheck report --run <id> --out report.html --client "Client name"
```

Use the run UUID printed by `chatcheck run`. If your run is in another database,
add `--db path/to/runs.db`. Output directories must already exist. The command
refuses to overwrite existing HTML or PDF files; choose a new `--out` filename.
HTML output must have an `.html` or `.htm` extension.

For a comparison, select a baseline in the same database:

```powershell
python -m chatcheck report --run <new-id> --compare <baseline-id> --out comparison.html --client "Client name" --db runs.db
```

Reports contain a client/target cover, dates and run identity, suite identity,
overall test score, a deterministic executive summary of at most five sentences,
category/language score tables with inline SVG bars, the top five failure groups,
judge disagreements, scope and limits, and every saved test's pass/fail outcome.
The HTML appendix has expandable prompt/response evidence without JavaScript.
Response excerpts are truncated after redaction; prompts remain complete except
for redaction. Every category/check recommendation comes from the reviewed static
catalog in [`fixes.json`](../chatcheck/report_templates/fixes.json).

## Exact demo commands

The generated [weak](../reports/meher_threads/samples/weak.html) and
[hardened](../reports/meher_threads/samples/hardened.html) reports are committed
as self-contained HTML. Their local database is ignored by Git. To reconstruct
both reports and their database from archived saved response exports:

```powershell
python -m scripts.demo_chatcheck_report --out-dir reports/meher_threads/samples-local
```

Choose a fresh directory if those files already exist. No target server, provider
key or human labels are required. Then generate another client report:

```powershell
python -m chatcheck report --run 78cd767d-5c2e-4c16-b3ee-e3ec354f2a09 --compare a3a35254-3c4b-4ae1-88a9-9de62eb312fb --db reports/meher_threads/samples-local/runs.db --client "Meher Threads" --out comparison.html
```

The archived weak target passed 15/76 tests (19.7%); hardened passed 76/76
(100.0%). The comparison lists 61 fixed tests, zero newly failing tests and a
score change of +80.3 percentage points. The weak run was recorded after the
hardened run in the original evaluation loop, so the report identifies this as
a scenario comparison rather than a chronological improvement claim. Neither
sample has LLM verdicts or human labels; neither claims measured judge quality.

## Scoring, comparisons and provenance

Scores use saved hybrid verdicts, with the existing rule fallback. A pass earns
credit; fail, uncertain and pending receive none. The denominator is all saved
tests, making incomplete work visible. This is a **test pass score**, not a
probability that a chatbot is safe. The report shows rules, LLM, hybrid and human
labels separately. Human labels do not rewrite the score. Generating a report
never reruns judges or alters their verdicts.

Category and language rows show passed/total, failed, uncertain and pending
counts. Only definite failures enter the top-five issue ranking. Issue groups
are category/check-type pairs, ranked first by highest test severity, then by
the number of distinct affected tests. Ties use category/check names for stable
ordering. Each group includes the highest-severity example, exact prompt,
redacted response excerpt, saved check reason, why it matters and a catalog fix.
One test may occur in multiple check groups; these frequencies must not be summed
to infer total failing tests. Connector errors have their own guidance.

Comparisons match stable test keys **and unchanged definitions**: prompt, checks,
expected behavior, category, language, severity and tags. Fail-to-pass is fixed;
pass-to-fail is newly failing. Transitions involving uncertainty or pending work
are listed separately. Added, removed and modified tests are listed and excluded
from matched-test changes. Both whole-run and matched-test score differences are
shown. Warnings identify target, judge-provenance or timestamp differences. No
matched tests means the matched score change is unavailable, not zero.

Legacy runs store a suite path and test definitions but no declared suite version.
The default cover uses the saved filename and a SHA-256 identifier of the saved
test-definition snapshot. It never reads the current suite file to invent a
historical version. If you have a verified client-facing name/version, supply it:

```powershell
python -m chatcheck report --run <id> --out named-suite.html --suite-name "Store support acceptance suite" --suite-version "v2"
```

The cover identifies supplied name/version metadata as report inputs, and retains
the test-definition fingerprint in scope. Report generation time and saved run
time are shown separately. The executive summary uses fixed data templates and
does not make an LLM call.

## Scope and human agreement

Scope states the test count, categories/languages represented and missing,
run status, judge provenance, completed LLM/fake evaluations, human-review flags,
and whether human labels exist. With labels it shows accuracy, precision, recall,
F1, Cohen's kappa and covered/definite counts for rule-only, LLM-only and hybrid.
Human `unsure` and unjudged/uncertain predictions are excluded from definite-pair
metrics. Undefined scores are displayed as unavailable. Common-subset size and
selection-bias notes prevent direct comparisons of different covered subsets.
No labels means measured human agreement is explicitly unavailable.

Default exclusions include production traffic, behavior after the saved run,
multi-turn conversations, tool side effects, real-account authorization, load
testing, exhaustive attacks and independent compliance certification. Add
client-specific exclusions with repeated `--not-tested` arguments:

```powershell
python -m chatcheck report --run <id> --out scoped.html --not-tested "Live payment processing." --not-tested "Customer identity verification."
```

Every report includes: **These results do not prove a chatbot is completely safe.**

## Escaping, redaction and evidence handling

All run data, including responses, prompts, expected behavior, names, identifiers,
judge reasons and comparison lists, passes through redaction and Jinja HTML
autoescaping. Chatbot HTML appears as literal text; it is never a template,
script, link, image or stylesheet. Only trusted local templates generate markup
and numeric SVG bars. A restrictive content security policy provides an additional
browser boundary. No external fonts, images, styles or scripts are loaded.

Built-in redaction covers synthetic canary identifiers, private-order identifiers,
the synthetic other-customer email, common API/token prefixes, credential-like
assignments and private-key blocks. Additional secret-like regexes are additive:

```powershell
$env:CHATCHECK_REPORT_REDACT_PATTERNS = '["CLIENT-TOKEN-[A-Za-z0-9]+", "account_id=[0-9]+"]'
python -m chatcheck report --run <id> --out redacted.html --redact-pattern 'INTERNAL-[A-Z0-9]+'
```

Invalid JSON or regex configuration stops generation before writing the report.
Patterns use Python regex syntax against plain stored text. The complete response
is redacted **before** truncation, then escaped in the template, so truncation
cannot expose the start of an otherwise matching secret or split an HTML entity.
The default response limit is 2,000 characters; set `--response-limit` from 1 to
20,000. Redaction affects the report only; saved originals remain in SQLite.
Pattern matching does not guarantee discovery of arbitrary or encoded secrets.

The catalog is reviewed static guidance for reporting, not a claim of human
approval or a client-specific audit. Its `review_note` records this distinction.
Update catalog entries under category and check type, retaining category/global
`*` fallbacks. The generator validates the catalog before rendering.

## Urdu, Roman Urdu and PDF

HTML is written as UTF-8. Urdu evidence uses `dir="rtl"`, `lang="ur"` and a font
stack starting with Noto Nastaliq Urdu, then Noto Naskh Arabic, Urdu Typesetting,
Nirmala UI and other fallbacks. Roman Urdu stays left-to-right with `lang="ur-Latn"`.
Install Noto Nastaliq Urdu locally for the intended typography; no font download
occurs while opening or exporting a report. Available system fonts determine the
final glyph appearance.

PDF export uses Chromium from the core Playwright dependency. This repository's
matching `.tools/playwright` browser installation is reused automatically unless
`PLAYWRIGHT_BROWSERS_PATH` explicitly selects another location. On a new machine:

```powershell
python -m playwright install chromium
python -m chatcheck report --run <id> --out report-with-pdf.html --pdf
```

This writes HTML and a sibling `report-with-pdf.pdf`: A4, print backgrounds,
defined margins and page numbers. Chromium runs with JavaScript disabled, an
offline context, blocked service workers and every resource route aborted. It
renders the same escaped/redacted report without network access.

If Chromium fails, the optional WeasyPrint backend is tried. Install that fallback
with `python -m pip install -r requirements-chatcheck-pdf.txt` or the package's
`[pdf]` extra. On Windows, WeasyPrint also needs native libraries including Pango;
follow its
[official installation instructions](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html).
The fallback receives only the same escaped, redacted HTML and denies URL-based
network, local-file and data resources. Fonts are resolved from installed system
fonts. See the [WeasyPrint API](https://doc.courtbouillon.org/weasyprint/stable/api_reference.html)
and [Jinja autoescaping documentation](https://jinja.palletsprojects.com/en/stable/api/)
for the underlying APIs. If neither renderer works, HTML is retained and a clear
message gives both installation options; successful HTML generation still exits 0.

## Verification checklist

```powershell
python -m pytest tests/chatcheck/test_report.py -q -p no:cacheprovider
python -m pytest -q -p no:cacheprovider
```

- Cover, five-sentence deterministic summary, scores, SVG bars, top issues,
  disagreements, complete appendix and scope render from saved data.
- Hostile HTML/JavaScript, template syntax and malicious metadata remain text;
  synthetic and configured secrets are redacted throughout the report.
- Urdu text survives UTF-8 output and has RTL direction; Roman Urdu remains LTR.
- Comparisons distinguish fixes, regressions, uncertainty and changed definitions.
- Labels/metrics appear only when stored; reports never call a judge or label items.
- Missing PDF backends leave HTML available with a clear message. A real-browser
  test verifies a multipage PDF and footer numbers; mocked tests also verify safe
  HTML input, offline context settings and denied resource loading.
- Weak/hardened samples retain all 76 appendix rows and their original outcomes.
