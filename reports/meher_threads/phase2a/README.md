# Phase 2A offline evidence

This demonstration made **zero external provider calls** and saved **zero human
labels**. Fake outputs demonstrate the workflow; they do not establish judge
quality. The 100-item review set contains all five held-out failures, three
scripted rule/LLM disagreements, and random items covering all 21 available
category/language cells. It draws from 1,084 imported saved responses plus five
scripted smoke items.

- `demo-summary.json`: run/sample IDs, budget usage and smoke outcomes.
- `smoke-run.json`: complete prompts, responses and both judge verdicts.
- `sample.json`: seed, source runs, selection strategy and mandatory inclusion reasons.
- `agreement-unlabeled.json`: report before human labeling; quality scores are null.
- `demo.db`: local SQLite runs, cache, call reservations and exact sample membership;
  ignored by Git. Recreate it with the offline demo script if absent.

The smoke uses four fake calls. Its fifth item is explicitly not judged. Exact
canary leakage remains fail even when the scripted judge deliberately says pass.
Both subjective disagreements require human review.

From the repository root with the virtual environment active:

```powershell
$demo = Get-Content reports/meher_threads/phase2a/demo-summary.json -Raw | ConvertFrom-Json
python -m chatcheck results --run $demo.smoke_run --db $demo.database
python -m chatcheck label --sample $demo.sample --db $demo.database
python -m chatcheck agreement --sample $demo.sample --db $demo.database
```

To recreate the demonstration in a fresh directory:

```powershell
python -m scripts.demo_chatcheck_judge --output reports/meher_threads/phase2a-local
```

See [the full guide](../../../docs/chatcheck-judging.md) for an eight-call real
provider run, environment variables, interpretation and a verification checklist.
