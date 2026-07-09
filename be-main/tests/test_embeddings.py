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


class FakeEmbeddingClient:
    """Returns deterministic vectors keyed by exact text, for offline tests."""

    def __init__(self, table: dict[str, list[float]]):
        self.table = table

    def get_embeddings(self, texts, model=None):
        return [self.table[t] for t in texts]


class TestRankChunksByRelevance:
    def test_ranks_by_cosine_similarity_to_query(self):
        table = {
            "cat": [1.0, 0.0],
            "dog": [0.0, 1.0],
            "kitten": [0.9, 0.1],
        }
        manager = EmbeddingManager(FakeEmbeddingClient(table))
        chunks = [{"text": "dog"}, {"text": "kitten"}, {"text": "cat"}]
        ranked = manager.rank_chunks_by_relevance("cat", chunks)
        assert [c["text"] for c in ranked] == ["cat", "kitten", "dog"]
        assert all("similarity_score" in c for c in ranked)
        assert ranked[0]["similarity_score"] >= ranked[-1]["similarity_score"]

    def test_top_k_limits_results(self):
        table = {"cat": [1.0, 0.0], "dog": [0.0, 1.0], "kitten": [0.9, 0.1]}
        manager = EmbeddingManager(FakeEmbeddingClient(table))
        chunks = [{"text": "dog"}, {"text": "kitten"}, {"text": "cat"}]
        ranked = manager.rank_chunks_by_relevance("cat", chunks, top_k=2)
        assert [c["text"] for c in ranked] == ["cat", "kitten"]

    def test_empty_chunks_returns_empty(self):
        manager = EmbeddingManager(FakeEmbeddingClient({}))
        assert manager.rank_chunks_by_relevance("q", []) == []


class TestDeduplicateChunks:
    def test_drops_near_identical_chunks(self):
        table = {
            "cat": [1.0, 0.0],
            "cat again": [1.0, 0.0],  # identical vector -> duplicate
            "dog": [0.0, 1.0],
        }
        manager = EmbeddingManager(FakeEmbeddingClient(table))
        chunks = [{"text": "cat"}, {"text": "cat again"}, {"text": "dog"}]
        deduped = manager.deduplicate_chunks(chunks, similarity_threshold=0.95)
        assert [c["text"] for c in deduped] == ["cat", "dog"]

    def test_keeps_distinct_chunks(self):
        table = {"a": [1.0, 0.0], "b": [0.0, 1.0]}
        manager = EmbeddingManager(FakeEmbeddingClient(table))
        chunks = [{"text": "a"}, {"text": "b"}]
        assert len(manager.deduplicate_chunks(chunks)) == 2

    def test_empty_input_returns_empty(self):
        manager = EmbeddingManager(FakeEmbeddingClient({}))
        assert manager.deduplicate_chunks([]) == []
