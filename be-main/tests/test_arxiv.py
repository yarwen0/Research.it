"""Unit tests for arXiv client helpers (no network)."""

from api.arxiv import REFERENCES_MAX_CHARS, ArxivClient, _arxiv_transient_error


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


class TestReferencesSection:
    """The slice handed to the reference extractor.

    Sending the whole paper instead used to exceed the LLM request timeout,
    which returned no references at all and left the citation graph edgeless.
    """

    def test_starts_at_the_references_heading(self):
        text = "Intro citing references in prose.\n\nReferences\n[1] A. Author. A paper. 2020."
        section = ArxivClient._references_section(text)
        assert section.startswith("[1] A. Author.")

    def test_prefers_the_last_heading(self):
        # "References" can appear in a table of contents as well as the real section.
        text = "References\n\nbody text\n\nBibliography\n[9] Z. Last. Final work. 2024."
        assert ArxivClient._references_section(text).startswith("[9] Z. Last.")

    def test_accepts_numbered_and_uppercase_headings(self):
        for heading in ("REFERENCES", "7. References", "Works Cited"):
            text = f"body\n\n{heading}\n[1] Cited work. 2021."
            assert ArxivClient._references_section(text) == "[1] Cited work. 2021."

    def test_falls_back_to_the_tail_when_no_heading(self):
        text = "x" * (REFERENCES_MAX_CHARS + 5_000) + "TAIL"
        section = ArxivClient._references_section(text)
        assert section.endswith("TAIL")
        assert len(section) <= REFERENCES_MAX_CHARS

    def test_caps_an_oversized_section(self):
        text = "References\n" + "y" * (REFERENCES_MAX_CHARS * 3)
        assert len(ArxivClient._references_section(text)) <= REFERENCES_MAX_CHARS
