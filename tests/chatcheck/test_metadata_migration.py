import json
import sqlite3

import pytest

from chatcheck.judge import judge
from chatcheck.models import RunOptions, TestCase as Case
from chatcheck.storage import MIGRATIONS, Storage


def make_v1_database(path):
    """Create the pre-metadata schema and populate all four related tables."""
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE chatcheck_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        for statement in MIGRATIONS[0]:
            conn.execute(statement)
        conn.execute("INSERT INTO chatcheck_migrations VALUES (1, '2026-01-01')")
        conn.execute("INSERT INTO runs VALUES ('legacy', 'mock', 'old.json', '{}', 'start', 'end', 'completed', NULL)")
        checks = json.dumps([{"type": "contains", "value": "hello"}])
        conn.execute("INSERT INTO tests VALUES (11, 'legacy', 'greeting', 0, 'hello', ?)", (checks,))
        conn.execute("INSERT INTO responses VALUES (21, 11, 1, 'hello there', 12.5, NULL, 'then')")
        conn.execute("INSERT INTO verdicts VALUES (31, 11, 1, 'original reason', '[]')")


def test_v1_upgrade_preserves_all_history_and_is_idempotent(tmp_path):
    path = tmp_path / "v1.db"
    make_v1_database(path)
    for _ in range(2):
        with Storage(path) as db:
            result = db.results("legacy")
            assert result["status"] == "completed"
            assert result["finished_at"] == "end"
            test = result["tests"][0]
            assert test["id"] == 11 and test["prompt"] == "hello"
            assert test["category"] is test["language"] is test["expected_behavior"] is test["severity"] is None
            assert test["tags"] == []
            assert "tags_json" not in test
            assert test["responses"][0]["text"] == "hello there"
            assert test["responses"][0]["latency_ms"] == 12.5
            assert test["verdict"]["reason"] == "original reason"
            assert result["summary"] == {"total": 1, "passed": 1, "failed": 0, "pending": 0}
            assert [r[0] for r in db.connection.execute("SELECT version FROM chatcheck_migrations ORDER BY version")] == [1, 2]
            assert db.connection.execute("SELECT applied_at FROM chatcheck_migrations WHERE version=1").fetchone()[0] == "2026-01-01"
            assert not db.connection.execute("PRAGMA foreign_key_check").fetchall()


def test_metadata_is_snapshotted_and_exported_after_reopening(tmp_path):
    path = tmp_path / "new.db"
    case = Case("language.ur", "اردو", [{"type": "contains", "value": "14"}],
                category="language", language="ur", expected_behavior="14 دن بتائیں۔", severity="high", tags=["اردو", "returns"])
    with Storage(path) as db:
        run_id, ids = db.start_run([case], "mock", "suite.json", RunOptions())
        db.record_attempt(ids[0], 1, "14 دن", 5, None)
        db.record_verdict(ids[0], judge("14 دن", case.checks))
        db.finish_run(run_id)
    case.tags.append("later-edit")
    with Storage(path) as db:
        test = db.results(run_id)["tests"][0]
        for name in ("category", "language", "expected_behavior", "severity"):
            assert test[name] == getattr(case, name)
        assert test["tags"] == ["اردو", "returns"]


def test_failed_migration_rolls_back_columns_and_version(tmp_path, monkeypatch):
    path = tmp_path / "rollback.db"
    make_v1_database(path)
    monkeypatch.setattr("chatcheck.storage.MIGRATIONS", (MIGRATIONS[0], (*MIGRATIONS[1], "INVALID SQL")))
    with pytest.raises(sqlite3.OperationalError):
        Storage(path)
    with sqlite3.connect(path) as conn:
        assert [r[0] for r in conn.execute("SELECT version FROM chatcheck_migrations")] == [1]
        assert "category" not in [r[1] for r in conn.execute("PRAGMA table_info(tests)")]
        assert conn.execute("SELECT text FROM responses").fetchone()[0] == "hello there"
