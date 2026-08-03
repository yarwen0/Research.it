"""Run the gap-finder evaluation.

    python -m evals.run_eval                 # score the shipped defaults
    python -m evals.run_eval --sweep         # search the threshold space
    python -m evals.run_eval --show-misses   # list what it got wrong
    python -m evals.run_eval --json out.json # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import product
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.harness import (  # noqa: E402
    GroundTruth,
    evaluate,
    load_corpus,
    load_labels,
)

# The settings api/api.py currently passes when running gap analysis.
SHIPPED_CONFIG: dict[str, Any] = {
    "method_transfer_min_score": 0,
    "dataset_transfer_min_score": 0,
    "limitation_pressure_threshold": 1,
    "limitation_ratio_threshold": 0.5,
    "future_work_min_mentions": 1,
    "loose_mode": True,
}

SWEEP_GRID: dict[str, list[Any]] = {
    "method_transfer_min_score": [0, 1, 2],
    "dataset_transfer_min_score": [0, 1, 2],
    "limitation_pressure_threshold": [1, 2, 3],
    "limitation_ratio_threshold": [0.3, 0.5, 0.7],
    "future_work_min_mentions": [1, 2, 3],
    "loose_mode": [True, False],
}


def _format_row(label: str, metrics: dict[str, Any]) -> str:
    return (
        f"  {label:<20} "
        f"P {metrics['precision']:.3f}  "
        f"R {metrics['recall']:.3f}  "
        f"F1 {metrics['f1']:.3f}   "
        f"(tp {metrics['tp']}, fp {metrics['fp']}, fn {metrics['fn']})"
    )


def report(result: dict[str, Any], *, show_misses: bool = False) -> None:
    print(f"\nCorpus: {result['num_papers']} papers")
    print(f"Predicted {result['num_predicted']} gaps, {result['num_expected']} expected\n")

    print(_format_row("OVERALL", result["overall"]))
    print()
    for gap_type, metrics in result["per_type"].items():
        print(_format_row(gap_type, metrics))

    if not show_misses:
        print()
        return

    breakdown = result["breakdown"]
    print("\n  Missed (in ground truth, not predicted):")
    for key in sorted(breakdown["false_negatives"], key=str):
        print(f"    - {key}")
    print("\n  Spurious (predicted, not in ground truth):")
    for key in sorted(breakdown["false_positives"], key=str):
        print(f"    - {key}")
    print()


def sweep(papers, truth, *, top_k_per_type: int) -> list[dict[str, Any]]:
    """Score every combination in the grid, best F1 first."""
    keys = list(SWEEP_GRID)
    results = []

    for values in product(*(SWEEP_GRID[k] for k in keys)):
        config = dict(zip(keys, values))
        result = evaluate(papers, truth, top_k_per_type=top_k_per_type, **config)
        results.append(result)

    results.sort(key=lambda r: r["overall"]["f1"], reverse=True)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sweep", action="store_true", help="search the threshold grid"
    )
    parser.add_argument(
        "--top", type=int, default=5, help="how many sweep results to print"
    )
    parser.add_argument(
        "--top-k-per-type",
        type=int,
        default=5,
        help="gaps the finder returns per type (default matches the API)",
    )
    parser.add_argument(
        "--show-misses", action="store_true", help="list false positives/negatives"
    )
    parser.add_argument("--json", type=Path, help="write full results as JSON")
    args = parser.parse_args()

    papers = load_corpus()
    truth = GroundTruth(papers, load_labels())

    if not args.sweep:
        result = evaluate(
            papers, truth, top_k_per_type=args.top_k_per_type, **SHIPPED_CONFIG
        )
        print("=== Shipped configuration ===")
        report(result, show_misses=args.show_misses)

        if args.json:
            args.json.write_text(
                json.dumps(_serializable(result), indent=2), encoding="utf-8"
            )
        return 0

    results = sweep(papers, truth, top_k_per_type=args.top_k_per_type)

    print(f"=== Threshold sweep: {len(results)} configurations ===")
    for rank, result in enumerate(results[: args.top], start=1):
        config = {k: v for k, v in result["config"].items() if k != "top_k_per_type"}
        print(f"\n#{rank}  F1 {result['overall']['f1']:.3f}")
        print(f"  {config}")
        print(_format_row("overall", result["overall"]))

    shipped = evaluate(
        papers, truth, top_k_per_type=args.top_k_per_type, **SHIPPED_CONFIG
    )
    print("\n=== Shipped configuration, for comparison ===")
    report(shipped)

    if args.json:
        args.json.write_text(
            json.dumps([_serializable(r) for r in results], indent=2), encoding="utf-8"
        )
    return 0


def _serializable(result: dict[str, Any]) -> dict[str, Any]:
    """Drop the key sets, which are tuples and not JSON-encodable."""
    out = {k: v for k, v in result.items() if k != "breakdown"}
    out["breakdown"] = {
        name: sorted(str(k) for k in keys)
        for name, keys in result["breakdown"].items()
    }
    return out


if __name__ == "__main__":
    raise SystemExit(main())
