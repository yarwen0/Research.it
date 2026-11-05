"""Hybrid retrieval: a dense and a lexical ranking, fused.

The two are combined with Reciprocal Rank Fusion, which works on ranks rather
than scores. Cosine similarity and BM25 live on unrelated scales, and RRF
needs no calibration between them — a passage ranked well by either list
rises, and one ranked well by both rises furthest.

Which of the three strategies is the default is decided by the benchmark in
`evals/retrieval`, not by this docstring.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TypeVar

from sqlalchemy.orm import Session

from retrieval.embedder import Embedder
from retrieval.lexical import BM25, tokenize
from retrieval.store import ChunkStore, Passage

STRATEGIES = ("hybrid", "dense", "lexical")

# The constant from Cormack, Clarke and Büttcher (SIGIR 2009). It damps the
# difference between the very top ranks, so one list's first place does not
# drown out agreement between both lists further down.
RRF_K = 60

# How many candidates each ranking contributes before fusion. Far more than
# any answer uses, so fusion has room to promote a passage one list ranked
# low.
CANDIDATES = 50

# A long paper has many near-duplicate passages on its own topic; without a
# cap one paper fills the whole context and crowds out the others. Measured,
# not guessed (evals/retrieval): no cap halves evidence recall on questions
# spanning papers, and a cap of 3 starves questions about a single paper of
# the passages they need. 5 keeps the first and recovers most of the second.
MAX_PER_PAPER = 5

T = TypeVar("T")


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[int]], *, k: int = RRF_K
) -> list[tuple[int, float]]:
    """Fuse rankings of ids into one, best first; ties go to the lower id."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


def combine(
    strategy: str,
    dense: Sequence[tuple[int, float]],
    lexical: Sequence[tuple[int, float]],
) -> list[tuple[int, float]]:
    """One ranking from either or both of the candidate lists."""
    if strategy == "dense":
        return list(dense)
    if strategy == "lexical":
        return list(lexical)
    if strategy == "hybrid":
        return reciprocal_rank_fusion([[i for i, _ in dense], [i for i, _ in lexical]])
    raise ValueError(f"Unknown strategy {strategy!r}; expected one of {STRATEGIES}")


def cap_per_paper(items: Iterable[T], paper_of: Callable[[T], str], limit: int) -> list[T]:
    """Keep ranking order, dropping anything past `limit` from one paper."""
    taken: dict[str, int] = {}
    kept: list[T] = []
    for item in items:
        paper = paper_of(item)
        if taken.get(paper, 0) < limit:
            taken[paper] = taken.get(paper, 0) + 1
            kept.append(item)
    return kept


@dataclass(frozen=True)
class RetrievedChunk:
    """A passage chosen for an answer, and how each ranking saw it."""

    chunk_id: int
    paper_id: str
    paper_title: str
    kind: str
    section: str | None
    text: str
    score: float  # the fused score in hybrid mode, the single list's otherwise
    dense_rank: int | None  # 1-based; None when the list did not return it
    lexical_rank: int | None


class _LexicalIndexCache:
    """BM25 indexes per project and model, rebuilt when the chunks change.

    Building one means loading and tokenizing every passage in the project;
    an assistant asking several questions in a row should pay that once.
    """

    def __init__(self, capacity: int = 16) -> None:
        self._entries: OrderedDict[
            tuple[str, str], tuple[tuple[int, int], BM25, list[Passage]]
        ] = OrderedDict()
        self._capacity = capacity
        self._lock = threading.Lock()

    def get(self, store: ChunkStore, project_id: str, model: str) -> tuple[BM25, list[Passage]]:
        key = (project_id, model)
        version = store.version(project_id, model)
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry[0] == version:
                self._entries.move_to_end(key)
                return entry[1], entry[2]

        passages = store.passages(project_id, model)
        index = BM25([tokenize(passage.text) for passage in passages])
        with self._lock:
            self._entries[key] = (version, index, passages)
            self._entries.move_to_end(key)
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)
        return index, passages

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


LEXICAL_INDEXES = _LexicalIndexCache()


class HybridRetriever:
    """Retrieves passages from one project's indexed chunks."""

    def __init__(
        self,
        session: Session,
        embedder: Embedder,
        *,
        strategy: str = "hybrid",
        candidates: int = CANDIDATES,
        max_per_paper: int = MAX_PER_PAPER,
    ) -> None:
        if strategy not in STRATEGIES:
            raise ValueError(f"Unknown strategy {strategy!r}; expected one of {STRATEGIES}")
        self.store = ChunkStore(session)
        self.embedder = embedder
        self.strategy = strategy
        self.candidates = candidates
        self.max_per_paper = max_per_paper

    def retrieve(self, project_id: str, query: str, *, k: int = 8) -> list[RetrievedChunk]:
        model = self.embedder.model_id
        passages: dict[int, Passage] = {}
        dense: list[tuple[int, float]] = []
        lexical: list[tuple[int, float]] = []

        if self.strategy in ("hybrid", "dense"):
            for hit in self.store.search(
                project_id, model, self.embedder.embed_query(query), k=self.candidates
            ):
                dense.append((hit.chunk_id, hit.score))
                passages[hit.chunk_id] = Passage(
                    hit.chunk_id, hit.paper_id, hit.paper_title, hit.kind, hit.section, hit.text
                )

        if self.strategy in ("hybrid", "lexical"):
            index, corpus = LEXICAL_INDEXES.get(self.store, project_id, model)
            for position, score in index.top(tokenize(query), self.candidates):
                passage = corpus[position]
                lexical.append((passage.chunk_id, score))
                passages.setdefault(passage.chunk_id, passage)

        dense_rank = {chunk_id: rank for rank, (chunk_id, _) in enumerate(dense, start=1)}
        lexical_rank = {chunk_id: rank for rank, (chunk_id, _) in enumerate(lexical, start=1)}
        ranked = cap_per_paper(
            combine(self.strategy, dense, lexical),
            lambda pair: passages[pair[0]].paper_id,
            self.max_per_paper,
        )[:k]

        return [
            RetrievedChunk(
                chunk_id=chunk_id,
                paper_id=passages[chunk_id].paper_id,
                paper_title=passages[chunk_id].paper_title,
                kind=passages[chunk_id].kind,
                section=passages[chunk_id].section,
                text=passages[chunk_id].text,
                score=score,
                dense_rank=dense_rank.get(chunk_id),
                lexical_rank=lexical_rank.get(chunk_id),
            )
            for chunk_id, score in ranked
        ]
