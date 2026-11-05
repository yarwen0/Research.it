"""Turning processed papers into stored, embedded chunks."""

from __future__ import annotations

import uuid

import numpy as np
import pytest

from db.repositories import GraphRepository, ProjectRepository
from db.session import session_scope
from retrieval.embedder import ClientEmbedder
from retrieval.indexer import PaperIndexer
from retrieval.store import ChunkStore
from telemetry import current_stage
from tests.fakes import HashingEmbedder

BODY = "1 Introduction\n" + "\n".join(
    f"Sentence {i} describes how the diffusion model lifts 2D poses to 3D." for i in range(40)
)
NORMALIZED = {
    "problem": "3D human pose estimation",
    "methods": [["diffusion_model", "Diffusion model"]],
    "datasets": [["human36m", "Human3.6M"]],
}


class FakeEmbeddingClient:
    """A provider client as ClientEmbedder sees it."""

    embedding_model_id = "fake-embed"

    def __init__(self, *, short_by=0):
        self.calls: list[tuple[list[str], str | None]] = []
        self.short_by = short_by

    def get_embeddings(self, texts, model=None, *, task=None):
        self.calls.append((list(texts), task))
        vectors = [[float(len(text)), 1.0] for text in texts]
        return vectors[: len(vectors) - self.short_by]


class TestClientEmbedder:
    def test_documents_go_in_batches_with_the_document_hint(self):
        client = FakeEmbeddingClient()
        vectors = ClientEmbedder(client, batch_size=2).embed_documents(["a", "bb", "ccc"])

        assert [(len(texts), task) for texts, task in client.calls] == [(2, "document"), (1, "document")]
        assert len(vectors) == 3

    def test_queries_get_the_query_hint(self):
        client = FakeEmbeddingClient()
        ClientEmbedder(client).embed_query("which datasets?")
        assert client.calls == [(["which datasets?"], "query")]

    def test_vectors_come_back_as_float32(self):
        [vector] = ClientEmbedder(FakeEmbeddingClient()).embed_documents(["abc"])
        assert vector.dtype == np.float32
        np.testing.assert_array_equal(vector, [3.0, 1.0])

    def test_a_short_response_raises_rather_than_misaligning(self):
        embedder = ClientEmbedder(FakeEmbeddingClient(short_by=1))
        with pytest.raises(RuntimeError, match="returned 1 embeddings for 2 texts"):
            embedder.embed_documents(["one", "two"])

    def test_the_model_id_comes_from_the_client(self):
        assert ClientEmbedder(FakeEmbeddingClient()).model_id == "fake-embed"


class TestPrepare:
    def test_the_profile_comes_first_then_the_body(self):
        chunks = PaperIndexer(HashingEmbedder()).prepare(
            title="DreamPose3D", text=BODY, normalized=NORMALIZED
        )
        assert chunks[0].kind == "profile"
        assert "Datasets: Human3.6M (human36m)" in chunks[0].text
        assert {chunk.kind for chunk in chunks[1:]} == {"text"}
        assert len(chunks) > 2

    def test_body_chunks_are_embedded_under_their_title_and_section(self):
        embedder = HashingEmbedder()
        PaperIndexer(embedder).prepare(title="DreamPose3D", text=BODY, normalized=NORMALIZED)

        [embedded] = embedder.document_batches
        assert embedded[1].startswith("DreamPose3D — 1 Introduction\n")

    def test_the_stored_text_carries_no_header(self):
        chunks = PaperIndexer(HashingEmbedder()).prepare(title="DreamPose3D", text=BODY)
        assert chunks[0].text.startswith("Sentence 0")

    def test_headers_can_be_switched_off(self):
        embedder = HashingEmbedder()
        PaperIndexer(embedder, contextual_headers=False).prepare(title="DreamPose3D", text=BODY)
        [embedded] = embedder.document_batches
        assert embedded[0].startswith("Sentence 0")

    def test_a_paper_with_nothing_to_index_embeds_nothing(self):
        embedder = HashingEmbedder()
        assert PaperIndexer(embedder).prepare(title="Empty", text="") == []
        assert embedder.document_batches == []


def _seed_paper(paper_id="2301.001"):
    project_id = uuid.uuid4().hex
    paper = {"paper_id": paper_id, "title": "DreamPose3D", "authors": [], "normalized": NORMALIZED}
    with session_scope() as session:
        ProjectRepository(session).create(project_id, "prompt")
        GraphRepository(session, project_id).add_processed_paper(paper)
    return project_id, paper


class TestIndexPaper:
    def test_stores_the_papers_chunks(self):
        project_id, paper = _seed_paper()
        count = PaperIndexer(HashingEmbedder()).index_paper(project_id, paper, BODY)

        with session_scope() as session:
            assert ChunkStore(session).count(project_id) == count > 2

    def test_reindexing_replaces_rather_than_appends(self):
        project_id, paper = _seed_paper()
        indexer = PaperIndexer(HashingEmbedder())
        indexer.index_paper(project_id, paper, BODY)
        count = indexer.index_paper(project_id, paper, "")

        with session_scope() as session:
            # Only the profile is left once the body is gone.
            assert ChunkStore(session).count(project_id) == count == 1

    def test_an_unknown_paper_is_an_error(self):
        project_id, _ = _seed_paper()
        with pytest.raises(LookupError, match="not in project"):
            PaperIndexer(HashingEmbedder()).index_paper(
                project_id, {"paper_id": "missing", "title": "?"}, BODY
            )

    def test_embedding_calls_are_attributed_to_indexing(self):
        stages = []

        class StageRecordingEmbedder(HashingEmbedder):
            def embed_documents(self, texts):
                stages.append(current_stage())
                return super().embed_documents(texts)

        project_id, paper = _seed_paper()
        PaperIndexer(StageRecordingEmbedder()).index_paper(project_id, paper, BODY)
        assert stages == ["indexing"]
