import json
import sqlite3
import subprocess
import sys

from chatcheck.cli import main
from chatcheck.storage import MIGRATIONS


def cli(*args):
    return subprocess.run([sys.executable, "-m", "chatcheck", *map(str, args)], capture_output=True, text=True, timeout=30)


def test_cli_run_results_export_end_to_end(tmp_path, mock_chatbot):
    target = tmp_path / "target.json"
    target.write_text(json.dumps({"name": "CLI mock", "type": "http", "url": mock_chatbot.url + "/chat"}), encoding="utf-8")
    database = tmp_path / "cli.db"
    run = cli("run", "--target", target, "--suite", "examples/chatcheck/suite.json", "--db", database, "--concurrency", "2")
    assert run.returncode == 0, run.stderr
    assert "6 passed, 0 failed" in run.stdout
    run_id = run.stdout.splitlines()[0].split()[1]
    results = cli("results", "--run", run_id, "--db", database)
    assert results.returncode == 0, results.stderr
    assert results.stdout == run.stdout
    exported = cli("export", "--run", run_id, "--format", "json", "--db", database)
    assert exported.returncode == 0, exported.stderr
    payload = json.loads(exported.stdout)
    assert payload["options"]["concurrency"] == 2
    assert payload["summary"]["passed"] == 6
    assert payload["tests"][4]["responses"][0]["text"].endswith("\u263a")
    with sqlite3.connect(database) as db:
        for table, count in (("runs", 1), ("tests", 6), ("responses", 6), ("verdicts", 6), ("chatcheck_migrations", len(MIGRATIONS))):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == count
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_cli_failures_exit_one_and_store_results(tmp_path, mock_chatbot):
    target = tmp_path / "target.json"
    target.write_text(json.dumps({"type": "http", "url": mock_chatbot.url + "/chat", "runner": {"retry_backoff": 0}}), encoding="utf-8")
    run = cli("run", "--target", target, "--suite", "examples/chatcheck/suite.failures.json", "--db", tmp_path / "failures.db")
    assert run.returncode == 1, run.stderr
    assert "1 passed, 2 failed" in run.stdout
    assert "HTTP 500" in run.stdout


def test_missing_database_does_not_create_one(tmp_path, capsys):
    path = tmp_path / "missing.db"
    assert main(["results", "--run", "missing", "--db", str(path)]) == 2
    assert not path.exists()
    assert "Database not found" in capsys.readouterr().err


def test_invalid_checks_fail_before_database_or_network(tmp_path, mock_chatbot, capsys):
    target, suite, database = (tmp_path / name for name in ("target.json", "suite.json", "invalid.db"))
    target.write_text(json.dumps({"type": "http", "url": mock_chatbot.url + "/chat"}), encoding="utf-8")
    suite.write_text(json.dumps([{"prompt": "hello", "checks": [{"type": "typo"}]}]), encoding="utf-8")
    assert main(["run", "--target", str(target), "--suite", str(suite), "--db", str(database)]) == 2
    assert not database.exists()
    assert not mock_chatbot.events
    assert "Unknown check" in capsys.readouterr().err
