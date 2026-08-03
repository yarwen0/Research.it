"""Tests for LaTeX compilation hardening.

These exercise the subprocess wiring, not a real TeX install — pdflatex is
stubbed so the suite stays hermetic.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from utils import latex as latex_module
from utils.latex import (
    MAX_LATEX_BYTES,
    LatexCompilationError,
    LatexUnavailableError,
    _describe_failure,
    _restricted_env,
    compile_latex_to_pdf,
)


class TestRestrictedEnv:
    def test_enables_paranoid_file_access(self):
        env = _restricted_env()
        # Paranoid mode is what stops \input{/etc/passwd} leaking server files
        # into the returned PDF.
        assert env["openin_any"] == "p"
        assert env["openout_any"] == "p"

    def test_disables_shell_escape(self):
        assert _restricted_env()["shell_escape"] == "f"


class TestCompileInvocation:
    """pdflatex must never be invoked in a way that permits \\write18."""

    @staticmethod
    def _fake_run(recorder, *, write_pdf: bool = True):
        def run(cmd, **kwargs):
            recorder.append((cmd, kwargs))
            if write_pdf and cmd[0] == "pdflatex":
                Path(kwargs["cwd"], "output.pdf").write_bytes(b"%PDF-1.4 fake")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        return run

    def test_passes_no_shell_escape_on_every_pass(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(subprocess, "run", self._fake_run(calls))

        compile_latex_to_pdf(r"\documentclass{article}\begin{document}hi\end{document}")

        pdflatex_calls = [cmd for cmd, _ in calls if cmd[0] == "pdflatex"]
        assert len(pdflatex_calls) == 3
        for cmd in pdflatex_calls:
            assert "-no-shell-escape" in cmd

    def test_runs_with_restricted_environment(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(subprocess, "run", self._fake_run(calls))

        compile_latex_to_pdf(r"\documentclass{article}\begin{document}hi\end{document}")

        for _, kwargs in calls:
            assert kwargs["env"]["openin_any"] == "p"
            assert kwargs["env"]["openout_any"] == "p"

    def test_returns_pdf_bytes(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", self._fake_run([]))
        assert compile_latex_to_pdf(r"\documentclass{article}").startswith(b"%PDF")

    def test_missing_pdflatex_reports_unavailable(self, monkeypatch):
        def run(cmd, **kwargs):
            raise FileNotFoundError(cmd[0])

        monkeypatch.setattr(subprocess, "run", run)

        with pytest.raises(LatexUnavailableError):
            compile_latex_to_pdf(r"\documentclass{article}")

    def test_timeout_becomes_compilation_error(self, monkeypatch):
        def run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, timeout=60)

        monkeypatch.setattr(subprocess, "run", run)

        with pytest.raises(LatexCompilationError, match="timed out"):
            compile_latex_to_pdf(r"\documentclass{article}")

    def test_no_pdf_produced_is_an_error(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", self._fake_run([], write_pdf=False))

        with pytest.raises(LatexCompilationError, match="PDF generation failed"):
            compile_latex_to_pdf(r"\documentclass{article}")

    def test_rejects_oversized_document(self):
        oversized = "x" * (MAX_LATEX_BYTES + 1)
        with pytest.raises(LatexCompilationError, match="too large"):
            compile_latex_to_pdf(oversized)

    def test_oversized_check_runs_before_any_subprocess(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(subprocess, "run", self._fake_run(calls))

        with pytest.raises(LatexCompilationError):
            compile_latex_to_pdf("x" * (MAX_LATEX_BYTES + 1))

        assert calls == []


class TestDescribeFailure:
    def test_reports_emergency_stop(self, tmp_path):
        (tmp_path / "output.log").write_text("! Emergency stop\n", encoding="utf-8")
        assert "emergency stop" in _describe_failure(tmp_path)

    def test_reports_fatal_error(self, tmp_path):
        (tmp_path / "output.log").write_text("Fatal error occurred\n", encoding="utf-8")
        assert "fatal error" in _describe_failure(tmp_path)

    def test_surfaces_first_tex_error_line(self, tmp_path):
        (tmp_path / "output.log").write_text(
            "This is pdfTeX\n! Undefined control sequence.\n", encoding="utf-8"
        )
        assert "Undefined control sequence." in _describe_failure(tmp_path)

    def test_falls_back_without_a_log(self, tmp_path):
        assert _describe_failure(tmp_path) == "PDF generation failed"


def test_module_declares_a_sane_size_limit():
    # Guards against a future edit turning the cap into something unbounded.
    assert 0 < MAX_LATEX_BYTES <= 5 * 1024 * 1024
    assert latex_module._PASSES == 3
