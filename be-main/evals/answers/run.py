"""Run the grounded-answer pipeline on labelled questions, with a real model.

    LLM_PROVIDER=ollama python -m evals.answers.run

Needs the configured provider and its embedding model (nomic-embed-text, the
model the retrieval benchmark's cached document embeddings come from). Uses a
throwaway database, indexes the three example papers into it, asks every
question through `CorpusQA` — the code /ask runs — and writes per-question
results and a summary to results.json.

Not a CI gate: it needs a model, and a model's answers vary from run to run.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Before any app import reads DATABASE_URL.
_DB_DIR = tempfile.mkdtemp(prefix="researchit-answers-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_DB_DIR) / 'answers.db'}"
os.environ.setdefault("RATE_LIMIT_DISABLED", "1")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core import create_llm_client  # noqa: E402
from db.models import Base  # noqa: E402
from db.repositories import GraphRepository, ProjectRepository  # noqa: E402
from db.session import get_engine, session_scope  # noqa: E402
from evals.answers.harness import RESULTS_PATH, load_questions, score, summarize  # noqa: E402
from evals.retrieval.harness import DOCS_DIR, PAPERS, CachedEmbedder, EmbeddingCache  # noqa: E402
from retrieval.embedder import ClientEmbedder  # noqa: E402
from retrieval.indexer import PaperIndexer  # noqa: E402
from services.rag import CorpusQA  # noqa: E402

PROJECT_ID = "answers-eval"


def build_corpus(client) -> None:
    """The example papers, indexed exactly as the retrieval benchmark indexes them."""
    Base.metadata.create_all(get_engine())
    with session_scope() as session:
        ProjectRepository(session).create(PROJECT_ID, "answer quality benchmark")
        for paper_id, title in PAPERS.items():
            GraphRepository(session, PROJECT_ID).add_processed_paper(
                {"paper_id": paper_id, "title": title, "authors": []}
            )
    indexer = PaperIndexer(CachedEmbedder(EmbeddingCache(), task_hints=True, client=client))
    for paper_id, title in PAPERS.items():
        text = (DOCS_DIR / f"{paper_id}.txt").read_text(encoding="utf-8")
        indexer.index_paper(PROJECT_ID, {"paper_id": paper_id, "title": title}, text)


def main() -> int:
    client = create_llm_client()
    embedder = ClientEmbedder(client)
    if embedder.model_id != "nomic-embed-text":
        print("This benchmark's document embeddings come from nomic-embed-text; run with LLM_PROVIDER=ollama.")
        return 1

    build_corpus(client)
    qa = CorpusQA(client, embedder)
    questions = load_questions()
    records, verdicts = [], []
    started = time.perf_counter()

    for question in questions:
        result = qa.answer(PROJECT_ID, question["question"])
        cited = {source.id: source.chunk.text for source in result.sources}
        answer = {
            "answer": result.answer,
            "insufficient_evidence": result.insufficient_evidence,
            "grounded": result.grounded,
            "dropped_citations": result.dropped_citations,
            "cited_texts": [cited[source_id] for source_id in result.cited],
            "latency_ms": result.latency_ms,
            "usage": result.usage,
        }
        verdict = score(question, answer)
        verdicts.append(verdict)
        records.append({**verdict, "question": question["question"], "answer": result.answer})
        mark = "ok " if verdict["correct"] else "MISS"
        print(f"  {mark} {question['id']} {result.latency_ms / 1000:5.1f}s  {result.answer[:110]!r}")

    summary = summarize(verdicts)
    RESULTS_PATH.write_text(
        json.dumps(
            {
                "model": getattr(client, "model", "unknown"),
                "embedding_model": embedder.model_id,
                "wall_clock_s": round(time.perf_counter() - started, 1),
                "summary": summary,
                "questions": records,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    print("\n" + json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
