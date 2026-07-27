"""Unit tests for arXiv client helpers (no network)."""

from api.arxiv import _arxiv_transient_error


class TestArxivTransientError:
    def test_detects_rate_limit(self):
        assert _arxiv_transient_error(Exception("HTTP 429 Too Many Requests")) is True
        assert _arxiv_transient_error(Exception("rate limit exceeded")) is True

    def test_detects_service_unavailable(self):
        assert _arxiv_transient_error(Exception("HTTP 503 Service Unavailable")) is True
        assert _arxiv_transient_error(Exception("HTTP 502 Bad Gateway")) is True
        assert _arxiv_transient_error(Exception("HTTP 504 Gateway Timeout")) is True

    def test_detects_timeout(self):
        assert _arxiv_transient_error(Exception("Connection timed out")) is True
        assert _arxiv_transient_error(TimeoutError("request timeout")) is True

    def test_non_transient_errors(self):
        assert _arxiv_transient_error(Exception("404 Not Found")) is False
        assert _arxiv_transient_error(ValueError("invalid query")) is False
