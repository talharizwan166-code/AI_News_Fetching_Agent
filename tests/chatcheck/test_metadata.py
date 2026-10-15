import json
from dataclasses import asdict

import pytest

from chatcheck.models import CATEGORIES, LANGUAGES, SEVERITIES, TestCase as Case, load_suite


def base_row():
    return {"id": "sample", "prompt": "hello", "checks": [{"type": "contains", "value": "hello"}]}


def write_suite(tmp_path, rows):
    path = tmp_path / "suite.json"
    path.write_text(json.dumps({"tests": rows}, ensure_ascii=False), encoding="utf-8")
    return path


def test_old_suite_defaults_and_independent_tag_lists(tmp_path):
    first, second = load_suite(write_suite(tmp_path, [base_row(), {**base_row(), "id": "second"}]))
    assert first.category is first.language is first.severity is first.expected_behavior is None
    assert first.tags == second.tags == []
    first.tags.append("local")
    assert second.tags == []
    # The original three positional arguments remain valid for API callers.
    assert Case("old", "hello", base_row()["checks"]).tags == []


@pytest.mark.parametrize("path,count", [
    ("examples/chatcheck/suite.json", 6),
    ("examples/chatcheck/suite.failures.json", 3),
])
def test_existing_example_suites_load_without_metadata(path, count):
    cases = load_suite(path)
    assert len(cases) == count
    assert all(case.category is None and case.tags == [] for case in cases)


def test_all_metadata_round_trips_from_utf8_json(tmp_path):
    row = {**base_row(), "category": "language", "language": "ur", "severity": "high",
           "expected_behavior": "اردو میں واپسی کی مدت بتائیں۔", "tags": ["urdu", "واپسی"]}
    case = load_suite(write_suite(tmp_path, [row]))[0]
    assert asdict(case) == row


@pytest.mark.parametrize("field,values", [("category", CATEGORIES), ("language", LANGUAGES), ("severity", SEVERITIES)])
def test_each_allowed_enum_value_and_explicit_null(tmp_path, field, values):
    for value in (*values, None):
        assert getattr(load_suite(write_suite(tmp_path, [{**base_row(), field: value}]))[0], field) == value


@pytest.mark.parametrize("field,value", [
    ("category", "unsupported"), ("category", "Groundedness"), ("category", []),
    ("language", "fr"), ("language", "urdu"), ("language", True),
    ("severity", "urgent"), ("severity", "HIGH"), ("severity", 3),
    ("expected_behavior", ""), ("expected_behavior", "  "), ("expected_behavior", 42),
    ("tags", None), ("tags", "privacy"), ("tags", ["ok", ""]),
    ("tags", ["ok", 3]), ("tags", ["  "]), ("tags", {}),
])
def test_invalid_metadata_has_test_id_and_field_in_error(tmp_path, field, value):
    with pytest.raises(ValueError, match=f"Test sample: {field} must"):
        load_suite(write_suite(tmp_path, [{**base_row(), field: value}]))


def test_enum_error_lists_allowed_values(tmp_path):
    with pytest.raises(ValueError, match="critical, high, medium, low"):
        load_suite(write_suite(tmp_path, [{**base_row(), "severity": "urgent"}]))


def test_direct_model_construction_validates_metadata():
    with pytest.raises(ValueError, match="language must"):
        Case("direct", "hello", base_row()["checks"], language="invalid")
