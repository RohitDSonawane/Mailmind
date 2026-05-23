"""
tests/test_config.py — Unit tests for config.py environment variable loading.

Tests use monkeypatch to control environment state without touching the
real .env file or the host system's environment variables.
"""

import importlib
import sys

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload_config(monkeypatch, env_overrides: dict) -> object:
    """
    Remove config from sys.modules, apply env_overrides via monkeypatch,
    then re-import config so the module-level code re-runs.
    Returns the freshly imported config module.
    """
    # Prevent load_dotenv from loading the real .env file
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)

    # Ensure a clean import each time
    monkeypatch.delitem(sys.modules, "config", raising=False)

    # Set all six required variables to valid defaults, then apply overrides
    defaults = {
        "GMAIL_ADDRESS": "bot@example.com",
        "GMAIL_APP_PASSWORD": "abcd-efgh-ijkl-mnop",
        "GROQ_API_KEY": "gsk_test1234567890",
        "MEETING_DURATION_MINUTES": "60",
        "POLL_INTERVAL_SECONDS": "30",
        "DEFAULT_TIMEZONE": "UTC",
    }
    for key, value in defaults.items():
        monkeypatch.setenv(key, value)
    for key, value in env_overrides.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)

    # Prevent load_dotenv from reading the real .env file during tests
    monkeypatch.setenv("DOTENV_PATH", "nonexistent_path_for_tests")

    return importlib.import_module("config")


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

class TestConfigHappyPath:
    def test_all_variables_loaded_with_correct_types(self, monkeypatch):
        cfg = _reload_config(monkeypatch, {})
        assert cfg.GMAIL_ADDRESS == "bot@example.com"
        assert cfg.GMAIL_APP_PASSWORD == "abcd-efgh-ijkl-mnop"
        assert cfg.GROQ_API_KEY == "gsk_test1234567890"
        assert cfg.MEETING_DURATION_MINUTES == 60
        assert cfg.POLL_INTERVAL_SECONDS == 30
        assert cfg.DEFAULT_TIMEZONE == "UTC"

    def test_integer_variables_are_int_not_str(self, monkeypatch):
        cfg = _reload_config(monkeypatch, {})
        assert isinstance(cfg.MEETING_DURATION_MINUTES, int)
        assert isinstance(cfg.POLL_INTERVAL_SECONDS, int)

    def test_string_variables_are_str(self, monkeypatch):
        cfg = _reload_config(monkeypatch, {})
        assert isinstance(cfg.GMAIL_ADDRESS, str)
        assert isinstance(cfg.GMAIL_APP_PASSWORD, str)
        assert isinstance(cfg.GROQ_API_KEY, str)
        assert isinstance(cfg.DEFAULT_TIMEZONE, str)


# ---------------------------------------------------------------------------
# Missing variable tests
# ---------------------------------------------------------------------------

class TestConfigMissingVariables:
    @pytest.mark.parametrize("missing_var", [
        "GMAIL_ADDRESS",
        "GMAIL_APP_PASSWORD",
        "GROQ_API_KEY",
        "MEETING_DURATION_MINUTES",
        "POLL_INTERVAL_SECONDS",
        "DEFAULT_TIMEZONE",
    ])
    def test_missing_variable_raises_value_error(self, monkeypatch, missing_var):
        with pytest.raises(ValueError) as exc_info:
            _reload_config(monkeypatch, {missing_var: None})
        assert missing_var in str(exc_info.value), (
            f"Error message should name the missing variable '{missing_var}'"
        )

    @pytest.mark.parametrize("empty_var", [
        "GMAIL_ADDRESS",
        "GMAIL_APP_PASSWORD",
        "GROQ_API_KEY",
        "DEFAULT_TIMEZONE",
    ])
    def test_empty_string_variable_raises_value_error(self, monkeypatch, empty_var):
        with pytest.raises(ValueError) as exc_info:
            _reload_config(monkeypatch, {empty_var: ""})
        assert empty_var in str(exc_info.value)

    def test_whitespace_only_variable_raises_value_error(self, monkeypatch):
        with pytest.raises(ValueError) as exc_info:
            _reload_config(monkeypatch, {"GMAIL_ADDRESS": "   "})
        assert "GMAIL_ADDRESS" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Invalid integer tests
# ---------------------------------------------------------------------------

class TestConfigInvalidIntegers:
    def test_non_integer_meeting_duration_raises(self, monkeypatch):
        with pytest.raises(ValueError) as exc_info:
            _reload_config(monkeypatch, {"MEETING_DURATION_MINUTES": "sixty"})
        assert "MEETING_DURATION_MINUTES" in str(exc_info.value)

    def test_non_integer_poll_interval_raises(self, monkeypatch):
        with pytest.raises(ValueError) as exc_info:
            _reload_config(monkeypatch, {"POLL_INTERVAL_SECONDS": "30.5"})
        assert "POLL_INTERVAL_SECONDS" in str(exc_info.value)

    def test_zero_meeting_duration_raises(self, monkeypatch):
        with pytest.raises(ValueError) as exc_info:
            _reload_config(monkeypatch, {"MEETING_DURATION_MINUTES": "0"})
        assert "MEETING_DURATION_MINUTES" in str(exc_info.value)

    def test_negative_meeting_duration_raises(self, monkeypatch):
        with pytest.raises(ValueError) as exc_info:
            _reload_config(monkeypatch, {"MEETING_DURATION_MINUTES": "-10"})
        assert "MEETING_DURATION_MINUTES" in str(exc_info.value)

    def test_zero_poll_interval_raises(self, monkeypatch):
        with pytest.raises(ValueError) as exc_info:
            _reload_config(monkeypatch, {"POLL_INTERVAL_SECONDS": "0"})
        assert "POLL_INTERVAL_SECONDS" in str(exc_info.value)

    def test_negative_poll_interval_raises(self, monkeypatch):
        with pytest.raises(ValueError) as exc_info:
            _reload_config(monkeypatch, {"POLL_INTERVAL_SECONDS": "-5"})
        assert "POLL_INTERVAL_SECONDS" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Import-graph smoke test
# ---------------------------------------------------------------------------

class TestPackageImports:
    def test_all_packages_import_cleanly(self):
        """Verify the full package tree is intact and importable."""
        import agent       # noqa: F401
        import tools       # noqa: F401
        import database    # noqa: F401
        import pipeline    # noqa: F401
