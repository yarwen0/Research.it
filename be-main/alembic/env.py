"""Alembic environment.

The database URL comes from the app's own config rather than alembic.ini, so
there is one source of truth and `alembic upgrade head` always targets whatever
DATABASE_URL points at.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make the backend package importable when alembic runs from be-main/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DATABASE_URL
from db.models import Base

config = context.config

# ConfigParser treats % as interpolation, and passwords in URLs contain them.
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

# Only when alembic is driving. Running migrations in-process at app startup
# would otherwise have fileConfig tear down the handlers the app just
# installed, and every log line afterwards reverts to the default format.
if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _is_sqlite() -> bool:
    return DATABASE_URL.startswith("sqlite")


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        # SQLite cannot ALTER most things in place; batch mode rebuilds the
        # table instead. A no-op on Postgres, required on SQLite.
        render_as_batch=_is_sqlite(),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and apply migrations."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=_is_sqlite(),
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
