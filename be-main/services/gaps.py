"""Turn processed papers into suggested papers via symbolic gap analysis.

The LLM only verbalizes here — `GapFinder` decides what the gaps are, and the
generator phrases them as paper titles. That split is deliberate: it keeps the
reasoning inspectable and measurable (see `evals/`) instead of hidden in a
prompt.
"""

from __future__ import annotations

import logging
from typing import Any

from gap_finder import GapFinder, Paper

logger = logging.getLogger(__name__)

# Loose settings, matching what the API has always passed. Note that
# `loose_mode` clamps every threshold below it in GapFinder's constructor, so
# these numbers are largely inert — see evals/README.md.
GAP_FINDER_SETTINGS: dict[str, Any] = {
    "method_transfer_min_score": 0,
    "dataset_transfer_min_score": 0,
    "limitation_pressure_threshold": 1,
    "limitation_ratio_threshold": 0.5,
    "future_work_min_mentions": 1,
    "loose_mode": True,
}

# Gaps returned per type. The API's long-standing value; measured as the
# precision-favouring end of the trade-off in evals/README.md.
TOP_K_PER_TYPE = 5

MAX_SUGGESTIONS = 10


def to_gap_finder_papers(processed_papers: list[dict[str, Any]]) -> list[Paper]:
    """Project pipeline output onto the finder's normalized model.

    Papers that fail to convert are skipped rather than aborting the run — one
    malformed extraction should not cost the whole analysis.
    """
    papers: list[Paper] = []

    for paper in processed_papers:
        normalized = paper.get("normalized") or {}
        try:
            papers.append(
                Paper.from_canonical(
                    {
                        "paper_id": paper.get("paper_id", ""),
                        "problem": normalized.get("problem", ""),
                        "methods": normalized.get("methods", []),
                        "datasets": normalized.get("datasets", []),
                        "limitations_implied": normalized.get("limitations_implied", []),
                        "limitations_explicit": normalized.get("limitations_explicit", []),
                        "future_work": normalized.get("future_work", []),
                    }
                )
            )
        except Exception as exc:
            logger.warning(
                "Failed to convert paper %s for gap analysis: %s",
                paper.get("paper_id", "unknown"),
                exc,
            )

    return papers


def find_gaps(papers: list[Paper]) -> list[dict[str, Any]]:
    """Run gap detection and flatten the results for the verbalizer."""
    if not papers:
        logger.warning("No papers available for gap analysis")
        return []

    gaps = GapFinder(papers, **GAP_FINDER_SETTINGS).find_all_gaps(
        top_k_per_type=TOP_K_PER_TYPE
    )

    if not gaps:
        logger.warning("No research gaps found")
        return []

    return [
        {
            "gap_type": gap.gap_type,
            "problem": gap.problem,
            "score": gap.score,
            "method": gap.method,
            "dataset": gap.dataset,
            "limitation": gap.limitation,
            "future_work": gap.future_work_label,
        }
        for gap in gaps
    ]


def generate_suggested_papers(
    processed_papers: list[dict[str, Any]],
    user_prompt: str,
    topic_generator: Any,
) -> list[dict[str, Any]]:
    """Full path from processed papers to suggested follow-up papers."""
    gaps = find_gaps(to_gap_finder_papers(processed_papers))
    if not gaps:
        return []

    try:
        suggestions = topic_generator.generate_paper_suggestions(
            gaps=gaps,
            user_prompt=user_prompt,
            num_papers=min(MAX_SUGGESTIONS, len(gaps)),
        )
    except Exception as exc:
        # A failed verbalization should not sink an otherwise complete run.
        logger.error("Failed to generate paper suggestions: %s", exc)
        return []

    logger.info("Generated %s paper suggestions", len(suggestions))
    return suggestions
