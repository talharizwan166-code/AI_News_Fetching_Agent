"""Score transport coverage separately from behavior on received responses."""

from collections import Counter


def has_response(test):
    responses = test.get("responses", [])
    # An empty delivered answer is still a response, and can fail its checks.
    return bool(responses and isinstance(responses[-1].get("text"), str) and not responses[-1].get("error"))


def outcome(test):
    if test.get("combined_verdict"):
        return test["combined_verdict"]["verdict"]
    rule = test.get("verdict")
    return ("pass" if rule["passed"] else "fail") if rule else "not_judged"


def score_values(tests, *, denominator=None):
    counts = Counter(outcome(test) for test in tests)
    total = len(tests) if denominator is None else denominator
    percentage = round(100 * counts["pass"] / total, 1) if total else None
    return {"total": total, "passed": counts["pass"], "failed": counts["fail"],
            "uncertain": counts["uncertain"], "pending": total - counts["pass"] - counts["fail"] - counts["uncertain"],
            "percent": percentage, "display": f"{percentage:.1f}%" if percentage is not None else "Not available",
            "bar_width": f"{percentage or 0:.1f}"}


def coverage_scores(tests):
    received = [test for test in tests if has_response(test)]
    errors = sum(bool(test.get("responses")) and bool(test["responses"][-1].get("error")) for test in tests)
    return {"planned": len(tests), "received": len(received), "errors": errors,
            "not_run": len(tests) - len(received),
            "responses_only": score_values(received),
            "errors_as_not_run": score_values(received, denominator=len(tests))}
