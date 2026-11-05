"""Retrieval benchmark: does the passage that answers a question come back?

The corpus is the three papers in `examples/docs`, chunked by the production
chunker and embedded the way the indexer embeds them. Questions in
`questions.json` are labelled with short evidence phrases rather than chunk
ids, so the labels survive a change to chunking: a retrieved passage is
relevant when it comes from the labelled paper and contains one of that
paper's evidence phrases. Phrases from one paper are alternatives — any
passage that answers will do — while a question with evidence in several
papers needs each of them.

Embeddings are read from `embeddings.npz`, computed once with nomic-embed-text
and committed, so CI scores real embeddings with no model and no network.
Running with `refresh=True` computes anything missing through the configured
provider. Vectors are stored as float16, as pgvector's halfvec would hold
them; that moves a cosine score by about 1e-3.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from retrieval.hybrid import CANDIDATES, MAX_PER_PAPER, cap_per_paper, combine
from retrieval.indexer import PaperIndexer
from retrieval.lexical import BM25, tokenize

EVAL_DIR = Path(__file__).resolve().parent
DOCS_DIR = EVAL_DIR.parent.parent / "examples" / "docs"
QUESTIONS_PATH = EVAL_DIR / "questions.json"
CACHE_PATH = EVAL_DIR / "embeddings.npz"

EMBEDDING_MODEL = "nomic-embed-text"
PAPERS = {
    "hourglass": "Stacked Hourglass Networks for Human Pose Estimation",
    "batch_normal": (
        "Batch Normalization: Accelerating Deep Network Training by Reducing "
        "Internal Covariate Shift"
    ),
    "dreampose": "DreamPose3D: Hallucinative Diffusion with Prompt Learning for 3D Human Pose Estimation",
}
KS = (1, 3, 5, 10)


@dataclass(frozen=True)
class Variant:
    """One retrieval configuration to score."""

    name: str
    strategy: str
    task_hints: bool = True
    headers: bool = True
    max_per_paper: int = MAX_PER_PAPER


# The shipped configuration first, then the strategies it was chosen over
# (with the same cap), then each detail it depends on, removed one at a time.
SHIPPED = "hybrid (shipped)"
NO_CAP = 10_000
VARIANTS = (
    Variant(SHIPPED, "hybrid"),
    Variant("dense", "dense"),
    Variant("lexical", "lexical"),
    Variant("hybrid, cap of 3 per paper", "hybrid", max_per_paper=3),
    Variant("hybrid, no per-paper cap", "hybrid", max_per_paper=NO_CAP),
    Variant("hybrid, no title/section headers", "hybrid", headers=False),
    Variant("hybrid, no task hints", "hybrid", task_hints=False),
)


class MissingEmbeddings(RuntimeError):
    """The cache lacks vectors and no live provider was allowed."""


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def cache_key(task: str | None, text: str) -> str:
    return hashlib.sha256(f"{EMBEDDING_MODEL}\0{task or ''}\0{text}".encode()).hexdigest()


class EmbeddingCache:
    """Vectors keyed by model, task and exact input text."""

    def __init__(self, path: Path = CACHE_PATH) -> None:
        self.path = path
        self.vectors: dict[str, np.ndarray] = {}
        self.dirty = False
        if path.exists():
            with np.load(path) as data:
                self.vectors = dict(zip(data["keys"].tolist(), data["vectors"], strict=True))

    def save(self) -> None:
        keys = sorted(self.vectors)
        np.savez_compressed(
            self.path,
            keys=np.array(keys),
            vectors=np.stack([self.vectors[key] for key in keys]).astype(np.float16),
        )
        self.dirty = False


class CachedEmbedder:
    """An Embedder answering from the cache, or from a live client if allowed."""

    model_id = EMBEDDING_MODEL

    def __init__(self, cache: EmbeddingCache, *, task_hints: bool, client: Any = None) -> None:
        self.cache = cache
        self.task_hints = task_hints
        self.client = client

    def _embed(self, texts: Sequence[str], task: str) -> list[np.ndarray]:
        task_sent = task if self.task_hints else None
        keys = [cache_key(task_sent, text) for text in texts]
        missing = [i for i, key in enumerate(keys) if key not in self.cache.vectors]
        if missing:
            if self.client is None:
                raise MissingEmbeddings(
                    f"{len(missing)} embeddings are not cached; "
                    "rerun with --refresh and Ollama running"
                )
            fresh = self.client.get_embeddings([texts[i] for i in missing], task=task_sent)
            for i, vector in zip(missing, fresh, strict=True):
                self.cache.vectors[keys[i]] = np.asarray(vector, dtype=np.float16)
            self.cache.dirty = True
        return [self.cache.vectors[key].astype(np.float32) for key in keys]

    def embed_documents(self, texts: Sequence[str]) -> list[np.ndarray]:
        return self._embed(texts, "document")

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text], "query")[0]


@dataclass(frozen=True)
class Evidence:
    paper: str
    text: str


@dataclass(frozen=True)
class Question:
    id: str
    type: str
    question: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class CorpusChunk:
    paper: str
    section: str | None
    text: str


def load_questions(path: Path = QUESTIONS_PATH) -> list[Question]:
    with path.open(encoding="utf-8") as handle:
        return [
            Question(
                id=entry["id"],
                type=entry["type"],
                question=entry["question"],
                evidence=tuple(Evidence(**item) for item in entry["evidence"]),
            )
            for entry in json.load(handle)
        ]


def build_corpus(embedder: CachedEmbedder, *, headers: bool) -> tuple[list[CorpusChunk], np.ndarray]:
    """Chunk and embed the papers exactly as the indexer would."""
    indexer = PaperIndexer(embedder, contextual_headers=headers)
    chunks: list[CorpusChunk] = []
    vectors: list[np.ndarray] = []
    for paper, title in PAPERS.items():
        text = (DOCS_DIR / f"{paper}.txt").read_text(encoding="utf-8")
        for prepared in indexer.prepare(title=title, text=text):
            chunks.append(CorpusChunk(paper, prepared.section, prepared.text))
            vectors.append(prepared.embedding)
    return chunks, np.vstack(vectors)


def _relevant(chunk: CorpusChunk, evidence: Evidence) -> bool:
    return chunk.paper == evidence.paper and _normalize(evidence.text) in _normalize(chunk.text)


def check_labels(chunks: Sequence[CorpusChunk], questions: Sequence[Question]) -> list[str]:
    """Evidence phrases found in no passage — a broken label, not a miss."""
    return [
        f"{question.id}: {evidence.paper!r} has no passage containing {evidence.text!r}"
        for question in questions
        for evidence in question.evidence
        if not any(_relevant(chunk, evidence) for chunk in chunks)
    ]


@dataclass
class QuestionResult:
    question: Question
    ranking: list[int]  # corpus indices, best first, after fusion and capping
    first_relevant: int | None  # 1-based rank, None when not in the top 10
    # k -> share of the papers holding an answer that an answering passage
    # in the top k came from.
    coverage: dict[int, float] = field(default_factory=dict)


def _cosine_top(matrix: np.ndarray, query: np.ndarray, k: int) -> list[tuple[int, float]]:
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        scores = (matrix @ query) / (np.linalg.norm(matrix, axis=1) * np.linalg.norm(query))
    order = np.argsort(-scores, kind="stable")[:k]
    return [(int(i), float(scores[i])) for i in order]


def run_variant(
    variant: Variant,
    questions: Sequence[Question],
    cache: EmbeddingCache,
    *,
    client: Any = None,
) -> list[QuestionResult]:
    embedder = CachedEmbedder(cache, task_hints=variant.task_hints, client=client)
    chunks, matrix = build_corpus(embedder, headers=variant.headers)
    bm25 = BM25([tokenize(chunk.text) for chunk in chunks])

    results: list[QuestionResult] = []
    for question in questions:
        dense = (
            _cosine_top(matrix, embedder.embed_query(question.question), CANDIDATES)
            if variant.strategy in ("hybrid", "dense")
            else []
        )
        lexical = (
            bm25.top(tokenize(question.question), CANDIDATES)
            if variant.strategy in ("hybrid", "lexical")
            else []
        )
        ranking = [
            index
            for index, _ in cap_per_paper(
                combine(variant.strategy, dense, lexical),
                lambda pair: chunks[pair[0]].paper,
                variant.max_per_paper,
            )[: max(KS)]
        ]

        first = next(
            (
                rank
                for rank, index in enumerate(ranking, start=1)
                if any(_relevant(chunks[index], evidence) for evidence in question.evidence)
            ),
            None,
        )
        papers = sorted({evidence.paper for evidence in question.evidence})
        coverage = {
            k: sum(
                any(
                    _relevant(chunks[index], evidence)
                    for index in ranking[:k]
                    for evidence in question.evidence
                    if evidence.paper == paper
                )
                for paper in papers
            )
            / len(papers)
            for k in KS
        }
        results.append(QuestionResult(question, ranking, first, coverage))
    return results


def summarize(results: Sequence[QuestionResult]) -> dict[str, float]:
    """Hit@k, MRR@10 and coverage@k over a set of questions."""
    total = len(results)
    if not total:
        return {}
    summary = {
        f"hit@{k}": sum(r.first_relevant is not None and r.first_relevant <= k for r in results)
        / total
        for k in KS
    }
    summary["mrr"] = sum(1 / r.first_relevant for r in results if r.first_relevant) / total
    for k in (5, 10):
        summary[f"coverage@{k}"] = sum(r.coverage[k] for r in results) / total
    return {name: round(value, 3) for name, value in summary.items()}


def evaluate(*, refresh: bool = False, client: Any = None) -> dict[str, Any]:
    """Score every variant. With `refresh`, embed what the cache lacks."""
    questions = load_questions()
    cache = EmbeddingCache()
    live = client if refresh else None

    report: dict[str, Any] = {"questions": len(questions), "variants": {}}
    for variant in VARIANTS:
        results = run_variant(variant, questions, cache, client=live)
        by_type = {
            kind: summarize([r for r in results if r.question.type == kind])
            for kind in sorted({q.type for q in questions})
        }
        report["variants"][variant.name] = {
            "overall": summarize(results),
            "by_type": by_type,
            "results": results,
        }

    if cache.dirty:
        cache.save()
    return report
