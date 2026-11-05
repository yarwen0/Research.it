"""Embedding for retrieval: batched, typed, and told what each text is for."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

import numpy as np


class Embedder(Protocol):
    """What retrieval needs from an embedding model."""

    # Stored with every vector; a query is only ever compared against vectors
    # from the same model.
    model_id: str

    def embed_documents(self, texts: Sequence[str]) -> list[np.ndarray]: ...

    def embed_query(self, text: str) -> np.ndarray: ...


class ClientEmbedder:
    """Adapts a provider client (Gemini, Ollama, OpenRouter, Vertex).

    Documents and queries are embedded with different task hints, which is
    how asymmetric retrieval models are meant to be used: a six-word question
    and the paragraph that answers it are not embedded alike.
    """

    def __init__(self, client: Any, *, batch_size: int = 32) -> None:
        self._client = client
        self.model_id: str = client.embedding_model_id
        self.batch_size = batch_size

    def embed_documents(self, texts: Sequence[str]) -> list[np.ndarray]:
        vectors: list[np.ndarray] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            embedded = self._client.get_embeddings(batch, task="document")
            if len(embedded) != len(batch):
                # A silent misalignment would attach vectors to the wrong text.
                raise RuntimeError(
                    f"{self.model_id} returned {len(embedded)} embeddings for {len(batch)} texts"
                )
            vectors.extend(np.asarray(vector, dtype=np.float32) for vector in embedded)
        return vectors

    def embed_query(self, text: str) -> np.ndarray:
        [vector] = self._client.get_embeddings([text], task="query")
        return np.asarray(vector, dtype=np.float32)
