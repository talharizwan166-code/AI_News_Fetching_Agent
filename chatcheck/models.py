"""Validated input formats shared by the CLI and runner."""

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


CATEGORIES = ("groundedness", "prompt_injection", "data_leakage", "scope", "policy_accuracy", "language", "tone", "robustness")
LANGUAGES = ("ur", "roman_ur", "en")
SEVERITIES = ("critical", "high", "medium", "low")


@dataclass(frozen=True)
class RunOptions:
    concurrency: int = 4
    timeout: float = 30.0
    retries: int = 2
    rate_limit: float = 0.0
    retry_backoff: float = 0.25

    def __post_init__(self):
        for name in ("concurrency", "retries"):
            value = getattr(self, name)
            if type(value) is not int or value < (1 if name == "concurrency" else 0):
                raise ValueError(f"{name} must be an integer >= {1 if name == 'concurrency' else 0}")
        for name in ("timeout", "rate_limit", "retry_backoff"):
            value = getattr(self, name)
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or value < 0 or (name == "timeout" and value == 0)):
                raise ValueError(f"{name} must be finite and {'positive' if name == 'timeout' else 'nonnegative'}")

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class TestCase:
    id: str
    prompt: str
    checks: list[dict[str, Any]]
    category: str | None = None
    language: str | None = None
    expected_behavior: str | None = None
    severity: str | None = None
    tags: list[str] = field(default_factory=list)

    def __post_init__(self):
        for name, allowed in (("category", CATEGORIES), ("language", LANGUAGES), ("severity", SEVERITIES)):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or value not in allowed):
                raise ValueError(f"Test {self.id}: {name} must be one of {', '.join(allowed)}, or null")
        if self.expected_behavior is not None and (
            not isinstance(self.expected_behavior, str) or not self.expected_behavior.strip()
        ):
            raise ValueError(f"Test {self.id}: expected_behavior must be a nonempty string or null")
        if not isinstance(self.tags, list) or any(not isinstance(tag, str) or not tag.strip() for tag in self.tags):
            raise ValueError(f"Test {self.id}: tags must be a list of nonempty strings")


def read_json(path: str | Path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def load_suite(path: str | Path) -> list[TestCase]:
    from .judge import validate_checks

    data = read_json(path)
    rows = data.get("tests") if isinstance(data, dict) else data
    if not isinstance(rows, list) or not rows:
        raise ValueError("Suite must be a nonempty array or an object containing 'tests'")
    tests, seen = [], set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"Test {index} must be an object")
        test_id = row.get("id", str(index))
        if not isinstance(test_id, str) or not test_id.strip() or test_id in seen:
            raise ValueError(f"Test {index} needs a unique, nonempty string id")
        prompt = row.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"Test {test_id}: prompt must be a nonempty string")
        checks = row.get("checks")
        validate_checks(checks)
        metadata = {name: row[name] for name in ("category", "language", "expected_behavior", "severity", "tags") if name in row}
        tests.append(TestCase(test_id, prompt, checks, **metadata))
        seen.add(test_id)
    return tests
