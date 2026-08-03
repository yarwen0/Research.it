"""Regression gate on gap-detection quality.

The numbers in evals/README.md are only meaningful if a change that degrades
them fails visibly. These lock in the measured baselines with a little slack,
so an intentional improvement passes and a silent regression does not.
"""

from __future__ import annotations

import pytest

from evals.harness import GroundTruth, evaluate, load_corpus, load_labels
from evals.run_eval import SHIPPED_CONFIG

# Measured on the 18-paper benchmark; see evals/README.md.
SHIPPED_BASELINE = {"precision": 0.722, "recall": 0.188, "f1": 0.299}
TOLERANCE = 0.02


@pytest.fixture(scope="module")
def papers():
    return load_corpus()


@pytest.fixture(scope="module")
def truth(papers):
    return GroundTruth(papers, load_labels())


@pytest.fixture(scope="module")
def shipped(papers, truth):
    return evaluate(papers, truth, top_k_per_type=5, **SHIPPED_CONFIG)


class TestCorpusIntegrity:
    def test_corpus_size_is_unchanged(self, papers):
        # The baselines below are only comparable against the same corpus.
        assert len(papers) == 18

    def test_every_paper_has_a_problem(self, papers):
        assert all(paper.problem for paper in papers)

    def test_ground_truth_is_non_trivial(self, truth):
        expected = truth.all_gaps()
        assert len(expected) == 69

    def test_labels_cover_every_corpus_method_and_dataset(self, papers, truth):
        # An unlabelled method or dataset is silently treated as impossible,
        # which would understate ground truth without any test failing.
        for paper in papers:
            for method in paper.methods:
                assert method in truth.method_requires, f"unlabelled method: {method}"
            for dataset in paper.datasets:
                assert dataset in truth.dataset_provides, f"unlabelled dataset: {dataset}"


class TestCompatibilityOracle:
    def test_temporal_method_rejected_on_static_dataset(self, truth):
        # MPII is still images; there is nothing for a temporal model to use.
        assert not truth.is_runnable("3d_pose_estimation", "temporal_smoothing", "mpii")

    def test_temporal_method_accepted_on_video_dataset(self, truth):
        assert truth.is_runnable("3d_pose_estimation", "temporal_smoothing", "threedpw")

    def test_body_method_rejected_on_hand_dataset(self, truth):
        assert not truth.is_runnable("hand_pose_estimation", "smpl_regression", "freihand")

    def test_problem_region_must_match_dataset_region(self, truth):
        # A body problem evaluated on a hand dataset is not a research gap.
        assert not truth.is_runnable("3d_pose_estimation", "stacked_hourglass", "freihand")

    def test_multiview_method_rejected_on_monocular_dataset(self, truth):
        assert not truth.is_runnable("human_mesh_reconstruction", "nerf_volumetric", "threedpw")

    def test_unknown_names_are_not_runnable(self, truth):
        assert not truth.is_runnable("3d_pose_estimation", "no_such_method", "human36m")


class TestShippedQuality:
    @pytest.mark.parametrize("metric", ["precision", "recall", "f1"])
    def test_metric_has_not_regressed(self, shipped, metric):
        measured = shipped["overall"][metric]
        baseline = SHIPPED_BASELINE[metric]
        assert measured >= baseline - TOLERANCE, (
            f"{metric} fell from {baseline} to {measured}; "
            "see evals/README.md for the recorded baseline"
        )

    def test_limitation_detection_still_finds_everything(self, shipped):
        assert shipped["per_type"]["limitation_gap"]["recall"] == 1.0

    def test_future_work_detection_still_finds_everything(self, shipped):
        assert shipped["per_type"]["future_work_gap"]["recall"] == 1.0


class TestOutputCapTradeoff:
    """Raising the cap must buy recall. If it stops doing so, ranking broke."""

    def test_recall_increases_with_the_cap(self, papers, truth):
        recalls = [
            evaluate(papers, truth, top_k_per_type=k, **SHIPPED_CONFIG)["overall"]["recall"]
            for k in (5, 15, 30, 50)
        ]
        assert recalls == sorted(recalls)
        assert recalls[-1] > recalls[0]

    def test_shipped_cap_favours_precision_over_recall(self, shipped):
        # Documents the actual trade-off being made, so changing it is a
        # deliberate act rather than an accident.
        assert shipped["overall"]["precision"] > shipped["overall"]["recall"]


def test_evaluation_is_reproducible(papers, truth):
    first = evaluate(papers, truth, top_k_per_type=25, **SHIPPED_CONFIG)
    second = evaluate(papers, truth, top_k_per_type=25, **SHIPPED_CONFIG)
    assert first["overall"] == second["overall"]
    assert first["breakdown"] == second["breakdown"]
