import pytest
import runpy
from pathlib import Path
from unittest.mock import patch

import main


@pytest.fixture(autouse=True)
def isolated_entry_point(monkeypatch):
    monkeypatch.setattr("sys.argv", ["main.py"])
    monkeypatch.setattr(main, "setup_logging", lambda: None)
    monkeypatch.setattr(main, "check_env_not_tracked", lambda: True)
    monkeypatch.setattr(main, "check_secrets_rotation", lambda: None)
    monkeypatch.setattr(main, "validate_config", lambda: True)


@pytest.mark.parametrize("status, expected", [
    ("success", 0),
    ("no_articles", 0),
    ("all_published", 0),
    ("below_threshold", 0),
    ("gemini_failed", 1),
    ("delivery_failed", 1),
    ("error", 1),
    ("unknown", 1),
    (None, 1),
])
def test_status_exit_codes(monkeypatch, status, expected):
    monkeypatch.setattr(main, "run_agent", lambda **kwargs: {"status": status})
    assert main.main() == expected


def test_pipeline_exception_exits_nonzero(monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("Pipeline failed")

    monkeypatch.setattr(main, "run_agent", fail)
    assert main.main() == 1


def test_invalid_configuration_exits_nonzero(monkeypatch):
    monkeypatch.setattr(main, "validate_config", lambda: False)
    with pytest.MonkeyPatch.context() as guard:
        guard.setattr(main, "run_agent", lambda **kwargs: pytest.fail("Must not run"))
        assert main.main() == 1


def test_tracked_environment_blocks_pipeline(monkeypatch):
    monkeypatch.setattr(main, "check_env_not_tracked", lambda: False)
    monkeypatch.setattr(main, "run_agent", lambda **kwargs: pytest.fail("Must not run"))
    assert main.main() == 1


def test_cli_tracking_guard_runs_before_loading_credentials():
    entry_point = Path(__file__).resolve().parents[1] / "main.py"
    with patch("src.env_safety.check_env_not_tracked", return_value=False), \
            patch("dotenv.load_dotenv") as load, \
            patch("src.agent.run_agent") as run:
        with pytest.raises(SystemExit) as error:
            runpy.run_path(str(entry_point), run_name="__main__")
        assert error.value.code == 1
        load.assert_not_called()
        run.assert_not_called()


def test_ci_guard_cannot_stop_successful_pipeline(monkeypatch):
    from src.env_safety import check_env_not_tracked

    monkeypatch.setenv("CI", "true")
    monkeypatch.setattr(main, "check_env_not_tracked", check_env_not_tracked)
    monkeypatch.setattr(main, "run_agent", lambda **kwargs: {"status": "success"})
    with patch("src.env_safety.subprocess.run", side_effect=FileNotFoundError()) as git:
        assert main.main() == 0
    git.assert_not_called()
