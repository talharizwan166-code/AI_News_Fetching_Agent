"""Agreement against explicit human labels. Failure is the positive class."""

from collections import Counter, defaultdict


def metrics(actual, predicted):
    if len(actual) != len(predicted):
        raise ValueError("Label vectors must have the same length")
    if any(value not in {"pass", "fail"} for value in actual):
        raise ValueError("Metrics require definite human labels")
    if any(value not in {"pass", "fail", "uncertain", "not_judged"} for value in predicted):
        raise ValueError("Unknown prediction")
    matrix = {truth: {pred: 0 for pred in ("pass", "fail", "uncertain", "not_judged")} for truth in ("pass", "fail")}
    for truth, pred in zip(actual, predicted):
        matrix[truth][pred] += 1
    covered = [(a, p) for a, p in zip(actual, predicted) if p in {"pass", "fail"}]
    n = len(covered)
    correct = sum(a == p for a, p in covered)
    tp, fp, fn = matrix["fail"]["fail"], matrix["pass"]["fail"], matrix["fail"]["pass"]
    observed = correct / n if n else None
    kappa = None
    if n:
        human, judge = Counter(a for a, _ in covered), Counter(p for _, p in covered)
        expected = sum(human[key] * judge[key] for key in ("pass", "fail")) / (n * n)
        if expected < 1:
            kappa = (observed - expected) / (1 - expected)
    return {"n": len(actual), "judged": n, "abstained": len(actual) - n,
            "coverage": n / len(actual) if actual else None,
            "accuracy": observed,
            "accuracy_with_abstentions_wrong": correct / len(actual) if actual else None,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            "kappa": kappa, "confusion_matrix": matrix}


def predictions(test):
    rule, llm = test.get("verdict"), test.get("llm_verdict")
    return {"rule_only": ("pass" if rule["passed"] else "fail") if rule else "not_judged",
            "llm_only": llm["verdict"] if llm and llm["status"] == "judged" else "not_judged",
            "hybrid": test["combined_verdict"]["verdict"]}


def score(tests):
    return {name: metrics([test["human_label"]["label"] for test in tests], [predictions(test)[name] for test in tests])
            for name in ("rule_only", "llm_only", "hybrid")}


def agreement_report(tests):
    definite = [test for test in tests if test.get("human_label") and test["human_label"]["label"] in {"pass", "fail"}]
    common = [test for test in definite if all(value in {"pass", "fail"} for value in predictions(test).values())]
    report = {"total": len(tests), "labeled": sum(bool(test.get("human_label")) for test in tests),
              "human_unsure": sum((test.get("human_label") or {}).get("label") == "unsure" for test in tests),
              "definite_labels": len(definite), "positive_class": "fail", "overall": score(definite),
              "common_subset": score(common), "per_category": {}, "per_language": {}, "disagreements": [],
              "notes": "Accuracy, precision, recall, F1 and kappa use definite predictions and definite human labels. See coverage and common_subset for fair comparisons. Undefined metrics are null. This stratified review sample does not estimate population accuracy."}
    provenance = Counter((t["llm_verdict"].get("provider", "unspecified"), t["llm_verdict"].get("model", "unspecified"),
                          t["llm_verdict"].get("rubric_version", "unspecified")) for t in tests if t.get("llm_verdict"))
    report["judge_provenance"] = [{"provider": key[0], "model": key[1], "rubric_version": key[2], "items": count}
                                  for key, count in sorted(provenance.items())]
    for field in ("category", "language"):
        groups = defaultdict(list)
        for test in definite:
            groups[test.get(field) or "unspecified"].append(test)
        report[f"per_{field}"] = {key: score(group) for key, group in sorted(groups.items())}
    for test in definite:
        human = test["human_label"]["label"]
        pred = predictions(test)
        mismatch = [name for name, value in pred.items() if value != human]
        if mismatch:
            report["disagreements"].append({"test_id": test["id"], "run_id": test["run_id"], "test_key": test["test_key"],
                                             "category": test.get("category"), "language": test.get("language"),
                                             "human": human, **pred, "judges_differing_from_human": mismatch})
    return report
