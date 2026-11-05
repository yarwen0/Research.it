"""Deterministic stand-ins shared across test modules."""

from __future__ import annotations

import re
import zlib
from collections.abc import Sequence

import numpy as np

from telemetry import track_llm_call


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


class FakeLLMClient:
    """A provider client with scripted chat replies and hashed embeddings.

    Chat calls go through `track_llm_call` exactly as a real client's do, so
    usage attribution is exercised too. With no scripted reply left, it
    declines, which is the safe answer.
    """

    def __init__(self, replies: Sequence[str] = (), *, embedder: HashingEmbedder | None = None) -> None:
        self.replies = list(replies)
        self.requests: list[tuple[list[dict], dict | None]] = []
        self.embedder = embedder or HashingEmbedder()
        self.embedding_model_id = self.embedder.model_id

    def chat_completion(self, messages, *, response_format):
        self.requests.append((messages, response_format))
        with track_llm_call("fake", "fake-chat", "chat") as call:
            reply = (
                self.replies.pop(0)
                if self.replies
                else '{"answer": "The sources do not say.", "insufficient_evidence": true}'
            )
            call.input_tokens = sum(len(m["content"]) for m in messages) // 4
            call.output_tokens = len(reply) // 4
        return reply

    def get_embeddings(self, texts, model=None, *, task=None):
        return [self.embedder.vector(text).tolist() for text in texts]
