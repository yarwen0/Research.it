"""Tests for EmbeddingManager pure-math helpers (cosine similarity, chunking)."""

from __future__ import annotations

import pytest

from utils.embeddings import EmbeddingManager


@pytest.fixture
def manager() -> EmbeddingManager:
    # cosine_similarity and chunk_text never touch the client.
    return EmbeddingManager(openrouter_client=None)


class TestCosineSimilarity:
    def test_identical_vectors(self, manager):
        assert manager.cosine_similarity([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self, manager):
        assert manager.cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_opposite_vectors(self, manager):
        assert manager.cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_zero_vector_is_guarded(self, manager):
        assert manager.cosine_similarity([0, 0], [1, 1]) == 0.0

    def test_returns_python_float(self, manager):
        assert isinstance(manager.cosine_similarity([1, 1], [1, 0]), float)


class TestChunkText:
    def test_short_text_is_single_chunk(self, manager):
        assert manager.chunk_text("hello world", chunk_size=1000) == ["hello world"]

    def test_oversized_single_chunk_is_truncated(self, manager):
        text = "x" * 9000
        chunks = manager.chunk_text(text, chunk_size=10000, max_chunk_size=8000)
        assert len(chunks) == 1
        assert len(chunks[0]) == 8000

    def test_long_text_splits_into_multiple_stripped_chunks(self, manager):
        text = "This is a sentence. " * 100  # 2000 chars
        chunks = manager.chunk_text(text, chunk_size=500, overlap=100)
        assert len(chunks) > 1
        assert chunks[0].startswith("This is a sentence")
        for chunk in chunks:
            assert chunk == chunk.strip()
            assert chunk
            assert len(chunk) <= 8000
