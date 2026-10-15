import pytest
import logging
import re
import runpy
from pathlib import Path
from unittest.mock import patch

import main

REAL_SETUP_LOGGING = main.setup_logging
REAL_VALIDATE_CONFIG = main.validate_config


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


@pytest.mark.parametrize("setting, value, expected_name", [
    ("MIN_QUALITY_THRESHOLD", 1.5, "MIN_QUALITY_THRESHOLD"),
    ("MIN_AI_RELEVANCE", -0.1, "MIN_AI_RELEVANCE"),
    ("SCORING_WEIGHTS", {"ai_relevance": -1, "freshness": 2}, "SCORING_WEIGHT_AI_RELEVANCE"),
    ("SCORING_WEIGHTS", {"ai_relevance": 0.5}, "SCORING_WEIGHT_"),
    ("FETCH_TIMEOUT_SECONDS", 0, "FETCH_TIMEOUT_SECONDS"),
    ("EMAIL_SMTP_PORT", 70000, "EMAIL_SMTP_PORT"),
    ("GEMINI_MAX_RETRIES", 0, "GEMINI_MAX_RETRIES"),
    ("GEMINI_RETRY_WAIT_MIN", -1, "GEMINI_RETRY_WAIT_MIN"),
    ("GEMINI_RETRY_WAIT_MAX", -1, "GEMINI_RETRY_WAIT_MAX"),
])
def test_invalid_runtime_settings_stop_before_pipeline(monkeypatch, caplog, setting, value, expected_name):
    monkeypatch.setattr(main, "validate_config", REAL_VALIDATE_CONFIG)
    monkeypatch.setattr(main.config, "REQUIRED_VARS", {name: "fake-value" for name in main.config.REQUIRED_VARS})
    monkeypatch.setattr(f"src.config.{setting}", value)
    with patch("main.run_agent") as run:
        assert main.main() == 1
    run.assert_not_called()
    assert expected_name in caplog.text


def test_cli_tracking_guard_runs_before_loading_credentials():
    entry_point = Path(__file__).resolve().parents[1] / "main.py"

    def blocked_guard():
        # Logging must already be configured when the first guard is called.
        configure.assert_called_once()
        assert configure.call_args.kwargs["force"] is True
        return False

    with patch("src.env_safety.check_env_not_tracked", side_effect=blocked_guard), \
            patch("dotenv.load_dotenv") as load, \
            patch("src.agent.run_agent") as run, \
            patch("logging.basicConfig") as configure:
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


@pytest.fixture
def real_logging(monkeypatch):
    # Detach pytest's handlers so force=True cannot close them; restore afterward.
    root = logging.getLogger()
    original_handlers, original_level = root.handlers[:], root.level
    root.handlers = []
    monkeypatch.setattr(main, "setup_logging", REAL_SETUP_LOGGING)
    try:
        yield
    finally:
        for handler in root.handlers:
            if handler not in original_handlers:
                handler.close()
        root.handlers = original_handlers
        root.setLevel(original_level)


@pytest.mark.parametrize("sha, dry_run", [("a" * 40, False), (None, True)])
def test_agent_info_visible_after_early_ci_warning_and_startup_context_is_safe(
    monkeypatch, capsys, real_logging, sha, dry_run,
):
    from src.env_safety import check_env_not_tracked

    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setenv("CI", "true")
    monkeypatch.delenv("EMAIL_SMTP_HOST", raising=False)
    monkeypatch.setenv("EMAIL_SMTP_PORT", " \t ")
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "private-option-must-not-appear")
    if sha is None:
        monkeypatch.delenv("GITHUB_SHA", raising=False)
    else:
        monkeypatch.setenv("GITHUB_SHA", sha)
    monkeypatch.setattr("sys.argv", ["main.py", "--dry-run"] if dry_run else ["main.py"])
    monkeypatch.setattr(main, "check_env_not_tracked", check_env_not_tracked)

    # Reproduce a root handler already installed at WARNING before main() starts.
    # Pytest attaches capture handlers after fixture setup; detach them here too.
    logging.getLogger().handlers = []
    logging.basicConfig(level=logging.WARNING)
    assert check_env_not_tracked() is True
    assert "CI environment detected" in capsys.readouterr().err
    assert logging.getLogger().getEffectiveLevel() == logging.WARNING

    def agent(**kwargs):
        assert kwargs == {"dry_run": dry_run}
        logging.getLogger("src.agent").info("Agent INFO regression marker")
        return {"status": "success"}

    monkeypatch.setattr(main, "run_agent", agent)
    assert main.main() == 0
    output = capsys.readouterr().err
    assert logging.getLogger().getEffectiveLevel() == logging.INFO
    assert re.search(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| INFO\s+\| src.agent \| Agent INFO regression marker",
        output,
    )
    assert "| src.env_safety | CI environment detected" in output
    startup = [line for line in output.splitlines() if "Startup:" in line]
    assert len(startup) == 1
    assert f"git_sha={sha or 'unknown'} dry_run={dry_run}" in startup[0]
    assert "EMAIL_SMTP_HOST" in startup[0]
    assert "EMAIL_SMTP_PORT" in startup[0]
    assert "LINKEDIN_ACCESS_TOKEN" not in startup[0]
    assert "GEMINI_API_KEY" not in startup[0]
    assert "private-option-must-not-appear" not in output
