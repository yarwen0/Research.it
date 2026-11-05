"""Recognising the structure of paper text extracted from a PDF.

Shared by reference extraction, which wants only the bibliography, and by
retrieval chunking, which wants everything except it.
"""

from __future__ import annotations

import re

# A line that is only a bibliography heading — "References", "7. References",
# "**Bibliography**", LREC's "Bibliographical References" — and nothing else,
# so the word in running prose does not count.
REFERENCE_HEADING = re.compile(
    r"^\s*\*{0,2}(?:\d+\.?\s*)?"
    r"((?:bibliographical\s+)?references|bibliography|works\s+cited|literature\s+cited)"
    r"\*{0,2}\s*$",
    re.IGNORECASE | re.MULTILINE,
)
