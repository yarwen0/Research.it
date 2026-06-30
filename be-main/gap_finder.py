"""Symbolic research gap detection utilities.

This module implements the gap discovery loop described in the prompt:

1. Normalize the paper corpus into a uniform data model.
2. Build coverage indices (problem ↔ method ↔ dataset ↔ limitation).
3. Detect concrete gap patterns and score them based on corpus density.
4. Emit structured title conditions so an LLM can act purely as a
   verbalizer instead of the decision engine.

The implementation favors transparency – every gap object carries the
supporting counts and reference paper identifiers so downstream layers
can explain *why* a gap was surfaced.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Dict, Iterable, List, Sequence


def _unwrap_normalized_list(items: Iterable | None) -> List[str]:
    """Return only the normalized tokens from schema-conforming lists."""

    normalized: List[str] = []
    if not items:
        return normalized
    for item in items:
        if isinstance(item, (list, tuple)) and item:
            normalized.append(str(item[0]))
        elif isinstance(item, str):
            normalized.append(item)
    return normalized


@dataclass(frozen=True)
class Paper:
    """Normalized representation of a paper entry."""

    paper_id: str
    problem: str
    methods: List[str]
    datasets: List[str]
    limitations_implied: List[str]
    limitations_explicit: List[str]
    future_work: List[str]

    @classmethod
    def from_canonical(cls, data: Dict) -> "Paper":
        return cls(
            paper_id=data.get("paper_id") or data["id"],
            problem=data.get("problem", ""),
            methods=_unwrap_normalized_list(data.get("methods")),
            datasets=_unwrap_normalized_list(data.get("datasets")),
            limitations_implied=_unwrap_normalized_list(data.get("limitations_implied")),
            limitations_explicit=_unwrap_normalized_list(data.get("limitations_explicit")),
            future_work=_unwrap_normalized_list(data.get("future_work")),
        )


@dataclass
class Gap:
    gap_type: str
    problem: str | None
    score: int
    method: str | None = None
    dataset: str | None = None
    limitation: str | None = None
    future_work_label: str | None = None
    metadata: Dict[str, object] = field(default_factory=dict)

    def to_title_condition(self) -> Dict[str, object]:
        """Return a minimal spec consumable by a title generator LLM."""

        return {
            "gap_type": self.gap_type,
            "problem": self.problem,
            "method": self.method,
            "dataset": self.dataset,
            "target_limitation": self.limitation,
            "future_work_label": self.future_work_label,
            "score": self.score,
        }


class GapFinder:
    """Compute gap candidates from a normalized corpus."""

    def __init__(
        self,
        papers: Sequence[Paper],
        *,
        method_transfer_min_score: int = 1,
        dataset_transfer_min_score: int = 1,
        limitation_pressure_threshold: int = 2,
        limitation_ratio_threshold: float = 0.7,
        future_work_min_mentions: int = 2,
        loose_mode: bool = True,
    ) -> None:
        self.papers = list(papers)
        self.method_transfer_min_score = method_transfer_min_score
        self.dataset_transfer_min_score = dataset_transfer_min_score
        self.limitation_pressure_threshold = limitation_pressure_threshold
        self.limitation_ratio_threshold = limitation_ratio_threshold
        self.future_work_min_mentions = future_work_min_mentions
        self.loose_mode = loose_mode
        if self.loose_mode:
            self.method_transfer_min_score = 0
            self.dataset_transfer_min_score = 0
            self.limitation_pressure_threshold = max(1, limitation_pressure_threshold // 2 or 1)
            self.limitation_ratio_threshold = max(0.2, limitation_ratio_threshold * 0.5)
            self.future_work_min_mentions = max(1, future_work_min_mentions - 1)

        self.methods_by_problem: Dict[str, set[str]] = defaultdict(set)
        self.datasets_by_problem: Dict[str, set[str]] = defaultdict(set)
        self.methods_by_problem_dataset: Dict[tuple[str, str], set[str]] = defaultdict(set)
        self.datasets_by_problem_method: Dict[tuple[str, str], set[str]] = defaultdict(set)
        self.problem_to_paper_ids: Dict[str, List[str]] = defaultdict(list)
        self.problem_dataset_to_paper_ids: Dict[tuple[str, str], List[str]] = defaultdict(list)
        self.problem_method_to_paper_ids: Dict[tuple[str, str], List[str]] = defaultdict(list)
        self.count_problem: Counter[str] = Counter()
        self.count_problem_dataset: Counter[tuple[str, str]] = Counter()
        self.count_problem_method: Counter[tuple[str, str]] = Counter()
        self.count_problem_method_dataset: Counter[tuple[str, str, str]] = Counter()
        self.limitations_by_problem: Counter[tuple[str, str]] = Counter()
        self.limitations_by_problem_method: Counter[tuple[str, str, str]] = Counter()
        self.future_work_counts: Counter[str] = Counter()
        self.future_work_by_problem: Dict[str, Counter[str]] = defaultdict(Counter)
        self.method_global_counts: Counter[str] = Counter()
        self.dataset_global_counts: Counter[str] = Counter()

        self._build_indices()

    def _build_indices(self) -> None:
        for paper in self.papers:
            problem = paper.problem
            self.problem_to_paper_ids[problem].append(paper.paper_id)
            self.count_problem[problem] += 1

            unique_methods = list(dict.fromkeys(paper.methods))
            unique_datasets = list(dict.fromkeys(paper.datasets))

            self.methods_by_problem[problem].update(unique_methods)
            self.datasets_by_problem[problem].update(unique_datasets)
            for dataset in unique_datasets:
                self.dataset_global_counts[dataset] += 1

            for dataset in unique_datasets:
                self.count_problem_dataset[(problem, dataset)] += 1
                self.problem_dataset_to_paper_ids[(problem, dataset)].append(paper.paper_id)
                self.methods_by_problem_dataset[(problem, dataset)].update(unique_methods)

            for method in unique_methods:
                self.count_problem_method[(problem, method)] += 1
                self.problem_method_to_paper_ids[(problem, method)].append(paper.paper_id)
                self.datasets_by_problem_method[(problem, method)].update(unique_datasets)
                self.method_global_counts[method] += 1

            for method in unique_methods:
                for dataset in unique_datasets:
                    self.count_problem_method_dataset[(problem, method, dataset)] += 1

            limitation_tokens = paper.limitations_implied + paper.limitations_explicit
            for limitation in limitation_tokens:
                self.limitations_by_problem[(problem, limitation)] += 1
                for method in unique_methods:
                    self.limitations_by_problem_method[(problem, method, limitation)] += 1

            for fw in paper.future_work:
                self.future_work_counts[fw] += 1
                self.future_work_by_problem[problem][fw] += 1

    def find_method_transfer_gaps(self, *, top_k: int = 5) -> List[Gap]:
        gaps: List[Gap] = []
        global_methods = set(self.method_global_counts)
        global_datasets = set(self.dataset_global_counts)
        for problem, methods in self.methods_by_problem.items():
            method_pool = set(methods)
            dataset_pool = set(self.datasets_by_problem.get(problem, set()))
            if self.loose_mode:
                if not method_pool:
                    method_pool = set(global_methods)
                else:
                    method_pool.update(global_methods)
                if not dataset_pool:
                    dataset_pool = set(global_datasets)
                else:
                    dataset_pool.update(global_datasets)
            if not method_pool or not dataset_pool:
                continue
            original_datasets = self.datasets_by_problem.get(problem, set())
            for dataset in dataset_pool:
                used_methods = self.methods_by_problem_dataset.get((problem, dataset), set())
                skip_methods = used_methods if dataset in original_datasets else set()
                candidate_methods = method_pool - skip_methods if skip_methods else method_pool
                for method in candidate_methods:
                    score = min(
                        self.count_problem.get(problem, 0),
                        self.count_problem_dataset.get((problem, dataset), 0),
                        self.count_problem_method.get((problem, method), 0),
                    )
                    if score < self.method_transfer_min_score:
                        continue
                    metadata = {
                        "method_papers": self.problem_method_to_paper_ids.get((problem, method), []),
                        "dataset_papers": self.problem_dataset_to_paper_ids.get((problem, dataset), []),
                    }
                    gaps.append(
                        Gap(
                            gap_type="method_transfer",
                            problem=problem,
                            method=method,
                            dataset=dataset,
                            score=score,
                            metadata=metadata,
                        )
                    )
        gaps.sort(key=lambda g: g.score, reverse=True)
        return gaps[:top_k]

    def find_dataset_transfer_gaps(self, *, top_k: int = 5) -> List[Gap]:
        gaps: List[Gap] = []
        global_methods = set(self.method_global_counts)
        global_datasets = set(self.dataset_global_counts)
        for problem, methods in self.methods_by_problem.items():
            method_pool = set(methods)
            dataset_pool = set(self.datasets_by_problem.get(problem, set()))
            if self.loose_mode:
                if not method_pool:
                    method_pool = set(global_methods)
                else:
                    method_pool.update(global_methods)
                if not dataset_pool:
                    dataset_pool = set(global_datasets)
                else:
                    dataset_pool.update(global_datasets)
            if not method_pool:
                continue
            original_methods = self.methods_by_problem.get(problem, set())
            for method in method_pool:
                used_datasets = self.datasets_by_problem_method.get((problem, method), set())
                skip_datasets = used_datasets if method in original_methods else set()
                candidate_datasets = dataset_pool - skip_datasets if skip_datasets else dataset_pool
                for dataset in candidate_datasets:
                    score = min(
                        self.count_problem.get(problem, 0),
                        self.count_problem_method.get((problem, method), 0),
                        self.count_problem_dataset.get((problem, dataset), 0),
                    )
                    if score < self.dataset_transfer_min_score:
                        continue
                    metadata = {
                        "method_papers": self.problem_method_to_paper_ids.get((problem, method), []),
                        "dataset_papers": self.problem_dataset_to_paper_ids.get((problem, dataset), []),
                    }
                    gaps.append(
                        Gap(
                            gap_type="dataset_transfer",
                            problem=problem,
                            method=method,
                            dataset=dataset,
                            score=score,
                            metadata=metadata,
                        )
                    )
        gaps.sort(key=lambda g: g.score, reverse=True)
        return gaps[:top_k]

    def find_limitation_gaps(self, *, top_k: int = 5) -> List[Gap]:
        gaps: List[Gap] = []
        for (problem, limitation), count in self.limitations_by_problem.items():
            if count < self.limitation_pressure_threshold:
                continue
            methods = self.methods_by_problem.get(problem, set())
            if not methods:
                continue
            method_ratios: Dict[str, float] = {}
            saturated = True
            allowed_failures = 0
            if self.loose_mode:
                allowed_failures = max(1, len(methods) // 2 or 1)
            failures = 0
            for method in methods:
                total = self.count_problem_method.get((problem, method), 0)
                if total == 0:
                    continue
                with_limitation = self.limitations_by_problem_method.get((problem, method, limitation), 0)
                ratio = with_limitation / total if total else 0.0
                method_ratios[method] = ratio
                if ratio < self.limitation_ratio_threshold:
                    failures += 1
                    if failures > allowed_failures:
                        saturated = False
                        break
            if saturated and method_ratios:
                metadata = {
                    "limitation_count": count,
                    "method_ratios": {k: round(v, 2) for k, v in method_ratios.items()},
                }
                gaps.append(
                    Gap(
                        gap_type="limitation_gap",
                        problem=problem,
                        limitation=limitation,
                        score=count,
                        metadata=metadata,
                    )
                )
        gaps.sort(key=lambda g: g.score, reverse=True)
        return gaps[:top_k]

    def find_future_work_gaps(self, *, top_k: int = 5) -> List[Gap]:
        problem_candidates: Dict[str, Dict[str, int]] = defaultdict(dict)
        for problem, fw_counter in self.future_work_by_problem.items():
            for fw_label, count in fw_counter.items():
                problem_candidates[fw_label][problem] = count

        gaps: List[Gap] = []
        future_work_realized: Dict[str, int] = {
            label: self.method_global_counts.get(label, 0) + self.count_problem.get(label, 0)
            for label in self.future_work_counts
        }
        for fw_label, count in self.future_work_counts.items():
            if count < self.future_work_min_mentions:
                continue
            realized = future_work_realized.get(fw_label, 0)
            if not self.loose_mode and realized > 0:
                continue
            if self.loose_mode and realized >= count:
                continue
            demand_map = problem_candidates.get(fw_label)
            if not demand_map:
                continue
            top_problem = max(demand_map.items(), key=lambda item: item[1])[0]
            metadata = {
                "requested_by_problems": demand_map,
                "global_mentions": count,
            }
            gaps.append(
                Gap(
                    gap_type="future_work_gap",
                    problem=top_problem,
                    future_work_label=fw_label,
                    score=count,
                    metadata=metadata,
                )
            )
        gaps.sort(key=lambda g: g.score, reverse=True)
        return gaps[:top_k]

    def find_all_gaps(self, *, top_k_per_type: int = 5) -> List[Gap]:
        results: List[Gap] = []
        results.extend(self.find_method_transfer_gaps(top_k=top_k_per_type))
        results.extend(self.find_dataset_transfer_gaps(top_k=top_k_per_type))
        results.extend(self.find_limitation_gaps(top_k=top_k_per_type))
        results.extend(self.find_future_work_gaps(top_k=top_k_per_type))
        return results


def load_papers_from_path(path: str | Path) -> List[Paper]:
    path_obj = Path(path)
    with path_obj.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return [Paper.from_canonical(entry) for entry in data]
