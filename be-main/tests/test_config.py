"""Tests for config env-parsing helpers.

conftest.py sets LLM_PROVIDER=ollama so importing config never fails for lack of
a provider key during the test session.
"""

from __future__ import annotations

import importlib

import config
from config import _int, _maybe, _truthy


class TestTruthy:
    def test_truthy_values(self):
        for value in ("1", "true", "TRUE", "Yes", "on"):
            assert _truthy(value) is True

    def test_falsy_values(self):
        for value in ("0", "false", "no", "off", "", None, "  "):
            assert _truthy(value) is False


class TestMaybe:
    def test_returns_stripped_value(self, monkeypatch):
        monkeypatch.setenv("RESEARCHIT_TEST_VAR", "  hello  ")
        assert _maybe("RESEARCHIT_TEST_VAR") == "hello"

    def test_blank_becomes_none(self, monkeypatch):
        monkeypatch.setenv("RESEARCHIT_TEST_VAR", "   ")
        assert _maybe("RESEARCHIT_TEST_VAR") is None

    def test_unset_is_none(self, monkeypatch):
        monkeypatch.delenv("RESEARCHIT_TEST_VAR", raising=False)
        assert _maybe("RESEARCHIT_TEST_VAR") is None


def test_cors_origins_defaults_to_wildcard():
    # No CORS_ORIGINS set in the test environment.
    assert config.CORS_ORIGINS == ["*"]


def test_wildcard_origins_disable_credentialed_cors():
    # Wildcard origin + credentials is the combination Starlette resolves by
    # echoing back any Origin, so credentials must be off here.
    assert config.CORS_ORIGINS == ["*"]
    assert config.CORS_ALLOW_CREDENTIALS is False


def test_explicit_origins_allow_credentialed_cors(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com,https://example.com")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.CORS_ORIGINS == [
            "https://app.example.com",
            "https://example.com",
        ]
        assert reloaded.CORS_ALLOW_CREDENTIALS is True
    finally:
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        importlib.reload(config)


class TestInt:
    def test_returns_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("RESEARCHIT_TEST_INT", raising=False)
        assert _int("RESEARCHIT_TEST_INT", 42) == 42

    def test_parses_valid_integer(self, monkeypatch):
        monkeypatch.setenv("RESEARCHIT_TEST_INT", "7")
        assert _int("RESEARCHIT_TEST_INT", 42) == 7

    def test_invalid_value_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("RESEARCHIT_TEST_INT", "not-a-number")
        assert _int("RESEARCHIT_TEST_INT", 42) == 42


def test_host_and_port_defaults():
    assert config.HOST == "0.0.0.0"
    assert config.PORT == 8000
