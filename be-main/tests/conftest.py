"""Database fixtures.

Each test gets a fresh in-memory SQLite database, so nothing leaks between
tests and the suite still needs no services installed.
"""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import Base


@pytest.fixture(scope="session")
def _span_exporter() -> InMemorySpanExporter:
    # The global tracer provider can be installed once per process, so every
    # test that inspects spans shares this one.
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


@pytest.fixture
def spans(_span_exporter: InMemorySpanExporter) -> InMemorySpanExporter:
    """Spans finished during the test, and only those."""
    _span_exporter.clear()
    return _span_exporter


@pytest.fixture
def engine():
    # StaticPool keeps every connection pointed at the same in-memory database;
    # the default pool would hand out a fresh, empty one per connection.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        # Off by default in SQLite; the cascade assertions depend on it.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine) -> Session:
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as session:
        yield session
