"""Shared pytest setup for the backend test suite.

Runs before any test module is imported, so importing ``config`` (which requires
a provider unless one is set) succeeds without real API keys, and env-dependent
defaults are deterministic.
"""

import os
import tempfile
from pathlib import Path

os.environ.setdefault("LLM_PROVIDER", "ollama")
os.environ.pop("CORS_ORIGINS", None)

# Point the suite at a scratch database before `config` is imported and freezes
# DATABASE_URL. Without this, tests would read and write the developer's real
# data/researchit.db.
_TEST_DB_DIR = tempfile.mkdtemp(prefix="researchit-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_TEST_DB_DIR) / 'test.db'}"

import pytest


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    """Build the schema once for tests that go through the real app engine.

    Repository tests use their own in-memory fixtures (tests/conftest.py); this
    covers the endpoint tests, which reach the engine via `session_scope`.
    """
    from db.models import Base
    from db.session import get_engine, reset_engine

    Base.metadata.create_all(get_engine())
    yield
    reset_engine()
