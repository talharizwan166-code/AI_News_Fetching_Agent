"""Deterministic checks. Invalid rules fail validation before any requests."""

import json
import re
from dataclasses import asdict, dataclass, field

from .text_normalization import normalize_phrase
from .trace_checks import TRACE_RULES, evaluate_trace, validate_trace_check
from .delivery_checks import DELIVERY_RULES, evaluate_delivery, validate_delivery_check


RULES = {"contains", "not_contains", "equals", "regex", "min_length", "max_length", "json_valid", "any_of_phrases"} | TRACE_RULES | DELIVERY_RULES


def reject_json_constant(value):
    raise ValueError(f"Non-JSON constant: {value}")


def validate_checks(checks):
    if not isinstance(checks, list) or not checks:
        raise ValueError("checks must be a nonempty list of rule objects")
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("type"), str) or check["type"] not in RULES:
            raise ValueError("Unknown check type; supported: " + ", ".join(sorted(RULES)))
        kind, value = check["type"], check.get("value")
        if kind in DELIVERY_RULES:
            validate_delivery_check(check)
            continue
        if kind in TRACE_RULES:
            validate_trace_check(check)
            continue
        allowed = {"type", "value", "case_sensitive"}
        if set(check) - allowed:
            raise ValueError(f"Unknown fields in {kind} check: {sorted(set(check) - allowed)}")
        if "case_sensitive" in check:
            if type(check["case_sensitive"]) is not bool or kind in {"min_length", "max_length", "json_valid", "any_of_phrases"}:
                raise ValueError("case_sensitive must be boolean and applies only to text checks")
        if kind == "any_of_phrases":
            if (not isinstance(value, list) or not value
                    or any(not isinstance(phrase, str) or not normalize_phrase(phrase) for phrase in value)):
                raise ValueError("any_of_phrases requires a nonempty list of phrases that remain nonempty after normalization")
        if kind in {"contains", "not_contains", "equals", "regex"}:
            if not isinstance(value, str) or (kind != "equals" and not value):
                raise ValueError(f"{kind} requires a {'nonempty ' if kind != 'equals' else ''}string value")
        if kind in {"min_length", "max_length"} and (type(value) is not int or value < 0):
            raise ValueError(f"{kind} requires a nonnegative integer value")
        if kind == "json_valid" and "value" in check:
            raise ValueError("json_valid does not take a value")
        if kind == "regex":
            try:
                re.compile(value)
            except re.error as exc:
                raise ValueError(f"Invalid regex: {exc}") from exc


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reason: str
    checks: list[dict] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def judge(text: str | None, checks: list[dict], error: str | None = None, *, trace=None) -> Verdict:
    validate_checks(checks)
    if error is not None:
        return Verdict(False, f"Connector error: {error}")
    if not isinstance(text, str):
        return Verdict(False, "Connector returned no text")
    details = []
    for check in checks:
        kind, expected = check["type"], check.get("value")
        if kind in DELIVERY_RULES:
            passed, reason = evaluate_delivery(check, trace)
            details.append({"type": kind, "passed": passed, "reason": reason})
            continue
        if kind in TRACE_RULES:
            passed, reason = evaluate_trace(check, trace)
            details.append({"type": kind, "passed": passed, "reason": reason})
            continue
        sensitive = check.get("case_sensitive", True)
        actual = text if sensitive else text.casefold()
        value = expected if sensitive or not isinstance(expected, str) else expected.casefold()
        if kind == "contains":
            passed = value in actual
        elif kind == "not_contains":
            passed = value not in actual
        elif kind == "equals":
            passed = actual == value
        elif kind == "regex":
            passed = re.search(expected, text, 0 if sensitive else re.IGNORECASE) is not None
        elif kind == "min_length":
            passed = len(text) >= value
        elif kind == "max_length":
            passed = len(text) <= value
        elif kind == "any_of_phrases":
            normalized = normalize_phrase(text)
            passed = any(normalize_phrase(phrase) in normalized for phrase in expected)
        else:
            try:
                json.loads(text, parse_constant=reject_json_constant)
                passed = True
            except (ValueError, RecursionError):
                passed = False
        reason = f"{kind} {'passed' if passed else 'failed'}"
        if kind != "json_valid":
            reason += f" (expected {expected!r})"
        details.append({"type": kind, "passed": passed, "reason": reason})
    failures = [detail["reason"] for detail in details if not detail["passed"]]
    return Verdict(not failures, "; ".join(failures) if failures else f"All {len(details)} checks passed", details)
