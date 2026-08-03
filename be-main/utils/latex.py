"""LaTeX → PDF compilation.

The compile endpoint accepts arbitrary LaTeX from the browser, and LaTeX is a
programming language with filesystem access. Two things keep that contained:

* ``-no-shell-escape`` — refuses ``\\write18``, which would otherwise run
  shell commands. Most distributions default to this, but a local
  ``texmf.cnf`` can turn it back on, so it is passed explicitly.
* ``openin_any=p`` / ``openout_any=p`` — TeX's "paranoid" mode. Without it,
  ``\\input{/etc/passwd}`` happily pastes server files into the returned PDF.
  Paranoid mode confines reads and writes to the working directory and blocks
  dotfiles.

Everything runs in a throwaway temp directory that is deleted afterwards.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Generated reviews run to a few tens of KB; this is headroom, not a target.
MAX_LATEX_BYTES = 512 * 1024

_PASSES = 3
_PDFLATEX_TIMEOUT = 60
_BIBTEX_TIMEOUT = 30

# Homebrew's BasicTeX is not on PATH for GUI-launched processes on macOS.
_MACOS_TEX_BIN = "/Library/TeX/texbin"


class LatexUnavailableError(RuntimeError):
    """Raised when no TeX toolchain is installed on this server."""


class LatexCompilationError(RuntimeError):
    """Raised when the document could not be turned into a PDF."""


def _restricted_env() -> dict[str, str]:
    """Environment for TeX subprocesses, with file access locked down."""
    env = os.environ.copy()
    if os.path.exists(_MACOS_TEX_BIN):
        env["PATH"] = f"{_MACOS_TEX_BIN}:{env.get('PATH', '')}"

    # Paranoid mode — see the module docstring.
    env["openin_any"] = "p"
    env["openout_any"] = "p"
    env["shell_escape"] = "f"
    return env


def _run_pdflatex(tex_path: Path, workdir: Path, env: dict[str, str], pass_no: int) -> None:
    """Run one pdflatex pass. Non-zero exits are tolerated; a missing PDF is not.

    LaTeX routinely exits non-zero over recoverable warnings while still
    producing usable output, so the PDF's existence is the real success
    signal and is checked by the caller.
    """
    try:
        result = subprocess.run(
            [
                "pdflatex",
                "-no-shell-escape",
                "-interaction=nonstopmode",
                "-output-directory",
                str(workdir),
                str(tex_path),
            ],
            cwd=str(workdir),
            env=env,
            capture_output=True,
            text=True,
            timeout=_PDFLATEX_TIMEOUT,
            check=False,
        )
    except FileNotFoundError as exc:
        raise LatexUnavailableError(
            "pdflatex is not installed on this server"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise LatexCompilationError(
            f"LaTeX compilation timed out on pass {pass_no}"
        ) from exc

    if result.returncode != 0:
        logger.warning("pdflatex pass %s returned %s", pass_no, result.returncode)
        logger.debug("pdflatex stdout: %s", result.stdout)


def _run_bibtex(workdir: Path, env: dict[str, str]) -> None:
    """Resolve the bibliography. Absent or failing BibTeX is not fatal."""
    if not (workdir / "output.aux").exists():
        return

    try:
        result = subprocess.run(
            ["bibtex", "output"],
            cwd=str(workdir),
            env=env,
            capture_output=True,
            text=True,
            timeout=_BIBTEX_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("BibTeX timed out, continuing without bibliography")
        return
    except FileNotFoundError:
        logger.warning("bibtex not found, skipping bibliography processing")
        return

    # Undefined-citation warnings are routine and still produce a document.
    if result.returncode != 0:
        logger.warning("bibtex returned code %s", result.returncode)
        logger.debug("bibtex stdout: %s", result.stdout)


def _describe_failure(workdir: Path) -> str:
    """Pull a usable reason out of the TeX log, if there is one."""
    log_path = workdir / "output.log"
    if not log_path.exists():
        return "PDF generation failed"

    log_content = log_path.read_text(encoding="utf-8", errors="ignore")

    if "! Emergency stop" in log_content:
        return "PDF generation failed: emergency stop in LaTeX compilation"
    if "Fatal error" in log_content:
        return "PDF generation failed: fatal error in LaTeX compilation"

    # TeX prefixes real errors with "! ".
    for line in log_content.splitlines():
        if line.startswith("! "):
            return f"PDF generation failed: {line[2:].strip()}"

    return "PDF generation failed"


def compile_latex_to_pdf(latex_text: str) -> bytes:
    """Compile LaTeX source to PDF bytes.

    Runs pdflatex → bibtex → pdflatex → pdflatex, the sequence needed to
    resolve citations and cross-references.

    Raises:
        LatexCompilationError: on oversized input, timeout, or no PDF produced.
        LatexUnavailableError: when no TeX toolchain is installed.
    """
    size = len(latex_text.encode("utf-8"))
    if size > MAX_LATEX_BYTES:
        raise LatexCompilationError(
            f"LaTeX document is too large ({size} bytes, limit {MAX_LATEX_BYTES})"
        )

    env = _restricted_env()

    with tempfile.TemporaryDirectory() as temp_dir:
        workdir = Path(temp_dir)
        tex_path = workdir / "output.tex"
        tex_path.write_text(latex_text, encoding="utf-8")
        pdf_path = workdir / "output.pdf"

        for pass_no in range(1, _PASSES + 1):
            _run_pdflatex(tex_path, workdir, env, pass_no)
            # BibTeX needs the .aux from the first pass; the later passes then
            # pick up the generated .bbl and settle the cross-references.
            if pass_no == 1:
                _run_bibtex(workdir, env)

        if not pdf_path.exists():
            raise LatexCompilationError(_describe_failure(workdir))

        return pdf_path.read_bytes()
