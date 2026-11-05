"""Splitting a paper into retrievable passages.

PDF text arrives as lines: hard-wrapped, hyphenated at line ends, with section
headings on lines of their own and the bibliography near the end. Chunks are
built one section at a time — so each carries the heading it sits under — out
of whole sentences, with a short overlap so a statement that straddles a
boundary is still complete in one of the two chunks.

The bibliography is dropped. It is a long run of author names and venues that
looks similar to nearly any query about the field and answers none of them;
reference extraction already reads it separately. Appendices that follow it
are kept, since implementation details tend to live there.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from utils.sections import REFERENCE_HEADING

# About 300 tokens: comfortably inside the input limit of every embedding
# model the providers offer, and short enough that one chunk is about one
# thing.
TARGET_CHARS = 1200
OVERLAP_CHARS = 200
# Shorter than this, a "chunk" is a stray caption, page number or heading.
MIN_CHARS = 40

# "3 Method", "4.2 Ablation Study", "IV. EXPERIMENTS". A line, not a sentence:
# no full stop, comma or semicolon, so an enumerated list item in prose does
# not pass for one.
_NUMBERED_HEADING = re.compile(
    r"^(?:\d{1,2}(?:\.\d{1,2}){0,3}|[IVX]{1,4})\.?\s+[A-Z][A-Za-z0-9\-\u2013:&'()/ ]{1,80}$"
)
_NAMED_HEADING = re.compile(
    r"^(?:abstract|introduction|related\s+work|background|preliminaries|"
    r"method(?:s|ology)?|approach|experiments?|evaluation|results|discussion|"
    r"conclusions?|limitations|future\s+work|acknowledg(?:e)?ments?|"
    r"appendix|appendices|supplementary\s+material)$",
    re.IGNORECASE,
)
# What ends the bibliography: "Appendix ...", or a lettered section
# ("A Implementation Details", "B.1 More Results").
_APPENDIX_NAMED = re.compile(r"^(?:appendix|appendices|supplementary)\b", re.IGNORECASE)
_APPENDIX_LETTERED = re.compile(r"^[A-H](?:\.\d{1,2}){0,2}\.?\s+[A-Z][A-Za-z\-\u2013:&' ]{2,60}$")

# A wrapped sentence often ends a line on one of these; a heading never does.
_TRAILING_STOPWORDS = frozenset(
    {"a", "an", "and", "as", "at", "by", "for", "from", "in", "is", "of", "on", "or",
     "that", "the", "to", "we", "with"}
)

_MAX_HEADING_CHARS = 90

# A sentence ends at . ! or ? followed by whitespace and something that can
# start a sentence. Abbreviations ("et al. In") split too; at worst that moves
# a chunk boundary by a few words.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\[(\"'“])")


@dataclass(frozen=True)
class TextChunk:
    text: str
    section: str | None
    ordinal: int


def _is_heading(line: str) -> bool:
    if not line or len(line) > _MAX_HEADING_CHARS:
        return False
    if _NAMED_HEADING.match(line):
        return True
    if not _NUMBERED_HEADING.match(line):
        return False
    return line.rsplit(None, 1)[-1].lower() not in _TRAILING_STOPWORDS


def _is_appendix_heading(line: str) -> bool:
    if len(line) > _MAX_HEADING_CHARS:
        return False
    return bool(_APPENDIX_NAMED.match(line) or _APPENDIX_LETTERED.match(line))


def clean_text(text: str) -> str:
    """Undo the commonest PDF extraction artefacts, keeping line structure.

    NFKC folds ligatures ("ﬁ" → "fi") and full-width forms; soft hyphens are
    dropped; a word hyphenated across a line break is rejoined. Line breaks
    themselves stay, because headings are found line by line.
    """
    text = unicodedata.normalize("NFKC", text).replace("\u00ad", "")
    return re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", text)


def _drop_bibliography(lines: list[str]) -> list[str]:
    """Remove the last bibliography, up to any appendix that follows it."""
    starts = [i for i, line in enumerate(lines) if REFERENCE_HEADING.match(line)]
    if not starts:
        return lines
    start = starts[-1]
    end = next(
        (i for i in range(start + 1, len(lines)) if _is_appendix_heading(lines[i])),
        len(lines),
    )
    return lines[:start] + lines[end:]


def split_sections(text: str) -> list[tuple[str | None, str]]:
    """Split paper text into (heading, body) pairs, bibliography excluded.

    Text before the first heading — title, authors, sometimes the abstract —
    comes back under a heading of None.
    """
    lines = _drop_bibliography([line.strip() for line in clean_text(text).splitlines()])

    sections: list[tuple[str | None, str]] = []
    heading: str | None = None
    body: list[str] = []
    for line in lines:
        if _is_heading(line) or _is_appendix_heading(line):
            if body:
                sections.append((heading, " ".join(body)))
            heading, body = line, []
        elif line:
            body.append(line)
    if body:
        sections.append((heading, " ".join(body)))

    return [(name, re.sub(r"\s+", " ", content).strip()) for name, content in sections]


def _sentences(text: str, max_chars: int) -> Iterator[str]:
    """Sentences, with any longer than `max_chars` split at word boundaries."""
    for sentence in _SENTENCE_BOUNDARY.split(text):
        sentence = sentence.strip()
        while len(sentence) > max_chars:
            cut = sentence.rfind(" ", 0, max_chars)
            if cut <= 0:
                cut = max_chars
            yield sentence[:cut].strip()
            sentence = sentence[cut:].strip()
        if sentence:
            yield sentence


def _tail(sentences: list[str], overlap_chars: int) -> list[str]:
    """The trailing sentences that fit in the overlap budget."""
    tail: list[str] = []
    length = 0
    for sentence in reversed(sentences):
        length += len(sentence) + 1
        if length > overlap_chars:
            break
        tail.insert(0, sentence)
    return tail


def _pack(text: str, target_chars: int, overlap_chars: int) -> list[str]:
    """Greedily pack sentences into chunks of at most about `target_chars`.

    A chunk is at most target_chars plus the overlap carried from the one
    before it, since no single sentence piece exceeds target_chars.
    """
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for sentence in _sentences(text, target_chars):
        if current and length + 1 + len(sentence) > target_chars:
            chunks.append(" ".join(current))
            current = _tail(current, overlap_chars)
            length = len(" ".join(current))
        current.append(sentence)
        length += len(sentence) + (1 if length else 0)
    if current:
        chunks.append(" ".join(current))
    return chunks


def chunk_paper_text(
    text: str,
    *,
    target_chars: int = TARGET_CHARS,
    overlap_chars: int = OVERLAP_CHARS,
) -> list[TextChunk]:
    """The paper's body as ordered, section-labelled chunks."""
    chunks: list[TextChunk] = []
    for section, body in split_sections(text):
        for piece in _pack(body, target_chars, overlap_chars):
            if len(piece) >= MIN_CHARS:
                chunks.append(TextChunk(text=piece, section=section, ordinal=len(chunks)))
    return chunks


# Structured fields rendered into a paper's profile, in reading order.
_PROFILE_FIELDS = (
    ("methods", "Methods"),
    ("datasets", "Datasets"),
    ("limitations_explicit", "Stated limitations"),
    ("limitations_implied", "Implied limitations"),
    ("future_work", "Future work"),
)


def _fold(term: str) -> str:
    """Case and snake_case folded away, punctuation kept.

    Punctuation is what separates "Human3.6M" from "human36m" for a lexical
    search, so it has to count as a difference.
    """
    return " ".join(term.replace("_", " ").lower().split())


def _terms(value: Any) -> list[str]:
    """Readable terms from an extraction list or a normalized pair list.

    Normalized items are [canonical_term, original_text]. The original reads
    better; the canonical form is kept alongside when it differs, because it
    is the spelling other papers in the corpus were normalized to — which is
    what lets a lexical search for "human36m" find "Human3.6M".
    """
    if not isinstance(value, list):
        return []
    terms: list[str] = []
    for item in value:
        if isinstance(item, str):
            term = item.strip()
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            canonical, original = (str(part or "").strip() for part in item)
            term = original or canonical
            if canonical and original and _fold(canonical) != _fold(original):
                term = f"{original} ({canonical})"
        else:
            continue
        if term and term not in terms:
            terms.append(term)
    return terms


def render_profile(
    title: str,
    extraction: Mapping[str, Any] | None,
    normalized: Mapping[str, Any] | None,
) -> str:
    """A paper's structured record as a short passage of text.

    Prefers the normalized record, which carries the canonical terms, and
    falls back to the raw extraction field by field. Empty when there is
    nothing beyond the title, which a text chunk already says.
    """
    extraction = extraction or {}
    normalized = normalized or {}

    lines: list[str] = []
    problem = normalized.get("problem") or extraction.get("problem")
    if isinstance(problem, str) and problem.strip():
        lines.append(f"Problem: {problem.strip()}")
    for key, label in _PROFILE_FIELDS:
        terms = _terms(normalized.get(key)) or _terms(extraction.get(key))
        if terms:
            lines.append(f"{label}: {'; '.join(terms)}")

    if not lines:
        return ""
    return "\n".join([title.strip(), *lines] if title and title.strip() else lines)

