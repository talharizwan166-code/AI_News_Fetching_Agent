# V2 delivery-boundary check-set

V2 was written **AFTER seeing the frozen Phase 5 and Phase 5B results**. It is a
retrospective regression check-set, **not an independent benchmark**. Its expected
outcome was known before running it: the old target should fail the three known
findings and the fixed target should pass. A perfect v2 score does not estimate
resistance to unseen attacks or live Gemini prompt injection.

The frozen `suite.json`, scenario builder, fixtures, worker, trace checks and
original sandbox tests remain unchanged. All 30 IDs, serialized scenario prompts,
categories, languages, severities and tags are identical in `suite_v2.json`.
No scenarios were dropped, added or reweighted. Expected behavior and checks change
only in this separate v2 file.

Why the old expectations do not measure the requested delivery boundary:

- `no_marker_in_payloads` includes `draft_generated`, captured by the fake LLM
  before production validation. It usefully measures contaminated raw model output,
  but cannot credit the validator for preventing its delivery. V2 checks all issue,
  email and publish payloads, including encoded issue post data and decoded MIME
  text/HTML. Raw draft evidence remains in SQLite and the full report.
- The unsafe-output cases require issue creation in the frozen suite. V2 requires
  zero attempted deliveries and an actual categorical validation rejection log.
  It does not manufacture rejection evidence from an expected result or merely
  accept a response saying the draft was rejected.
- The frozen cost check is **at most one** LLM call (not exactly one). V2 allows
  at most two, matching Phase 5B's shared per-article budget. Explicit stricter
  scenario caps remain. Every scenario selects at most one article; the repeated
  scenario checks deduplication across two pipeline invocations.

Approval ordering, issue-to-publication ordering, recipient allowlists, endpoint
allowlists, step/token limits and all unrelated frozen expectations are retained.
Benign scenarios require a successful delivery so rejecting everything cannot pass.
Existing malformed-feed, egress and budget-stop cases still require no deliveries.
The issue-failure scenario requires the successful email fallback.

`delivery_policy` uses explicit, exact forbidden strings and destination allowlists.
It permits the article URL, its LinkedIn sharing URL, synthetic sender/recipient
addresses and the exact local approval-issue URL. Loopback addresses are not
blanket-allowlisted. Failed delivery attempts are inspected too. These lexical
checks are not an exhaustive semantic or encoding detector.

The new wrapper captures only recognized safe rejection categories from the
target logger; it leaves the frozen worker and fakes untouched. Both target
revisions use this same wrapper. The pre-fix target does not emit these logs.
This instrumentation adds trace events and therefore consumes step slots, without
changing existing step limits.

The comparison exports `src/` and the approval workflow from commits `0bfb2f1`
(pre-fix) and `e7726b0` (fixed), then overlays the same current sandbox/chatcheck
harness. Only generator/config differ in those target sources. This is a local
source-export retest, not replaying stored verdicts or changing the main checkout.
Provenance records both full commit IDs, source/harness hashes and the v2 suite hash.

The same 30 scenarios contain no new adversarial model outputs for external URLs
or emails. Negative checker unit tests cover those payloads; the retest alone does
not establish target protection against those additional attacks. The Urdu case
contains Urdu article input with the existing deterministic fake draft, not a live
Urdu generation assessment. All external services and the LLM are local fakes.
