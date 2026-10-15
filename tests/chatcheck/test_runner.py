import asyncio
import json

import pytest

from chatcheck.connectors import Connector, create_connector
from chatcheck.models import RunOptions, TestCase as Case, load_suite
from chatcheck.runner import run_suite
from chatcheck.storage import Storage


def case(key, prompt, expected):
    return Case(key, prompt, [{"type": "equals", "value": expected}])


def execute(tmp_path, server, tests, options=None, **config):
    path = tmp_path / "results.db"
    connector = create_connector({"type": "http", "url": server.url + "/chat", **config})
    with Storage(path) as db:
        run_id = asyncio.run(run_suite(tests, connector, db, options))
    # Reopening checks persistence and idempotent migrations.
    with Storage(path) as db:
        return db.results(run_id)


def test_full_example_suite(tmp_path, mock_chatbot):
    suite = load_suite("examples/chatcheck/suite.json")
    result = execute(tmp_path, mock_chatbot, suite, response_json_path="$.choices[0].message.content")
    assert result["status"] == "completed"
    assert result["summary"] == {"total": 6, "passed": 6, "failed": 0, "pending": 0}
    assert [test["test_key"] for test in result["tests"]] == [test.id for test in suite]
    assert all(t["responses"][0]["latency_ms"] > 0 for t in result["tests"])


def test_retries_keep_error_and_success_attempts(tmp_path, mock_chatbot):
    result = execute(tmp_path, mock_chatbot, [case("retry", "flaky:echo:recovered", "recovered")], RunOptions(retries=1, retry_backoff=0))
    test = result["tests"][0]
    assert test["verdict"]["passed"]
    assert [r["error"] for r in test["responses"]] == ["HTTP 503", None]
    assert [r["attempt"] for r in test["responses"]] == [1, 2]
    assert test["responses"][-1]["text"] == "recovered"


def test_exhausted_retries_and_no_retry_for_permanent_error(tmp_path, mock_chatbot):
    result = execute(tmp_path, mock_chatbot, [case("temporary", "error", "ok"), case("permanent", "bad-request", "ok"), case("invalid", "invalid-json", "ok")], RunOptions(retries=2, retry_backoff=0))
    assert result["summary"]["failed"] == 3
    assert [len(t["responses"]) for t in result["tests"]] == [3, 1, 1]
    assert "HTTP 500" in result["tests"][0]["verdict"]["reason"]


def test_timeout_is_recorded_and_does_not_stop_other_tests(tmp_path, mock_chatbot):
    result = execute(tmp_path, mock_chatbot, [case("slow", "delay:0.4:echo:late", "late"), case("fast", "echo:ok", "ok")], RunOptions(timeout=0.1, retries=1, retry_backoff=0))
    slow, fast = result["tests"]
    assert not slow["verdict"]["passed"]
    assert len(slow["responses"]) == 2
    assert all("Timed out" in r["error"] for r in slow["responses"])
    assert fast["verdict"]["passed"]


def test_concurrency_is_bounded_and_requests_overlap(tmp_path, mock_chatbot):
    tests = [case(str(i), f"delay:0.15:echo:{i}", str(i)) for i in range(6)]
    result = execute(tmp_path, mock_chatbot, tests, RunOptions(concurrency=2, retries=0))
    assert result["summary"]["passed"] == 6
    assert mock_chatbot.max_active_requests == 2


def test_rate_limit_is_shared_across_workers_and_retries(tmp_path, mock_chatbot):
    tests = [case(str(i), f"flaky:echo:{i}", str(i)) for i in range(3)]
    result = execute(tmp_path, mock_chatbot, tests, RunOptions(concurrency=3, rate_limit=8, retries=1, retry_backoff=0))
    assert result["summary"]["passed"] == 3
    starts = sorted(event["time"] for event in mock_chatbot.events)
    assert len(starts) == 6
    assert all(b - a >= 0.10 for a, b in zip(starts, starts[1:]))


@pytest.mark.parametrize("path", ["$.missing", "$.choices[*]", "$"])
def test_invalid_response_selection_fails_without_retry(tmp_path, mock_chatbot, path):
    result = execute(tmp_path, mock_chatbot, [case("bad-path", "hello", "Hello")], response_json_path=path)
    test = result["tests"][0]
    assert not test["verdict"]["passed"]
    assert len(test["responses"]) == 1
    assert "exactly one string" in test["responses"][0]["error"]


def test_rule_failure_does_not_retry(tmp_path, mock_chatbot):
    result = execute(tmp_path, mock_chatbot, [case("fail", "echo:actual", "expected")])
    assert result["summary"]["failed"] == 1
    assert len(result["tests"][0]["responses"]) == 1
    assert "equals failed" in result["tests"][0]["verdict"]["reason"]


def test_cancellation_retains_partial_run_and_closes_connector(tmp_path):
    class BlockingConnector(Connector):
        closed = False

        async def send(self, prompt):
            await asyncio.Event().wait()

        async def __aexit__(self, *args):
            self.closed = True

    connector = BlockingConnector()
    with Storage(tmp_path / "cancel.db") as db:
        async def cancel_run():
            task = asyncio.create_task(run_suite([case("cancel", "hello", "hello")], connector, db))
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        asyncio.run(cancel_run())
        row = db.connection.execute("SELECT * FROM runs").fetchone()
        assert row["status"] == "cancelled"
        assert row["finished_at"]
        assert connector.closed


@pytest.mark.parametrize("options", [{"concurrency": 0}, {"retries": -1}, {"timeout": 0}, {"rate_limit": -1}, {"timeout": float("nan")}, {"concurrency": True}])
def test_invalid_options(options):
    with pytest.raises(ValueError):
        RunOptions(**options)


def test_duplicate_ids_and_invalid_checks_are_rejected(tmp_path):
    path = tmp_path / "suite.json"
    rows = [{"id": "same", "prompt": "hi", "checks": [{"type": "equals", "value": "hi"}]}] * 2
    path.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_suite(path)
