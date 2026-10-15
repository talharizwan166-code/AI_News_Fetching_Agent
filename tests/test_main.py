import pytest

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
