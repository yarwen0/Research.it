"""Deterministic stand-ins shared across test modules."""

from __future__ import annotations

import re
import zlib
from collections.abc import Sequence

import numpy as np


class HashingEmbedder:
    """Embeds text as a hashed bag of words.

    Similarity follows word overlap, which is enough for a retrieval test to
    mean something — a query shares words with the passage it should find —
    while staying offline and identical across processes (crc32, not the
    per-process salted `hash()`).
    """

    def __init__(self, dim: int = 256, model_id: str = "hashing-test-embedder") -> None:
        self.dim = dim
        self.model_id = model_id
        self.document_batches: list[list[str]] = []
        self.queries: list[str] = []

    def vector(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float32)
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            vector[zlib.crc32(token.encode()) % self.dim] += 1.0
        return vector

    def embed_documents(self, texts: Sequence[str]) -> list[np.ndarray]:
        self.document_batches.append(list(texts))
        return [self.vector(text) for text in texts]

    def embed_query(self, text: str) -> np.ndarray:
        self.queries.append(text)
        return self.vector(text)
