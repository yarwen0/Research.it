"""Normalization for LLM-generated literature reviews.

The review prompt asks for a specific, self-contained shape: BibTeX entries in
a ``filecontents`` block *before* ``\\documentclass``, ``natbib`` for citations,
and ``\\bibliographystyle{plainnat}``. That shape compiles under the
pdflatex → bibtex → pdflatex → pdflatex sequence in :mod:`utils.latex`.

Models do not reliably follow it. A local qwen2.5:7b run produced a review that
deviated three ways at once: it loaded ``biblatex`` instead of ``natbib``, used
the ``plain`` style, and dumped the BibTeX entries after ``\\end{document}``
behind a ``% references.bib`` comment. Each is independently fatal —
``biblatex.sty`` is absent from a minimal TeX install, and anything after
``\\end{document}`` is never read, so ``references.bib`` is never written and
every ``\\cite`` resolves to nothing even where the package does exist.

Rather than hope a stronger model complies, the generated document is repaired
into the documented shape before it is stored. Prompt compliance is a quality
signal; it is not something the compile step can depend on.
"""

from __future__ import annotations

import re

__all__ = ["normalize_review_latex"]

# A BibTeX entry opener at the start of a line: @article{key,
_ENTRY_START = re.compile(r"^[ \t]*@(\w+)\s*\{", re.MULTILINE)

_DOCUMENTCLASS = re.compile(r"^[ \t]*\\documentclass.*$", re.MULTILINE)
_END_DOCUMENT = re.compile(r"\\end\{document\}")

_BIBLATEX_PKG = re.compile(r"^[ \t]*\\usepackage(?:\[[^\]]*\])?\{biblatex\}[ \t]*\n?", re.MULTILINE)
_ADDBIBRESOURCE = re.compile(r"^[ \t]*\\addbibresource\{[^}]*\}[ \t]*\n?", re.MULTILINE)
_PRINTBIBLIOGRAPHY = re.compile(r"^[ \t]*\\printbibliography(?:\[[^\]]*\])?[ \t]*$", re.MULTILINE)

_NATBIB_PKG = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{natbib\}")
_BIBSTYLE = re.compile(r"\\bibliographystyle\{([^}]*)\}")
_BIBLIOGRAPHY = re.compile(r"\\bibliography\{([^}]*)\}")
_FILECONTENTS = re.compile(r"\\begin\{filecontents\*?\}")

# natbib ships plainnat; plain works but loses author-year support, and the
# prompt asks for plainnat, so an unqualified "plain" is treated as drift.
_STYLE_REPLACEMENTS = {"plain": "plainnat", "unsrt": "unsrtnat", "abbrv": "abbrvnat"}

_BIB_OPEN = "\\begin{filecontents*}{references.bib}\n"
_BIB_CLOSE = "\n\\end{filecontents*}\n"


def _entry_span(text: str, brace_pos: int) -> int | None:
    """Return the index just past the entry whose opening brace is at `brace_pos`.

    BibTeX values nest braces, so the end cannot be found by searching for the
    next ``}``. Returns None when the entry is unterminated.
    """
    depth = 0
    for i in range(brace_pos, len(text)):
        char = text[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def _extract_bib_entries(text: str) -> tuple[str, list[str]]:
    """Pull loose BibTeX entries out of `text`.

    Only entries outside a ``filecontents`` block are taken — one that is
    already in the right place is left alone.
    """
    if _FILECONTENTS.search(text):
        return text, []

    entries: list[str] = []
    spans: list[tuple[int, int]] = []
    for match in _ENTRY_START.finditer(text):
        end = _entry_span(text, match.end() - 1)
        if end is None:
            continue
        entries.append(text[match.start():end].strip())
        spans.append((match.start(), end))

    for start, end in reversed(spans):
        text = text[:start] + text[end:]
    return text, entries


def _strip_trailing_matter(text: str) -> str:
    """Drop anything after ``\\end{document}``; TeX never reads it."""
    matches = list(_END_DOCUMENT.finditer(text))
    if not matches:
        return text
    return text[: matches[-1].end()] + "\n"


def normalize_review_latex(text: str) -> str:
    """Repair a generated review into the shape the compiler expects.

    Idempotent: a document already in the documented shape is returned
    unchanged apart from whitespace at the very end.
    """
    if not text or not text.strip():
        return text

    text, entries = _extract_bib_entries(text)

    # biblatex needs biber and is absent from minimal TeX installs; natbib is
    # what the prompt asks for and what the bibtex-based compile step runs.
    had_biblatex = bool(_BIBLATEX_PKG.search(text))
    text = _BIBLATEX_PKG.sub("", text)
    text = _ADDBIBRESOURCE.sub("", text)
    text = _PRINTBIBLIOGRAPHY.sub(
        "\\\\bibliographystyle{plainnat}\n\\\\bibliography{references}", text
    )

    if had_biblatex and not _NATBIB_PKG.search(text):
        text = _DOCUMENTCLASS.sub(lambda m: m.group(0) + "\n\\usepackage{natbib}", text, count=1)

    def _fix_style(match: re.Match[str]) -> str:
        style = match.group(1).strip()
        return f"\\bibliographystyle{{{_STYLE_REPLACEMENTS.get(style, style)}}}"

    text = _BIBSTYLE.sub(_fix_style, text)
    text = _strip_trailing_matter(text)

    if entries:
        # filecontents must precede \documentclass so the .bib exists by the
        # time bibtex runs.
        block = _BIB_OPEN + "\n\n".join(entries) + _BIB_CLOSE
        if _DOCUMENTCLASS.search(text):
            text = _DOCUMENTCLASS.sub(lambda m: block + m.group(0), text, count=1)
        else:
            text = block + text

        # A bibliography the document never prints is entries wasted.
        if not _BIBLIOGRAPHY.search(text):
            addition = ""
            if not _BIBSTYLE.search(text):
                addition += "\\bibliographystyle{plainnat}\n"
            addition += "\\bibliography{references}\n"
            text = _END_DOCUMENT.sub(lambda m: addition + m.group(0), text, count=1)

    return text
