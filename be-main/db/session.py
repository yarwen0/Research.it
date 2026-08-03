"""Engine and session management.

The engine is created lazily so importing `db` never touches the filesystem or
opens a socket — which keeps `config` importable in tests and lets Alembic
drive the URL itself.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from config import DATABASE_URL, DB_ECHO, DB_MAX_OVERFLOW, DB_POOL_SIZE

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _create_engine(url: str) -> Engine:
    if _is_sqlite(url):
        # The pipeline writes from executor threads, so the connection cannot
        # be pinned to the creating thread.
        engine = create_engine(
            url,
            echo=DB_ECHO,
            future=True,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            # WAL lets readers proceed during a write, which matters because a
            # research run holds a write transaction while the graph is built.
            cursor.execute("PRAGMA journal_mode=WAL")
            # Off by default in SQLite, and the schema leans on cascades.
            cursor.execute("PRAGMA foreign_keys=ON")
            # Wait rather than fail instantly when another thread holds a lock.
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        return engine

    return create_engine(
        url,
        echo=DB_ECHO,
        future=True,
        pool_size=DB_POOL_SIZE,
        max_overflow=DB_MAX_OVERFLOW,
        # Recycle before a proxy or Postgres idle timeout kills the socket,
        # otherwise the first query after a quiet period fails.
        pool_pre_ping=True,
        pool_recycle=1800,
    )


def init_engine(url: str | None = None) -> Engine:
    """Create the engine and session factory. Idempotent."""
    global _engine, _session_factory

    if _engine is not None and url is None:
        return _engine

    target = url or DATABASE_URL

    if _is_sqlite(target):
        # Ensure the parent directory exists before SQLite tries to open a file
        # inside it, otherwise the failure is an opaque "unable to open".
        path = target.replace("sqlite:///", "", 1)
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)

    _engine = _create_engine(target)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    logger.info("Database engine initialised (%s)", _engine.dialect.name)
    return _engine


def get_engine() -> Engine:
    """Return the engine, creating it on first use."""
    return _engine if _engine is not None else init_engine()


def get_session() -> Session:
    """Return a new session. The caller owns closing it."""
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None  # narrowed by init_engine
    return _session_factory()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Session bound to a transaction: commit on success, roll back on error."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Drop the cached engine. Used by tests to swap in a fresh database."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
