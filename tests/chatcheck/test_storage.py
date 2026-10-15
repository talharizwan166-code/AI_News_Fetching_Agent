import asyncio
import sqlite3

import pytest

from chatcheck.connectors import Connector
from chatcheck.judge import judge
from chatcheck.models import RunOptions, TestCase as Case
from chatcheck.runner import run_suite
from chatcheck.storage import MIGRATIONS, Storage


def test_repeated_runs_preserve_history_and_foreign_keys(tmp_path):
    path = tmp_path / "history.db"
    case = Case("greeting", "hello", [{"type": "equals", "value": "hello"}])
    with Storage(path) as db:
        first, ids = db.start_run([case], "mock", "suite.json", RunOptions())
        db.record_attempt(ids[0], 1, "hello", 12, None)
        db.record_verdict(ids[0], judge("hello", case.checks))
        db.finish_run(first)
        second, _ = db.start_run([case], "mock", "suite.json", RunOptions())
        assert first != second
        with pytest.raises(sqlite3.IntegrityError):
            db.record_attempt(-1, 1, "orphan", 0, None)
    with Storage(path) as db:
        assert db.results(first)["summary"]["passed"] == 1
        assert db.results(second)["summary"]["pending"] == 1
        assert db.connection.execute("SELECT COUNT(*) FROM chatcheck_migrations").fetchone()[0] == len(MIGRATIONS)
        with pytest.raises(ValueError, match="Run not found"):
            db.results("absent")


def test_connector_startup_failure_marks_run_failed(tmp_path):
    class BrokenConnector(Connector):
        async def __aenter__(self):
            raise RuntimeError("browser unavailable")

        async def send(self, prompt):
            raise AssertionError("must not send")

    with Storage(tmp_path / "failed.db") as db:
        with pytest.raises(RuntimeError, match="browser unavailable"):
            asyncio.run(run_suite([Case("x", "hello", [{"type": "json_valid"}])], BrokenConnector(), db))
        row = db.connection.execute("SELECT * FROM runs").fetchone()
        assert row["status"] == "failed"
        assert row["finished_at"]


def test_future_schema_is_rejected_without_mutating_it(tmp_path):
    path = tmp_path / "future.db"
    with Storage(path) as db:
        with db.connection:
            db.connection.execute("INSERT INTO chatcheck_migrations VALUES (?, 'future')", (len(MIGRATIONS) + 1,))
    with pytest.raises(ValueError, match="Unsupported"):
        Storage(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM chatcheck_migrations").fetchone()[0] == len(MIGRATIONS) + 1
