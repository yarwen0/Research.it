"""Logging setup.

JSON in production so logs are queryable; human-readable colour locally, where
a log aggregator is not what you are reading them with.

Every line carries the request id that produced it. A research run emits
progress across several stages and threads, and without correlation the only
way to follow one run through the log is by timestamp — which interleaves the
moment two run at once.
"""

from __future__ import annotations

import logging
import sys

import structlog
from asgi_correlation_id import correlation_id
from structlog.typing import Processor

from config import LOG_JSON, LOG_LEVEL


def _add_request_id(_logger, _method_name, event_dict):
    """Attach the current request's correlation id, when there is one."""
    request_id = correlation_id.get()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging() -> None:
    """Route stdlib logging and structlog through one pipeline.

    Third-party libraries log through stdlib, so both have to end up in the
    same format — otherwise half the output is JSON and half is not.
    """
    # Annotated explicitly: the members have differing signatures, so the
    # inferred element type would collapse to `object`.
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _add_request_id,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if LOG_JSON
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # ProcessorFormatter lets records from `logging.getLogger(...)` — which is
    # what every module here and every dependency uses — run through the same
    # processors as structlog's own.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # Replace rather than append, so re-running this (tests, reload) does not
    # duplicate every line.
    root.handlers = [handler]
    root.setLevel(LOG_LEVEL)

    # uvicorn installs its own handlers; clear them so its output is not
    # emitted twice in two different formats.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True

    # Chatty at INFO and rarely what you are looking for.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_logger(name: str | None = None):
    """Return a structlog logger."""
    return structlog.stdlib.get_logger(name)
