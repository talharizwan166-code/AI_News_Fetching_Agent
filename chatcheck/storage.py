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
    (
        "CREATE TABLE llm_verdicts (test_id INTEGER PRIMARY KEY REFERENCES tests(id) ON DELETE CASCADE, result_json TEXT NOT NULL, combined_json TEXT NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE llm_cache (cache_key TEXT PRIMARY KEY, result_json TEXT NOT NULL, created_at TEXT NOT NULL)",
        "CREATE TABLE judge_calls (id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, metadata_json TEXT NOT NULL, estimated_cost REAL NOT NULL CHECK(estimated_cost >= 0), created_at TEXT NOT NULL)",
        "CREATE INDEX judge_calls_run ON judge_calls(run_id)",
        "CREATE TABLE human_labels (test_id INTEGER PRIMARY KEY REFERENCES tests(id) ON DELETE CASCADE, label TEXT NOT NULL CHECK(label IN ('pass', 'fail', 'unsure')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE label_samples (id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL)",
        "CREATE TABLE label_sample_items (sample_id TEXT NOT NULL REFERENCES label_samples(id) ON DELETE CASCADE, test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE, position INTEGER NOT NULL, PRIMARY KEY(sample_id, test_id), UNIQUE(sample_id, position))",
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
            llm = self.connection.execute("SELECT * FROM llm_verdicts WHERE test_id=?", (test["id"],)).fetchone()
            test["rule_verdict"] = test["verdict"]
            test["llm_verdict"] = json.loads(llm["result_json"]) if llm else None
            from .llm_judge import hybrid_verdict
            test["combined_verdict"] = json.loads(llm["combined_json"]) if llm else hybrid_verdict(test, None)
            label = self.connection.execute("SELECT * FROM human_labels WHERE test_id=?", (test["id"],)).fetchone()
            test["human_label"] = dict(label) if label else None
            run["tests"].append(test)
        passed = sum(t["verdict"] is not None and t["verdict"]["passed"] for t in run["tests"])
        failed = sum(t["verdict"] is not None and not t["verdict"]["passed"] for t in run["tests"])
        run["summary"] = {"total": len(run["tests"]), "passed": passed, "failed": failed, "pending": len(run["tests"]) - passed - failed}
        run["judge_summary"] = self.judge_usage(run_id)
        run["judge_summary"].update({
            "disagreements": sum(t["combined_verdict"]["disagreement"] for t in run["tests"]),
            "review": sum(t["combined_verdict"]["review"] for t in run["tests"]),
            "not_judged": sum(not t["llm_verdict"] or t["llm_verdict"]["status"] != "judged" for t in run["tests"]),
        })
        return run

    def record_llm_verdict(self, test_id, result, combined):
        with self.connection:
            self.connection.execute(
                "INSERT INTO llm_verdicts VALUES (?, ?, ?, ?) ON CONFLICT(test_id) DO UPDATE SET result_json=excluded.result_json, combined_json=excluded.combined_json, updated_at=excluded.updated_at",
                (test_id, json.dumps(result), json.dumps(combined), now()),
            )

    def get_judge_cache(self, key):
        row = self.connection.execute("SELECT result_json FROM llm_cache WHERE cache_key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_judge_cache(self, key, result):
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO llm_cache VALUES (?, ?, ?)", (key, json.dumps(result), now()))

    def judge_usage(self, run_id):
        row = self.connection.execute("SELECT COUNT(*), COALESCE(SUM(estimated_cost), 0) FROM judge_calls WHERE run_id=?", (run_id,)).fetchone()
        return {"calls": row[0], "estimated_cost": row[1]}

    def reserve_judge_call(self, run_id, metadata, estimated_cost):
        # Reserve before sending, including retries and calls that fail. A second
        # CLI process cannot spend the same remaining budget concurrently.
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            usage = self.judge_usage(run_id)
            config = metadata["config"]
            if usage["calls"] >= config["max_calls"] or usage["estimated_cost"] + estimated_cost > config["max_cost"]:
                return False
            self.connection.execute("INSERT INTO judge_calls (run_id, metadata_json, estimated_cost, created_at) VALUES (?, ?, ?, ?)",
                                    (run_id, json.dumps(metadata), estimated_cost, now()))
        return True

    def save_label(self, test_id, label):
        if label not in {"pass", "fail", "unsure"}:
            raise ValueError("Human label must be pass, fail or unsure")
        with self.connection:
            self.connection.execute(
                "INSERT INTO human_labels VALUES (?, ?, ?, ?) ON CONFLICT(test_id) DO UPDATE SET label=excluded.label, updated_at=excluded.updated_at",
                (test_id, label, now(), now()),
            )

    def list_runs(self):
        return [dict(row) for row in self.connection.execute("SELECT id, target_name, suite_path, status FROM runs ORDER BY started_at, id")]

    def save_sample(self, test_ids, metadata):
        sample_id = str(uuid.uuid4())
        with self.connection:
            self.connection.execute("INSERT INTO label_samples VALUES (?, ?, ?)", (sample_id, json.dumps(metadata), now()))
            self.connection.executemany("INSERT INTO label_sample_items VALUES (?, ?, ?)",
                                        [(sample_id, test_id, i) for i, test_id in enumerate(test_ids)])
        return sample_id

    def sample_tests(self, sample_id):
        if self.connection.execute("SELECT 1 FROM label_samples WHERE id=?", (sample_id,)).fetchone() is None:
            raise ValueError(f"Sample not found: {sample_id}")
        rows = self.connection.execute(
            "SELECT s.test_id, t.run_id FROM label_sample_items s JOIN tests t ON t.id=s.test_id WHERE sample_id=? ORDER BY s.position", (sample_id,)).fetchall()
        by_id = {}
        for run_id in dict.fromkeys(row["run_id"] for row in rows):
            by_id.update({test["id"]: test for test in self.results(run_id)["tests"]})
        return [by_id[row["test_id"]] for row in rows]

    def import_run(self, result):
        """Import a saved engine export without synthesizing responses or labels.

        Preserve run UUIDs, remap row IDs, and leave an existing run untouched.
        Only original rule verdicts are imported; judge results are measured here.
        """
        from .models import TestCase
        if not isinstance(result, dict) or not result.get("id") or not result.get("tests"):
            raise ValueError("Expected a saved chatcheck run export")
        run_id = result["id"]
        if self.connection.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone():
            return run_id
        with self.connection:
            self.connection.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, result["target_name"], result["suite_path"], json.dumps(result["options"]), result["started_at"],
                 result.get("finished_at"), result["status"], result.get("error")),
            )
            for position, test in enumerate(result["tests"]):
                # Validate metadata and checks before persisting an imported row.
                from .judge import validate_checks
                validate_checks(test["checks"])
                TestCase(test["test_key"], test["prompt"], test["checks"], **{
                    k: test[k] for k in ("category", "language", "expected_behavior", "severity", "tags") if k in test})
                cursor = self.connection.execute(
                    "INSERT INTO tests (run_id, test_key, position, prompt, checks_json, category, language, expected_behavior, severity, tags_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (run_id, test["test_key"], position, test["prompt"], json.dumps(test["checks"]), test.get("category"), test.get("language"),
                     test.get("expected_behavior"), test.get("severity"), json.dumps(test.get("tags", []))),
                )
                test_id = cursor.lastrowid
                for response in test["responses"]:
                    self.connection.execute("INSERT INTO responses (test_id, attempt, text, latency_ms, error, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                                            (test_id, response["attempt"], response["text"], response["latency_ms"], response["error"], response["created_at"]))
                verdict = test.get("verdict")
                if verdict:
                    self.connection.execute("INSERT INTO verdicts (test_id, passed, reason, checks_json) VALUES (?, ?, ?, ?)",
                                            (test_id, int(verdict["passed"]), verdict["reason"], json.dumps(verdict["checks"])))
        return run_id
