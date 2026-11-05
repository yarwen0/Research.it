"""Regression gate on retrieval quality.

The numbers in evals/retrieval/README.md chose the shipped configuration; a
change that quietly degrades them should fail here. Baselines carry about one
question of slack, so an improvement passes and a regression does not.

Runs from the committed embedding cache: no model, no network.
"""

from __future__ import annotations

import pytest

from evals.retrieval.harness import (
    NO_CAP,
    SHIPPED,
    VARIANTS,
    CachedEmbedder,
    EmbeddingCache,
    build_corpus,
    check_labels,
    evaluate,
    load_questions,
)
from retrieval.hybrid import MAX_PER_PAPER

# Measured; see evals/retrieval/README.md. One question is 1/35 = 0.029.
SHIPPED_BASELINE = {"hit@1": 0.743, "hit@5": 0.914, "mrr": 0.810, "coverage@10": 0.929}
TOLERANCE = 0.03


@pytest.fixture(scope="module")
def report():
    return evaluate()


def _overall(report, name):
    return report["variants"][name]["overall"]


class TestBenchmarkIntegrity:
    def test_question_set_is_unchanged(self):
        # The baselines are only comparable against the same questions.
        assert len(load_questions()) == 35

    def test_corpus_chunks_as_measured(self):
        # A chunker change moves passages, invalidates the cached embeddings
        # and the baselines with them: rerun with --refresh and re-measure.
        chunks, _ = build_corpus(CachedEmbedder(EmbeddingCache(), task_hints=True), headers=True)
        assert len(chunks) == 138

    def test_every_label_matches_a_passage(self):
        chunks, _ = build_corpus(CachedEmbedder(EmbeddingCache(), task_hints=True), headers=True)
        assert check_labels(chunks, load_questions()) == []

    def test_the_cache_covers_every_variant(self, report):
        # evaluate() raises MissingEmbeddings rather than scoring a partial run.
        assert set(report["variants"]) == {variant.name for variant in VARIANTS}

    def test_the_shipped_variant_is_what_production_runs(self):
        shipped = VARIANTS[0]
        assert shipped.name == SHIPPED
        assert (shipped.strategy, shipped.task_hints, shipped.headers) == ("hybrid", True, True)
        assert shipped.max_per_paper == MAX_PER_PAPER


class TestShippedQuality:
    @pytest.mark.parametrize("metric", sorted(SHIPPED_BASELINE))
    def test_does_not_regress(self, report, metric):
        measured = _overall(report, SHIPPED)[metric]
        assert measured >= SHIPPED_BASELINE[metric] - TOLERANCE, (
            f"{metric} fell to {measured}, below the {SHIPPED_BASELINE[metric]} baseline"
        )

    @pytest.mark.parametrize("alternative", ["dense", "lexical"])
    def test_hybrid_puts_the_answer_first_more_often(self, report, alternative):
        # The reason hybrid is the default. If this stops holding, the default
        # should be re-decided, not the test loosened.
        shipped, other = _overall(report, SHIPPED), _overall(report, alternative)
        assert shipped["hit@1"] > other["hit@1"]
        assert shipped["mrr"] > other["mrr"]

    def test_the_cap_protects_questions_spanning_papers(self, report):
        uncapped = next(v.name for v in VARIANTS if v.max_per_paper == NO_CAP)
        cross = "cross-paper"
        assert (
            report["variants"][SHIPPED]["by_type"][cross]["coverage@10"]
            > report["variants"][uncapped]["by_type"][cross]["coverage@10"]
        )
