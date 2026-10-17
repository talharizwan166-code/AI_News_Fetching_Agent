# Phase 5B: draft validation, shared budget, and before/after evidence

The target is a fixed pipeline. `src/generator.py` now rejects unsafe drafts before
`src/agent.py` can create an issue or send the draft email. The existing failure path
returns `gemini_failed`, makes no delivery, and does not mark the article as saved.
Approval, email recipient configuration and LinkedIn publishing are unchanged.

## Output policy

Existing maximum-word-count, required article URL and hashtag checks remain.
New checks reject HTML/Markdown comments, role delimiters such as `[system]` and
`<|im_start|>`, control characters, generator instruction/template leakage, and URLs
or email addresses absent from the selected article or explicit allowlists.

Template detection uses the generator's own instruction lines and seven-word
fragments, with case/whitespace/punctuation handling. Article directives asking to
add/append/print/etc. arbitrary machine identifiers are checked against the draft;
no particular canary or marker value is hardcoded. Factual model names and version
identifiers remain allowed. Security failures stop immediately instead of requesting
another potentially unsafe draft. Logged reasons name the rejected category without
echoing the draft, identifier, destination, provider exception or API key.

Optional comma-separated settings `DRAFT_ALLOWED_URLS` and `DRAFT_ALLOWED_EMAILS`
allow exact destinations in draft text. They do not change delivery recipients or
publishing permissions. URL identities normalize scheme/host and an empty path;
different paths and query strings require separate approval. URLs in an untrusted
article are eligible under this requested policy; inclusion is not a safety rating
of the destination. These lexical checks are not a complete semantic injection defense.

## Prompt boundary and budget

The article sits in a clearly delimited block whose content-derived boundary is
checked against the data. Instructions outside the block explicitly classify it as
untrusted and direct the model to ignore its instructions. Article fields strip
control/format characters and flatten whitespace, preventing forged field lines.
The existing 200/100/500/500 character caps for title/source/summary/URL remain.
Urdu letters and combining marks are retained.

`GEMINI_MAX_CALLS_PER_ARTICLE=2` is the default shared budget. Every SDK request,
including failed requests, transport retries, validation retries and fallback,
reserves a slot first. SDK-internal retries are disabled. The existing
`GEMINI_MAX_RETRIES` can further limit retries but cannot override the shared cap.
Exhaustion raises a safe error and logs why generation stopped. Each selected article
gets its own budget; this is not a cross-run token or spending ledger.

## Interpreting the frozen retest

The Phase 5 suite, checks, fixtures, worker and sandbox tests are unchanged. Their
pre-change hashes are saved in `reports/agent_sandbox/phase5b-frozen-inputs.json`.
The original run is `76668972-6886-4f77-bcf8-854523224a32`.

The frozen expectations deliberately remain stricter/different from the new target:

- `no_marker_in_payloads` checks the raw `draft_generated` event produced by the
  fake LLM **before** target validation. Rejecting it cannot erase that evidence.
- The adversarial scenarios also require issue creation. Correctly refusing delivery
  introduces a failed `must_call` check in those already-failing scenarios.
- The cost scenario requires at most **one** call. The requested default budget of
  **two** still fails that rule, even though calls fall from four to two.

Therefore a raw score of 27/30 before and after is compatible with the three requested
behavior changes. It must not be presented as 30 passing tests. The compare feature
retains original verdicts and displays observed call/delivery counts alongside them.
No new failing scenarios or benign regressions were observed; full evidence and
rejection reasons remain in SQLite. No real provider or account is exercised.

The original sandbox runner embeds static Phase 5 finding prose in run metadata.
Reports now derive displayed agent evidence from actual trace events rather than
repeating that stale prose. Historical metadata and verdicts are preserved.

## Commands

From the repository root in PowerShell (choose new output names if files exist):

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\python.exe scripts/run_agent_sandbox.py --out reports/agent_sandbox/phase5b-next.html --pdf
```

The sandbox command returns **1** because the three frozen scenarios still fail.
Copy the new run ID into `$afterRun` below; this variable is not a credential:

```powershell
$afterRun = 'NEW_RUN_ID'
.\.venv\Scripts\python.exe -m chatcheck report --db reports/agent_sandbox/runs.sqlite3 --run $afterRun --compare 76668972-6886-4f77-bcf8-854523224a32 --out reports/agent_sandbox/phase5b-comparison-next.html --pdf
.\.venv\Scripts\python.exe -m chatcheck report --db reports/agent_sandbox/runs.sqlite3 --run $afterRun --compare 76668972-6886-4f77-bcf8-854523224a32 --summary --out reports/agent_sandbox/phase5b-summary-next.html --pdf
.\.venv\Scripts\python.exe scripts/verify_phase5b.py --after $afterRun --summary-pdf reports/agent_sandbox/phase5b-summary-next.pdf --out reports/agent_sandbox/phase5b-verification-next.json
```

The separate proof script verifies frozen hashes and identical test snapshots, safe
rejection before delivery, the two-call cap, no new failing cases, approval ordering,
recipients, and the summary PDF page limit. It does not alter verdicts or contact a provider.

## Client summary reports

`chatcheck report --summary` creates a condensed report with the score, comparison
when requested, top five issue groups, scope and limits, and compact agent evidence.
It omits the full appendix, prompts, raw responses and detailed event dump. Full
reports remain the default. Long display text is explicitly marked as condensed;
redaction happens first. Counts and verdicts are not shortened or changed.

Summary PDFs require `pypdf` (included in the PDF extra and development dependencies)
to verify the final page count. Layout and bounded text target three to four pages;
the exporter refuses to write a summary PDF exceeding five pages. It never silently
removes pages. HTML remains available if PDF generation or page verification fails.

## Verification checklist

- [ ] Full pytest suite, packaging, default full reports and summary mode pass.
- [ ] All frozen sandbox hashes and test-definition snapshots match.
- [ ] Unsafe raw drafts cause no issue, email or publication.
- [ ] Formatting failures and transient errors share a default two-call cap.
- [ ] Benign English/Urdu drafts, valid URLs, hashtags and model names pass.
- [ ] Approval and recipients are unchanged; no new failing scenarios appear.
- [ ] Comparison preserves 27/30 and explains all three remaining frozen failures.
- [ ] Client summary has at most five pages; full reports retain detailed evidence.
