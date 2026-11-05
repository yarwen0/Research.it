"""Run the retrieval benchmark.

    python -m evals.retrieval.run                  # score from cached embeddings
    python -m evals.retrieval.run --show-misses    # list what the default missed
    python -m evals.retrieval.run --refresh        # embed what the cache lacks
    python -m evals.retrieval.run --json out.json  # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evals.retrieval.harness import (
    DOCS_DIR,
    PAPERS,
    VARIANTS,
    CachedEmbedder,
    EmbeddingCache,
    build_corpus,
    check_labels,
    evaluate,
    load_questions,
)

COLUMNS = ("hit@1", "hit@3", "hit@5", "hit@10", "mrr", "coverage@10")


def _row(label: str, metrics: dict[str, float], columns=COLUMNS) -> str:
    return f"  {label:<34}" + "".join(f"{metrics.get(c, 0):>9.3f}" for c in columns)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score retrieval strategies on labelled questions.")
    parser.add_argument("--refresh", action="store_true", help="embed anything the cache lacks")
    parser.add_argument("--show-misses", action="store_true", help="list the default's misses at k=5")
    parser.add_argument("--json", type=Path, help="write metrics to this file")
    args = parser.parse_args(argv)

    client = None
    if args.refresh:
        from core import create_llm_client

        client = create_llm_client()
        if client.embedding_model_id != "nomic-embed-text":
            parser.error("--refresh needs LLM_PROVIDER=ollama with nomic-embed-text")

    # Broken labels are a bug in the benchmark, not a retrieval miss.
    chunks, _ = build_corpus(
        CachedEmbedder(EmbeddingCache(), task_hints=True, client=client), headers=True
    )
    broken = check_labels(chunks, load_questions())
    if broken:
        print("Broken labels:\n  " + "\n  ".join(broken))
        return 1

    report = evaluate(refresh=args.refresh, client=client)
    print(
        f"\n{report['questions']} questions over {len(PAPERS)} papers in {DOCS_DIR.name}/ "
        f"({len(chunks)} passages), embedded with nomic-embed-text\n"
    )
    print(f"  {'variant':<34}" + "".join(f"{c:>9}" for c in COLUMNS))
    for variant in VARIANTS:
        print(_row(variant.name, report["variants"][variant.name]["overall"]))

    print("\nBy question type, hit@5 / MRR / coverage@10:\n")
    kinds = sorted(next(iter(report["variants"].values()))["by_type"])
    print(f"  {'variant':<34}" + "".join(f"{kind:>24}" for kind in kinds))
    for variant in VARIANTS:
        by_type = report["variants"][variant.name]["by_type"]
        print(
            f"  {variant.name:<34}"
            + "".join(
                f"   {by_type[k]['hit@5']:.3f} / {by_type[k]['mrr']:.3f} / {by_type[k]['coverage@10']:.3f}"
                for k in kinds
            )
        )

    if args.show_misses:
        default = report["variants"][VARIANTS[0].name]["results"]
        misses = [r for r in default if r.first_relevant is None or r.first_relevant > 5]
        print(f"\nMissed at k=5 by the default ({len(misses)}):")
        for result in misses:
            rank = result.first_relevant or "not in top 10"
            print(f"  {result.question.id} [{result.question.type}] rank {rank}: {result.question.question}")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    name: {"overall": data["overall"], "by_type": data["by_type"]}
                    for name, data in report["variants"].items()
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
