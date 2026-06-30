"""Example CLI for the symbolic gap finder pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from gap_finder import GapFinder, Gap, load_papers_from_path


def summarize_gaps(gaps: List[Gap]) -> None:
    for gap in gaps:
        headline = [f"[{gap.gap_type}]", f"problem={gap.problem}"]
        if gap.method:
            headline.append(f"method={gap.method}")
        if gap.dataset:
            headline.append(f"dataset={gap.dataset}")
        if gap.limitation:
            headline.append(f"limitation={gap.limitation}")
        if gap.future_work_label:
            headline.append(f"future_work={gap.future_work_label}")
        headline.append(f"score={gap.score}")
        print(" ".join(headline))
        if gap.metadata:
            print(json.dumps(gap.metadata, indent=2))
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the symbolic gap finder on a normalized corpus")
    parser.add_argument(
        "corpus",
        nargs="?",
        default=Path("examples") / "sample_corpus.json",
        help="Path to a JSON file that contains a list of canonicalized papers.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        dest="top_k",
        help="Keep at most this many gaps per gap type.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Disable loose heuristics to favor precision.",
    )
    args = parser.parse_args()

    papers = load_papers_from_path(args.corpus)
    finder = GapFinder(papers, loose_mode=not args.strict)
    gaps = finder.find_all_gaps(top_k_per_type=args.top_k)

    print("Detected gaps:\n")
    summarize_gaps(gaps)

    title_conditions = [gap.to_title_condition() for gap in gaps]
    print("Title conditions (feed these to a lightweight LLM prompt):")
    print(json.dumps(title_conditions, indent=2))


if __name__ == "__main__":
    main()
