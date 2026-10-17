"""Deterministic, self-contained client reports from saved run snapshots."""

import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from .agreement import agreement_report, predictions
from .models import CATEGORIES, LANGUAGES, SEVERITIES
from .scoring import coverage_scores, has_response


TEMPLATES = Path(__file__).with_name("report_templates")
DEFAULT_NOT_TESTED = (
    "Production traffic and changes made after this saved run.",
    "Multi-turn conversations, tool side effects and authorization of real customer accounts.",
    "Load testing, exhaustive attacks and independent compliance certification.",
)
DEFAULT_PATTERNS = (
    r"(?i)\b(?:[a-z0-9]+[_-])+CANARY(?:[_-][a-z0-9]+)*\b|\bCANARY(?:[_-][a-z0-9]+)+\b",
    r"(?i)\bPRIVATE_ORDER_[a-z0-9_-]+\b",
    r"(?i)other-customer@example\.invalid",
    r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b|\bAIza[A-Za-z0-9_-]{20,}\b|\bgh[pousr]_[A-Za-z0-9_]{20,}\b",
    r'''(?i)\b(?:api[_ -]?key|access[_ -]?token|authorization|password|secret)\s*[:=]\s*["']?(?:Bearer\s+)?[A-Za-z0-9_./+=-]{6,}["']?''',
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
)
SNAPSHOT_FIELDS = ("prompt", "checks", "category", "language", "expected_behavior", "severity", "tags")
SEVERITY_RANK = {value: i for i, value in enumerate(SEVERITIES)}


class Redactor:
    def __init__(self, patterns=()):
        if not isinstance(patterns, (list, tuple)) or any(not isinstance(p, str) or not p for p in patterns):
            raise ValueError("Redaction patterns must be a list of nonempty regex strings")
        try:
            self.patterns = [re.compile(pattern) for pattern in (*DEFAULT_PATTERNS, *patterns)]
        except re.error:
            raise ValueError("Invalid report redaction regex; no report was written") from None

    @classmethod
    def from_environment(cls, extra=()):
        try:
            configured = json.loads(os.environ.get("CHATCHECK_REPORT_REDACT_PATTERNS", "[]"))
        except ValueError:
            raise ValueError("CHATCHECK_REPORT_REDACT_PATTERNS must be a JSON array of regex strings") from None
        if not isinstance(configured, list):
            raise ValueError("CHATCHECK_REPORT_REDACT_PATTERNS must be a JSON array of regex strings")
        return cls([*configured, *extra])

    def text(self, value):
        result = str(value)
        for pattern in self.patterns:
            result = pattern.sub("[REDACTED]", result)
        return result

    def tree(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {key: self.tree(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.tree(item) for item in value]
        return value


def fingerprint(test):
    return {key: test.get(key, [] if key == "tags" else None) for key in SNAPSHOT_FIELDS}


def suite_snapshot(run):
    rows = [{"id": test["test_key"], **fingerprint(test)} for test in run["tests"]]
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def outcome(test):
    combined = test.get("combined_verdict")
    if combined:
        return combined["verdict"]
    rule = test.get("verdict")
    return ("pass" if rule["passed"] else "fail") if rule else "not_judged"


def scores(tests):
    counts = Counter(outcome(test) for test in tests)
    total = len(tests)
    percentage = round(100 * counts["pass"] / total, 1) if total else None
    return {"total": total, "passed": counts["pass"], "failed": counts["fail"],
            "uncertain": counts["uncertain"], "pending": counts["not_judged"], "percent": percentage,
            "display": f"{percentage:.1f}%" if percentage is not None else "Not available",
            "bar_width": f"{percentage or 0:.1f}"}


def score_rows(tests, field, *, response_only=False):
    groups = defaultdict(list)
    for test in tests:
        groups[test.get(field) or "unspecified"].append(test)
    rows = []
    for name, group in sorted(groups.items()):
        coverage = coverage_scores(group)
        rows.append({"name": name, **(coverage["responses_only"] if response_only else scores(group)),
                     "planned": coverage["planned"], "errors": coverage["errors"], "not_run": coverage["not_run"]})
    return rows


def compare_runs(current, older):
    before = {test["test_key"]: test for test in older["tests"]}
    after = {test["test_key"]: test for test in current["tests"]}
    shared = sorted(before.keys() & after.keys())
    modified = [key for key in shared if fingerprint(before[key]) != fingerprint(after[key])]
    matched = [key for key in shared if key not in set(modified)]
    def compared(test):
        return outcome(test) if has_response(test) else "not_run"
    fixed = [key for key in matched if compared(before[key]) == "fail" and compared(after[key]) == "pass"]
    newly_failing = [key for key in matched if compared(before[key]) == "pass" and compared(after[key]) == "fail"]
    changed_review = [key for key in matched if compared(before[key]) != compared(after[key]) and key not in fixed + newly_failing]
    old_coverage, new_coverage = coverage_scores(older["tests"]), coverage_scores(current["tests"])
    old_score, new_score = old_coverage["responses_only"], new_coverage["responses_only"]
    old_matched = coverage_scores([before[key] for key in matched])["responses_only"]
    new_matched = coverage_scores([after[key] for key in matched])["responses_only"]

    def delta(left, right):
        return round(right["percent"] - left["percent"], 1) if left["percent"] is not None and right["percent"] is not None else None

    warnings = []
    if old_coverage["not_run"] or new_coverage["not_run"]:
        warnings.append(f"Response-only scores use {old_coverage['received']}/{old_coverage['planned']} baseline and {new_coverage['received']}/{new_coverage['planned']} current responses; changing coverage can change the score.")
    if older["target_name"] != current["target_name"]:
        warnings.append("Targets differ; interpret this as a comparison of the selected configurations.")
    if modified or before.keys() != after.keys():
        warnings.append("Test definitions or membership changed; use the matched-test score for the direct comparison.")
    if older.get("started_at", "") > current.get("started_at", ""):
        warnings.append("The baseline timestamp is later than the selected run; this is a scenario comparison, not chronological evidence.")
    old_judges = agreement_report(older["tests"])["judge_provenance"]
    new_judges = agreement_report(current["tests"])["judge_provenance"]
    if {(p["provider"], p["model"], p["rubric_version"]) for p in old_judges} != {(p["provider"], p["model"], p["rubric_version"]) for p in new_judges}:
        warnings.append("Judge provenance differs; verdict changes may reflect a different evaluation method.")
    return {"run_id": older["id"], "target": older["target_name"], "date": older.get("started_at"),
            "fixed": fixed, "newly_failing": newly_failing, "review_changes": changed_review,
            "added": sorted(after.keys() - before.keys()), "removed": sorted(before.keys() - after.keys()),
            "modified": modified, "matched": len(matched), "before": old_score, "after": new_score,
            "delta": delta(old_score, new_score), "matched_before": old_matched, "matched_after": new_matched,
            "matched_delta": delta(old_matched, new_matched), "warnings": warnings}


def load_catalog(path=None):
    with Path(path or TEMPLATES / "fixes.json").open(encoding="utf-8") as stream:
        catalog = json.load(stream)
    if catalog.get("reviewed") is not True or not isinstance(catalog.get("fixes"), dict):
        raise ValueError("Fix catalog must contain reviewed static guidance")
    for checks in catalog["fixes"].values():
        if not isinstance(checks, dict):
            raise ValueError("Invalid fix catalog category")
        for fix in checks.values():
            if not isinstance(fix, dict) or any(not isinstance(fix.get(key), str) or not fix[key].strip() for key in ("why", "fix")):
                raise ValueError("Each catalog entry needs why and fix text")
    if "*" not in catalog["fixes"] or "*" not in catalog["fixes"]["*"]:
        raise ValueError("Fix catalog requires a default entry")
    return catalog


def text_direction(text, language=None):
    return "rtl" if language == "ur" or re.search(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]", text or "") else "ltr"


def response_preview(test, redactor, limit):
    responses = test.get("responses", [])
    original = responses[-1].get("text") if responses else None
    if original is None:
        return "(No response recorded)", False
    # Always redact the complete value before cutting it, and escape afterwards
    # in Jinja. This never cuts an HTML entity or exposes a partial secret match.
    text = redactor.text(original)
    truncated = len(text) > limit
    return (text[:limit] + "\n[… response truncated; full original retained in SQLite …]" if truncated else text), truncated


def issue_groups(tests, catalog, redactor, response_limit):
    groups = defaultdict(dict)
    for test in tests:
        if outcome(test) != "fail":
            continue
        rule = test.get("verdict") or {}
        responses = test.get("responses", [])
        if responses and responses[-1].get("error"):
            types = ["connector_error"]
        else:
            types = [detail["type"] for detail in rule.get("checks", []) if not detail["passed"]]
            types = types or ["llm_subjective" if test.get("llm_verdict") else "*"]
        for check_type in set(types):
            groups[(test.get("category") or "unspecified", check_type)][test["test_key"]] = test
    issues = []
    for (category, check_type), members in groups.items():
        ordered = sorted(members.values(), key=lambda test: (SEVERITY_RANK.get(test.get("severity"), 99), test["test_key"]))
        example = ordered[0]
        category_fixes = catalog["fixes"].get(category, {})
        fix = (category_fixes.get(check_type) or catalog["fixes"]["*"].get(check_type)
               or category_fixes.get("*") or catalog["fixes"]["*"]["*"])
        response, truncated = response_preview(example, redactor, response_limit)
        reason = (example.get("verdict") or {}).get("reason", "Selected hybrid verdict failed")
        issues.append({"category": category, "check_type": check_type, "severity": example.get("severity") or "unspecified",
                       "frequency": len(members), "test_key": example["test_key"], "prompt": example["prompt"],
                       "response": response, "truncated": truncated, "expected": example.get("expected_behavior") or "Not specified",
                       "reason": reason, "why": fix["why"], "fix": fix["fix"], "language": example.get("language") or "en",
                       "prompt_dir": text_direction(example["prompt"], example.get("language")),
                       "response_dir": text_direction(response, example.get("language"))})
    return sorted(issues, key=lambda item: (SEVERITY_RANK.get(item["severity"], 99), -item["frequency"], item["category"], item["check_type"]))[:5]


def build_context(run, *, client="Client not specified", compare=None, suite_name=None,
                  suite_version=None, not_tested=(), redactor=None, response_limit=2000, generated_at=None):
    if type(response_limit) is not int or not 1 <= response_limit <= 20000:
        raise ValueError("response-limit must be an integer from 1 to 20000")
    redactor = redactor or Redactor()
    catalog = load_catalog()
    tests = run["tests"]
    overall = scores(tests)
    coverage = coverage_scores(tests)
    headline = coverage["responses_only"]
    agreement = agreement_report(tests)
    categories = score_rows(tests, "category", response_only=True)
    languages = score_rows(tests, "language", response_only=True)
    issues = issue_groups(tests, catalog, redactor, response_limit)
    comparison = compare_runs(run, compare) if compare else None
    summary = [f"The run passed {headline['passed']} of {headline['total']} tests with model responses, giving a response-only score of {headline['display']}.",
               f"Of {overall['total']} planned tests, {coverage['errors']} ended with connector errors and {coverage['not_run']} have no usable response; counting these as not-run gives {coverage['errors_as_not_run']['display']} across all planned tests."]
    failed_categories = sorted({test.get("category") or "unspecified" for test in tests if has_response(test) and outcome(test) == "fail"})
    summary.append("Failures affected " + ", ".join(name.replace("_", " ") for name in failed_categories) + "." if failed_categories
                   else "No failures were observed in the saved tests; untested behavior remains outside this result.")
    disagreements = []
    appendix = []
    for test in tests:
        pred = predictions(test)
        rule = test.get("verdict") or {}
        llm = test.get("llm_verdict") or {}
        if pred["rule_only"] in {"pass", "fail"} and pred["llm_only"] in {"pass", "fail"} and pred["rule_only"] != pred["llm_only"]:
            disagreements.append({"test_key": test["test_key"], "rule": pred["rule_only"], "llm": pred["llm_only"],
                                  "hybrid": outcome(test), "rule_reason": rule.get("reason", ""),
                                  "llm_reason": llm.get("reason", ""), "evidence": llm.get("evidence", "")})
        appendix.append({"test_key": test["test_key"], "category": test.get("category") or "unspecified",
                         "language": test.get("language") or "unspecified", "severity": test.get("severity") or "unspecified",
                         "rule": pred["rule_only"], "llm": pred["llm_only"], "hybrid": outcome(test),
                         "human": (test.get("human_label") or {}).get("label", "unlabeled"), "reason": rule.get("reason", "No rule verdict"),
                         "prompt": test["prompt"], "response": response_preview(test, redactor, response_limit)[0],
                         "prompt_dir": text_direction(test["prompt"], test.get("language")),
                         "response_dir": text_direction(test["responses"][-1].get("text") if test["responses"] else "", test.get("language")),
                         "received": has_response(test),
                         "attempts": [{"number": row["attempt"], "error": row.get("error"),
                                       "status": "Response received" if row.get("text") is not None and not row.get("error") else "No model response"}
                                      for row in test.get("responses", [])]})
    summary.append(f"{len(disagreements)} rule and LLM disagreements require human review." if disagreements
                   else "No definite rule and LLM disagreements were recorded.")
    summary.append(f"Human labels exist for {agreement['labeled']} tests; agreement is shown in the scope section." if agreement["labeled"]
                   else "No human labels exist for this run, so judge quality has not been measured against human decisions.")
    snapshot = suite_snapshot(run)
    context = {"client": client, "target": run["target_name"], "run_id": run["id"], "status": run["status"],
               "run_date": run.get("started_at") or "Unavailable", "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
               "suite_name": suite_name or run.get("suite_name") or PureWindowsPath(run.get("suite_path") or "unnamed suite").stem,
               "suite_version": suite_version or run.get("suite_version") or f"Saved snapshot SHA-256 {snapshot[:16]}",
               "suite_note": "Suite name/version supplied for this report." if suite_name or suite_version else "Historical declared version unavailable; version identifies the saved test definitions." if not run.get("suite_version") else "Saved suite metadata.",
               "snapshot": snapshot, "overall": overall, "summary": summary, "categories": categories,
               "languages": languages, "issues": issues, "disagreements": disagreements, "appendix": appendix,
               "comparison": comparison, "agreement": agreement, "catalog_version": catalog["version"],
               "catalog_note": catalog["review_note"], "not_tested": [*DEFAULT_NOT_TESTED, *not_tested],
               "missing_categories": sorted(set(CATEGORIES) - {t.get("category") for t in tests}),
               "missing_languages": sorted(set(LANGUAGES) - {t.get("language") for t in tests}),
               "llm_judged": sum(bool(t.get("llm_verdict")) and t["llm_verdict"].get("status") == "judged" for t in tests),
               "review_count": sum(bool(t.get("combined_verdict", {}).get("review")) for t in tests),
               "response_limit": response_limit}
    context.update(headline=headline, coverage=coverage)
    context["not_run"] = sum(test.get("execution_status") == "not_run" for test in tests)
    context["target_llm"] = run.get("options", {}).get("target_llm")
    context["agent_behavior"] = [{"test_key": test["test_key"], "events": test["agent_behavior"]}
                                 for test in tests if test.get("agent_behavior")]
    context["sandbox"] = run.get("options", {}).get("sandbox")
    context["agent_evidence"] = agent_evidence(run, compare)
    context["connector_errors"] = sum(bool(test.get("responses")) and bool(test["responses"][-1].get("error")) for test in tests)
    context["retry_count"] = sum(len(test.get("retry_history", [])) for test in tests)
    # Redact every displayed string, not just response excerpts: prompts, judge
    # reasons, comparison keys and cover metadata can contain copied secrets too.
    return redactor.tree(context)


def agent_evidence(run, older=None):
    """Derive observed behavior from events, never from cached finding prose.

    Raw fake drafts are recorded before target validation. A failed raw-draft
    check does not establish that the target delivered the draft.
    """
    before = {t["test_key"]: t for t in older["tests"]} if older else {}

    def counts(test):
        events = test.get("agent_behavior", [])
        return {"calls": sum(e["action"] == "llm_call" and e["status"] != "blocked" for e in events),
                "deliveries": sum(e["action"] in {"issue_created", "email_sent", "post_published"} and e["status"] == "ok" for e in events)}

    return [{"test_key": t["test_key"], "current": counts(t),
             "before": counts(before[t["test_key"]]) if t["test_key"] in before else None,
             "reason": (t.get("verdict") or {}).get("reason", "Not evaluated")}
            for t in run["tests"] if t.get("agent_behavior") and outcome(t) == "fail"]


def summary_context(context):
    """Bound displayed content, explicitly eliding detail; no appendix or raw data."""
    def shorten(value, limit):
        text = " ".join(str(value).split())
        return text if len(text) <= limit else text[:limit] + "… [condensed]"

    result = dict(context)
    for key in ("client", "target", "suite_name", "suite_version", "run_date", "run_id"):
        result[key] = shorten(result[key], 100)
    result["summary"] = [shorten(item, 240) for item in context["summary"][:5]]
    result["issues"] = [{key: shorten(value, 220 if key in {"why", "fix", "reason"} else 90)
                          if isinstance(value, str) else value for key, value in issue.items()
                          if key not in {"prompt", "response"}} for issue in context["issues"][:5]]
    result["issue_pages"] = [result["issues"][i:i + 3] for i in range(0, len(result["issues"]), 3)] or [[]]
    result["not_tested"] = [shorten(item, 160) for item in context["not_tested"][:5]]
    result["scope_omitted"] = max(0, len(context["not_tested"]) - 5)
    result["agent_evidence"] = [{**row, "test_key": shorten(row["test_key"], 65), "reason": shorten(row["reason"], 150)}
                                for row in context["agent_evidence"][:5]]
    result.pop("appendix", None)
    result.pop("agent_behavior", None)
    return result


def render_report(run, *, summary=False, **options):
    try:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined
    except ImportError:
        raise ValueError("HTML reports require Jinja2; install requirements-chatcheck.txt") from None
    environment = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True, undefined=StrictUndefined)
    environment.policies["json.dumps_kwargs"] = {"sort_keys": True, "ensure_ascii": False}
    context = build_context(run, **options)
    return environment.get_template("summary.html" if summary else "report.html").render(
        **(summary_context(context) if summary else context))


def deny_resource(url, *args, **kwargs):
    raise ValueError("Report PDF resource loading is disabled")


def chromium_launch_options(executable_path):
    """Use Playwright's exact browser revision, including this repo's local install."""
    expected = Path(executable_path)
    if expected.is_file():
        return {"executable_path": str(expected)}
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        parts = expected.parts
        revision = next((i for i, part in enumerate(parts) if part.startswith("chromium-")), None)
        if revision is not None:
            for root in (Path(__file__).resolve().parents[1], Path.cwd()):
                candidate = root / ".tools" / "playwright" / Path(*parts[revision:])
                if candidate.is_file():
                    return {"executable_path": str(candidate)}
    return None


def chromium_pdf_bytes(html):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        options = chromium_launch_options(playwright.chromium.executable_path)
        if options is None:
            raise FileNotFoundError("Playwright Chromium is not installed")
        browser = playwright.chromium.launch(headless=True, args=["--disable-background-networking", "--disable-component-update", "--no-pings"], **options)
        try:
            context = browser.new_context(offline=True, java_script_enabled=False, service_workers="block")
            context.route("**/*", lambda route: route.abort("blockedbyclient"))
            page = context.new_page()
            print_style = "<style>@page { size: A4; margin: 17mm 14mm 18mm; @bottom-right { content: none; } }</style>"
            print_html = html.replace("</head>", print_style + "</head>", 1) if "</head>" in html else html + print_style
            page.set_content(print_html, wait_until="load", timeout=15000)
            page.emulate_media(media="print")
            return page.pdf(format="A4", print_background=True, prefer_css_page_size=False,
                            margin={"top": "17mm", "right": "14mm", "bottom": "18mm", "left": "14mm"},
                            display_header_footer=True, header_template="<span></span>",
                            footer_template='<div style="width:100%;text-align:center;font-size:9px;color:#64748b"><span class="pageNumber"></span> / <span class="totalPages"></span></div>')
        finally:
            browser.close()


def weasyprint_pdf_bytes(html):
    from weasyprint import HTML
    # WeasyPrint 70 uses a URLFetcher object; older installed versions accept
    # a callable. Both paths refuse network, data and local file resources.
    fetcher = deny_resource
    try:
        from weasyprint.urls import URLFetcher
    except ImportError:
        pass
    else:
        class OfflineFetcher(URLFetcher):
            def fetch(self, url, headers=None):
                return deny_resource(url)
        fetcher = OfflineFetcher()
    return HTML(string=html, url_fetcher=fetcher).write_pdf()


def pdf_bytes(html):
    """Prefer Chromium; retain WeasyPrint as an independently optional fallback."""
    for renderer in (chromium_pdf_bytes, weasyprint_pdf_bytes):
        try:
            return renderer(html)
        except Exception:
            # Upstream errors can include local paths or content. Keep the CLI
            # diagnostic stable and free of report text and credentials.
            continue
    raise RuntimeError("Neither Chromium nor WeasyPrint could export this report")


class SummaryPageLimitError(ValueError):
    pass


def write_report(run, out, *, pdf=False, summary=False, **options):
    out = Path(out)
    if out.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("--out must have an .html or .htm extension")
    pdf_path = out.with_suffix(".pdf")
    if out.exists() or (pdf and pdf_path.exists()):
        raise FileExistsError("Report output already exists; choose a new --out path")
    html = render_report(run, summary=summary, **options)
    with out.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(html)
    message = f"HTML report written: {out}"
    if pdf:
        try:
            rendered = pdf_bytes(html)
            if summary:
                # Refuse to emit an overlong summary. Full PDFs retain their
                # existing renderer/dependency behavior.
                from io import BytesIO
                from pypdf import PdfReader
                if not 1 <= len(PdfReader(BytesIO(rendered)).pages) <= 5:
                    raise SummaryPageLimitError("Summary PDF exceeds five pages")
        except SummaryPageLimitError:
            return message + "\nPDF not generated: summary exceeds five pages. The HTML is available; use the full report for additional detail."
        except Exception as exc:
            return message + f"\nPDF not generated ({type(exc).__name__}). Install the browser with python -m playwright install chromium, or install requirements-chatcheck-pdf.txt and WeasyPrint native dependencies as a fallback. The HTML report is available."
        with pdf_path.open("xb") as stream:
            stream.write(rendered)
        message += f"\nPDF report written: {pdf_path}"
    return message
