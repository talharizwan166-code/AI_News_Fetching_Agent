import pytest

from chatcheck.agreement import agreement_report, metrics


@pytest.mark.parametrize("actual,predicted,kappa", [
    (["pass", "pass", "fail", "fail"], ["pass", "pass", "pass", "fail"], 0.5),
    (["pass", "fail"], ["pass", "fail"], 1.0),
    (["pass", "fail"], ["fail", "pass"], -1.0),
    (["pass", "pass", "fail", "fail"], ["pass", "fail", "pass", "fail"], 0.0),
])
def test_known_cohens_kappa(actual, predicted, kappa):
    assert metrics(actual, predicted)["kappa"] == pytest.approx(kappa)


def test_failure_positive_metrics_and_confusion_matrix():
    result = metrics(["fail", "fail", "pass", "pass"], ["fail", "pass", "pass", "pass"])
    assert result["accuracy"] == 0.75
    assert result["precision"] == 1
    assert result["recall"] == 0.5
    assert result["f1"] == pytest.approx(2 / 3)
    assert result["confusion_matrix"]["fail"]["pass"] == 1


def test_abstentions_and_undefined_metrics_are_explicit():
    result = metrics(["pass", "fail", "fail"], ["pass", "uncertain", "not_judged"])
    assert result["accuracy"] == 1
    assert result["accuracy_with_abstentions_wrong"] == pytest.approx(1 / 3)
    assert result["coverage"] == pytest.approx(1 / 3)
    assert result["abstained"] == 2
    assert result["kappa"] is None
    assert metrics([], [])["accuracy"] is None
    with pytest.raises(ValueError):
        metrics(["pass"], [])
    with pytest.raises(ValueError):
        metrics(["unsure"], ["pass"])


def test_report_excludes_unsure_and_compares_common_subset():
    def test(key, human, rule, llm, category="tone", language="en"):
        return {"id": key, "run_id": "run", "test_key": str(key), "category": category, "language": language,
                "human_label": {"label": human} if human else None,
                "verdict": {"passed": rule}, "llm_verdict": {"status": "judged", "verdict": llm},
                "combined_verdict": {"verdict": "uncertain" if (llm == "pass") != rule else llm}}
    report = agreement_report([test(1, "pass", True, "pass"), test(2, "fail", True, "fail", "language", "ur"),
                               test(3, "unsure", False, "fail"), test(4, None, False, "pass")])
    assert report["labeled"] == 3 and report["human_unsure"] == 1 and report["definite_labels"] == 2
    assert report["overall"]["llm_only"]["accuracy"] == 1
    assert report["overall"]["rule_only"]["accuracy"] == 0.5
    assert report["common_subset"]["rule_only"]["n"] == 1
    assert set(report["per_category"]) == {"tone", "language"}
    assert set(report["per_language"]) == {"en", "ur"}
    assert len(report["disagreements"]) == 1
