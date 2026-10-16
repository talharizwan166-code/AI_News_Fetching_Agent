import asyncio
import json
import sqlite3

import pytest

from chatcheck.agreement import agreement_report
from chatcheck.cli import main
from chatcheck.labeling import build_sample, label_items
from chatcheck.llm_judge import FakeProvider, LLMJudge, judge_saved_run
from chatcheck.models import RunOptions, TestCase as Case
from chatcheck.judge import judge
from chatcheck.storage import MIGRATIONS, Storage


def make_run(db, *, count=4, target="weak", suite="suite.json"):
    cases = [Case(str(i), f"Prompt {i}", [{"type": "contains", "value": "hello"}],
                  category="tone" if i % 2 else "language", language="en" if i % 3 else "ur",
                  expected_behavior="A polite greeting", severity="medium") for i in range(count)]
    run_id, ids = db.start_run(cases, target, suite, RunOptions())
    for index, (case, test_id) in enumerate(zip(cases, ids)):
        response = "hello" if index % 2 else "wrong"
        db.record_attempt(test_id, 1, response, 0, None)
        db.record_verdict(test_id, judge(response, case.checks))
    db.finish_run(run_id)
    return run_id, ids


def test_blinded_label_storage_resumes_and_never_defaults(tmp_path):
    path = tmp_path / "labels.db"
    with Storage(path) as db:
        run_id, ids = make_run(db)
        llm = LLMJudge(FakeProvider({"wrong": {"verdict": "pass", "severity": "none", "reason": "HIDDEN_LLM_REASON", "evidence": "wrong"}}), db)
        asyncio.run(judge_saved_run(db, run_id, llm))
        tests = db.results(run_id)["tests"]
        answers = iter(["invalid", "pass", "fail", "unsure", "q"])
        shown = []
        count = label_items(db, tests, read=lambda prompt: next(answers), write=shown.append)
        assert count == 3
        display = "\n".join(shown)
        assert all(word in display for word in ("Prompt:", "Response:", "Expected behavior:", "Checks:"))
        assert "HIDDEN_LLM_REASON" not in display
        assert "contains failed" not in display and "DISAGREEMENT" not in display
        assert "verdict" not in display and "combined" not in display
    with Storage(path) as db:
        tests = db.results(run_id)["tests"]
        assert [t["human_label"]["label"] if t["human_label"] else None for t in tests] == ["pass", "fail", "unsure", None]
        assert label_items(db, tests, read=lambda _: "", write=lambda _: None) == 0
        assert db.results(run_id)["tests"][-1]["human_label"] is None
        with pytest.raises(ValueError):
            db.save_label(ids[3], "uncertain")
        with pytest.raises(sqlite3.IntegrityError):
            db.save_label(-1, "pass")
        created = db.results(run_id)["tests"][0]["human_label"]["created_at"]
        db.save_label(ids[0], "fail")
        assert db.results(run_id)["tests"][0]["human_label"]["created_at"] == created


def test_sampler_keeps_all_mandatory_even_over_size_and_is_seeded(tmp_path):
    with Storage(tmp_path / "sample.db") as db:
        first, ids = make_run(db, count=12, suite="suites/clothing_store_heldout.json", target="hardened")
        second, _ = make_run(db, count=12, target="mutant")
        third, _ = make_run(db, count=12, target="weak")
        tests = db.results(second)["tests"]
        test = tests[1]
        db.record_llm_verdict(test["id"], {"status": "judged", "verdict": "fail"},
                              {"verdict": "uncertain", "disagreement": True, "review": True})
        sample, meta = build_sample(db, size=3)
        selected = {test["id"] for test in db.sample_tests(sample)}
        assert set(ids[::2]) <= selected
        assert test["id"] in selected
        assert len(selected) == len(meta["mandatory"]) == 7
        a, _ = build_sample(db, size=20, seed=42)
        b, _ = build_sample(db, size=20, seed=42)
        a_tests, b_tests = db.sample_tests(a), db.sample_tests(b)
        assert [t["id"] for t in a_tests] == [t["id"] for t in b_tests]
        assert len(a_tests) == 20
        assert {t["language"] for t in a_tests} == {"ur", "en"}
        assert {t["category"] for t in a_tests} == {"tone", "language"}
        pool_cells = {(t["category"], t["language"]) for run_id in (first, second, third) for t in db.results(run_id)["tests"]}
        assert {(t["category"], t["language"]) for t in a_tests} == pool_cells
        assert all(t["human_label"] is None for t in a_tests)
        with pytest.raises(ValueError, match="Sample not found"):
            db.sample_tests("missing")


def test_v2_migration_keeps_history_and_adds_empty_label_table(tmp_path):
    path = tmp_path / "v2.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE chatcheck_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        for version, statements in enumerate(MIGRATIONS[:2], 1):
            for statement in statements:
                conn.execute(statement)
            conn.execute("INSERT INTO chatcheck_migrations VALUES (?, 'then')", (version,))
        conn.execute("INSERT INTO runs VALUES ('old', 'target', 'suite', '{}', 'then', 'then', 'completed', NULL)")
    for _ in range(2):
        with Storage(path) as db:
            assert db.results("old")["target_name"] == "target"
            assert db.connection.execute("SELECT COUNT(*) FROM human_labels").fetchone()[0] == 0
            assert not db.connection.execute("PRAGMA foreign_key_check").fetchall()


def test_import_remaps_ids_and_does_not_import_labels(tmp_path):
    with Storage(tmp_path / "source.db") as source:
        run_id, ids = make_run(source)
        source.save_label(ids[0], "pass")
        exported = source.results(run_id)
    with Storage(tmp_path / "destination.db") as destination:
        make_run(destination)
        assert destination.import_run(exported) == run_id
        assert destination.import_run(exported) == run_id
        tests = destination.results(run_id)["tests"]
        assert tests[0]["id"] != ids[0]
        assert all(test["human_label"] is None for test in tests)
        assert destination.results(run_id)["summary"] == exported["summary"]


def test_cli_judge_label_and_agreement(tmp_path, capsys, monkeypatch):
    path = tmp_path / "cli.db"
    with Storage(path) as db:
        run_id, _ = make_run(db)
    assert main(["results", "--run", run_id, "--judge", "fake", "--db", str(path)]) == 0
    assert "llm=uncertain" in capsys.readouterr().out
    answers = iter(["pass", "fail", "unsure", "q"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert main(["label", "--run", run_id, "--db", str(path)]) == 0
    display = capsys.readouterr().out
    assert "llm=" not in display and "Fixture reason" not in display
    assert main(["agreement", "--run", run_id, "--db", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["labeled"] == 3
    assert report["overall"]["rule_only"]["n"] == 2
    assert report["overall"]["llm_only"]["abstained"] == 2


def test_zero_labels_reports_no_accuracy(tmp_path):
    with Storage(tmp_path / "empty.db") as db:
        run_id, _ = make_run(db)
        report = agreement_report(db.results(run_id)["tests"])
        assert report["labeled"] == 0
        assert report["overall"]["rule_only"]["accuracy"] is None


def test_cli_run_judge_switch_and_results_do_not_replay_target(tmp_path, mock_chatbot, capsys, monkeypatch):
    path, target, suite = (tmp_path / name for name in ("run.db", "target.json", "suite.json"))
    target.write_text(json.dumps({"type": "http", "url": mock_chatbot.url + "/chat"}), encoding="utf-8")
    suite.write_text(json.dumps([{"id": "greeting", "prompt": "echo:hello", "category": "tone", "language": "en",
                                 "expected_behavior": "Greet politely", "checks": [{"type": "contains", "value": "hello"}]}]), encoding="utf-8")
    monkeypatch.setenv("CHATCHECK_JUDGE_MAX_CALLS", "1")
    assert main(["run", "--target", str(target), "--suite", str(suite), "--db", str(path), "--judge", "fake"]) == 1
    display = capsys.readouterr().out
    assert "rule=pass llm=uncertain hybrid=uncertain" in display
    run_id = display.splitlines()[0].split()[1]
    calls = len(mock_chatbot.events)
    assert main(["results", "--run", run_id, "--db", str(path), "--judge", "fake"]) == 0
    assert len(mock_chatbot.events) == calls
    with Storage(path) as db:
        result = db.results(run_id)
        assert result["judge_summary"]["calls"] == 1
        assert result["tests"][0]["llm_verdict"]["cached"]
