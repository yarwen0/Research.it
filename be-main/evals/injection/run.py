"""Score the prompt-injection screen on labelled cases.

    python -m evals.injection.run              # both splits
    python -m evals.injection.run --show-dev   # what the screen got wrong in dev

Cases come in three kinds: attacks, ordinary paper prose, and prose *about*
attacks that quotes them. Each kind is reported on its own, because the
number that matters for the third is the false-positive rate, not recall.

The detector was designed against the dev split only. Test-split errors are
reported, not fixed — a pattern added after seeing one would make its score
meaningless.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from retrieval.screening import screen

CASES_PATH = Path(__file__).resolve().parent / "cases.json"


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(cases: list[dict]) -> dict:
    """Confusion counts and rates for one set of cases."""
    results = [(case, screen(case["text"])) for case in cases]
    tp = sum(1 for case, s in results if case["injection"] and s.flagged)
    fn = sum(1 for case, s in results if case["injection"] and not s.flagged)
    fp = sum(1 for case, s in results if not case["injection"] and s.flagged)
    tn = sum(1 for case, s in results if not case["injection"] and not s.flagged)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    by_kind = {}
    for kind in ("injection", "benign", "discussion"):
        of_kind = [s for case, s in results if case["kind"] == kind]
        by_kind[kind] = {
            "cases": len(of_kind),
            "flagged": sum(s.flagged for s in of_kind),
        }
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(2 * precision * recall / (precision + recall), 3) if precision + recall else 0.0,
        "by_kind": by_kind,
        "errors": [
            {"id": case["id"], "kind": case["kind"], "score": s.score, "reasons": s.reasons, "text": case["text"]}
            for case, s in results
            if case["injection"] != s.flagged
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--show-dev", action="store_true", help="list the dev split's errors")
    args = parser.parse_args(argv)

    cases = load_cases()
    print(f"\n{len(cases)} cases\n")
    print(f"  {'split':<6} {'precision':>9} {'recall':>7} {'F1':>6}   attacks caught   prose flagged   attack-prose flagged")
    for split in ("dev", "test"):
        result = evaluate([case for case in cases if case["split"] == split])
        kinds = result["by_kind"]
        print(
            f"  {split:<6} {result['precision']:>9.3f} {result['recall']:>7.3f} {result['f1']:>6.3f}"
            f"   {kinds['injection']['flagged']:>7}/{kinds['injection']['cases']:<8}"
            f"{kinds['benign']['flagged']:>7}/{kinds['benign']['cases']:<9}"
            f"{kinds['discussion']['flagged']:>7}/{kinds['discussion']['cases']}"
        )
        if split == "dev" and args.show_dev:
            for error in result["errors"]:
                print(f"      {error['id']} {error['kind']:<10} score {error['score']:<5} {error['reasons']}  {error['text'][:70]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
