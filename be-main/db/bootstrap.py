"""Schema bootstrap.

Applies migrations at startup so `git clone && make dev` works without a
separate migration step. Guarded by AUTO_MIGRATE for deployments that would
rather run migrations as an explicit release step — with several workers
starting at once, only one should be driving DDL.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic.config import Config

from alembic import command
from config import AUTO_MIGRATE, DATABASE_URL

logger = logging.getLogger(__name__)

_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def _alembic_config() -> Config:
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("script_location", str(_ALEMBIC_INI.parent / "alembic"))
    # ConfigParser reads % as interpolation; passwords in URLs contain them.
    config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))
    return config


def upgrade_to_head() -> None:
    """Run `alembic upgrade head` in-process."""
    command.upgrade(_alembic_config(), "head")


def ensure_schema() -> None:
    """Bring the database up to date, unless disabled.

    Failures are logged rather than raised: a health endpoint that answers is
    more useful for diagnosis than a container that will not boot.
    """
    if not AUTO_MIGRATE:
        logger.info("AUTO_MIGRATE is off; skipping schema check")
        return

    try:
        upgrade_to_head()
        logger.info("Database schema is up to date")
    except Exception:
        logger.exception("Failed to apply database migrations")
