"""Tests for config env-parsing helpers.

conftest.py sets LLM_PROVIDER=ollama so importing config never fails for lack of
a provider key during the test session.
"""

from __future__ import annotations

import config
from config import _maybe, _truthy


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
