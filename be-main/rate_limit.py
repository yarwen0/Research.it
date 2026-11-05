"""Shared rate limiter.

Lives at the package root rather than inside `api/` so both `main` (which
registers the middleware and error handler) and the route modules (which apply
per-endpoint limits) can import it without a cycle.
"""

from __future__ import annotations

import contextlib

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
    TRUSTED_PROXY_HOPS,
)


def client_identifier(request: Request) -> str:
    """Identify the caller for quota purposes.

    Behind a proxy every request appears to come from the proxy, so one caller
    would burn the quota for all of them. X-Forwarded-For fixes that, but it is
    client-supplied and spoofable, so it is only consulted when the deployment
    declares what sits in front of it:

    * TRUSTED_PROXY_HOPS=n — n proxies that append to the header. The caller is
      the n-th entry from the right; whatever is left of it the client wrote
      itself. Reading the left-most entry here would let any caller pick its
      own quota bucket.
    * TRUST_PROXY_HEADERS — a proxy that overwrites the header, leaving the
      original client left-most.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and TRUSTED_PROXY_HOPS:
        hops = [entry.strip() for entry in forwarded.split(",") if entry.strip()]
        # Fewer entries than trusted proxies means the header did not come
        # through them; fall back to the peer rather than guess.
        if len(hops) >= TRUSTED_PROXY_HOPS:
            return hops[-TRUSTED_PROXY_HOPS]
    elif forwarded and TRUST_PROXY_HEADERS:
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
        with contextlib.suppress(AttributeError, IndexError, TypeError):
            headers["Retry-After"] = str(view_limit[0].get_expiry())

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
