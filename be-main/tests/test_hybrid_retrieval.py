"""Lexical scoring, rank fusion and the hybrid retriever."""

from __future__ import annotations

import numpy as np
import pytest

from db.models import Paper, Project
from retrieval.hybrid import (
    LEXICAL_INDEXES,
    HybridRetriever,
    cap_per_paper,
    combine,
    reciprocal_rank_fusion,
)
from retrieval.lexical import BM25, tokenize
from retrieval.store import ChunkStore, PreparedChunk


class TestTokenize:
    def test_lowercases_and_drops_function_words(self):
        assert tokenize("What is the Learning Rate of the model?") == ["learning", "rate", "model"]

    def test_keeps_identifiers_whole_and_adds_their_parts(self):
        assert tokenize("Human3.6M") == ["human3.6m", "human3", "6m", "human36m"]
        assert tokenize("GPT-4") == ["gpt-4", "gpt", "4", "gpt4"]

    def test_the_three_spellings_of_a_dataset_meet(self):
        paper, question, normalized = (
            set(tokenize(text)) for text in ("Human3.6M", "Human 3.6M", "human36m")
        )
        assert paper & question
        assert paper & normalized

    def test_numbers_survive(self):
        assert "2.5e-4" in tokenize("a learning rate of 2.5e-4")


DOCS = [
    tokenize("Stacked hourglass networks for human pose estimation"),
    tokenize("Batch normalization reduces internal covariate shift"),
    tokenize("Pose estimation with diffusion models and pose priors"),
]


class TestBM25:

    def test_ranks_the_document_containing_the_rare_term_first(self):
        [(best, _), *_] = BM25(DOCS).top(tokenize("covariate shift"), 3)
        assert best == 1

    def test_documents_sharing_no_term_are_not_returned(self):
        hits = BM25(DOCS).top(tokenize("covariate"), 3)
        assert [index for index, _ in hits] == [1]

    def test_repetition_saturates(self):
        index = BM25([["pose"], ["pose"] * 10, ["other"]])
        once, ten_times = index.scores(["pose"])[:2]
        assert ten_times > once
        assert ten_times < 3 * once

    def test_longer_documents_are_normalized(self):
        index = BM25([["pose", "filler"], ["pose"] + ["filler"] * 50])
        short, long = index.scores(["pose"])
        assert short > long

    def test_a_term_in_every_document_never_scores_negative(self):
        index = BM25([["pose", "a"], ["pose", "b"], ["pose", "c"]])
        assert (index.scores(["pose"]) >= 0).all()

    def test_an_empty_corpus(self):
        assert BM25([]).top(["anything"], 5) == []


class TestFusion:
    def test_reciprocal_rank_fusion(self):
        fused = reciprocal_rank_fusion([[1, 2, 3], [3, 1]])
        assert [item for item, _ in fused] == [1, 3, 2]
        assert dict(fused)[1] == pytest.approx(1 / 61 + 1 / 62)

    def test_agreement_beats_a_single_first_place(self):
        # Ranked second by both lists beats first in one list only.
        fused = reciprocal_rank_fusion([[7, 5], [8, 5]])
        assert fused[0][0] == 5

    def test_ties_go_to_the_lower_id(self):
        assert [item for item, _ in reciprocal_rank_fusion([[9], [4]])] == [4, 9]

    def test_single_strategies_pass_their_list_through(self):
        dense, lexical = [(1, 0.9), (2, 0.8)], [(3, 7.0)]
        assert combine("dense", dense, lexical) == dense
        assert combine("lexical", dense, lexical) == lexical

    def test_an_unknown_strategy_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown strategy"):
            combine("rerank", [], [])

    def test_cap_keeps_order_and_limits_each_paper(self):
        items = ["a1", "a2", "b1", "a3", "b2", "a4"]
        assert cap_per_paper(items, lambda item: item[0], 2) == ["a1", "a2", "b1", "b2"]


class ScriptedEmbedder:
    """Fixed vectors per text, so the dense ranking is exactly what a test says."""

    model_id = "scripted"

    def __init__(self, vectors):
        self.vectors = {text: np.asarray(vector, dtype=np.float32) for text, vector in vectors.items()}

    def embed_documents(self, texts):
        return [self.vectors[text] for text in texts]

    def embed_query(self, text):
        return self.vectors[text]


# Dense similarity says the paraphrase is the answer; only BM25 sees the exact
# identifier in the table row. Hybrid should surface both.
PARAPHRASE = "The model improves accuracy on difficult joints such as wrists."
TABLE_ROW = "DreamPose3D CPN 29.5 23.4 GT 15.9 12.2"
FILLER = "Related work surveys earlier lifting methods."
QUERY = "What is the 29.5 result on CPN?"
EMBEDDER = ScriptedEmbedder(
    {
        PARAPHRASE: [1.0, 0.0, 0.0],
        TABLE_ROW: [0.0, 1.0, 0.0],
        FILLER: [0.6, 0.0, 0.8],
        QUERY: [0.9, 0.1, 0.4],
    }
)


@pytest.fixture
def project(db_session):
    LEXICAL_INDEXES.clear()
    db_session.add(Project(id="hybrid-proj", user_prompt="prompt"))
    papers = [Paper(project_id="hybrid-proj", external_id=f"p{i}", title=f"Paper {i}") for i in range(2)]
    db_session.add_all(papers)
    db_session.flush()

    store = ChunkStore(db_session)
    for paper, texts in zip(papers, ([PARAPHRASE, TABLE_ROW], [FILLER]), strict=True):
        store.replace_paper_chunks(
            project_id="hybrid-proj",
            paper_pk=paper.id,
            embedding_model=EMBEDDER.model_id,
            chunks=[
                PreparedChunk("text", i, "4 Experiments", text, EMBEDDER.vectors[text])
                for i, text in enumerate(texts)
            ],
        )
    return db_session


def _texts(hits):
    return [hit.text for hit in hits]


class TestHybridRetriever:
    def test_dense_alone_misses_the_exact_match(self, project):
        hits = HybridRetriever(project, EMBEDDER, strategy="dense").retrieve("hybrid-proj", QUERY, k=2)
        assert TABLE_ROW not in _texts(hits)

    def test_lexical_alone_finds_only_the_exact_match(self, project):
        hits = HybridRetriever(project, EMBEDDER, strategy="lexical").retrieve("hybrid-proj", QUERY, k=3)
        assert _texts(hits) == [TABLE_ROW]

    def test_hybrid_surfaces_both(self, project):
        hits = HybridRetriever(project, EMBEDDER).retrieve("hybrid-proj", QUERY, k=2)
        assert set(_texts(hits)) == {PARAPHRASE, TABLE_ROW}

    def test_each_hit_reports_how_both_lists_ranked_it(self, project):
        hits = HybridRetriever(project, EMBEDDER).retrieve("hybrid-proj", QUERY, k=3)
        table = next(hit for hit in hits if hit.text == TABLE_ROW)
        filler = next(hit for hit in hits if hit.text == FILLER)
        assert table.lexical_rank == 1
        assert table.dense_rank == 3
        assert filler.lexical_rank is None

    def test_hits_carry_provenance(self, project):
        [hit] = HybridRetriever(project, EMBEDDER, strategy="lexical").retrieve("hybrid-proj", QUERY, k=1)
        assert (hit.paper_id, hit.paper_title, hit.section) == ("p0", "Paper 0", "4 Experiments")

    def test_the_per_paper_cap_applies(self, project):
        hits = HybridRetriever(project, EMBEDDER, max_per_paper=1).retrieve("hybrid-proj", QUERY, k=3)
        assert sorted(hit.paper_id for hit in hits) == ["p0", "p1"]

    def test_the_lexical_index_sees_new_chunks(self, project):
        retriever = HybridRetriever(project, EMBEDDER, strategy="lexical")
        assert retriever.retrieve("hybrid-proj", "covariate", k=1) == []

        paper = project.query(Paper).filter_by(external_id="p1").one()
        EMBEDDER.vectors["Batch normalization reduces covariate shift."] = np.ones(3, dtype=np.float32)
        ChunkStore(project).replace_paper_chunks(
            project_id="hybrid-proj",
            paper_pk=paper.id,
            embedding_model=EMBEDDER.model_id,
            chunks=[
                PreparedChunk(
                    "text", 0, None, "Batch normalization reduces covariate shift.", np.ones(3)
                )
            ],
        )
        assert _texts(retriever.retrieve("hybrid-proj", "covariate", k=1)) == [
            "Batch normalization reduces covariate shift."
        ]

    def test_an_unknown_strategy_is_rejected(self, project):
        with pytest.raises(ValueError, match="Unknown strategy"):
            HybridRetriever(project, EMBEDDER, strategy="magic")
