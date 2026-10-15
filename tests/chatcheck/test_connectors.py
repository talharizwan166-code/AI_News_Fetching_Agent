import asyncio
import os

import pytest

from chatcheck.connectors import create_connector, render_template
from chatcheck.models import RunOptions, TestCase as Case, load_suite
from chatcheck.runner import run_suite
from chatcheck.storage import Storage


def test_template_is_recursive_and_does_not_mutate_source():
    source = {"messages": [{"role": "user", "content": "prefix: {{prompt}}"}], "temperature": 0}
    rendered = render_template(source, 'quote: "\n\u263a')
    assert rendered["messages"][0]["content"] == 'prefix: quote: "\n\u263a'
    assert source["messages"][0]["content"] == "prefix: {{prompt}}"
    assert rendered["temperature"] == 0


def test_environment_headers_and_missing_variable(monkeypatch):
    monkeypatch.setenv("CHATCHECK_FAKE_TOKEN", "fake-test-token")
    config = {"type": "http", "url": "http://localhost/chat", "headers": {"Authorization": "Bearer ${CHATCHECK_FAKE_TOKEN}"}}
    connector = create_connector(config)
    assert connector.headers["Authorization"] == "Bearer fake-test-token"
    monkeypatch.delenv("CHATCHECK_FAKE_TOKEN")
    with pytest.raises(ValueError, match="Missing header environment variable"):
        create_connector(config)


@pytest.mark.skipif(os.getenv("CHATCHECK_TEST_WIDGET") != "1", reason="Set CHATCHECK_TEST_WIDGET=1 after installing Chromium")
def test_real_widget_full_suite(tmp_path, mock_chatbot):
    config = {"type": "widget", "url": mock_chatbot.url, "input_selector": "#message", "reply_selector": ".reply[data-complete='true']", "submit_selector": "#send"}
    with Storage(tmp_path / "widget.db") as db:
        run_id = asyncio.run(run_suite(load_suite("examples/chatcheck/suite.json"), create_connector(config), db, RunOptions(concurrency=2, timeout=15, retries=0)))
        assert next(e["message"] for e in mock_chatbot.events if "friend" in e["message"]) == 'echo:Hello "friend"!\nUnicode: \u263a'
        assert db.results(run_id)["summary"] == {"total": 6, "passed": 6, "failed": 0, "pending": 0}


@pytest.mark.skipif(os.getenv("CHATCHECK_TEST_WIDGET") != "1", reason="Set CHATCHECK_TEST_WIDGET=1 after installing Chromium")
def test_widget_enter_submission_and_timeout_cleanup(tmp_path, mock_chatbot):
    config = {"type": "widget", "url": mock_chatbot.url, "input_selector": "#message", "reply_selector": ".reply[data-complete='true']"}
    cases = [Case("timeout", "delay:3:echo:late", [{"type": "equals", "value": "late"}]), Case("next", "echo:ok", [{"type": "equals", "value": "ok"}])]
    with Storage(tmp_path / "widget-timeout.db") as db:
        connector = create_connector(config)
        run_id = asyncio.run(run_suite(cases, connector, db, RunOptions(concurrency=1, timeout=2, retries=0)))
        result = db.results(run_id)
        assert result["summary"]["failed"] == 1
        assert "Timed out" in result["tests"][0]["responses"][0]["error"]
        assert result["tests"][1]["verdict"]["passed"]
        assert not connector.browser.is_connected()
