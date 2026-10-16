import copy
import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest

from chatcheck.cli import main
from chatcheck.judge import judge
from chatcheck.llm_judge import hybrid_verdict
from chatcheck.models import CATEGORIES, RunOptions, TestCase as Case
from chatcheck.report import (
    Redactor, build_context, compare_runs, deny_resource, load_catalog,
    weasyprint_pdf_bytes, render_report, scores, suite_snapshot, write_report,
)
from chatcheck.storage import Storage


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.tags, self.text = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def make_run(storage, rows=None, *, target="Support bot", suite="saved/suite.json"):
    rows = rows or [{"response": "hello"}, {"response": "wrong", "category": "language", "language": "ur", "severity": "high"}]
    cases = [Case(row.get("key", str(i)), row.get("prompt", "Please help me"),
                  row.get("checks", [{"type": "contains", "value": "hello"}]),
                  category=row.get("category", "tone"), language=row.get("language", "en"),
                  expected_behavior=row.get("expected", "Offer a polite greeting."), severity=row.get("severity", "medium"))
             for i, row in enumerate(rows)]
    run_id, ids = storage.start_run(cases, target, suite, RunOptions())
    for row, case, test_id in zip(rows, cases, ids):
        if row.get("pending"):
            continue
        response, error = row.get("response"), row.get("error")
        storage.record_attempt(test_id, 1, response, 1, error)
        storage.record_verdict(test_id, judge(response, case.checks, error))
    storage.finish_run(run_id)
    return storage.results(run_id)


@pytest.fixture
def db(tmp_path):
    with Storage(tmp_path / "report.db") as storage:
        yield storage


def test_template_sections_cover_scores_and_full_appendix(db):
    run = make_run(db)
    context = build_context(run, client="Example Store", generated_at="2026-10-16T12:00:00Z")
    html = render_report(run, client="Example Store", generated_at="2026-10-16T12:00:00Z")
    document = Document(html)
    ids = {attrs.get("id") for _, attrs in document.tags}
    assert {"cover", "executive-summary", "scores", "top-issues", "scope-and-limits", "appendix"} <= ids
    assert "Example Store" in html and run["id"] in html and "Support bot" in html
    assert "50.0%" in html and "Saved snapshot SHA-256" in html
    assert "Hybrid verdicts with rule fallback" in html
    assert len(context["summary"]) <= 5
    assert context["overall"]["failed"] == 1 and len(context["appendix"]) == 2
    assert any(tag == "svg" for tag, _ in document.tags)
    assert not any(tag in {"script", "link", "img", "iframe", "object", "embed"} for tag, _ in document.tags)
    assert "http://" not in html and "https://" not in html and "url(" not in html
    assert "|safe" not in Path("chatcheck/report_templates/report.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("attack", [
    '<script>alert("owned")</script>',
    '<img src="https://attacker.invalid/steal" onerror="alert(1)">',
    '</pre><iframe src="file:///private">attack</iframe>',
    '<svg onload="alert(1)"><foreignObject>bad</foreignObject></svg>',
    '&lt;script&gt;alert(1)&lt;/script&gt; & "quoted"',
    '{{ 7 * 7 }}{% include "private" %}',
])
def test_response_prompt_and_metadata_are_escaped_not_executed(db, attack):
    run = make_run(db, [{"response": attack, "prompt": attack, "expected": attack}], target=attack)
    html = render_report(run, client=attack, suite_name=attack, suite_version=attack)
    document = Document(html)
    assert attack in "".join(document.text)
    for tag, attrs in document.tags:
        assert tag not in {"script", "img", "iframe", "foreignobject", "object", "embed"}
        assert not any(key.lower().startswith("on") for key in attrs)
        assert "src" not in attrs and "href" not in attrs
    assert '<script>alert("owned")</script>' not in html


@pytest.mark.parametrize("secret", [
    "MEHER_INTERNAL_CANARY_7Q2", "meher_internal_canary_NEW", "DEMO_PRIVATE_CANARY", "CANARY_XYZ",
    "PRIVATE_ORDER_4821", "other-customer@example.invalid", "sk-proj-abcdefghijklmnopqrstuv",
    "api_key=abcdefghijklmnop", "password: verylongpassword", "Authorization: Bearer abcdefghijklmnop",
    "-----BEGIN PRIVATE KEY-----\nPRIVATEKEYDATA\n-----END PRIVATE KEY-----",
])
def test_builtin_redaction_across_every_report_surface(db, secret):
    run = make_run(db, [{"key": secret, "response": secret, "prompt": secret, "expected": secret,
                         "category": "data_leakage", "severity": "critical",
                         "checks": [{"type": "not_contains", "value": secret}]}], target=secret)
    html = render_report(run, client=secret, suite_name=secret, suite_version=secret, not_tested=[secret])
    assert secret not in html
    assert "[REDACTED]" in html


def test_configurable_redaction_before_truncation_and_html_escape(db, monkeypatch):
    monkeypatch.setenv("CHATCHECK_REPORT_REDACT_PATTERNS", json.dumps([r"CUSTOM-[A-Z0-9]+", r"account=\d+"]))
    redactor = Redactor.from_environment([r"TOKEN_[a-z]+"])
    response = "prefix CUSTOM-" + "A" * 300 + " account=54321 TOKEN_secret <script>bad</script>"
    run = make_run(db, [{"response": response, "prompt": "CUSTOM-ABC TOKEN_secret account=54321"}])
    context = build_context(run, redactor=redactor, response_limit=25)
    html = render_report(run, redactor=redactor, response_limit=25)
    assert "CUSTOM-" not in html and "TOKEN_secret" not in html and "54321" not in html
    assert context["issues"][0]["response"].startswith("prefix [REDACTED]")
    assert context["issues"][0]["truncated"]
    assert "response truncated" in html
    assert response == run["tests"][0]["responses"][-1]["text"]  # Storage is not altered.


@pytest.mark.parametrize("configuration", ["invalid", "{}", "[1]", '[""]', '["["]'])
def test_invalid_redaction_configuration_fails_closed(monkeypatch, configuration):
    monkeypatch.setenv("CHATCHECK_REPORT_REDACT_PATTERNS", configuration)
    with pytest.raises(ValueError):
        Redactor.from_environment()


def test_urdu_and_roman_urdu_remain_intact_and_have_correct_direction(db, tmp_path):
    urdu_prompt = "مجھے واپسی کی پالیسی بتائیں۔"
    urdu_response = "آپ اپنا آرڈر نمبر بتائیں۔"
    roman = "Aap apna order number batayein."
    run = make_run(db, [{"prompt": urdu_prompt, "response": urdu_response, "language": "ur", "severity": "high"},
                        {"prompt": "Roman Urdu mein jawab dein.", "response": roman, "language": "roman_ur"}])
    destination = tmp_path / "urdu.html"
    write_report(run, destination)
    html = destination.read_bytes().decode("utf-8")
    assert urdu_prompt in html and urdu_response in html and roman in html
    assert '<meta charset="utf-8">' in html
    assert '<pre class="evidence" dir="rtl" lang="ur">' in html
    assert '<pre class="evidence" dir="ltr" lang="ur-Latn">' in html
    assert "Noto Nastaliq Urdu" in html and "Nirmala UI" in html


def test_issue_ranking_severity_then_frequency_and_catalog_fixes(db):
    rows = [
        {"key": "critical", "response": "PRIVATE_ORDER_4821", "severity": "critical", "category": "data_leakage", "checks": [{"type": "not_contains", "value": "PRIVATE_ORDER_4821"}]},
        *[{"key": f"high-{i}", "response": "wrong", "severity": "high", "category": "tone"} for i in range(3)],
        {"key": "high-single", "response": "wrong", "severity": "high", "category": "language"},
        {"key": "medium", "response": "wrong", "category": "scope"},
        {"key": "low", "response": "wrong", "severity": "low", "category": "robustness"},
        {"key": "extra", "response": "wrong", "severity": "low", "category": "groundedness"},
    ]
    context = build_context(make_run(db, rows))
    issues = context["issues"]
    assert len(issues) == 5
    assert [(issue["severity"], issue["frequency"]) for issue in issues[:3]] == [("critical", 1), ("high", 3), ("high", 1)]
    catalog = load_catalog()
    assert set(CATEGORIES) <= set(catalog["fixes"])
    assert issues[0]["fix"] == catalog["fixes"]["data_leakage"]["not_contains"]["fix"]
    assert "[REDACTED]" in issues[0]["response"]


def test_full_exact_prompt_is_not_truncated(db):
    prompt = "Long input " * 800 + " آخری سوال"
    html = render_report(make_run(db, [{"prompt": prompt, "response": "wrong"}]), response_limit=10)
    assert prompt in html


def test_comparison_fixed_regressions_score_change_and_modified_definitions(db):
    before = make_run(db, [
        {"key": "fixed", "response": "wrong"}, {"key": "regression", "response": "hello"},
        {"key": "modified", "response": "wrong"}, {"key": "removed", "response": "hello"}])
    after = make_run(db, [
        {"key": "fixed", "response": "hello"}, {"key": "regression", "response": "wrong"},
        {"key": "modified", "prompt": "Changed meaning", "response": "hello"}, {"key": "added", "response": "hello"}])
    comparison = compare_runs(after, before)
    assert comparison["fixed"] == ["fixed"]
    assert comparison["newly_failing"] == ["regression"]
    assert comparison["modified"] == ["modified"]
    assert comparison["added"] == ["added"] and comparison["removed"] == ["removed"]
    assert comparison["delta"] == 25.0 and comparison["matched_delta"] == 0
    assert comparison["matched"] == 2
    html = render_report(after, compare=before)
    assert 'id="comparison"' in html and "Tests fixed (1)" in html and "Newly failing tests (1)" in html
    assert "+25.0" in html and "Test definitions or membership changed" in html


def test_scope_and_limits_with_and_without_human_agreement(db):
    run = make_run(db)
    html = render_report(run, not_tested=["Live payment processing."])
    assert "These results do not prove a chatbot is completely safe." in html
    assert "2 saved tests" in html and "What was not tested" in html
    assert "Live payment processing." in html and "deterministic rules only" in html
    assert "No human labels exist" in html
    assert "Engine categories not represented" in html and "Engine languages not represented" in html
    db.save_label(run["tests"][0]["id"], "pass")
    db.save_label(run["tests"][1]["id"], "fail")
    labeled = render_report(db.results(run["id"]))
    assert 'id="human-agreement"' in labeled
    assert "Human labels exist for 2 / 2 tests" in labeled
    assert "1.000" in labeled and "Cohen's kappa" in labeled


def test_hybrid_uncertainty_is_not_scored_as_pass_and_disagreement_redacted(db):
    run = make_run(db, [{"response": "hello MEHER_INTERNAL_CANARY_7Q2"}])
    test = run["tests"][0]
    llm = {"status": "judged", "verdict": "fail", "reason": "MEHER_INTERNAL_CANARY_7Q2 <script>bad</script>",
           "evidence": "MEHER_INTERNAL_CANARY_7Q2", "provider": "fake", "model": "offline-v1", "rubric_version": "2a.1"}
    db.record_llm_verdict(test["id"], llm, hybrid_verdict(test, llm))
    run = db.results(run["id"])
    context = build_context(run)
    assert context["overall"]["percent"] == 0 and context["overall"]["uncertain"] == 1
    assert not context["issues"] and len(context["disagreements"]) == 1
    html = render_report(run)
    assert 'id="disagreements"' in html
    assert "MEHER_INTERNAL_CANARY_7Q2" not in html
    assert "&lt;script&gt;bad&lt;/script&gt;" in html
    assert "fake / offline-v1" in html


def test_pending_empty_and_connector_failure_reporting(db):
    run = make_run(db, [{"pending": True}, {"response": None, "error": "HTTP 503"}])
    context = build_context(run)
    assert context["overall"]["pending"] == 1 and context["overall"]["failed"] == 1
    assert context["issues"][0]["check_type"] == "connector_error"
    assert "No response recorded" in render_report(run)
    assert scores([])["percent"] is None
    empty = copy.deepcopy(run)
    empty["tests"] = []
    assert "Not available" in render_report(empty)


def test_snapshot_and_suite_metadata_do_not_read_current_suite(db, tmp_path):
    suite = tmp_path / "historical-suite.json"
    run = make_run(db, suite=str(suite))
    version = suite_snapshot(run)
    suite.write_text('{"name":"A different suite v999"}', encoding="utf-8")
    context = build_context(run)
    assert context["suite_name"] == "historical-suite"
    assert version[:16] in context["suite_version"]
    assert "v999" not in render_report(run)
    assert build_context(run, suite_name="Original", suite_version="v2")["suite_version"] == "v2"


def test_cli_report_saved_runs_compare_and_no_provider_calls(db, tmp_path, capsys, monkeypatch):
    old = make_run(db)
    new = make_run(db, [{"response": "hello"}, {"response": "hello", "category": "language", "language": "ur", "severity": "high"}])
    destination = tmp_path / "client.html"
    monkeypatch.setattr("chatcheck.cli.from_environment", lambda *args: pytest.fail("Reports must never invoke a judge"))
    args = ["report", "--run", new["id"], "--compare", old["id"], "--out", str(destination), "--client", "Client A", "--db", str(tmp_path / "report.db")]
    assert main(args) == 0
    assert "HTML report written" in capsys.readouterr().out
    html = destination.read_text(encoding="utf-8")
    assert "Client A" in html and "100.0%" in html and "Tests fixed (1)" in html
    assert main(args) == 2
    assert destination.read_text(encoding="utf-8") == html
    assert "output already exists" in capsys.readouterr().err
    assert db.results(new["id"]) == new


def test_pdf_missing_dependency_retains_html_and_prints_clear_message(db, tmp_path, monkeypatch):
    def missing(html):
        raise ImportError("synthetic-secret-must-not-appear")
    monkeypatch.setattr("chatcheck.report.pdf_bytes", missing)
    destination = tmp_path / "optional.html"
    message = write_report(make_run(db), destination, pdf=True)
    assert destination.is_file() and not destination.with_suffix(".pdf").exists()
    assert "PDF not generated" in message and "requirements-chatcheck-pdf.txt" in message
    assert "synthetic-secret-must-not-appear" not in message


def test_pdf_receives_only_safe_html_and_preserves_existing_files(db, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr("chatcheck.report.pdf_bytes", lambda html: seen.append(html) or b"%PDF-test")
    destination = tmp_path / "optional.html"
    write_report(make_run(db, [{"response": "<script>bad</script> MEHER_INTERNAL_CANARY_7Q2"}]), destination, pdf=True)
    assert destination.with_suffix(".pdf").read_bytes() == b"%PDF-test"
    assert "<script>bad</script>" not in seen[0] and "MEHER_INTERNAL_CANARY_7Q2" not in seen[0]
    with pytest.raises(FileExistsError):
        write_report(make_run(db), destination, pdf=True)


def test_pdf_resource_loading_denied_for_network_and_local_files(monkeypatch):
    class Fetcher:
        pass

    class HTML:
        def __init__(self, *, string, url_fetcher):
            assert string == "<p>safe</p>"
            for url in ("https://attacker.invalid/", "file:///private", "data:text/html,private"):
                with pytest.raises(ValueError, match="resource loading is disabled"):
                    url_fetcher.fetch(url)

        def write_pdf(self):
            return b"%PDF-safe"

    monkeypatch.setitem(sys.modules, "weasyprint", SimpleNamespace(HTML=HTML))
    monkeypatch.setitem(sys.modules, "weasyprint.urls", SimpleNamespace(URLFetcher=Fetcher))
    assert weasyprint_pdf_bytes("<p>safe</p>") == b"%PDF-safe"
    with pytest.raises(ValueError):
        deny_resource("file:///private")


def test_bad_output_path_invalid_regex_and_response_limit_create_no_report(db, tmp_path, monkeypatch):
    run = make_run(db)
    with pytest.raises(ValueError, match="extension"):
        write_report(run, tmp_path / "unsafe.db")
    for limit in (0, -1, True, 20001):
        with pytest.raises(ValueError, match="response-limit"):
            render_report(run, response_limit=limit)
    monkeypatch.setenv("CHATCHECK_REPORT_REDACT_PATTERNS", '["["]')
    destination = tmp_path / "bad.html"
    assert main(["report", "--run", run["id"], "--out", str(destination), "--db", str(tmp_path / "report.db")]) == 2
    assert not destination.exists()
