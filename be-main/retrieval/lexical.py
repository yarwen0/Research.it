"""Okapi BM25 over a project's passages.

Dense embeddings blur exactly the tokens this domain turns on: dataset names,
metric acronyms, model identifiers, numbers. "Human3.6M", "MPJPE" and "0.0002"
are rare strings to an embedding model and exact matches to BM25, which is why
retrieval runs both.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

import numpy as np

# A token keeps internal dots and hyphens — "human3.6m", "gpt-4", "2d-3d" —
# so identifiers survive whole.
_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")

# Function words that carry no topic. Short on purpose: BM25's idf already
# discounts common words, and every word dropped here is one a question can no
# longer match on.
STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does",
        "for", "from", "how", "in", "is", "it", "its", "of", "on", "or",
        "that", "the", "their", "this", "to", "was", "were", "what", "when",
        "which", "who", "why", "with",
    }
)


def tokenize(text: str) -> list[str]:
    """Lowercased tokens, with each compound also split into its parts.

    "Human3.6M" yields "human3.6m", "human3", "6m" and "human36m", so the paper's
    spelling, a question's "Human 3.6M" and the normalizer's "human36m" all
    meet on at least one token.
    """
    tokens: list[str] = []
    for token in _TOKEN.findall(text.lower()):
        if token in STOPWORDS:
            continue
        tokens.append(token)
        if "." in token or "-" in token:
            parts = re.split(r"[.\-]", token)
            tokens.extend(part for part in parts if part and part not in STOPWORDS)
            tokens.append("".join(parts))
    return tokens


class BM25:
    """Okapi BM25 over a fixed set of documents.

    Uses the non-negative idf from Lucene, log(1 + (N - df + 0.5)/(df + 0.5)),
    so a term in most documents contributes little rather than negatively.
    """

    def __init__(
        self, documents: Sequence[Sequence[str]], *, k1: float = 1.5, b: float = 0.75
    ) -> None:
        self.k1 = k1
        self.b = b
        self._term_counts = [Counter(document) for document in documents]
        self._lengths = np.array([len(document) for document in documents], dtype=np.float64)
        self._average_length = float(self._lengths.mean()) if len(documents) else 0.0

        document_frequency: Counter[str] = Counter()
        for counts in self._term_counts:
            document_frequency.update(counts.keys())
        total = len(documents)
        self._idf = {
            term: math.log(1 + (total - df + 0.5) / (df + 0.5))
            for term, df in document_frequency.items()
        }

    def __len__(self) -> int:
        return len(self._term_counts)

    def scores(self, query: Sequence[str]) -> np.ndarray:
        """A score per document; zero where no query term occurs."""
        scores = np.zeros(len(self._term_counts))
        if not self._term_counts or self._average_length == 0:
            return scores
        normalizer = self.k1 * (1 - self.b + self.b * self._lengths / self._average_length)
        for term in set(query):
            idf = self._idf.get(term)
            if idf is None:
                continue
            frequencies = np.array([counts.get(term, 0) for counts in self._term_counts])
            scores += idf * frequencies * (self.k1 + 1) / (frequencies + normalizer)
        return scores

    def top(self, query: Sequence[str], k: int) -> list[tuple[int, float]]:
        """Indices and scores of the best `k` matching documents.

        Documents sharing no term with the query are not matches at all, so
        they are left out instead of padding the list with zeros.
        """
        scores = self.scores(query)
        order = np.argsort(-scores, kind="stable")[:k]
        return [(int(index), float(scores[index])) for index in order if scores[index] > 0]
