"""SQLite persistence; ordered, transactional schema migrations."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


MIGRATIONS = (
    (
        "CREATE TABLE runs (id TEXT PRIMARY KEY, target_name TEXT NOT NULL, suite_path TEXT NOT NULL, options_json TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, error TEXT)",
        "CREATE TABLE tests (id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, test_key TEXT NOT NULL, position INTEGER NOT NULL, prompt TEXT NOT NULL, checks_json TEXT NOT NULL, UNIQUE(run_id, test_key), UNIQUE(run_id, position))",
        "CREATE TABLE responses (id INTEGER PRIMARY KEY, test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE, attempt INTEGER NOT NULL, text TEXT, latency_ms REAL NOT NULL, error TEXT, created_at TEXT NOT NULL, UNIQUE(test_id, attempt))",
        "CREATE TABLE verdicts (id INTEGER PRIMARY KEY, test_id INTEGER NOT NULL UNIQUE REFERENCES tests(id) ON DELETE CASCADE, passed INTEGER NOT NULL CHECK(passed IN (0, 1)), reason TEXT NOT NULL, checks_json TEXT NOT NULL)",
    ),
    (
        "ALTER TABLE tests ADD COLUMN category TEXT",
        "ALTER TABLE tests ADD COLUMN language TEXT",
        "ALTER TABLE tests ADD COLUMN expected_behavior TEXT",
        "ALTER TABLE tests ADD COLUMN severity TEXT",
        "ALTER TABLE tests ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'",
    ),
)


def now():
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, path: str | Path):
        self.connection = sqlite3.connect(path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA foreign_keys = ON")
            self._migrate()
        except BaseException:
            self.connection.close()
            raise

    def _migrate(self):
        # BEGIN IMMEDIATE also serializes two CLI processes initializing a new DB.
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute("CREATE TABLE IF NOT EXISTS chatcheck_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            versions = [row[0] for row in self.connection.execute("SELECT version FROM chatcheck_migrations ORDER BY version")]
            if versions != list(range(1, len(versions) + 1)) or len(versions) > len(MIGRATIONS):
                raise ValueError("Unsupported chatcheck database schema version")
            for version, statements in enumerate(MIGRATIONS, 1):
                if version > len(versions):
                    for statement in statements:
                        self.connection.execute(statement)
                    self.connection.execute("INSERT INTO chatcheck_migrations VALUES (?, ?)", (version, now()))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.close()

    def start_run(self, tests, target_name, suite_path, options):
        run_id = str(uuid.uuid4())
        test_ids = []
        with self.connection:
            self.connection.execute(
                "INSERT INTO runs (id, target_name, suite_path, options_json, started_at, status) VALUES (?, ?, ?, ?, ?, 'running')",
                (run_id, target_name, str(suite_path), json.dumps(options.to_dict()), now()),
            )
            for position, test in enumerate(tests):
                cursor = self.connection.execute(
                    "INSERT INTO tests (run_id, test_key, position, prompt, checks_json, category, language, expected_behavior, severity, tags_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (run_id, test.id, position, test.prompt, json.dumps(test.checks), test.category,
                     test.language, test.expected_behavior, test.severity, json.dumps(test.tags)),
                )
                test_ids.append(cursor.lastrowid)
        return run_id, test_ids

    def record_attempt(self, test_id, attempt, text, latency_ms, error):
        with self.connection:
            self.connection.execute(
                "INSERT INTO responses (test_id, attempt, text, latency_ms, error, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (test_id, attempt, text, latency_ms, error, now()),
            )

    def record_verdict(self, test_id, verdict):
        with self.connection:
            self.connection.execute(
                "INSERT INTO verdicts (test_id, passed, reason, checks_json) VALUES (?, ?, ?, ?)",
                (test_id, int(verdict.passed), verdict.reason, json.dumps(verdict.checks)),
            )

    def finish_run(self, run_id, status="completed", error=None):
        with self.connection:
            self.connection.execute("UPDATE runs SET finished_at=?, status=?, error=? WHERE id=?", (now(), status, error, run_id))

    def results(self, run_id):
        row = self.connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"Run not found: {run_id}")
        run = dict(row)
        run["options"] = json.loads(run.pop("options_json"))
        run["tests"] = []
        for row in self.connection.execute("SELECT * FROM tests WHERE run_id=? ORDER BY position", (run_id,)):
            test = dict(row)
            test["checks"] = json.loads(test.pop("checks_json"))
            test["tags"] = json.loads(test.pop("tags_json"))
            test["responses"] = [dict(r) for r in self.connection.execute("SELECT * FROM responses WHERE test_id=? ORDER BY attempt", (test["id"],))]
            verdict = self.connection.execute("SELECT * FROM verdicts WHERE test_id=?", (test["id"],)).fetchone()
            test["verdict"] = dict(verdict) if verdict else None
            if verdict:
                test["verdict"]["passed"] = bool(verdict["passed"])
                test["verdict"]["checks"] = json.loads(test["verdict"].pop("checks_json"))
            run["tests"].append(test)
        passed = sum(t["verdict"] is not None and t["verdict"]["passed"] for t in run["tests"])
        failed = sum(t["verdict"] is not None and not t["verdict"]["passed"] for t in run["tests"])
        run["summary"] = {"total": len(run["tests"]), "passed": passed, "failed": failed, "pending": len(run["tests"]) - passed - failed}
        return run
