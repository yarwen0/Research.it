"""Shared pytest setup for the backend test suite.

Runs before any test module is imported, so importing ``config`` (which requires
a provider unless one is set) succeeds without real API keys, and env-dependent
defaults are deterministic.
"""

import os

os.environ.setdefault("LLM_PROVIDER", "ollama")
os.environ.pop("CORS_ORIGINS", None)
