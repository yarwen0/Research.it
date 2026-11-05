"""Tests for rate-limit client identification and the 429 response shape."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

import rate_limit
from rate_limit import client_identifier, limiter, rate_limit_handler


def _request_with(headers: dict[str, str], client_host: str = "10.0.0.1") -> Request:
    """Build a bare ASGI scope — enough for the key function, no server needed."""
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": raw_headers,
            "client": (client_host, 12345),
        }
    )


class TestClientIdentifier:
    def test_uses_peer_address_by_default(self, monkeypatch):
        # X-Forwarded-For is client-supplied, so an untrusted deployment must
        # ignore it — otherwise every caller can forge a fresh quota bucket.
        monkeypatch.setattr(rate_limit, "TRUST_PROXY_HEADERS", False)
        request = _request_with({"x-forwarded-for": "1.2.3.4"}, client_host="10.0.0.1")
        assert client_identifier(request) == "10.0.0.1"

    def test_honours_forwarded_header_when_trusted(self, monkeypatch):
        monkeypatch.setattr(rate_limit, "TRUST_PROXY_HEADERS", True)
        request = _request_with({"x-forwarded-for": "1.2.3.4"}, client_host="10.0.0.1")
        assert client_identifier(request) == "1.2.3.4"

    def test_takes_the_original_client_from_a_hop_chain(self, monkeypatch):
        monkeypatch.setattr(rate_limit, "TRUST_PROXY_HEADERS", True)
        request = _request_with({"x-forwarded-for": "1.2.3.4, 10.0.0.9, 10.0.0.8"})
        assert client_identifier(request) == "1.2.3.4"

    def test_falls_back_when_trusted_but_header_absent(self, monkeypatch):
        monkeypatch.setattr(rate_limit, "TRUST_PROXY_HEADERS", True)
        request = _request_with({}, client_host="10.0.0.1")
        assert client_identifier(request) == "10.0.0.1"


class TestAppendingProxies:
    """Proxies that append to X-Forwarded-For, like Google's front end.

    The client controls everything left of what the trusted proxy appended, so
    keying on the left-most entry would let it mint a fresh bucket per request.
    """

    @pytest.fixture(autouse=True)
    def one_trusted_hop(self, monkeypatch):
        monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 1)
        monkeypatch.setattr(rate_limit, "TRUST_PROXY_HEADERS", False)

    def test_uses_the_address_the_proxy_appended(self):
        request = _request_with({"x-forwarded-for": "6.6.6.6, 203.0.113.7"})
        assert client_identifier(request) == "203.0.113.7"

    def test_a_forged_entry_cannot_change_the_bucket(self):
        honest = _request_with({"x-forwarded-for": "203.0.113.7"})
        forged = _request_with({"x-forwarded-for": "1.1.1.1, 2.2.2.2, 203.0.113.7"})
        assert client_identifier(honest) == client_identifier(forged) == "203.0.113.7"

    def test_counts_hops_from_the_right(self, monkeypatch):
        # A load balancer in front of the proxy appends its own address too.
        monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 2)
        request = _request_with({"x-forwarded-for": "6.6.6.6, 203.0.113.7, 10.1.1.1"})
        assert client_identifier(request) == "203.0.113.7"

    def test_too_few_entries_falls_back_to_the_peer(self, monkeypatch):
        monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_HOPS", 2)
        request = _request_with({"x-forwarded-for": "203.0.113.7"}, client_host="10.0.0.1")
        assert client_identifier(request) == "10.0.0.1"

    def test_takes_precedence_over_trusting_the_left_most(self, monkeypatch):
        monkeypatch.setattr(rate_limit, "TRUST_PROXY_HEADERS", True)
        request = _request_with({"x-forwarded-for": "6.6.6.6, 203.0.113.7"})
        assert client_identifier(request) == "203.0.113.7"


@pytest.fixture
def throttled_app():
    """A minimal app with a 2/minute endpoint, isolated from the real routes."""
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)

    # Returns a Response subclass, matching every decorated endpoint in the
    # real app — headers_enabled has nowhere to write X-RateLimit-* otherwise.
    @app.get("/cheap")
    @limiter.limit("2/minute")
    async def cheap(request: Request):
        return JSONResponse({"ok": True})

    limiter.reset()
    yield TestClient(app)
    limiter.reset()


class TestThrottling:
    def test_allows_requests_within_the_budget(self, throttled_app):
        assert throttled_app.get("/cheap").status_code == 200
        assert throttled_app.get("/cheap").status_code == 200

    def test_rejects_once_the_budget_is_spent(self, throttled_app):
        throttled_app.get("/cheap")
        throttled_app.get("/cheap")
        response = throttled_app.get("/cheap")
        assert response.status_code == 429

    def test_429_uses_the_apps_error_shape(self, throttled_app):
        for _ in range(3):
            response = throttled_app.get("/cheap")

        # The frontend renders `detail` for every other failure; matching it
        # means a throttled call surfaces a readable message.
        assert "detail" in response.json()
        assert "Rate limit exceeded" in response.json()["detail"]


@pytest.mark.parametrize(
    ("module_name", "endpoint_name"),
    [
        ("api.api", "research_endpoint"),
        ("api.api", "create_review_endpoint"),
        ("api.api", "compile_latex_endpoint"),
        ("api.retrieval", "ask_endpoint"),
    ],
)
def test_decorated_api_endpoints_satisfy_header_injection(module_name, endpoint_name):
    """headers_enabled needs somewhere to write X-RateLimit-* headers.

    slowapi injects into the returned value when it is a Response, and falls
    back to a `response: Response` parameter otherwise — a decorated endpoint
    satisfying neither raises at request time, not at import time, so nothing
    else in the suite would catch the regression.
    """
    import importlib
    import inspect

    endpoint = getattr(importlib.import_module(module_name), endpoint_name)
    params = inspect.signature(endpoint).parameters
    assert "request" in params, f"{endpoint_name} needs a `request` parameter"

    # functools.wraps keeps the undecorated function reachable.
    source = inspect.getsource(endpoint.__wrapped__)
    returns_a_response = "return StreamingResponse(" in source or "return FileResponse(" in source

    assert returns_a_response or "response" in params, (
        f"{endpoint_name} must return a Response subclass or declare a "
        "`response: Response` parameter"
    )


def test_expensive_endpoints_are_capped_tighter_than_the_default():
    import config

    def per_hour(limit: str) -> float:
        count, _, window = limit.partition("/")
        per = {"second": 1 / 3600, "minute": 1 / 60, "hour": 1, "day": 24}[window]
        return int(count) / per

    assert per_hour(config.RATE_LIMIT_RESEARCH) < per_hour(config.RATE_LIMIT_DEFAULT)
    assert per_hour(config.RATE_LIMIT_REVIEW) < per_hour(config.RATE_LIMIT_DEFAULT)
    assert per_hour(config.RATE_LIMIT_ASK) < per_hour(config.RATE_LIMIT_DEFAULT)
