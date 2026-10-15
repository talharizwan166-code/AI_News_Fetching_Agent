from pathlib import Path
import logging
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.env_safety import check_env_not_tracked


@pytest.fixture(autouse=True)
def local_environment(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


@pytest.mark.parametrize("returncode, stdout, expected", [
    (0, "", True),
    (0, ".env\n", False),
    (0, "notes.env\n", True),
])
def test_tracking_guard_reads_only_git_metadata(returncode, stdout, expected, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = SimpleNamespace(returncode=returncode, stdout=stdout)
    with patch("src.env_safety.subprocess.run", return_value=result) as run:
        assert check_env_not_tracked() is expected
    command = run.call_args.args[0]
    assert command[:2] == ["git", "-C"]
    assert Path(command[2]) == Path(__file__).resolve().parents[1]
    assert command[3:] == ["ls-files", "--", ".env"]
    assert run.call_args.kwargs["capture_output"] is True
    assert run.call_args.kwargs["timeout"] == 5


@pytest.mark.parametrize("error", [FileNotFoundError(), PermissionError(), subprocess.TimeoutExpired("git", 5)])
def test_tracking_guard_warns_and_continues_on_git_errors(error, caplog):
    with patch("src.env_safety.subprocess.run", side_effect=error):
        with caplog.at_level(logging.WARNING):
            assert check_env_not_tracked() is True
    assert "continuing" in caplog.text
    assert any(record.levelno == logging.WARNING for record in caplog.records)


@pytest.mark.parametrize("stderr", [
    "fatal: not a git repository", "fatal: detected dubious ownership; safe.directory",
    "fatal: cannot read index",
])
def test_tracking_guard_warns_for_non_repo_ownership_and_other_git_failures(stderr, caplog):
    result = SimpleNamespace(returncode=128, stdout="", stderr=stderr)
    with patch("src.env_safety.subprocess.run", return_value=result):
        with caplog.at_level(logging.WARNING):
            assert check_env_not_tracked() is True
    assert "continuing" in caplog.text


@pytest.mark.parametrize("flag", ["CI", "GITHUB_ACTIONS"])
@pytest.mark.parametrize("value", ["true", " TRUE "])
def test_ci_flags_warn_and_continue_without_git_check(flag, value, monkeypatch, caplog):
    monkeypatch.setenv(flag, value)
    with patch("src.env_safety.subprocess.run") as run:
        with caplog.at_level(logging.WARNING):
            assert check_env_not_tracked() is True
    run.assert_not_called()
    assert "CI environment detected" in caplog.text
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert all(record.name == "src.env_safety" for record in caplog.records)
