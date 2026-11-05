"""Tests for splitting paper text into retrievable chunks."""

from __future__ import annotations

from pathlib import Path

import pytest

from retrieval.chunking import (
    MIN_CHARS,
    chunk_paper_text,
    clean_text,
    render_profile,
    split_sections,
)

DOCS = Path(__file__).resolve().parent.parent / "examples" / "docs"

PAPER = """DreamPose3D: Hallucinative Diffusion
Jane Doe, John Roe
Abstract
We estimate 3D human pose with a diffusion model conditioned on action prompts.
1 Introduction
Pose estimation from monocular video is ambiguous. Depth is lost in projec-
tion, and occluded joints must be inferred.
2 Related Work
Lifting methods regress 3D joints from 2D detections.
References
[1] A. Author. Some lifting paper. CVPR, 2020.
[2] B. Author. Another paper. ICCV, 2021.
A Implementation Details
We train for 80 epochs with a learning rate of 0.0002.
"""


def sections(text):
    return [heading for heading, _ in split_sections(text)]


class TestCleanText:
    def test_rejoins_words_hyphenated_across_lines(self):
        assert clean_text("projec-\ntion") == "projection"

    def test_keeps_hyphens_that_are_not_line_breaks(self):
        assert clean_text("prompt-driven\ndenoiser") == "prompt-driven\ndenoiser"

    def test_does_not_join_across_a_capitalised_line(self):
        # "Batch-\nNormalized" is a compound broken at a line, not a split word.
        assert clean_text("Batch-\nNormalized") == "Batch-\nNormalized"

    def test_folds_ligatures(self):
        assert clean_text("eﬃcient ﬁne-tuning") == "efficient fine-tuning"

    def test_drops_soft_hyphens(self):
        assert clean_text("re­construction") == "reconstruction"


class TestSplitSections:
    def test_finds_numbered_and_named_headings(self):
        assert sections(PAPER)[:4] == [None, "Abstract", "1 Introduction", "2 Related Work"]

    def test_drops_the_bibliography(self):
        body = " ".join(content for _, content in split_sections(PAPER))
        assert "Some lifting paper" not in body
        assert "ICCV" not in body

    def test_keeps_an_appendix_after_the_bibliography(self):
        found = dict(split_sections(PAPER))
        assert "learning rate of 0.0002" in found["A Implementation Details"]

    def test_uses_the_last_references_heading(self):
        # The word on its own line earlier (a table of contents, say) must not
        # cut the body short.
        text = "1 Introduction\nReferences\nThe body continues here.\nReferences\n[1] X."
        body = " ".join(content for _, content in split_sections(text))
        assert "The body continues here." in body
        assert "[1] X." not in body

    def test_joins_wrapped_lines_into_one_paragraph(self):
        found = dict(split_sections(PAPER))
        assert found["1 Introduction"].startswith(
            "Pose estimation from monocular video is ambiguous. Depth is lost in projection,"
        )

    def test_a_wrapped_sentence_is_not_mistaken_for_a_heading(self):
        text = "1 Introduction\nWe study pose.\n2 We propose a new approach for\nlifting."
        assert "2 We propose a new approach for" not in sections(text)

    def test_a_heading_with_no_body_is_skipped(self):
        text = "3 Method\n3.1 Encoder\nThe encoder maps joints to tokens."
        assert sections(text) == ["3.1 Encoder"]

    def test_empty_text(self):
        assert split_sections("") == []

    def test_rejoins_a_section_number_printed_on_its_own_line(self):
        # LREC and ACL templates come out of PyMuPDF this way.
        text = "1.\nIntroduction\nWe record signers.\n5.2.1.\nHardware and Sensor Setup\nA depth camera."
        assert sections(text) == ["1. Introduction", "5.2.1. Hardware and Sensor Setup"]

    def test_a_bare_page_number_does_not_swallow_the_next_line(self):
        text = "1 Introduction\nFirst paragraph.\n4\nThe model is trained on the full dataset\n"
        found = dict(split_sections(text))
        assert "The model is trained on the full dataset" in found["1 Introduction"]

    def test_drops_an_lrec_style_bibliography(self):
        text = (
            "1.\nIntroduction\nBody text about corpora.\n"
            "11.\nBibliographical References\nOrbbec. 2026. Femto Bolt.\n"
        )
        body = " ".join(content for _, content in split_sections(text))
        assert "Body text about corpora." in body
        assert "Orbbec" not in body


class TestChunkPaperText:
    @staticmethod
    def long_section(sentences=80):
        return "1 Introduction\n" + "\n".join(
            f"Sentence number {i} explains one more detail of the method." for i in range(sentences)
        )

    def test_chunks_respect_the_size_bound(self):
        chunks = chunk_paper_text(self.long_section(), target_chars=400, overlap_chars=100)
        assert len(chunks) > 3
        # Target plus at most one carried overlap.
        assert all(len(chunk.text) <= 400 + 100 for chunk in chunks)

    def test_neighbouring_chunks_overlap(self):
        chunks = chunk_paper_text(self.long_section(), target_chars=400, overlap_chars=100)
        last_sentence = chunks[0].text.rsplit(". ", 1)[-1]
        assert chunks[1].text.startswith(last_sentence)

    def test_chunks_end_on_sentence_boundaries(self):
        chunks = chunk_paper_text(self.long_section(), target_chars=400, overlap_chars=0)
        assert all(chunk.text.endswith(".") for chunk in chunks)

    def test_a_sentence_longer_than_the_target_is_split_at_words(self):
        text = "1 Introduction\n" + " ".join(["word"] * 500) + "."
        chunks = chunk_paper_text(text, target_chars=300, overlap_chars=0)
        assert all(len(chunk.text) <= 300 for chunk in chunks)
        assert all(not chunk.text.startswith(" ") for chunk in chunks)

    def test_chunks_carry_their_section_and_a_running_ordinal(self):
        chunks = chunk_paper_text(PAPER)
        assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
        assert {chunk.section for chunk in chunks} >= {"1 Introduction", "2 Related Work"}

    def test_fragments_too_short_to_mean_anything_are_dropped(self):
        text = "1 Introduction\nShort.\n2 Method\n" + "A meaningful sentence about the method. " * 3
        chunks = chunk_paper_text(text)
        assert all(len(chunk.text) >= MIN_CHARS for chunk in chunks)
        assert [chunk.section for chunk in chunks] == ["2 Method"]

    @pytest.mark.parametrize("name", ["dreampose", "hourglass", "batch_normal"])
    def test_real_papers_chunk_cleanly(self, name):
        text = (DOCS / f"{name}.txt").read_text(encoding="utf-8")
        chunks = chunk_paper_text(text)

        assert len(chunks) > 20
        assert all(MIN_CHARS <= len(chunk.text) <= 1200 + 200 for chunk in chunks)
        # The bibliography's telltale run of venues and years is gone.
        assert not any(chunk.section and chunk.section.lower() == "references" for chunk in chunks)

    def test_the_dreampose_appendix_survives(self):
        text = (DOCS / "dreampose.txt").read_text(encoding="utf-8")
        found = {chunk.section for chunk in chunk_paper_text(text)}
        assert "B Implementation Details" in found
        assert "G Limitations and Future Works" in found


NORMALIZED = {
    "problem": "3D human pose estimation from monocular video",
    "methods": [["diffusion_model", "Diffusion models"], ["action_prompt", "Action prompts"]],
    "datasets": [["human36m", "Human3.6M"], ["mpi_inf_3dhp", "MPI-INF-3DHP"]],
    "limitations_explicit": [["occlusion", "Fails under heavy occlusion"]],
    "future_work": [],
}


class TestRenderProfile:

    def test_renders_the_structured_record(self):
        profile = render_profile("DreamPose3D", None, NORMALIZED)
        assert profile.splitlines()[0] == "DreamPose3D"
        assert "Problem: 3D human pose estimation from monocular video" in profile
        assert "Stated limitations: Fails under heavy occlusion (occlusion)" in profile
        # Empty fields are left out rather than rendered as "Future work: ".
        assert "Future work" not in profile

    def test_keeps_the_canonical_term_when_it_differs(self):
        profile = render_profile("DreamPose3D", None, NORMALIZED)
        assert "Human3.6M (human36m)" in profile

    def test_drops_the_canonical_term_when_it_says_the_same_thing(self):
        profile = render_profile("P", None, {"methods": [["diffusion_models", "Diffusion models"]]})
        assert "Methods: Diffusion models" in profile
        assert "(diffusion_models)" not in profile

    def test_falls_back_to_the_raw_extraction_field_by_field(self):
        extraction = {"problem": "Raw problem", "datasets": ["COCO", "MPII"]}
        profile = render_profile("P", extraction, {"methods": [["vit", "ViT"]]})
        assert "Problem: Raw problem" in profile
        assert "Datasets: COCO; MPII" in profile
        assert "Methods: ViT" in profile

    def test_ignores_malformed_items(self):
        profile = render_profile("P", None, {"methods": [["only-one"], 42, "Plain string"]})
        assert "Methods: Plain string" in profile

    def test_nothing_but_a_title_renders_nothing(self):
        assert render_profile("A Title", {}, {"methods": []}) == ""
