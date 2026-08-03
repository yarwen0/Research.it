"""Evaluation harness for :mod:`gap_finder`.

Turns "does the gap finder work?" into a number. The detector sees only the
corpus; the labels file holds attributes it has no access to (what input a
method needs, what a dataset provides, which body region each concerns), and
ground truth is derived from those.

That asymmetry is the point. A gap the detector proposes is only genuine if
the untried pairing could actually be run — and nothing in the corpus says so.
Measuring against the labels quantifies how much of the detector's output is
structurally impossible.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gap_finder import Gap, GapFinder, Paper

EVAL_DIR = Path(__file__).resolve().parent
CORPUS_PATH = EVAL_DIR / "corpus.json"
LABELS_PATH = EVAL_DIR / "labels.json"

# A gap is identified by these fields; score and metadata are not part of it.
GapKey = tuple[str, str | None, str | None, str | None, str | None]


def gap_key(gap: Gap) -> GapKey:
    return (
        gap.gap_type,
        gap.problem,
        gap.method,
        gap.dataset,
        gap.limitation or gap.future_work_label,
    )


@dataclass(frozen=True)
class Metrics:
    """Standard retrieval metrics for one gap type (or all of them)."""

    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def precision(self) -> float:
        predicted = self.true_positives + self.false_positives
        return self.true_positives / predicted if predicted else 0.0

    @property
    def recall(self) -> float:
        actual = self.true_positives + self.false_negatives
        return self.true_positives / actual if actual else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tp": self.true_positives,
            "fp": self.false_positives,
            "fn": self.false_negatives,
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
        }


def load_corpus(path: Path = CORPUS_PATH) -> list[Paper]:
    with path.open("r", encoding="utf-8") as handle:
        return [Paper.from_canonical(entry) for entry in json.load(handle)]


def load_labels(path: Path = LABELS_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class GroundTruth:
    """Derives the set of genuine gaps from the held-out labels."""

    def __init__(self, papers: list[Paper], labels: dict[str, Any]) -> None:
        self.papers = papers
        self.labels = labels
        self.method_requires = labels["method_requires"]
        self.dataset_provides = labels["dataset_provides"]
        self.problem_region = labels["problem_region"]

        # What the corpus actually contains, per problem.
        self.methods_by_problem: dict[str, set[str]] = {}
        self.datasets_by_problem: dict[str, set[str]] = {}
        self.pairs_by_problem: dict[str, set[tuple[str, str]]] = {}

        for paper in papers:
            methods = set(paper.methods)
            datasets = set(paper.datasets)
            self.methods_by_problem.setdefault(paper.problem, set()).update(methods)
            self.datasets_by_problem.setdefault(paper.problem, set()).update(datasets)
            pairs = self.pairs_by_problem.setdefault(paper.problem, set())
            for method in methods:
                for dataset in datasets:
                    pairs.add((method, dataset))

    # -- compatibility -----------------------------------------------------

    def is_runnable(self, problem: str, method: str, dataset: str) -> bool:
        """Could this method actually be run on this dataset for this problem?

        Three ways it cannot be:

        * the dataset does not provide the input the method consumes (a
          temporal model on a single-image dataset);
        * the method is specific to a body region the dataset does not cover
          (an SMPL body regressor on a hand dataset);
        * the dataset covers a different region than the problem studies.
        """
        requires = self.method_requires.get(method)
        provides = self.dataset_provides.get(dataset)
        if requires is None or provides is None:
            return False

        if requires["input"] not in provides["modalities"]:
            return False

        method_region = requires["region"]
        if method_region != "any" and method_region != provides["region"]:
            return False

        expected_region = self.problem_region.get(problem)
        return not (expected_region is not None and provides["region"] != expected_region)

    # -- expected gaps -----------------------------------------------------

    def transfer_gaps(self, gap_type: str) -> set[GapKey]:
        """Untried but runnable (method, dataset) pairings, per problem."""
        expected: set[GapKey] = set()

        for problem in self.methods_by_problem:
            tried = self.pairs_by_problem.get(problem, set())
            for method in self.method_requires:
                for dataset in self.dataset_provides:
                    if (method, dataset) in tried:
                        continue
                    if not self.is_runnable(problem, method, dataset):
                        continue
                    expected.add((gap_type, problem, method, dataset, None))

        return expected

    def limitation_gaps(self) -> set[GapKey]:
        return {
            ("limitation_gap", entry["problem"], None, None, entry["limitation"])
            for entry in self.labels["limitation_gaps"]["true"]
        }

    def future_work_gaps(self) -> set[GapKey]:
        """Future-work labels are keyed on the label alone.

        The detector attributes each to whichever problem requested it most, and
        that attribution is not part of what is being judged.
        """
        return {
            ("future_work_gap", None, None, None, entry["future_work"])
            for entry in self.labels["future_work_gaps"]["true"]
        }

    def all_gaps(self) -> set[GapKey]:
        return (
            self.transfer_gaps("method_transfer")
            | self.transfer_gaps("dataset_transfer")
            | self.limitation_gaps()
            | self.future_work_gaps()
        )


def _normalize_predicted(gap: Gap) -> GapKey:
    """Drop the problem from future-work keys, matching GroundTruth."""
    key = gap_key(gap)
    if key[0] == "future_work_gap":
        return (key[0], None, None, None, key[4])
    return key


def score_predictions(
    predicted: Iterable[Gap], expected: set[GapKey]
) -> tuple[Metrics, dict[str, set[GapKey]]]:
    """Compare predicted gaps against ground truth.

    Returns the metrics plus the sets behind them, so a caller can show which
    gaps were missed rather than only how many.
    """
    predicted_keys = {_normalize_predicted(gap) for gap in predicted}

    true_positives = predicted_keys & expected
    false_positives = predicted_keys - expected
    false_negatives = expected - predicted_keys

    metrics = Metrics(
        true_positives=len(true_positives),
        false_positives=len(false_positives),
        false_negatives=len(false_negatives),
    )
    breakdown = {
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
    }
    return metrics, breakdown


def evaluate(
    papers: list[Paper],
    truth: GroundTruth,
    *,
    top_k_per_type: int = 5,
    **finder_kwargs: Any,
) -> dict[str, Any]:
    """Run the finder once and score it overall and per gap type."""
    finder = GapFinder(papers, **finder_kwargs)
    predictions = finder.find_all_gaps(top_k_per_type=top_k_per_type)

    expected = truth.all_gaps()
    overall, breakdown = score_predictions(predictions, expected)

    per_type: dict[str, dict[str, Any]] = {}
    expected_by_type = {
        "method_transfer": truth.transfer_gaps("method_transfer"),
        "dataset_transfer": truth.transfer_gaps("dataset_transfer"),
        "limitation_gap": truth.limitation_gaps(),
        "future_work_gap": truth.future_work_gaps(),
    }
    for gap_type, type_expected in expected_by_type.items():
        type_predicted = [g for g in predictions if g.gap_type == gap_type]
        type_metrics, _ = score_predictions(type_predicted, type_expected)
        per_type[gap_type] = type_metrics.as_dict()

    return {
        "config": {"top_k_per_type": top_k_per_type, **finder_kwargs},
        "num_papers": len(papers),
        "num_predicted": len(predictions),
        "num_expected": len(expected),
        "overall": overall.as_dict(),
        "per_type": per_type,
        "breakdown": breakdown,
    }
