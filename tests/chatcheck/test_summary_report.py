import io
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from chatcheck.cli import main
from chatcheck import report
from chatcheck.storage import Storage
from tests.chatcheck.test_report import make_run


def test_summary_omits_appendix_and_preserves_full_default(tmp_path):
    with Storage(tmp_path / "run.db") as store:
        run = make_run(store)
    concise = report.render_report(run, summary=True)
    full = report.render_report(run)
    assert "CLIENT SUMMARY" in concise and "Top issues" in concise and "Scope and limits" in concise
    assert 'id="appendix"' not in concise and "Full pass/fail appendix" not in concise
    assert "Full pass/fail appendix" in full
    assert run["id"] in concise


def test_summary_redacts_before_shortening_and_escapes(tmp_path):
    with Storage(tmp_path / "run.db") as store:
        run = make_run(store, target='<script>alert(1)</script> API_KEY=syntheticprivatevalue')
    html = report.render_report(run, summary=True, client="Client " + "X" * 10000)
    assert "syntheticprivatevalue" not in html and "[REDACTED]" in html
    assert "<script>alert(1)</script>" not in html
    assert "[condensed]" in html
    assert "X" * 1000 not in html


def test_summary_cli_compare_and_real_pdf_at_most_five_pages(tmp_path):
    path = tmp_path / "runs.db"
    with Storage(path) as store:
        before = make_run(store)
        after = make_run(store)
    out = tmp_path / "summary.html"
    assert main(["report", "--db", str(path), "--run", after["id"], "--compare", before["id"],
                 "--summary", "--pdf", "--out", str(out)]) == 0
    assert "Before / after" in out.read_text(encoding="utf-8")
    assert 1 <= len(PdfReader(out.with_suffix(".pdf")).pages) <= 5


def test_large_multilingual_summary_fits_without_hidden_overflow(tmp_path):
    rows = [{"key": f"case-{n}", "category": category, "response": "wrong", "severity": "critical",
             "prompt": "مصنوعی ذہانت " * 2000} for n, category in enumerate(
                 ["language", "tone", "data_leakage", "robustness", "prompt_injection"])]
    with Storage(tmp_path / "run.db") as store:
        run = make_run(store, rows, target="لمبا نام " * 3000)
    html = report.render_report(run, summary=True, client="X" * 10000,
                                not_tested=["حدود " * 2000] * 20)
    assert "overflow:hidden" not in html and "overflow: hidden" not in html
    assert "additional scope exclusions" in html
    result = report.pdf_bytes(html)
    assert 1 <= len(PdfReader(io.BytesIO(result)).pages) <= 5


def test_summary_refuses_overlong_pdf_instead_of_truncating_it(tmp_path, monkeypatch):
    writer = PdfWriter()
    for _ in range(6):
        writer.add_blank_page(width=595, height=842)
    stream = io.BytesIO()
    writer.write(stream)
    monkeypatch.setattr(report, "pdf_bytes", lambda _: stream.getvalue())
    with Storage(tmp_path / "run.db") as store:
        run = make_run(store)
    out = tmp_path / "summary.html"
    message = report.write_report(run, out, pdf=True, summary=True)
    assert "exceeds five pages" in message
    assert out.exists() and not out.with_suffix(".pdf").exists()


def test_trace_evidence_does_not_repeat_stale_finding_prose(tmp_path):
    with Storage(tmp_path / "run.db") as store:
        run = make_run(store)
    test = run["tests"][1]
    test["agent_behavior"] = [{"seq": 1, "action": "llm_call", "status": "ok", "timestamp": "now", "arguments": {}, "result": {}}]
    run["options"]["sandbox"] = {"mode": "fake", "description": "Local testing",
                                  "findings": [{"finding": "STALE CLAIM: four calls", "test": "x", "suggestion": "x"}]}
    html = report.render_report(run)
    assert "STALE CLAIM" not in html
    assert "1 LLM calls; 0 successful downstream deliveries" in html
