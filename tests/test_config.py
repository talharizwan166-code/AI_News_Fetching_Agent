import logging
import runpy
import traceback
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import ConfigError, env_float, env_int, env_str


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("GEMINI_API_KEY", "EMAIL_SENDER", "EMAIL_PASSWORD", "EMAIL_RECIPIENT")
DEFAULTS = {
    "FETCH_TIMEOUT_SECONDS": 15,
    "MIN_QUALITY_THRESHOLD": 0.25,
    "MIN_AI_RELEVANCE": 0.30,
    "GEMINI_API_KEY": "",
    "GEMINI_MODEL": "gemini-3.5-flash",
    "GEMINI_FALLBACK_MODEL": "gemini-3.5-flash-lite",
    "GEMINI_MAX_RETRIES": 3,
    "GEMINI_RETRY_WAIT_MIN": 2,
    "GEMINI_RETRY_WAIT_MAX": 30,
    "EMAIL_SENDER": "",
    "EMAIL_PASSWORD": "",
    "EMAIL_RECIPIENT": "",
    "EMAIL_SMTP_HOST": "smtp.gmail.com",
    "EMAIL_SMTP_PORT": 587,
    "LINKEDIN_ACCESS_TOKEN": "",
    "LINKEDIN_PERSON_URN": "",
    "LINKEDIN_API_VERSION": "202610",
    "DB_PATH": "news_agent.db",
}
WEIGHTS = {
    "ai_relevance": 0.30,
    "developer_relevance": 0.20,
    "innovation": 0.20,
    "freshness": 0.15,
    "source_credibility": 0.15,
}


@pytest.fixture
def isolated_config(monkeypatch):
    # Never read real credentials or let the developer's dotenv mask a missing env.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)
    for name in (*DEFAULTS, *("SCORING_WEIGHT_" + key.upper() for key in WEIGHTS)):
        monkeypatch.delenv(name, raising=False)

    def load():
        # Avoid reloading shared modules and contaminating other tests' imports.
        return runpy.run_path(str(ROOT / "src/config.py"))

    return load


@pytest.mark.parametrize("helper, default", [(env_str, "fallback"), (env_int, 587), (env_float, 0.25)])
@pytest.mark.parametrize("value", [None, "", " \t\n "])
def test_helpers_default_for_missing_or_blank(monkeypatch, helper, default, value):
    if value is None:
        monkeypatch.delenv("TEST_CONFIG_VALUE", raising=False)
    else:
        monkeypatch.setenv("TEST_CONFIG_VALUE", value)
    assert helper("TEST_CONFIG_VALUE", default) == default


@pytest.mark.parametrize("value, expected", [
    (" smtp.example.com ", "smtp.example.com"), ("42", "42"),
    ("5.5", "5.5"), ("not-a-number", "not-a-number"), ("0", "0"),
])
def test_env_str_accepts_text_including_numeric_text(monkeypatch, value, expected):
    monkeypatch.setenv("TEST_CONFIG_VALUE", value)
    assert env_str("TEST_CONFIG_VALUE", "fallback") == expected


@pytest.mark.parametrize("helper, value, expected", [
    (env_int, " 2525 ", 2525), (env_int, "0", 0), (env_int, "-3", -3),
    (env_float, " 0.75 ", 0.75), (env_float, "0", 0.0),
    (env_float, "-0.5", -0.5), (env_float, "1e-2", 0.01),
])
def test_numeric_helpers_accept_valid_numbers(monkeypatch, helper, value, expected):
    monkeypatch.setenv("TEST_CONFIG_VALUE", value)
    result = helper("TEST_CONFIG_VALUE", 1)
    assert result == expected
    assert type(result) is type(expected)


@pytest.mark.parametrize("helper, value", [
    (env_int, "private-invalid-number"), (env_int, "5.5"), (env_int, "NaN"),
    (env_float, "private-invalid-number"), (env_float, "NaN"),
    (env_float, "inf"), (env_float, "-inf"), (env_float, "1e999"),
])
def test_numeric_errors_name_variable_without_value(monkeypatch, helper, value):
    monkeypatch.setenv("TEST_CONFIG_VALUE", value)
    with pytest.raises(ConfigError) as caught:
        helper("TEST_CONFIG_VALUE", 1)
    assert "TEST_CONFIG_VALUE" in str(caught.value)
    assert value not in str(caught.value)
    assert value not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("value", [None, "", " \t\n "])
def test_all_configuration_defaults_include_smtp_host_and_port(monkeypatch, isolated_config, value):
    if value is not None:
        for name in (*DEFAULTS, *("SCORING_WEIGHT_" + key.upper() for key in WEIGHTS)):
            monkeypatch.setenv(name, value)
    settings = isolated_config()
    for name, expected in DEFAULTS.items():
        assert settings[name] == expected, name
    assert settings["SCORING_WEIGHTS"] == WEIGHTS
    assert settings["config"].validate() == (False, list(REQUIRED))


@pytest.mark.parametrize("name, value, expected", [
    ("EMAIL_SMTP_PORT", " 2525 ", 2525), ("EMAIL_SMTP_PORT", "587", 587),
    ("EMAIL_SMTP_HOST", " smtp.example.com ", "smtp.example.com"),
    # String settings accept numeric text; only numeric helpers parse it.
    ("EMAIL_SMTP_HOST", "123", "123"),
    ("EMAIL_SMTP_HOST", "not-a-number", "not-a-number"),
    ("GEMINI_MAX_RETRIES", "5", 5), ("GEMINI_RETRY_WAIT_MIN", "4", 4),
    ("GEMINI_RETRY_WAIT_MAX", "40", 40), ("FETCH_TIMEOUT_SECONDS", "20", 20),
    ("MIN_QUALITY_THRESHOLD", "0.5", 0.5), ("MIN_AI_RELEVANCE", "0.4", 0.4),
    ("GEMINI_MODEL", "custom-model", "custom-model"),
    ("GEMINI_FALLBACK_MODEL", "custom-fallback", "custom-fallback"),
    ("LINKEDIN_API_VERSION", "202609", "202609"), ("DB_PATH", "custom.db", "custom.db"),
])
def test_configuration_overrides(monkeypatch, isolated_config, name, value, expected):
    monkeypatch.setenv(name, value)
    assert isolated_config()[name] == expected


@pytest.mark.parametrize("name", [
    "EMAIL_SMTP_PORT", "FETCH_TIMEOUT_SECONDS", "MIN_QUALITY_THRESHOLD", "MIN_AI_RELEVANCE",
    "GEMINI_MAX_RETRIES", "GEMINI_RETRY_WAIT_MIN", "GEMINI_RETRY_WAIT_MAX",
    *("SCORING_WEIGHT_" + key.upper() for key in WEIGHTS),
])
def test_invalid_numeric_config_raises_safe_error(monkeypatch, isolated_config, name):
    monkeypatch.setenv(name, "private-invalid-number")
    with pytest.raises(ValueError) as caught:
        isolated_config()
    assert type(caught.value).__name__ == "ConfigError"
    assert name in str(caught.value)
    assert "private-invalid-number" not in str(caught.value)


def test_scoring_weight_overrides_and_sum_validation(monkeypatch, isolated_config):
    monkeypatch.setenv("SCORING_WEIGHT_AI_RELEVANCE", "0.4")
    monkeypatch.setenv("SCORING_WEIGHT_DEVELOPER_RELEVANCE", "0.1")
    settings = isolated_config()
    assert settings["SCORING_WEIGHTS"]["ai_relevance"] == 0.4
    assert settings["SCORING_WEIGHTS"]["developer_relevance"] == 0.1
    assert settings["config"].validate_scoring_weights() == (True, "")
    monkeypatch.setenv("SCORING_WEIGHT_AI_RELEVANCE", "0.9")
    assert isolated_config()["config"].validate_scoring_weights()[0] is False


def test_validate_reports_all_missing_required_names_together(monkeypatch, isolated_config):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-config-key")
    monkeypatch.setenv("EMAIL_SENDER", " \t ")
    assert isolated_config()["config"].validate() == (False, list(REQUIRED[1:]))
    for name in REQUIRED:
        monkeypatch.setenv(name, "fake-required-value")
    assert isolated_config()["config"].validate() == (True, [])


@pytest.mark.parametrize("value", [None, "", " \t ", " debug "])
def test_log_level_uses_shared_default(monkeypatch, value):
    import main

    if value is None:
        monkeypatch.delenv("LOG_LEVEL", raising=False)
    else:
        monkeypatch.setenv("LOG_LEVEL", value)
    with patch("main.logging.basicConfig") as configure:
        main.setup_logging()
    assert configure.call_args.kwargs["level"] == (logging.DEBUG if value == " debug " else logging.INFO)
    assert configure.call_args.kwargs["force"] is True


def test_env_helpers_do_not_load_dotenv_before_security_guard():
    with patch("dotenv.load_dotenv") as load:
        runpy.run_path(str(ROOT / "src/env.py"))
    load.assert_not_called()
