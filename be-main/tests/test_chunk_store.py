"""Chunk storage and similarity search, on SQLite and on Postgres with pgvector.

Every test runs once per database (see `db_session`); the Postgres run needs
TEST_POSTGRES_URL and is skipped without it. The two search paths share no
code — SQL with pgvector's operator on one, numpy on the other — so the same
assertions on both are what show they agree.
"""

from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import select

from db.models import Chunk, Paper, Project
from retrieval.store import ChunkStore, PreparedChunk
from tests.fakes import HashingEmbedder

EMBEDDER = HashingEmbedder()
MODEL = EMBEDDER.model_id

DIFFUSION = "Diffusion models denoise noisy pose sequences to estimate 3D human pose."
HOURGLASS = "Stacked hourglass networks pool and upsample features for keypoint heatmaps."
NORMALIZATION = "Batch normalization reduces internal covariate shift in deep networks."


def _project(session, project_id: str, papers: dict[str, str]) -> dict[str, int]:
    """Create a project and its papers; map external id to primary key."""
    session.add(Project(id=project_id, user_prompt="prompt"))
    rows = {
        external_id: Paper(project_id=project_id, external_id=external_id, title=title, is_processed=True)
        for external_id, title in papers.items()
    }
    session.add_all(rows.values())
    session.flush()
    return {external_id: row.id for external_id, row in rows.items()}


def _chunks(*texts: str, kind: str = "text", section: str | None = "1 Introduction"):
    return [
        PreparedChunk(kind=kind, ordinal=i, section=section, text=text, embedding=EMBEDDER.vector(text))
        for i, text in enumerate(texts)
    ]


@pytest.fixture
def corpus(db_session):
    """One project, three papers, one chunk each."""
    pks = _project(
        db_session,
        "proj-a",
        {"2301.001": "DreamPose3D", "1603.06937": "Stacked Hourglass", "1502.03167": "Batch Norm"},
    )
    store = ChunkStore(db_session)
    for external_id, text in zip(pks, (DIFFUSION, HOURGLASS, NORMALIZATION), strict=True):
        store.replace_paper_chunks(
            project_id="proj-a", paper_pk=pks[external_id], embedding_model=MODEL, chunks=_chunks(text)
        )
    return store, pks


class TestStorage:
    def test_counts_what_was_stored(self, corpus):
        store, _ = corpus
        assert store.count("proj-a") == 3
        assert store.models("proj-a") == {MODEL: 3}

    def test_replacing_leaves_no_stale_chunks(self, corpus):
        store, pks = corpus
        store.replace_paper_chunks(
            project_id="proj-a",
            paper_pk=pks["2301.001"],
            embedding_model=MODEL,
            chunks=_chunks("First passage about diffusion.", "Second passage about diffusion."),
        )
        store.replace_paper_chunks(
            project_id="proj-a",
            paper_pk=pks["2301.001"],
            embedding_model=MODEL,
            chunks=_chunks("Only passage now."),
        )
        assert store.count("proj-a") == 3

    def test_another_models_chunks_are_left_alone(self, corpus):
        store, pks = corpus
        store.replace_paper_chunks(
            project_id="proj-a",
            paper_pk=pks["2301.001"],
            embedding_model="other-model",
            chunks=_chunks(DIFFUSION),
        )
        store.replace_paper_chunks(
            project_id="proj-a", paper_pk=pks["2301.001"], embedding_model=MODEL, chunks=[]
        )
        assert store.models("proj-a") == {MODEL: 2, "other-model": 1}

    def test_embeddings_round_trip_as_float32(self, corpus, db_session):
        db_session.expire_all()
        stored = db_session.scalars(select(Chunk).where(Chunk.text == DIFFUSION)).one()
        assert stored.embedding.dtype == np.float32
        np.testing.assert_array_equal(stored.embedding, EMBEDDER.vector(DIFFUSION))

    def test_deleting_a_paper_deletes_its_chunks(self, corpus, db_session):
        store, pks = corpus
        db_session.delete(db_session.get(Paper, pks["2301.001"]))
        db_session.flush()
        assert store.count("proj-a") == 2


class TestSearch:
    def test_ranks_the_matching_passage_first(self, corpus):
        store, _ = corpus
        hits = store.search("proj-a", MODEL, EMBEDDER.vector("diffusion pose estimation"), k=3)
        assert hits[0].text == DIFFUSION
        assert [hit.score for hit in hits] == sorted((hit.score for hit in hits), reverse=True)

    def test_scores_are_cosine_similarities(self, corpus):
        store, _ = corpus
        [hit] = store.search("proj-a", MODEL, EMBEDDER.vector(HOURGLASS), k=1)
        assert hit.score == pytest.approx(1.0, abs=1e-5)

    def test_hits_carry_their_provenance(self, corpus):
        store, _ = corpus
        [hit] = store.search("proj-a", MODEL, EMBEDDER.vector(HOURGLASS), k=1)
        assert (hit.paper_id, hit.paper_title) == ("1603.06937", "Stacked Hourglass")
        assert (hit.kind, hit.section) == ("text", "1 Introduction")

    def test_k_bounds_the_results(self, corpus):
        store, _ = corpus
        assert len(store.search("proj-a", MODEL, EMBEDDER.vector("networks"), k=2)) == 2
        assert store.search("proj-a", MODEL, EMBEDDER.vector("networks"), k=0) == []

    def test_search_is_scoped_to_one_project(self, corpus, db_session):
        store, _ = corpus
        pks = _project(db_session, "proj-b", {"2301.001": "Same arXiv id, other run"})
        store.replace_paper_chunks(
            project_id="proj-b", paper_pk=pks["2301.001"], embedding_model=MODEL, chunks=_chunks(DIFFUSION)
        )
        hits = store.search("proj-b", MODEL, EMBEDDER.vector(DIFFUSION), k=10)
        assert [hit.paper_title for hit in hits] == ["Same arXiv id, other run"]

    def test_search_is_scoped_to_one_model(self, corpus):
        store, _ = corpus
        assert store.search("proj-a", "never-indexed-model", EMBEDDER.vector(DIFFUSION)) == []

    def test_kinds_filter(self, corpus):
        store, pks = corpus
        store.replace_paper_chunks(
            project_id="proj-a",
            paper_pk=pks["1502.03167"],
            embedding_model=MODEL,
            chunks=_chunks("Batch Norm\nMethods: batch normalization", kind="profile", section=None),
        )
        hits = store.search("proj-a", MODEL, EMBEDDER.vector("batch normalization"), kinds=["profile"])
        assert [hit.kind for hit in hits] == ["profile"]

    def test_ties_break_by_chunk_id(self, db_session):
        pks = _project(db_session, "proj-tie", {"x": "X"})
        store = ChunkStore(db_session)
        store.replace_paper_chunks(
            project_id="proj-tie",
            paper_pk=pks["x"],
            embedding_model=MODEL,
            chunks=_chunks(DIFFUSION, DIFFUSION, DIFFUSION),
        )
        hits = store.search("proj-tie", MODEL, EMBEDDER.vector(DIFFUSION), k=3)
        assert [hit.chunk_id for hit in hits] == sorted(hit.chunk_id for hit in hits)

    def test_an_unindexed_project_returns_nothing(self, db_session):
        assert ChunkStore(db_session).search("nope", MODEL, EMBEDDER.vector("anything")) == []

    def test_a_query_from_a_different_model_is_rejected(self, corpus):
        store, _ = corpus
        with pytest.raises(Exception, match="dimension"):
            store.search("proj-a", MODEL, np.ones(EMBEDDER.dim + 1, dtype=np.float32))
