from collections import Counter
from pathlib import Path

import pytest

from chatcheck.judge import judge
from chatcheck.models import CATEGORIES, load_suite, read_json


ROOT = Path(__file__).resolve().parents[2]
CASES = load_suite(ROOT / "suites/clothing_store.json")
SAMPLES = read_json(Path(__file__).parent / "fixtures/clothing_store_responses.json")


def test_library_is_balanced_and_has_ground_truth_metadata():
    assert len(CASES) == 64
    assert Counter(case.category for case in CASES) == {category: 8 for category in CATEGORIES}
    assert {case.id for case in CASES} == set(SAMPLES)
    assert all(case.language and case.severity and case.expected_behavior and case.tags for case in CASES)
    assert all("private-fixture" in case.tags for case in CASES if case.category == "data_leakage")
    assert (ROOT / "examples/chatcheck/kb/faq.md").is_file()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_library_checks_accept_known_good_and_reject_known_bad_responses(case):
    # These are authored response fixtures, not claims about a real model's behavior.
    samples = SAMPLES[case.id]
    good = judge(samples["passing_response"], case.checks)
    assert good.passed, good.reason
    bad = judge(samples["failing_response"], case.checks)
    assert not bad.passed
    assert not judge("", case.checks).passed
