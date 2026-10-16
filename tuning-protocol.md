# Chatcheck tuning protocol

The MAIN suite is the development set. The HELD-OUT suite is an evaluation set:
its observed failures, wording and human labels must not guide changes to checks,
the bot prompt, FAQ, refusal wording, phrase alternatives or category thresholds.
The current held-out set has already been inspected in earlier phases. Freezing
it now protects future provenance; it does not make that set independently blind.
Use a newly authored, independently reviewed split for a new blind evaluation.

## Register and verify the suites

```powershell
.\.venv\Scripts\Activate.ps1
python -m chatcheck freeze --suite suites/clothing_store_heldout.json
python -m chatcheck freeze --suite suites/clothing_store.json --role main
python -m chatcheck validate --suite suites/clothing_store_heldout.json
```

Each command writes or verifies `<suite>.freeze.json` beside the suite. It stores
SHA-256 of canonical JSON for the complete suite and a separate hash/snapshot of
the checks by test ID, plus dated history and a check changelog. JSON whitespace
or key ordering changes do not change the canonical hash. Prompts, expectations,
membership and other definition changes are protected as well as checks.

`load_suite` verifies registered suites before execution. Validation, ordinary
runs, the real demo, retry preflight and other library loaders all refuse a
changed frozen definition. Copy the sidecar with its suite when moving it; both
are package data in built wheels. Direct filesystem edits are possible, but the
edited suite will not load. This is an audit/control in the library, not an OS
permission boundary or protection against someone deleting/replacing the audit
or changing the program. Commit and review suite and audit files together.

## Revise a main check only after human review

1. Run the original MAIN suite and keep its saved response/check snapshot.
2. Label responses blindly using `chatcheck label`. A proposed false failure
   needs your explicit `pass` label on a delivered response whose rule failed.
   Heuristic candidate flags and LLM verdicts are not human approval.
3. Write a proposed checks array to a new JSON file. Accept only verified
   equivalent wording; preserve policy conditions, negative examples, and all
   original `not_contains` leakage guards. Do not turn broad keywords into a
   substitute for factual correctness.
4. Apply the reviewed revision through the command below. It checks the human
   label in SQLite and requires the exact original test ID, prompt and checks
   from a MAIN run. Held-out review rows cannot authorize MAIN revisions.
5. Inspect the recorded old/new checks, reason, date, human-label timestamp,
   source response and run ID. Run the existing pass/fail fixtures, mutants and
   the full regression suite. Review additional positive/negative paraphrase
   examples before accepting a broadened check.
6. Make a new MAIN experiment/version to measure the effect. Saved runs keep
   their original checks; never rewrite old verdicts under a revised rubric or
   present that comparison as a model improvement.

```powershell
# Label first; do not substitute an automated judgment for your pass label.
python -m chatcheck label --run <main-run-id> --db reports/real_llm/runs.db
# revised-checks.json must contain a JSON checks ARRAY, for example:
# [{"type":"any_of_phrases","value":["14 days","fourteen days"]}]
python -m chatcheck revise --suite suites/clothing_store.json --test-id <test-id> --checks revised-checks.json --reason 'Human confirmed equivalent policy wording' --review-db reports/real_llm/runs.db --review-run <main-run-id>
```

Every applied revision creates a changelog entry in the suite's sidecar with
`test_id`, `old_check`, `new_check`, `reason` and UTC `date`, plus the review
reference. The command immediately records the new suite/check hashes. An
interruption between writing the suite and the sidecar leaves verification
failing closed. External check edits to registered MAIN files are refused;
`--unfreeze` cannot bypass human review of MAIN check changes. No checks were
revised automatically as part of Phase 2E.

## Held-out exceptions are explicit and remain visible

`chatcheck revise` refuses HELD-OUT suites, even if a human label exists. Do not
use an exception to fit observed held-out answers. For a documented data error
or governance correction, keep the previous version in version control, prepare
the proposed edit, and explicitly record why this benchmark exception is needed:

```powershell
python -m chatcheck freeze --suite suites/clothing_store_heldout.json --unfreeze 'Documented benchmark correction: describe the specific error and provenance impact'
```

The command records the reason, old/new hashes, date and each changed test's
old/new checks, then **immediately freezes the current version**. It does not
leave an unlocked interval. The role cannot be silently changed to MAIN. Reports
using the changed benchmark must disclose the exception and its loss of blind
evaluation status. The existing mutation-freeze audit is retained separately;
these sidecars do not rewrite historical experiment evidence.

## Optional phrase matching

```json
{"type":"any_of_phrases","value":["کیا واپس","واپس نہیں","return policy"]}
```

This positive check passes if any supplied phrase is a substring after Unicode
NFC normalization, Arabic/Persian yeh and kaf normalization, removal of combining
diacritics and zero-width/format characters, whitespace normalization and Latin
case folding. Bari yeh remains distinct. Do not specify `case_sensitive` for this
type: normalization is always applied. Empty or normalization-empty alternatives
are rejected. Existing `contains`, `equals`, regex and exact negative checks keep
their prior behavior. This is encoding/phrase tolerance, not semantic inference:
negation, incorrect numbers or missing conditions can still match a broad phrase.

Use it only where human-reviewed MAIN evidence supports the alternatives.
Never normalize away or broaden exact synthetic-canary/secret checks.

## Error-only retry is not tuning

The [retry procedure](docs/chatcheck-retries.md) may obtain the first model
response for a connection/provider failure. It preserves the original attempt,
uses a new explicit persistent cap and refuses any test that has ever received
a response, including a real answer that failed its checks. That prevents
sampling repeatedly until an answer passes. No check changes accompany retry.
Human labels/LLM verdicts from an old no-response attempt remain archived with
that attempt and do not apply automatically to a new response.
