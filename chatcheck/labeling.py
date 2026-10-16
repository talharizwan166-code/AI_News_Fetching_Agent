"""Blinded human labeling and reproducible sampling of saved responses."""

import json
import random
from collections import defaultdict


def build_sample(storage, run_ids=None, *, size=100, seed=42, real_run_ids=None, min_real=0):
    if type(size) is not int or size < 1:
        raise ValueError("Sample size must be positive")
    runs = [storage.results(run_id) for run_id in (run_ids or [run["id"] for run in storage.list_runs()])]
    real_run_ids = set(real_run_ids or [])
    if type(min_real) is not int or not 0 <= min_real <= size:
        raise ValueError("Real-run quota must be between zero and sample size")
    if not real_run_ids <= {run["id"] for run in runs}:
        raise ValueError("Real runs must belong to the selected source runs")
    real_ids = set()
    pool, required, strata = {}, {}, defaultdict(list)
    for run in runs:
        heldout = "heldout" in run["suite_path"].lower() or "held-out" in run["suite_path"].lower()
        for test in run["tests"]:
            if test["verdict"] is None:
                continue
            test_id = test["id"]
            pool[test_id] = test
            if run["id"] in real_run_ids and test["responses"] and test["responses"][-1].get("text") and not test["responses"][-1].get("error"):
                real_ids.add(test_id)
            reasons = []
            if heldout and (not test["verdict"]["passed"] or test["combined_verdict"]["verdict"] == "fail" or (test["llm_verdict"] or {}).get("verdict") == "fail"):
                reasons.append("heldout_failure")
            if test["combined_verdict"]["disagreement"]:
                reasons.append("judge_disagreement")
            if reasons:
                required[test_id] = reasons
            # Cover each target as well as category and language.
            strata[(test.get("category"), test.get("language"), run["target_name"])].append(test_id)
    rng = random.Random(seed)
    selected = dict.fromkeys(sorted(required))
    if len(real_ids) < min_real:
        raise ValueError(f"Real-run quota requires {min_real} usable responses; only {len(real_ids)} available")
    # Fill the real quota first. Prefer the least represented language, then
    # category/language cell and category. Seeded ties keep selection reproducible.
    candidates = sorted(real_ids - set(selected))
    rng.shuffle(candidates)
    while len(real_ids & set(selected)) < min_real:
        chosen = [pool[key] for key in real_ids & set(selected)]
        def balance(key):
            test = pool[key]
            return (sum(t["language"] == test["language"] for t in chosen),
                    sum((t["category"], t["language"]) == (test["category"], test["language"]) for t in chosen),
                    sum(t["category"] == test["category"] for t in chosen))
        key = min(candidates, key=balance)
        selected[key] = None
        candidates.remove(key)
    groups = list(strata.values())
    for group in groups:
        rng.shuffle(group)
    rng.shuffle(groups)
    # Cover category/language cells before filling finer target strata, when
    # the requested size has room. Mandatory items count toward this coverage.
    cells = defaultdict(list)
    for test_id, test in pool.items():
        cells[(test.get("category"), test.get("language"))].append(test_id)
    covered = {(pool[test_id].get("category"), pool[test_id].get("language")) for test_id in selected}
    cell_keys = list(cells)
    rng.shuffle(cell_keys)
    for cell in cell_keys:
        if cell not in covered and len(selected) < size:
            selected[rng.choice(cells[cell])] = None
    while len(selected) < min(size, len(pool)):
        progressed = False
        for group in groups:
            while group and group[-1] in selected:
                group.pop()
            if group and len(selected) < size:
                selected[group.pop()] = None
                progressed = True
        if not progressed:
            break
    test_ids = list(selected)
    rng.shuffle(test_ids)  # Hide selection order from the labeler.
    metadata = {"seed": seed, "requested_size": size, "size": len(test_ids), "pool_size": len(pool),
                "runs": [run["id"] for run in runs], "mandatory": {str(k): v for k, v in required.items()},
                "strategy": "all heldout failures and judge disagreements; cover category/language cells, then random round-robin target strata"}
    if real_run_ids:
        metadata.update(real_runs=sorted(real_run_ids), min_real=min_real, real_items=len(real_ids & set(selected)))
    return storage.save_sample(test_ids, metadata), metadata


def visible(value):
    """Render terminal controls literally; retain newlines and tabs for readability."""
    return "".join(char if char in "\n\t" or char.isprintable() else f"\\u{ord(char):04x}" for char in str(value))


def label_items(storage, tests, *, read=None, write=print):
    read = read or input
    pending = [test for test in tests if test.get("human_label") is None]
    saved = 0
    for position, test in enumerate(pending, 1):
        # Deliberately construct the view from raw inputs, never verdict objects,
        # judge reasons, target names or sampler inclusion reasons.
        write(f"Item {position}/{len(pending)} | category={test.get('category')} language={test.get('language')}")
        write("Prompt:\n" + visible(test["prompt"]))
        response = test["responses"][-1]["text"] if test["responses"] else None
        write("Response:\n" + visible(response if response is not None else "(no response)"))
        write("Expected behavior:\n" + visible(test.get("expected_behavior") or "(unspecified)"))
        write("Checks:\n" + visible(json.dumps(test["checks"], ensure_ascii=False, indent=2)))
        while True:
            try:
                answer = read("Your label [pass/fail/unsure; s=skip, q=quit]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return saved
            if answer in {"q", "quit"}:
                return saved
            if answer in {"", "s", "skip"}:
                break
            if answer in {"pass", "fail", "unsure"}:
                storage.save_label(test["id"], answer)
                saved += 1
                break
            write("Enter pass, fail, unsure, s or q.")
    return saved
