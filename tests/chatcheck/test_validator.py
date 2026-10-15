import json
import subprocess
import sys

import pytest

from chatcheck.cli import main


def test_validator_counts_missing_and_present_metadata_without_side_effects(tmp_path, monkeypatch, capsys):
    suite = tmp_path / "mixed.json"
    suite.write_text(json.dumps([
        {"id": "old", "prompt": "hello", "checks": [{"type": "equals", "value": "hello"}]},
        {"id": "new", "prompt": "hello", "checks": [{"type": "equals", "value": "hello"}],
         "category": "tone", "language": "ur", "severity": "high"},
        {"id": "newer", "prompt": "hello", "checks": [{"type": "equals", "value": "hello"}],
         "category": "tone", "language": "en", "severity": "low"},
    ]), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Validation must not create a connector or open SQLite")

    monkeypatch.setattr("chatcheck.cli.create_connector", forbidden)
    monkeypatch.setattr("chatcheck.cli.Storage", forbidden)
    assert main(["validate", "--suite", str(suite)]) == 0
    output = capsys.readouterr()
    assert not output.err
    assert "Valid suite: 3 tests" in output.out
    assert "tone: 2" in output.out
    assert "ur: 1" in output.out and "en: 1" in output.out
    assert "high: 1" in output.out and "low: 1" in output.out
    assert output.out.count("unspecified: 1") == 3
    assert list(tmp_path.iterdir()) == [suite]


@pytest.mark.parametrize("payload,expected", [
    ('{"tests": []}', "nonempty"),
    ('{"tests": [', "Error:"),
    (json.dumps([{"id": "bad", "prompt": "hello", "checks": [{"type": "equals", "value": "hello"}], "severity": "urgent"}]), "Test bad: severity"),
    (json.dumps([{"prompt": "hello", "checks": [{"type": "bogus"}]}]), "Unknown check type"),
])
def test_validator_reports_clear_errors_and_exit_two(tmp_path, capsys, payload, expected):
    suite = tmp_path / "invalid.json"
    suite.write_text(payload, encoding="utf-8")
    assert main(["validate", "--suite", str(suite)]) == 2
    output = capsys.readouterr()
    assert expected in output.err
    assert "Traceback" not in output.err
    assert "Valid suite" not in output.out


def test_validate_library_from_real_cli():
    result = subprocess.run([sys.executable, "-m", "chatcheck", "validate", "--suite", "suites/clothing_store.json"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "Valid suite: 76 tests" in result.stdout
    assert "groundedness: 8" in result.stdout and "robustness: 11" in result.stdout
    assert "roman_ur: 9" in result.stdout


def test_run_results_and_export_show_metadata(tmp_path, mock_chatbot, capsys):
    target, suite, database = (tmp_path / name for name in ("target.json", "suite.json", "metadata.db"))
    target.write_text(json.dumps({"type": "http", "url": mock_chatbot.url + "/chat"}), encoding="utf-8")
    suite.write_text(json.dumps([{"id": "metadata", "prompt": "hello", "checks": [{"type": "contains", "value": "Hello"}],
                                 "category": "tone", "language": "en", "severity": "low", "expected_behavior": "Greet politely.", "tags": ["greeting"]}]), encoding="utf-8")
    assert main(["run", "--target", str(target), "--suite", str(suite), "--db", str(database)]) == 0
    output = capsys.readouterr().out
    run_id = output.splitlines()[0].split()[1]
    assert "category=tone severity=low" in output
    assert main(["results", "--run", run_id, "--db", str(database)]) == 0
    assert capsys.readouterr().out == output
    assert main(["export", "--run", run_id, "--format", "json", "--db", str(database)]) == 0
    exported = json.loads(capsys.readouterr().out)["tests"][0]
    assert exported["category"] == "tone" and exported["severity"] == "low"
    assert exported["expected_behavior"] == "Greet politely."
    assert exported["language"] == "en" and exported["tags"] == ["greeting"]
