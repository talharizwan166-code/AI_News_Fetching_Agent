"""Blinded human labeling and reproducible sampling of saved responses."""

import json
import random
from collections import defaultdict


def build_sample(storage, run_ids=None, *, size=100, seed=42):
    if type(size) is not int or size < 1:
        raise ValueError("Sample size must be positive")
    runs = [storage.results(run_id) for run_id in (run_ids or [run["id"] for run in storage.list_runs()])]
    pool, required, strata = {}, {}, defaultdict(list)
    for run in runs:
        heldout = "heldout" in run["suite_path"].lower() or "held-out" in run["suite_path"].lower()
        for test in run["tests"]:
            if test["verdict"] is None:
                continue
            test_id = test["id"]
            pool[test_id] = test
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
