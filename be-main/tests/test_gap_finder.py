"""Tests for the symbolic gap finder (pure logic, no network/LLM)."""

from __future__ import annotations

from pathlib import Path

from gap_finder import (
    Gap,
    GapFinder,
    Paper,
    _unwrap_normalized_list,
    load_papers_from_path,
)

GAP_TYPES = {"method_transfer", "dataset_transfer", "limitation_gap", "future_work_gap"}


def make_paper(**overrides) -> Paper:
    base = dict(
        paper_id="p",
        problem="",
        methods=[],
        datasets=[],
        limitations_implied=[],
        limitations_explicit=[],
        future_work=[],
    )
    base.update(overrides)
    return Paper(**base)


class TestUnwrapNormalizedList:
    def test_none_and_empty_return_empty(self):
        assert _unwrap_normalized_list(None) == []
        assert _unwrap_normalized_list([]) == []

    def test_plain_strings_pass_through(self):
        assert _unwrap_normalized_list(["a", "b"]) == ["a", "b"]

    def test_schema_lists_take_first_token(self):
        assert _unwrap_normalized_list([["a", 0.9], ["b", 0.1]]) == ["a", "b"]
        assert _unwrap_normalized_list([("x", 1)]) == ["x"]

    def test_mixed_input_skips_non_string_scalars_and_empties(self):
        assert _unwrap_normalized_list([[], "c", 123, ["d"]]) == ["c", "d"]


class TestPaperFromCanonical:
    def test_unwraps_nested_lists(self):
        paper = Paper.from_canonical(
            {
                "paper_id": "x1",
                "problem": "seg",
                "methods": [["unet", 0.9]],
                "datasets": [["coco", 0.8]],
                "future_work": ["3d"],
            }
        )
        assert paper.paper_id == "x1"
        assert paper.methods == ["unet"]
        assert paper.datasets == ["coco"]
        assert paper.future_work == ["3d"]

    def test_paper_id_falls_back_to_id(self):
        paper = Paper.from_canonical({"id": "fallback", "problem": "p"})
        assert paper.paper_id == "fallback"


class TestGapFinder:
    def test_method_transfer_gaps_are_detected(self):
        papers = [
            make_paper(paper_id="a", problem="p", methods=["m1"], datasets=["d1"]),
            make_paper(paper_id="b", problem="p", methods=["m2"], datasets=["d2"]),
        ]
        gaps = GapFinder(papers).find_method_transfer_gaps(top_k=10)
        assert gaps, "expected at least one method-transfer gap"
        for gap in gaps:
            assert gap.gap_type == "method_transfer"
            assert gap.method in {"m1", "m2"}
            assert gap.dataset in {"d1", "d2"}
            assert isinstance(gap.score, int) and gap.score >= 0

    def test_future_work_gap_surfaces_unrealized_demand(self):
        papers = [
            make_paper(paper_id="a", problem="p", future_work=["explore_zzz"]),
            make_paper(paper_id="b", problem="p", future_work=["explore_zzz"]),
        ]
        gaps = GapFinder(papers).find_future_work_gaps(top_k=10)
        assert any(g.future_work_label == "explore_zzz" for g in gaps)

    def test_dataset_transfer_gaps_are_detected(self):
        papers = [
            make_paper(paper_id="a", problem="p", methods=["m1"], datasets=["d1"]),
            make_paper(paper_id="b", problem="p", methods=["m2"], datasets=["d2"]),
        ]
        gaps = GapFinder(papers).find_dataset_transfer_gaps(top_k=10)
        assert gaps, "expected at least one dataset-transfer gap"
        for gap in gaps:
            assert gap.gap_type == "dataset_transfer"
            assert gap.method in {"m1", "m2"}
            assert gap.dataset in {"d1", "d2"}

    def test_limitation_gap_surfaces_saturated_limitation(self):
        papers = [
            make_paper(paper_id="a", problem="p", methods=["m1"],
                       limitations_explicit=["lim"]),
            make_paper(paper_id="b", problem="p", methods=["m1"],
                       limitations_explicit=["lim"]),
        ]
        gaps = GapFinder(papers).find_limitation_gaps(top_k=10)
        assert any(g.gap_type == "limitation_gap" and g.limitation == "lim" for g in gaps)

    def test_find_all_gaps_only_emits_known_types(self):
        papers = [
            make_paper(paper_id="a", problem="p", methods=["m1"], datasets=["d1"],
                       future_work=["future_x"]),
            make_paper(paper_id="b", problem="p", methods=["m2"], datasets=["d2"],
                       future_work=["future_x"]),
        ]
        gaps = GapFinder(papers).find_all_gaps(top_k_per_type=5)
        assert all(isinstance(g, Gap) for g in gaps)
        assert {g.gap_type for g in gaps} <= GAP_TYPES

    def test_to_title_condition_shape(self):
        gap = Gap(gap_type="method_transfer", problem="p", score=3,
                  method="m", dataset="d")
        cond = gap.to_title_condition()
        assert cond["gap_type"] == "method_transfer"
        assert cond["score"] == 3
        assert set(cond) == {
            "gap_type", "problem", "method", "dataset",
            "target_limitation", "future_work_label", "score",
        }

    def test_empty_corpus_produces_no_gaps(self):
        assert GapFinder([]).find_all_gaps() == []


def test_load_papers_from_sample_corpus():
    corpus = Path(__file__).resolve().parents[1] / "examples" / "sample_corpus.json"
    papers = load_papers_from_path(corpus)
    assert papers, "sample corpus should not be empty"
    assert all(isinstance(p, Paper) for p in papers)
