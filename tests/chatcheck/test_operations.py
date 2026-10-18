import asyncio
import copy
import json
from datetime import datetime, timezone

import pytest

from chatcheck.cli import main
from chatcheck.judge import judge
from chatcheck.labeling import build_sample
from chatcheck.llm_judge import FakeProvider, LLMJudge, judge_saved_run
from chatcheck.models import RunOptions, TestCase as Case, load_suite
from chatcheck.storage import Storage
from chatcheck.workspace import init_workspace, library_directory


TABLES = ("runs", "tests", "responses", "verdicts", "llm_verdicts", "human_labels", "judge_calls",
          "judge_cache_runs", "llm_cache", "label_sample_items", "label_samples")


def populated(db, *, response="hello", target="Client", started_at=None):
    case = Case("greeting", "Please greet me", [{"type": "contains", "value": "hello"}],
                category="tone", language="en", expected_behavior="Greet politely.", severity="low")
    run_id, ids = db.start_run([case], target, "suite.json", RunOptions())
    db.record_attempt(ids[0], 1, response, 1, None)
    db.record_verdict(ids[0], judge(response, case.checks))
    db.finish_run(run_id)
    db.save_label(ids[0], "pass")  # Explicit test fixture only; never production labels.
    asyncio.run(judge_saved_run(db, run_id, LLMJudge(FakeProvider(), db)))
    if started_at:
        with db.connection:
            db.connection.execute("UPDATE runs SET started_at=? WHERE id=?", (started_at, run_id))
    return run_id, ids[0]


def snapshot(db):
    return {table: [tuple(row) for row in db.connection.execute(f"SELECT * FROM {table}")] for table in TABLES}


def test_purge_deletes_all_client_rows_and_cache_and_empty_samples(tmp_path):
    path = tmp_path / "retention.db"
    with Storage(path) as db:
        run_id, _ = populated(db)
        build_sample(db)
        assert all(db.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0 for table in TABLES)
        result = db.purge(run_id=run_id, confirmed=True)
        assert all(count > 0 for count in result["deleted"].values())
        assert all(not rows for rows in snapshot(db).values())
        assert not db.connection.execute("PRAGMA foreign_key_check").fetchall()
    with Storage(path) as db:
        assert all(not rows for rows in snapshot(db).values())


def test_purge_leaves_other_runs_and_shared_cache_intact_and_scrubs_samples(tmp_path):
    with Storage(tmp_path / "shared.db") as db:
        delete_id, delete_test = populated(db)
        keep_id, keep_test = populated(db)  # Identical input uses a shared cache hit.
        sample_id, _ = build_sample(db)
        original = copy.deepcopy(db.results(keep_id))
        assert db.connection.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 1
        assert db.connection.execute("SELECT COUNT(*) FROM judge_cache_runs").fetchone()[0] == 2
        result = db.purge(run_id=delete_id, confirmed=True)
        assert result["deleted"]["llm_cache"] == 0
        assert result["samples_updated"] == 1
        assert db.results(keep_id) == original
        assert [test["id"] for test in db.sample_tests(sample_id)] == [keep_test]
        metadata = db.connection.execute("SELECT metadata_json FROM label_samples WHERE id=?", (sample_id,)).fetchone()[0]
        assert delete_id not in metadata
        assert str(delete_test) not in json.loads(metadata).get("mandatory", {})
        assert json.loads(metadata)["runs"] == [keep_id]
        assert db.connection.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 1
        db.purge(run_id=keep_id, confirmed=True)
        assert all(not rows for rows in snapshot(db).values())


def test_purge_unshared_cache_does_not_touch_other_run_rows(tmp_path):
    with Storage(tmp_path / "separate.db") as db:
        delete_id, _ = populated(db, response="hello private-client-a")
        keep_id, _ = populated(db, response="hello private-client-b")
        original = copy.deepcopy(db.results(keep_id))
        result = db.purge(run_id=delete_id, confirmed=True)
        assert result["deleted"]["llm_cache"] == 1
        assert db.results(keep_id) == original
        for table in TABLES:
            serialized = json.dumps([tuple(row) for row in db.connection.execute(f"SELECT * FROM {table}")])
            assert delete_id not in serialized and "private-client-a" not in serialized


def test_purge_older_than_is_utc_strict_and_preserves_running_and_unknown_dates(tmp_path):
    with Storage(tmp_path / "age.db") as db:
        old, _ = populated(db, started_at="2026-09-15T23:59:59+00:00")
        edge, _ = populated(db, started_at="2026-09-16T00:00:00+00:00")
        recent, _ = populated(db, started_at="2026-10-15T00:00:00+00:00")
        running, _ = populated(db, started_at="2020-01-01T00:00:00+00:00")
        invalid, _ = populated(db, started_at="unknown")
        with db.connection:
            db.connection.execute("UPDATE runs SET status='running' WHERE id=?", (running,))
        result = db.purge(older_than=30, confirmed=True, clock=lambda: datetime(2026, 10, 16, tzinfo=timezone.utc))
        assert result["deleted"]["runs"] == 1
        assert {row["id"] for row in db.list_runs()} == {edge, recent, running, invalid}
        assert old not in json.dumps(snapshot(db))


@pytest.mark.parametrize("kwargs", [{}, {"run_id": "x", "older_than": 1}, {"older_than": -1}, {"older_than": float("nan")}, {"older_than": True}, {"older_than": 1e300}])
def test_invalid_purge_selectors_are_non_destructive(tmp_path, kwargs):
    with Storage(tmp_path / "invalid.db") as db:
        populated(db)
        before = snapshot(db)
        with pytest.raises(ValueError):
            db.purge(confirmed=True, **kwargs)
        assert snapshot(db) == before


def test_purge_confirmation_and_cli_counts(tmp_path, capsys):
    path = tmp_path / "cli.db"
    with Storage(path) as db:
        run_id, _ = populated(db)
        before = snapshot(db)
        with pytest.raises(ValueError, match="--yes"):
            db.purge(run_id=run_id)
        assert main(["purge", "--run", run_id, "--db", str(path)]) == 2
        assert "--yes" in capsys.readouterr().err
        assert snapshot(db) == before
    assert main(["purge", "--run", run_id, "--db", str(path), "--yes"]) == 0
    output = capsys.readouterr().out
    assert "runs: 1" in output and "responses: 1" in output and "human_labels: 1" in output
    with Storage(path) as db:
        assert all(not rows for rows in snapshot(db).values())


def test_no_confirmation_does_not_initialize_or_migrate_database(tmp_path, capsys):
    path = tmp_path / "missing.db"
    assert main(["purge", "--older-than", "30", "--db", str(path)]) == 2
    assert not path.exists()
    assert "--yes" in capsys.readouterr().err


def test_unknown_run_rolls_back_and_empty_age_selection_is_noop(tmp_path):
    with Storage(tmp_path / "noop.db") as db:
        populated(db)
        before = snapshot(db)
        with pytest.raises(ValueError, match="Run not found"):
            db.purge(run_id="missing", confirmed=True)
        assert snapshot(db) == before
        result = db.purge(older_than=100000, confirmed=True)
        assert not any(result["deleted"].values())
        assert snapshot(db) == before


def test_cache_ownership_migration_backfills_legacy_verdicts(tmp_path):
    path = tmp_path / "legacy-cache.db"
    with Storage(path) as db:
        run_id, _ = populated(db)
        # Restore schema v3 while retaining saved cache/verdict data. Drop all
        # later additions so the fixture remains valid after trace/monitor migrations.
        with db.connection:
            db.connection.execute("DROP TABLE monitor_alerts")
            db.connection.execute("DROP TABLE monitor_artifacts")
            db.connection.execute("DROP TABLE monitor_cycles")
            db.connection.execute("DROP TABLE agent_events")
            db.connection.execute("DROP TABLE judge_cache_runs")
            db.connection.execute("DELETE FROM chatcheck_migrations WHERE version>=4")
    with Storage(path) as db:
        assert db.connection.execute("SELECT run_id FROM judge_cache_runs").fetchone()[0] == run_id
        db.purge(run_id=run_id, confirmed=True)
        assert not db.connection.execute("SELECT * FROM llm_cache").fetchall()


def test_init_copies_empty_library_template_and_never_overwrites(tmp_path, capsys):
    folder = tmp_path / "client"
    assert main(["init", str(folder)]) == 0
    assert "Created:" in capsys.readouterr().out
    expected = {"target.json", "suite.json", ".env.example", "README.md"}
    assert {path.name for path in folder.iterdir()} == expected
    assert (folder / "suite.json").read_bytes() == library_directory().joinpath("starter.json").read_bytes()
    assert json.loads((folder / "suite.json").read_text(encoding="utf-8"))["tests"] == []
    with pytest.raises(ValueError, match="nonempty"):
        load_suite(folder / "suite.json")
    (folder / "target.json").write_text("User configuration", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in folder.iterdir()}
    assert main(["init", str(folder)]) == 0
    assert "Skipped existing:" in capsys.readouterr().out
    assert {path.name: path.read_bytes() for path in folder.iterdir()} == before
    assert not list(folder.glob("*.db"))


def test_init_skips_existing_directories_too(tmp_path):
    (tmp_path / "target.json").mkdir()
    result = init_workspace(tmp_path)
    assert result["skipped"] == ["target.json"]
    assert len(result["created"]) == 3
