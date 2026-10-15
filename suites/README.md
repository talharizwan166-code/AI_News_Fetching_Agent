# First chatbot test library

[`clothing_store.json`](clothing_store.json) contains **76 tests**: the original
64 unchanged (eight each for
groundedness, prompt injection, data leakage, scope, policy accuracy, language,
tone and robustness), plus 12 probes added for measured mutation gaps: six data
leakage, three scope and three robustness probes. Each gap has English, Urdu and
Roman Urdu coverage. This is one JSON suite so the complete library can be loaded
by the existing runner without a directory or manifest format.

[`clothing_store_heldout.json`](clothing_store_heldout.json) contains 20 separately
authored paraphrases (8 English, 6 Urdu, 6 Roman Urdu). These were frozen before
execution; neither bot nor rules were tuned after viewing their results. See the
[mutation audit](../reports/meher_threads/mutation/README.md) for the limitations
revealed by the held-out split. Keep that evidence intact; use a fresh unseen
split to evaluate future improvements.

## Ground truth and target setup

1. Configure a test chatbot for the fictional **Meher Threads** online clothing
   store using [`faq.md`](../examples/chatcheck/kb/faq.md) as its public knowledge
   base. The FAQ fixes the return window at 14 calendar days, Pakistan delivery
   at 3–5 business days, and disallows cash on delivery outside Pakistan.
2. Seed the **synthetic** values in
   [`private-fixture.md`](../examples/chatcheck/private-fixture.md) into the test
   target's private configuration or system context. Keep them out of the public
   FAQ/retrieval index. No real credentials or customer data are needed.
3. Configure the target's API or widget in a normal Chatcheck target JSON file.
   The target should answer each prompt as an independent conversation. Chatcheck
   does not automatically upload either fixture or provision a target chatbot.
4. Validate locally, then run against that configured target:

   ```powershell
   .\.venv\Scripts\python.exe -m chatcheck validate --suite suites/clothing_store.json
   .\.venv\Scripts\python.exe -m chatcheck run --target target.store.json --suite suites/clothing_store.json --db store-results.db
   ```

`target.store.json` is your target configuration, not a supplied working endpoint.
For a ready-to-run offline target, use the [Meher Threads demo](../demo_bots/meher_threads/README.md)
and the supplied `target.meher.weak.json` / `target.meher.hardened.json` configs.
It seeds both fixtures itself. The one-command comparison is:

```powershell
.\.venv\Scripts\python.exe -m demo_bots.meher_threads.compare
```

The Phase 1B mock server supports its original example suite; it does **not** know
this FAQ. Running this library against that mock exercises execution and storage
but is expected to produce failures.

## Coverage

| Category | Tests | Main probes |
| --- | ---: | --- |
| `groundedness` | 8 | Unknown stock, coupons, addresses, certification, tracking, fabric, warranty and exact delivery promises |
| `prompt_injection` | 8 | Claimed roles, quoted documents, HTML comments, encoded benign markers and Roman Urdu overrides |
| `data_leakage` | 8 | Private instructions, canaries, synthetic customer records and administrator/support impersonation |
| `scope` | 8 | Harmless off-topic weather, sports, recipes, homework, poems, games, code and travel |
| `policy_accuracy` | 8 | Return-window boundaries, processing time, delivery, international COD, shipping fees and eligibility |
| `language` | 8 | The same return question in English, Urdu and Roman Urdu, each with a misspelled variant; two delivery questions |
| `tone` | 8 | Empathy, respectful refusals, simple language, concise support and avoiding false promises |
| `robustness` | 8 | Punctuation, repetition, ambiguity, emoji, structured JSON, conflicting claims and multiple questions |

Language totals: **56 `en`, 3 `ur`, 5 `roman_ur`**. Severity totals: **12 critical,
26 high, 23 medium, 3 low**. `language` describes the intended answer language,
not automatic language detection. `severity` is triage metadata; every failed
test affects the run's pass/fail status equally.

Each case has a plain-language `expected_behavior` and only supported judge
checks. Attack prompts use fictional policy changes and harmless markers, never
instructions for dangerous activities. The leakage probes need the private
fixture seeded in the target; without that setup, avoiding the fixture strings
does not establish that the chatbot protects private data.

## What the checks prove

The executable `checks` are text/regex/length/JSON rules. `expected_behavior` is
documentation, not an additional semantic judge. The rules require useful answer
signals as well as forbidden-output checks; an empty response cannot pass any
library case. They still cannot prove every factual or linguistic nuance: a
paraphrase may fail, a contradictory answer may match expected keywords, and a
language regex does not guarantee fluency. Review the response text alongside
the expected behavior when interpreting results.

The authored passing and failing responses in
[`tests/chatcheck/fixtures/clothing_store_responses.json`](../tests/chatcheck/fixtures/clothing_store_responses.json)
exercise every case's rule configuration in pytest. They are judge fixtures,
not results from a live model and not a replacement chatbot implementation.

Regenerate this suite and its authored response fixtures with
`python scripts/build_chatcheck_library.py`. The source now lives in `scripts/`,
not `.tools/`. Use `--output-root <directory>` to regenerate into another directory
for review. The generator never changes the FAQ or the demo implementation.
