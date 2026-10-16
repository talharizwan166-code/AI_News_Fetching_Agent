import io

import pytest

from chatcheck import report


def test_pdf_prefers_chromium_and_falls_back_only_when_needed(monkeypatch):
    calls = []
    monkeypatch.setattr(report, "chromium_pdf_bytes", lambda html: calls.append("chromium") or b"%PDF-Chromium")
    monkeypatch.setattr(report, "weasyprint_pdf_bytes", lambda html: calls.append("weasyprint") or b"%PDF-WeasyPrint")
    assert report.pdf_bytes("safe") == b"%PDF-Chromium"
    assert calls == ["chromium"]

    def unavailable(html):
        calls.append("missing-chromium")
        raise FileNotFoundError("missing")

    monkeypatch.setattr(report, "chromium_pdf_bytes", unavailable)
    assert report.pdf_bytes("safe") == b"%PDF-WeasyPrint"
    assert calls[-2:] == ["missing-chromium", "weasyprint"]


def test_both_pdf_backends_unavailable_have_sanitized_diagnostic(monkeypatch):
    def missing(html):
        raise RuntimeError("private content in upstream error")
    monkeypatch.setattr(report, "chromium_pdf_bytes", missing)
    monkeypatch.setattr(report, "weasyprint_pdf_bytes", missing)
    with pytest.raises(RuntimeError, match="Neither Chromium nor WeasyPrint") as caught:
        report.pdf_bytes("private content")
    assert "private content" not in str(caught.value)


def test_real_chromium_pdf_is_multipage_and_blocks_external_requests(tmp_path):
    from playwright.sync_api import sync_playwright
    from pypdf import PdfReader

    # Only a missing browser justifies a skip; launch/render failures must fail.
    with sync_playwright() as playwright:
        if report.chromium_launch_options(playwright.chromium.executable_path) is None:
            pytest.skip("Playwright Chromium is missing; run python -m playwright install chromium")
    html = '''<!doctype html><html><head><meta charset="utf-8"><style>
      .new-page { break-before: page; } body { background: #effaf7; }
      </style></head><body><h1>First page</h1>
      <img src="http://127.0.0.1:9/blocked-network-request">
      <script>document.body.textContent = 'UNTRUSTED_SCRIPT_RAN';</script>
      <section class="new-page"><h1>Second page</h1><p>آخری سوال</p></section>
      <section class="new-page"><h1>Third page</h1></section></body></html>'''
    rendered = report.chromium_pdf_bytes(html)
    destination = tmp_path / "real.pdf"
    destination.write_bytes(rendered)
    assert destination.read_bytes().startswith(b"%PDF")
    pdf = PdfReader(io.BytesIO(rendered))
    assert len(pdf.pages) == 3
    text = "\n".join(page.extract_text() for page in pdf.pages)
    assert "First page" in text and "Second page" in text and "Third page" in text
    assert "UNTRUSTED_SCRIPT_RAN" not in text
    assert "1 / 3" in text and "3 / 3" in text
    assert float(pdf.pages[0].mediabox.width) == pytest.approx(595.3, abs=2)
    assert float(pdf.pages[0].mediabox.height) == pytest.approx(841.9, abs=2)


def test_chromium_context_is_offline_and_every_route_is_aborted(monkeypatch):
    from types import SimpleNamespace

    seen = {}

    class Page:
        def set_content(self, html, **options):
            seen["html"] = html

        def emulate_media(self, **options):
            seen["media"] = options

        def add_style_tag(self, **options):
            pass

        def evaluate(self, expression):
            assert expression == "document.fonts.ready"

        def pdf(self, **options):
            seen["pdf"] = options
            return b"%PDF-test"

    class Context:
        def route(self, pattern, handler):
            assert pattern == "**/*"
            for url in ("https://example.invalid/", "http://127.0.0.1:9/", "file:///private"):
                handler(SimpleNamespace(abort=lambda code: seen.setdefault("aborted", []).append((url, code))))

        def new_page(self):
            return Page()

    class Browser:
        def new_context(self, **options):
            seen["context"] = options
            return Context()

        def close(self):
            seen["closed"] = True

    class Chromium:
        executable_path = "fixture-browser"

        def launch(self, **options):
            seen["launch"] = options
            return Browser()

    class Playwright:
        def __enter__(self):
            return SimpleNamespace(chromium=Chromium())

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("playwright.sync_api.sync_playwright", Playwright)
    monkeypatch.setattr(report, "chromium_launch_options", lambda path: {})
    assert report.chromium_pdf_bytes("<p>safe</p>") == b"%PDF-test"
    assert seen["context"] == {"offline": True, "java_script_enabled": False, "service_workers": "block"}
    assert len(seen["aborted"]) == 3 and seen["closed"]
    assert seen["pdf"]["format"] == "A4" and seen["pdf"]["print_background"]
    assert "pageNumber" in seen["pdf"]["footer_template"]
