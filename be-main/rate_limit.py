"""Shared rate limiter.

Lives at the package root rather than inside `api/` so both `main` (which
registers the middleware and error handler) and the route modules (which apply
per-endpoint limits) can import it without a cycle.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from config import (
    RATE_LIMIT_DEFAULT,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_STORAGE_URI,
    TRUST_PROXY_HEADERS,
)


def client_identifier(request: Request) -> str:
    """Identify the caller for quota purposes.

    Behind a proxy every request appears to come from the proxy, so one caller
    would burn the quota for all of them. X-Forwarded-For fixes that, but it is
    client-supplied and spoofable, so it is only consulted when the deployment
    declares it is behind a proxy that overwrites the header.
    """
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Left-most entry is the original client; the rest are hops.
            return forwarded.split(",")[0].strip()

    return get_remote_address(request)


# headers_enabled surfaces X-RateLimit-* on responses, which is what lets a
# client back off intelligently. It carries one constraint: an endpoint wearing
# @limiter.limit must either return a Response subclass or declare a
# `response: Response` parameter, otherwise slowapi has nowhere to write the
# headers and raises at request time. Every decorated endpoint here returns a
# StreamingResponse or FileResponse, so the first form applies.
limiter = Limiter(
    key_func=client_identifier,
    storage_uri=RATE_LIMIT_STORAGE_URI,
    default_limits=[RATE_LIMIT_DEFAULT],
    enabled=RATE_LIMIT_ENABLED,
    headers_enabled=True,
)


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return 429 with the limit that tripped, in the app's error shape.

    The frontend surfaces `detail` for every other error, so matching that
    shape means a throttled request reads as a real message instead of an
    opaque failure.
    """
    headers = {}
    # slowapi stashes the window that tripped, but only on the decorator path —
    # the middleware's default limits do not set it, so this stays best-effort.
    view_limit = getattr(request.state, "view_rate_limit", None)
    if view_limit:
        try:
            headers["Retry-After"] = str(view_limit[0].get_expiry())
        except (AttributeError, IndexError, TypeError):
            pass

    return JSONResponse(
        status_code=429,
        content={
            "detail": (
                f"Rate limit exceeded: {exc.detail}. "
                "This endpoint is expensive; please wait before retrying."
            )
        },
        headers=headers,
    )
