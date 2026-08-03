"""The gap finder must return the same gaps for the same corpus.

Caught by the evaluation harness: identical input and configuration produced
F1 scores ranging 0.425–0.520 across runs. The finder iterates over sets, and
Python randomises string hashing per process, so candidate order — and
therefore which ties survive the top_k cut — varied run to run.

A subprocess is required: PYTHONHASHSEED is fixed at interpreter startup, so
one process cannot exercise two different orderings.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BE_MAIN = Path(__file__).resolve().parent.parent

_SCRIPT = """
import json, sys
sys.path.insert(0, {be_main!r})
from evals.harness import load_corpus
from gap_finder import GapFinder

papers = load_corpus()
finder = GapFinder(
    papers,
    method_transfer_min_score=0,
    dataset_transfer_min_score=0,
    limitation_pressure_threshold=1,
    limitation_ratio_threshold=0.5,
    future_work_min_mentions=1,
    loose_mode=True,
)
gaps = finder.find_all_gaps(top_k_per_type=10)
print(json.dumps([
    [g.gap_type, g.problem, g.method, g.dataset, g.limitation, g.future_work_label, g.score]
    for g in gaps
]))
"""


def _gaps_with_hash_seed(seed: str) -> list:
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT.format(be_main=str(BE_MAIN))],
        cwd=str(BE_MAIN),
        capture_output=True,
        text=True,
        env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin", "LLM_PROVIDER": "ollama"},
        check=True,
    )
    return json.loads(result.stdout)


def test_output_is_stable_across_hash_seeds():
    baseline = _gaps_with_hash_seed("0")

    for seed in ("1", "42", "12345"):
        assert _gaps_with_hash_seed(seed) == baseline, (
            f"gap output changed under PYTHONHASHSEED={seed}; "
            "set iteration order is leaking into results"
        )


def test_repeated_calls_agree_within_a_process():
    from evals.harness import load_corpus
    from gap_finder import GapFinder

    papers = load_corpus()

    def run() -> list:
        finder = GapFinder(papers, loose_mode=True)
        return [
            (g.gap_type, g.problem, g.method, g.dataset, g.score)
            for g in finder.find_all_gaps(top_k_per_type=10)
        ]

    assert run() == run()
