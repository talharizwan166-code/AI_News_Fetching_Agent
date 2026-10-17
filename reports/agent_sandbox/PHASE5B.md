# Phase 5B verified before/after

Baseline: `76668972-6886-4f77-bcf8-854523224a32`.
After: `ca884b52-fd8e-4485-92e9-f3f40d91f303`.

- [Client summary HTML](phase5b-summary.html) / [PDF, 4 pages](phase5b-summary.pdf)
- [Full comparison HTML](phase5b-comparison.html) / [PDF](phase5b-comparison.pdf)
- [Raw retest HTML](phase5b-retest.html) / [PDF](phase5b-retest.pdf)
- [Machine-readable verification](phase5b-verification.json)
- [Frozen input hashes](phase5b-frozen-inputs.json)
- [Implementation, limits and reproduction commands](../../docs/chatcheck-phase5b.md)

| Behavior | Before | After |
|---|---|---|
| Marker-contaminated fake draft | Accepted; issue and email created | Rejected; no issue, email or publication |
| Prompt-template fake draft | Accepted; issue and email created | Rejected; no issue, email or publication |
| One invalid article draft | 4 model calls | 2 calls, then clean budget exhaustion |
| Frozen scenario score | 27/30 | 27/30 |
| New failing scenarios | — | 0 |
| Previously passing / benign scenarios regressing | — | 0 |

The unchanged score is intentional evidence, not a claim that all scenarios pass.
The frozen checks inspect raw fake output before target validation and require an
issue even in the two adversarial cases. Those now also fail `must_call` because
unsafe content is correctly rejected. The cost check demands one call, stricter
than the requested two-call default. No verdict or test definition was modified.

Final regression verification: **770 passed, 2 optional widget tests skipped**.
The retest contains 188 ordered events and 25 fake LLM calls, with no connector
errors or pending scenarios. Frozen suite/check/fixture hashes match; all 30 test
definitions match the baseline. Approval ordering and recipient checks pass.
Real models and real accounts were not used.

The generator now strips control characters from article data, establishes explicit
untrusted-data boundaries, rejects general unsafe output categories, and shares a
two-call budget across validation retries, transport retries and fallback. No canary
string is special-cased. Approval/publishing/delivery-recipient code is unchanged.
Lexical validation is not proof against all semantic injection attacks.

The older four-call fallback unit test now explicitly opts into a four-call budget;
new tests verify the two-call default. Existing sandbox regression expectations are
unchanged. Summary mode is opt-in; the full report remains the default.
