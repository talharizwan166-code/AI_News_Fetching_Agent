import pytest

from chatcheck.judge import judge, validate_checks


@pytest.mark.parametrize("text,check,passed", [
    ("Hello WORLD", {"type": "contains", "value": "world", "case_sensitive": False}, True),
    ("Hello WORLD", {"type": "contains", "value": "world"}, False),
    ("Stra\u00dfe", {"type": "equals", "value": "STRASSE", "case_sensitive": False}, True),
    ("safe", {"type": "not_contains", "value": "secret"}, True),
    ("SECRET", {"type": "not_contains", "value": "secret", "case_sensitive": False}, False),
    ("four", {"type": "equals", "value": "four"}, True),
    ("four ", {"type": "equals", "value": "four"}, False),
    ("ID=42", {"type": "regex", "value": r"id=\d+", "case_sensitive": False}, True),
    ("ID=x", {"type": "regex", "value": r"ID=\d+"}, False),
    ("abc", {"type": "min_length", "value": 3}, True),
    ("ab", {"type": "min_length", "value": 3}, False),
    ("abc", {"type": "max_length", "value": 3}, True),
    ("abcd", {"type": "max_length", "value": 3}, False),
    ('{"ok":true}', {"type": "json_valid"}, True),
    ("false", {"type": "json_valid"}, True),
    ("{oops}", {"type": "json_valid"}, False),
    ("NaN", {"type": "json_valid"}, False),
])
def test_rules(text, check, passed):
    verdict = judge(text, [check])
    assert verdict.passed is passed
    assert verdict.reason
    assert verdict.checks[0]["passed"] is passed


def test_all_checks_must_pass_and_every_result_is_retained():
    verdict = judge("hello", [{"type": "contains", "value": "hello"}, {"type": "equals", "value": "bye"}])
    assert not verdict.passed
    assert "equals failed" in verdict.reason
    assert len(verdict.checks) == 2


@pytest.mark.parametrize("checks", [
    None, [], {}, [{"type": "unknown"}], [{"type": "contains", "value": ""}],
    [{"type": "regex", "value": "["}], [{"type": "max_length", "value": -1}],
    [{"type": "min_length", "value": True}], [{"type": "json_valid", "value": False}],
    [{"type": "contains", "value": "hi", "case_sensitive": "false"}],
    [{"type": "equals", "value": "hi", "case_sensitve": False}],
])
def test_invalid_rules_rejected(checks):
    with pytest.raises(ValueError):
        validate_checks(checks)


def test_connector_error_never_passes():
    verdict = judge("hello", [{"type": "equals", "value": "hello"}], "HTTP 500")
    assert not verdict.passed
    assert "HTTP 500" in verdict.reason
