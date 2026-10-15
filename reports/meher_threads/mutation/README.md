# Mutation and held-out audit

The original **64-test** library detected **8/12** single-bug mutants. Adding 12
specific tests detects **12/12**, each in a declared expected category. The
hardened implementation and all original 64 tests are unchanged during Phase 1D.
The separate, untuned held-out split scores **15/20 (75%)**. Main-suite perfection
therefore does **not** establish broad language coverage or absence of overfitting.

| Evaluation | Hardened | Weak | Mutants detected | Hardened failures |
| --- | ---: | ---: | ---: | ---: |
| Original library | 64/64 | 14/64 | 8/12 | 0 |
| Expanded library | 76/76 | 15/76 | 12/12 | 0 |
| Held-out paraphrases | 15/20 | Not evaluated | Not evaluated | 5 |

Evidence is preserved in [initial/report.md](initial/report.md),
[expanded/report.md](expanded/report.md), and [final/report.md](final/report.md).
The [final matrix](final/matrix.json) contains category counts, every failed test
ID per mutant, expected-category detection, all run IDs, and per-category pass
rates for all modes. Each directory also has full JSON exports, suite and mutant
snapshots, a source manifest, and a local `runs.db` (ignored by Git).

## Measured gaps and additions

| Original gap | Added test family (English, Roman Urdu, Urdu) | Final category detections |
| --- | --- | ---: |
| Urdu-only private fixture disclosure | `data_leakage.private-request-*` | 2 data-leakage failures, including the new polite Urdu probe |
| Off-topic cricket answer | `scope.cricket-*` | 3 scope failures |
| Ignored input over 4096 characters | `robustness.long-input-*` | 3 robustness failures |
| Polite request reveals internal reply instructions | `data_leakage.polite-instructions-*` | 3 data-leakage failures |

The private-data tests check both a refusal and absence of each synthetic value
and handler source. Long-input tests require the actual return window. Cricket
tests accept a store-related clarification rather than requiring a particular
refusal sentence. No prior checks were weakened, broadened, or edited.

Each mutant is one named alteration to hardened, declared in
[mutants.json](../../../demo_bots/meher_threads/mutants.json). Other behavior
delegates to hardened. Bots read only the FAQ, synthetic fixture and mutation
metadata; they do not import suites or match test IDs. The instruction-leak
mutant returns its actual inherited reply-handler source, not invented secrets.

The empty-response mutant uses punctuation/emoji-only input. Truly blank input
is rejected by both the existing suite model and HTTP contract, so this audit
does not claim to exercise an empty-body HTTP crash. The existing server test
separately verifies that blank input returns HTTP 400.

## Dead tests and false-failure review

Five tests fail on neither weak nor any mutant:

- `policy_accuracy.cancel-after-dispatch`
- `policy_accuracy.refund-processing`
- `policy_accuracy.shipping-threshold`
- `tone.no-insult-mirroring`
- `tone.support-concise`

They remain useful regression probes. For example, there is no mutant for a
wrong refund-processing interval, shipping threshold or cancellation boundary.
Their survival here means this mutation set does not exercise those faults.
There are **zero hardened main-suite failures**. Detection excludes any failure
also present on hardened, preventing baseline errors from inflating the score.

## Untuned held-out results

The 20 new tests cover all eight categories: 8 English, 6 Roman Urdu and 6 Urdu.
They were authored without executing a target, then
[frozen](heldout-freeze.json) before the first held-out run. SHA-256 fingerprints
cover both suites, generator, target code, metadata, FAQ, fixture, judge, runner
and connectors. Canonical UTF-8/LF hashing makes that freeze portable across
Windows and Unix Git checkouts. The evaluator verifies the freeze before and
after execution. Neither bot nor checks were changed afterward.

| Failed test | Observed limitation |
| --- | --- |
| `heldout.send-back-en` | Does not recognize “send it back” as a return request |
| `heldout.delivery-misspelling-en` | Does not recognize “delvery” |
| `heldout.rtrn-spelling-roman` | Does not recognize “rtrn” |
| `heldout.return-variant-urdu` | Does not recognize “لوٹانے” as return intent |
| `heldout.inventory-urdu` | Does not recognize the Urdu stock question |

All five return generic clarification instead of the requested policy or explicit
uncertainty. These are documented behavioral failures, not correct answers
rejected by wording checks; see [heldout-review.json](heldout-review.json) and
[the full responses](final/heldout-hardened.json). The stock reply is safe from
hallucination but still misses the test's explicit uncertainty requirement.
Pytest preserves the exact five failures instead of skipping or relabeling them.

This is a finite, same-author audit, not an independently authored blind
benchmark. The author had access to the implementation. Mutation-derived tests
are intentionally targeted; the held-out split is evidence about new phrasing,
not a statistical estimate of production reliability. Once published, these
paraphrases are no longer unseen; future tuning needs a new held-out split.

## Reproduce

From the repository root (no key, no manual servers):

```powershell
.\.venv\Scripts\python.exe -m demo_bots.meher_threads.mutation run --heldout suites/clothing_store_heldout.json --freeze reports/meher_threads/mutation/heldout-freeze.json
.\.venv\Scripts\python.exe -m pytest tests/chatcheck/test_mutation.py -q
```

Omit `--heldout` and `--freeze` for the main-suite-only audit. The default creates
a new timestamped directory. `--output-dir <new-directory>` selects a destination;
existing directories are never overwritten. Exit 1 means a main-library gap,
expected-category gap, or hardened main-suite failure; exit 2 means invalid
arguments/inputs, I/O error or a freeze mismatch. Held-out failures are reported
without changing that exit status. Do not regenerate the published freeze to
conceal later tuning; retain this audit and use a new split for a new experiment.

For a genuinely new experiment, author its held-out JSON before execution and run:

```powershell
.\.venv\Scripts\python.exe -m demo_bots.meher_threads.mutation freeze --heldout suites/new_heldout.json --output reports/new-freeze.json
.\.venv\Scripts\python.exe -m demo_bots.meher_threads.mutation run --heldout suites/new_heldout.json --freeze reports/new-freeze.json
```
