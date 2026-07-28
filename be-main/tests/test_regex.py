"""Tests for the stable helpers in utils.regex (vendored refextract, GPL-2.0+)."""

from __future__ import annotations

from datetime import datetime

from utils.regex import compute_months, compute_years, remove_year, extract_references_from_string


class TestComputeMonths:
    def test_all_zero_padded_months(self):
        assert compute_months() == "|".join(f"{m:02d}" for m in range(1, 13))


class TestComputeYears:
    def test_starts_at_1991_and_ends_at_current_year(self):
        tokens = compute_years().split("|")
        assert tokens[0] == "91"
        assert tokens[-1] == str(datetime.now().year)[2:]
        assert all(len(t) == 2 for t in tokens)

    def test_custom_start_year(self):
        tokens = compute_years(2013).split("|")
        assert tokens[0] == "13"


class TestRemoveYear:
    def test_removes_bracketed_year(self):
        result = remove_year("Smith [2019] on segmentation")
        assert "2019" not in result
        assert "Smith" in result

    def test_removes_parenthesized_year(self):
        assert "2020" not in remove_year("(2020)")

    def test_removes_bare_year_with_surrounding_spaces(self):
        assert remove_year("foo 1998 bar") == "foobar"

    def test_explicit_year_only_removes_that_year(self):
        result = remove_year("keep 2020 drop 2019", year="2019")
        assert "2019" not in result
        assert "2020" in result


class TestExtractReferencesFromString:
    def test_stub_returns_empty_list(self):
        assert extract_references_from_string("Smith et al. (2020). Some paper.") == []
