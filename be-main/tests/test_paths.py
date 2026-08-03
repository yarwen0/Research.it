"""Tests for client-supplied path containment."""

from __future__ import annotations

import pytest

from utils.paths import BASE_DIR, DATA_DIR, UnsafePathError, resolve_data_path


class TestResolveDataPath:
    def test_accepts_relative_path_handed_out_by_the_pipeline(self):
        resolved = resolve_data_path("data/processed_papers_topic_20260101_000000.json")
        assert resolved == DATA_DIR / "processed_papers_topic_20260101_000000.json"

    def test_accepts_nested_project_path(self):
        resolved = resolve_data_path("data/abc123/reference_graph.json")
        assert resolved == DATA_DIR / "abc123" / "reference_graph.json"

    def test_accepts_absolute_path_inside_data_dir(self):
        target = DATA_DIR / "reviews" / "review_1.json"
        assert resolve_data_path(str(target)) == target

    def test_strips_surrounding_whitespace(self):
        resolved = resolve_data_path("  data/reviews/review_1.json  ")
        assert resolved == DATA_DIR / "reviews" / "review_1.json"

    @pytest.mark.parametrize(
        "candidate",
        [
            "/etc/passwd",
            "data/../../etc/passwd",
            "data/../config.py",
            "../config.py",
            "data/../.env",
        ],
    )
    def test_rejects_paths_outside_data_dir(self, candidate):
        with pytest.raises(UnsafePathError):
            resolve_data_path(candidate)

    def test_rejects_sibling_directory_with_shared_prefix(self):
        # `data_backup` shares a string prefix with `data` but is not inside it.
        with pytest.raises(UnsafePathError):
            resolve_data_path(str(BASE_DIR / "data_backup" / "leak.json"))

    @pytest.mark.parametrize("candidate", ["", "   "])
    def test_rejects_blank_paths(self, candidate):
        with pytest.raises(UnsafePathError):
            resolve_data_path(candidate)

    def test_rejects_symlink_escaping_data_dir(self, tmp_path):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        outside = tmp_path / "secret.json"
        outside.write_text("{}", encoding="utf-8")

        link = DATA_DIR / "escape_link.json"
        link.unlink(missing_ok=True)
        link.symlink_to(outside)
        try:
            with pytest.raises(UnsafePathError):
                resolve_data_path("data/escape_link.json")
        finally:
            link.unlink(missing_ok=True)
