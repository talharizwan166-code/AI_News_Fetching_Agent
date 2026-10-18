"""SQLite persistence; ordered, transactional schema migrations."""

import json
import math
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
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
    (
        "CREATE TABLE judge_cache_runs (run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, cache_key TEXT NOT NULL REFERENCES llm_cache(cache_key) ON DELETE CASCADE, PRIMARY KEY(run_id, cache_key))",
        "CREATE INDEX judge_cache_runs_key ON judge_cache_runs(cache_key)",
        "INSERT OR IGNORE INTO judge_cache_runs SELECT t.run_id, c.cache_key FROM llm_verdicts l JOIN tests t ON t.id=l.test_id JOIN llm_cache c ON c.cache_key=json_extract(l.result_json, '$.cache_key')",
    ),
    (
        "CREATE TABLE agent_events (test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE, seq INTEGER NOT NULL, timestamp TEXT NOT NULL, action TEXT NOT NULL, arguments_json TEXT NOT NULL, status TEXT NOT NULL, result_json TEXT NOT NULL, PRIMARY KEY(test_id, seq))",
    ),
    (
        "CREATE TABLE monitor_cycles (id TEXT PRIMARY KEY, client_id TEXT NOT NULL, target_id TEXT NOT NULL, slot INTEGER NOT NULL, created_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, run_id TEXT REFERENCES runs(id) ON DELETE SET NULL, config_hash TEXT NOT NULL, schedule TEXT NOT NULL, report_root TEXT NOT NULL, calls INTEGER NOT NULL DEFAULT 0, reserved_cost REAL NOT NULL DEFAULT 0, summary_json TEXT, UNIQUE(client_id, target_id, slot))",
        "CREATE TABLE monitor_alerts (cycle_id TEXT NOT NULL REFERENCES monitor_cycles(id) ON DELETE CASCADE, channel TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY(cycle_id, channel))",
        "CREATE TABLE monitor_artifacts (path TEXT PRIMARY KEY, client_id TEXT NOT NULL, run_id TEXT REFERENCES runs(id) ON DELETE SET NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL, sha256 TEXT NOT NULL)",
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

    def record_event(self, test_id, event):
        with self.connection:
            self.connection.execute(
                "INSERT INTO agent_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                (test_id, event["seq"], event["timestamp"], event["action"],
                 json.dumps(event["arguments"], ensure_ascii=False), event["status"],
                 json.dumps(event.get("result", {}), ensure_ascii=False)),
            )

    def agent_events(self, test_id):
        return [{"seq": row["seq"], "timestamp": row["timestamp"], "action": row["action"],
                 "arguments": json.loads(row["arguments_json"]), "status": row["status"],
                 "result": json.loads(row["result_json"])} for row in self.connection.execute(
                     "SELECT * FROM agent_events WHERE test_id=? ORDER BY seq", (test_id,))]

    def reserve_target_retry(self, test_id, session):
        """Claim one error-only retry atomically; journal lives with the run."""
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            test = self.connection.execute("SELECT * FROM tests WHERE id=?", (test_id,)).fetchone()
            if test is None:
                raise ValueError("Retry test not found")
            run = self.connection.execute("SELECT options_json FROM runs WHERE id=?", (test["run_id"],)).fetchone()
            options = json.loads(run[0])
            events = options.setdefault("target_retries", [])
            if any(event["test_key"] == test["test_key"] and event["session"] == session for event in events):
                return None
            responses = self.connection.execute("SELECT * FROM responses WHERE test_id=? ORDER BY attempt", (test_id,)).fetchall()
            # Even an unusual response with text AND an error is protected from
            # recall. Never improve a failed answer by sampling another answer.
            if (not responses or not responses[-1]["error"]
                    or any(isinstance(row["text"], str) and (not row["error"] or row["text"].strip()) for row in responses)):
                return None
            verdict = self.connection.execute("SELECT * FROM verdicts WHERE test_id=?", (test_id,)).fetchone()
            rule = dict(verdict) if verdict else None
            if rule:
                rule["passed"] = bool(rule["passed"])
                rule["checks"] = json.loads(rule.pop("checks_json"))
            llm = self.connection.execute("SELECT * FROM llm_verdicts WHERE test_id=?", (test_id,)).fetchone()
            label = self.connection.execute("SELECT * FROM human_labels WHERE test_id=?", (test_id,)).fetchone()
            event = {"id": str(uuid.uuid4()), "test_key": test["test_key"], "session": session,
                     "attempt": responses[-1]["attempt"] + 1, "previous_response_id": responses[-1]["id"],
                     "status": "reserved", "created_at": now(),
                     "previous_judgments": {"rule": rule, "llm": json.loads(llm["result_json"]) if llm else None,
                                            "combined": json.loads(llm["combined_json"]) if llm else None,
                                            "human_label": dict(label) if label else None}}
            events.append(event)
            self.connection.execute("UPDATE runs SET options_json=? WHERE id=?", (json.dumps(options), test["run_id"]))
        return {**event, "run_id": test["run_id"], "test_id": test_id, "prompt": test["prompt"]}

    def finish_target_retry(self, run_id, event_id, text, latency_ms, error, *, sent=True):
        """Commit the new attempt and current verdict together, retaining history."""
        from .judge import judge
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute("SELECT options_json FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("Retry run not found")
            options = json.loads(row[0])
            event = next((item for item in options.get("target_retries", []) if item["id"] == event_id), None)
            if event is None or event["status"] != "reserved":
                raise ValueError("Retry event is absent or already finished")
            test = self.connection.execute("SELECT id, checks_json FROM tests WHERE run_id=? AND test_key=?", (run_id, event["test_key"])).fetchone()
            last = self.connection.execute("SELECT id FROM responses WHERE test_id=? ORDER BY attempt DESC LIMIT 1", (test["id"],)).fetchone()
            if last[0] != event["previous_response_id"]:
                raise ValueError("Retry source changed; refusing to overwrite newer results")
            if sent:
                verdict = judge(text, json.loads(test["checks_json"]), error)
                cursor = self.connection.execute(
                    "INSERT INTO responses (test_id, attempt, text, latency_ms, error, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (test["id"], event["attempt"], text, latency_ms, error, now()))
                self.connection.execute(
                    "INSERT INTO verdicts (test_id, passed, reason, checks_json) VALUES (?, ?, ?, ?) ON CONFLICT(test_id) DO UPDATE SET passed=excluded.passed, reason=excluded.reason, checks_json=excluded.checks_json",
                    (test["id"], int(verdict.passed), verdict.reason, json.dumps(verdict.checks)))
                # These judgments apply to the previous response. Their complete
                # records remain in previous_judgments, never counted as new labels.
                self.connection.execute("DELETE FROM llm_verdicts WHERE test_id=?", (test["id"],))
                self.connection.execute("DELETE FROM human_labels WHERE test_id=?", (test["id"],))
                options.get("not_run", {}).pop(event["test_key"], None)
                event.update(status="completed", response_id=cursor.lastrowid, finished_at=now())
            else:
                event.update(status="stopped", reason=error, finished_at=now())
            self.connection.execute("UPDATE runs SET options_json=? WHERE id=?", (json.dumps(options), run_id))

    def finish_run(self, run_id, status="completed", error=None):
        with self.connection:
            self.connection.execute("UPDATE runs SET finished_at=?, status=?, error=? WHERE id=?", (now(), status, error, run_id))

    def mark_not_run(self, run_id, test_keys, reason):
        """Persist skip reasons separately from verdicts: an uncalled test cannot fail."""
        with self.connection:
            row = self.connection.execute("SELECT options_json FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError(f"Run not found: {run_id}")
            options = json.loads(row[0])
            options.setdefault("not_run", {}).update(dict.fromkeys(test_keys, reason))
            self.connection.execute("UPDATE runs SET options_json=? WHERE id=?", (json.dumps(options), run_id))

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
            test["agent_behavior"] = self.agent_events(test["id"])
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
            test["execution_status"] = "attempted" if test["responses"] else "not_run" if test["test_key"] in run["options"].get("not_run", {}) else "pending"
            test["not_run_reason"] = run["options"].get("not_run", {}).get(test["test_key"]) if not test["responses"] else None
            test["retry_history"] = [event for event in run["options"].get("target_retries", []) if event["test_key"] == test["test_key"]]
            run["tests"].append(test)
        passed = sum(t["verdict"] is not None and t["verdict"]["passed"] for t in run["tests"])
        failed = sum(t["verdict"] is not None and not t["verdict"]["passed"] for t in run["tests"])
        run["summary"] = {"total": len(run["tests"]), "passed": passed, "failed": failed, "pending": len(run["tests"]) - passed - failed}
        run["execution_summary"] = {"not_run": sum(t["execution_status"] == "not_run" for t in run["tests"])}
        from .scoring import coverage_scores
        run["coverage_scores"] = coverage_scores(run["tests"])
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

    def get_judge_cache(self, key, *, run_id=None):
        row = self.connection.execute("SELECT result_json FROM llm_cache WHERE cache_key=?", (key,)).fetchone()
        if row and run_id is not None:
            with self.connection:
                self.connection.execute("INSERT OR IGNORE INTO judge_cache_runs VALUES (?, ?)", (run_id, key))
        return json.loads(row[0]) if row else None

    def put_judge_cache(self, key, result, *, run_id=None):
        with self.connection:
            self.connection.execute("INSERT INTO llm_cache VALUES (?, ?, ?) ON CONFLICT(cache_key) DO UPDATE SET result_json=excluded.result_json, created_at=excluded.created_at", (key, json.dumps(result), now()))
            if run_id is not None:
                self.connection.execute("INSERT OR IGNORE INTO judge_cache_runs VALUES (?, ?)", (run_id, key))

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

    def purge(self, *, run_id=None, older_than=None, confirmed=False, clock=None):
        """Delete selected run data transactionally, including cache/sample references.

        Files outside this database and provider-side logs are not affected.
        """
        if confirmed is not True:
            raise ValueError("Purge requires --yes; no run data was deleted")
        if (run_id is None) == (older_than is None):
            raise ValueError("Select exactly one of --run or --older-than")
        if older_than is not None and (type(older_than) not in (int, float) or not math.isfinite(older_than) or older_than < 0):
            raise ValueError("older-than must be a finite nonnegative number of days")
        tables = ("runs", "tests", "responses", "verdicts", "llm_verdicts", "human_labels",
                  "judge_calls", "judge_cache_runs", "llm_cache", "label_sample_items", "label_samples", "agent_events")
        self.connection.execute("PRAGMA secure_delete = ON")
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if run_id is not None:
                selected = [row[0] for row in self.connection.execute("SELECT id FROM runs WHERE id=?", (run_id,))]
                if not selected:
                    raise ValueError(f"Run not found: {run_id}")
            else:
                try:
                    cutoff = ((clock or (lambda: datetime.now(timezone.utc)))() - timedelta(days=older_than)).isoformat()
                except OverflowError:
                    raise ValueError("older-than exceeds the supported date range") from None
                selected = [row[0] for row in self.connection.execute(
                    "SELECT id FROM runs WHERE status != 'running' AND julianday(started_at) < julianday(?) ORDER BY id", (cutoff,))]
            before = {table: self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
            if selected:
                selected_set = set(selected)
                test_ids = set()
                for key in selected:
                    test_ids.update(str(row[0]) for row in self.connection.execute("SELECT id FROM tests WHERE run_id=?", (key,)))
                # Samples store source IDs in JSON as well as FK-linked members.
                # Keep other runs' members and labels; scrub only deleted sources.
                affected = []
                for row in self.connection.execute("SELECT id, metadata_json FROM label_samples"):
                    metadata = json.loads(row["metadata_json"])
                    members = {str(r[0]) for r in self.connection.execute("SELECT test_id FROM label_sample_items WHERE sample_id=?", (row["id"],))}
                    if members & test_ids or selected_set & set(metadata.get("runs", [])):
                        affected.append((row["id"], metadata))
                self.connection.executemany("DELETE FROM runs WHERE id=?", [(key,) for key in selected])
                # Live owners protect shared entries; unowned legacy cache entries
                # cannot be attributed safely and are discarded too.
                self.connection.execute("DELETE FROM llm_cache WHERE NOT EXISTS (SELECT 1 FROM judge_cache_runs r WHERE r.cache_key=llm_cache.cache_key)")
                updated = 0
                for sample_id, metadata in affected:
                    remaining = self.connection.execute("SELECT COUNT(*) FROM label_sample_items WHERE sample_id=?", (sample_id,)).fetchone()[0]
                    if not remaining:
                        self.connection.execute("DELETE FROM label_samples WHERE id=?", (sample_id,))
                        continue
                    metadata["runs"] = [key for key in metadata.get("runs", []) if key not in selected_set]
                    if "real_runs" in metadata:
                        metadata["real_runs"] = [key for key in metadata["real_runs"] if key not in selected_set]
                        metadata["real_items"] = sum(self.connection.execute(
                            "SELECT COUNT(*) FROM label_sample_items s JOIN tests t ON t.id=s.test_id WHERE s.sample_id=? AND t.run_id=? AND EXISTS (SELECT 1 FROM responses r WHERE r.test_id=t.id AND r.error IS NULL AND r.text != '' AND r.attempt=(SELECT MAX(r2.attempt) FROM responses r2 WHERE r2.test_id=t.id))",
                            (sample_id, key)).fetchone()[0] for key in metadata["real_runs"])
                    metadata["mandatory"] = {key: value for key, value in metadata.get("mandatory", {}).items() if key not in test_ids}
                    metadata["size"] = remaining
                    metadata["pool_size"] = sum(self.connection.execute(
                        "SELECT COUNT(*) FROM tests t JOIN verdicts v ON v.test_id=t.id WHERE t.run_id=?", (key,)).fetchone()[0] for key in metadata["runs"])
                    self.connection.execute("UPDATE label_samples SET metadata_json=? WHERE id=?", (json.dumps(metadata), sample_id))
                    updated += 1
            else:
                updated = 0
            counts = {table: before[table] - self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
            # Preserve the existing purge summary for non-agent databases.
            if counts.get("agent_events") == 0:
                counts.pop("agent_events")
        return {"deleted": counts, "samples_updated": updated}

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
                for event in test.get("agent_behavior", []):
                    self.connection.execute("INSERT INTO agent_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                                            (test_id, event["seq"], event["timestamp"], event["action"], json.dumps(event["arguments"]),
                                             event["status"], json.dumps(event.get("result", {}))))
                for response in test["responses"]:
                    self.connection.execute("INSERT INTO responses (test_id, attempt, text, latency_ms, error, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                                            (test_id, response["attempt"], response["text"], response["latency_ms"], response["error"], response["created_at"]))
                verdict = test.get("verdict")
                if verdict:
                    self.connection.execute("INSERT INTO verdicts (test_id, passed, reason, checks_json) VALUES (?, ?, ?, ?)",
                                            (test_id, int(verdict["passed"]), verdict["reason"], json.dumps(verdict["checks"])))
        return run_id
