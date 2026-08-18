"""Tests for config env-parsing helpers.

conftest.py sets LLM_PROVIDER=ollama so importing config never fails for lack of
a provider key during the test session.
"""

from __future__ import annotations

import importlib

import pytest

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


class TestDatabaseUrlNormalization:
    """Managed providers hand out `postgres://`, which SQLAlchemy maps to
    psycopg2 — a driver this project does not install. Only psycopg 3 is
    present, so the URL has to name it explicitly."""

    @pytest.mark.parametrize(
        "given",
        [
            "postgres://user:pw@host:5432/db",
            "postgresql://user:pw@host:5432/db",
        ],
    )
    def test_bare_postgres_urls_get_the_psycopg_driver(self, given):
        normalized = config._normalize_database_url(given)
        assert normalized.startswith("postgresql+psycopg://")
        assert normalized.endswith("user:pw@host:5432/db")

    def test_an_explicit_driver_is_left_alone(self):
        url = "postgresql+psycopg://user:pw@host:5432/db"
        assert config._normalize_database_url(url) == url

    def test_sqlite_is_untouched(self):
        url = "sqlite:////tmp/researchit.db"
        assert config._normalize_database_url(url) == url

    def test_credentials_containing_the_scheme_are_not_mangled(self):
        # Only the leading scheme is rewritten, not an occurrence inside the
        # password or database name.
        url = "postgres://user:postgres://pw@host/db"
        assert (
            config._normalize_database_url(url)
            == "postgresql+psycopg://user:postgres://pw@host/db"
        )
