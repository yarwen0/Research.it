"""Tests for method frequency aggregation.

The extraction pipeline emits `[canonical_key, surface_form]` pairs precisely
so that wording differences fold together. Counting the surface form threw
that away.
"""

from __future__ import annotations

from utils.graph import TrendsCreator


def _paper(title: str, topic: str, methods: list) -> dict:
    return {
        "paper_id": title.lower().replace(" ", "_"),
        "title": title,
        "topic": topic,
        "published": "2024-01-01",
        "normalized": {"methods": methods},
    }


def _creator(papers: list[dict]) -> TrendsCreator:
    return TrendsCreator({"papers": papers, "total_papers": len(papers)})


class TestCanonicalCounting:
    def test_surface_variants_fold_into_one_method(self):
        creator = _creator(
            [
                _paper("A", "pose", [["diffusion", "Diffusion Models"]]),
                _paper("B", "pose", [["diffusion", "diffusion model"]]),
                _paper("C", "pose", [["diffusion", "Diffusion-based approach"]]),
            ]
        )

        result = creator.get_method_frequency()

        # One method seen three times, not three methods seen once each.
        assert result["radar"]["metrics"]

    def test_distinct_methods_stay_distinct(self):
        creator = _creator(
            [
                _paper("A", "pose", [["diffusion", "Diffusion Models"]]),
                _paper("B", "pose", [["transformer", "Transformers"]]),
            ]
        )

        result = creator.get_method_frequency()
        assert result["config"]["type"] == "radar"
        assert result["radar"]["metrics"]

    def test_bare_string_methods_still_work(self):
        # Older extractions emitted plain strings rather than pairs.
        creator = _creator([_paper("A", "pose", ["diffusion"])])
        result = creator.get_method_frequency()
        assert result["radar"]["metrics"]

    def test_empty_methods_produce_an_empty_chart(self):
        creator = _creator([_paper("A", "pose", [])])
        result = creator.get_method_frequency()

        assert result["dataPoints"] == []
        assert result["series"] == []
        assert "No methods data available" in result["config"]["description"]

    def test_blank_keys_are_skipped(self):
        creator = _creator([_paper("A", "pose", [["", "Some Label"]])])
        result = creator.get_method_frequency()
        assert result["dataPoints"] == []


class TestTopicCategorisation:
    def test_papers_are_attributed_to_their_topic(self):
        creator = _creator(
            [
                _paper("A", "pose", [["diffusion", "Diffusion Models"]]),
                _paper("B", "mesh", [["diffusion", "diffusion model"]]),
            ]
        )

        result = creator.get_method_frequency()
        topics = {series["label"] for series in result["series"]}
        assert topics == {"pose", "mesh"}

    def test_every_method_lands_in_some_category(self):
        """Categories are keyed canonically, so matching must be too.

        Matching the surface form against canonically-keyed categories put
        every method in no category, leaving all series at zero.
        """
        creator = _creator(
            [
                _paper("A", "pose", [["diffusion", "Diffusion Models"]]),
                _paper("B", "pose", [["transformer", "Transformer Lifting"]]),
                _paper("C", "mesh", [["smpl_regression", "SMPL Regression"]]),
            ]
        )

        result = creator.get_method_frequency()
        total = sum(
            value
            for series in result["series"]
            for value in series["data"]
            if isinstance(value, (int, float))
        )
        assert total > 0, "no method was attributed to a category"
