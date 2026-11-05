"""Chunk storage and similarity search.

Search is exact, on both databases. Every query is scoped to one project and
one embedding model — tens of papers, a few thousand chunks — and scanning
that is fast. An approximate index (pgvector's HNSW) would be built across
every project and then filtered down to one, and approximate indexes lose
recall under exactly that kind of selective filter.

On Postgres the scan runs in the database with pgvector's cosine distance
operator. On SQLite the project's vectors are loaded and scored with numpy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from pgvector.sqlalchemy import VECTOR
from sqlalchemy import Float, bindparam, cast, delete, func, select
from sqlalchemy.orm import Session

from db.models import Chunk, Paper


@dataclass(frozen=True)
class PreparedChunk:
    """A chunk ready to store: text, provenance and its embedding."""

    kind: str
    ordinal: int
    section: str | None
    text: str
    embedding: np.ndarray


@dataclass(frozen=True)
class Passage:
    """A stored chunk with what it came from, for lexical indexing."""

    chunk_id: int
    paper_id: str  # the paper's external id, e.g. an arXiv id
    paper_title: str
    kind: str
    section: str | None
    text: str


@dataclass(frozen=True)
class ScoredChunk:
    """A search hit."""

    chunk_id: int
    paper_id: str  # the paper's external id, e.g. an arXiv id
    paper_title: str
    kind: str
    section: str | None
    text: str
    score: float  # cosine similarity, higher is closer


def _cosine(matrix: np.ndarray, query: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query)
    # Apple's Accelerate BLAS, which numpy uses on macOS, leaves floating-point
    # flags set after a matrix product, so numpy warns of divide-by-zero and
    # overflow on finite, unit-scale inputs. The scores themselves are right —
    # checked against float64 to 1e-7 on a real corpus — so the false alarm is
    # silenced here, and only here.
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        dots = matrix @ query
    # A zero vector matches nothing rather than dividing by zero.
    return np.divide(dots, norms, out=np.zeros(len(matrix)), where=norms > 0)


class ChunkStore:
    """Chunks and their embeddings, through one session.

    Leaves transaction control to the caller, like the other repositories.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    @property
    def _on_postgres(self) -> bool:
        return self.session.get_bind().dialect.name == "postgresql"

    # -- writes ------------------------------------------------------------

    def replace_paper_chunks(
        self,
        *,
        project_id: str,
        paper_pk: int,
        embedding_model: str,
        chunks: Sequence[PreparedChunk],
    ) -> int:
        """Swap a paper's chunks for one model with a fresh set.

        Replace rather than upsert: re-indexing after a chunking change must
        not leave stale chunks behind with ordinals the new set never reaches.
        """
        self.session.execute(
            delete(Chunk).where(
                Chunk.paper_id == paper_pk, Chunk.embedding_model == embedding_model
            )
        )
        self.session.add_all(
            Chunk(
                project_id=project_id,
                paper_id=paper_pk,
                kind=chunk.kind,
                ordinal=chunk.ordinal,
                section=chunk.section,
                text=chunk.text,
                embedding_model=embedding_model,
                embedding=chunk.embedding,
            )
            for chunk in chunks
        )
        self.session.flush()
        return len(chunks)

    # -- reads -------------------------------------------------------------

    def count(self, project_id: str, embedding_model: str | None = None) -> int:
        stmt = select(func.count()).select_from(Chunk).where(Chunk.project_id == project_id)
        if embedding_model is not None:
            stmt = stmt.where(Chunk.embedding_model == embedding_model)
        return self.session.scalar(stmt) or 0

    def models(self, project_id: str) -> dict[str, int]:
        """Chunk counts per embedding model the project has been indexed with."""
        rows = self.session.execute(
            select(Chunk.embedding_model, func.count())
            .where(Chunk.project_id == project_id)
            .group_by(Chunk.embedding_model)
        ).tuples()
        # .all() first: a Result has .keys(), so dict() would treat it as a
        # mapping instead of iterating its rows.
        return dict(rows.all())

    def version(self, project_id: str, embedding_model: str) -> tuple[int, int]:
        """(count, highest id) of a project's chunks for one model.

        Changes whenever chunks are added, replaced or removed, which makes it
        a cheap key for caching anything derived from them.
        """
        count, highest = self.session.execute(
            select(func.count(), func.max(Chunk.id)).where(
                Chunk.project_id == project_id, Chunk.embedding_model == embedding_model
            )
        ).one()
        return count or 0, highest or 0

    def passages(self, project_id: str, embedding_model: str) -> list[Passage]:
        """Every chunk of a project for one model, in id order, without vectors."""
        rows = self.session.execute(
            select(Chunk.id, Chunk.kind, Chunk.section, Chunk.text, Paper.external_id, Paper.title)
            .join(Paper, Paper.id == Chunk.paper_id)
            .where(Chunk.project_id == project_id, Chunk.embedding_model == embedding_model)
            .order_by(Chunk.id)
        )
        return [
            Passage(
                chunk_id=row.id,
                paper_id=row.external_id,
                paper_title=row.title,
                kind=row.kind,
                section=row.section,
                text=row.text,
            )
            for row in rows
        ]

    def search(
        self,
        project_id: str,
        embedding_model: str,
        query: np.ndarray,
        *,
        k: int = 20,
        kinds: Sequence[str] | None = None,
    ) -> list[ScoredChunk]:
        """The `k` chunks most similar to `query`, best first.

        Ties are broken by chunk id, so the same corpus and query always rank
        the same way — the lesson from the gap finder's ordering bug.
        """
        if k <= 0:
            return []
        query = np.asarray(query, dtype=np.float32)
        if self._on_postgres:
            return self._search_pgvector(project_id, embedding_model, query, k, kinds)
        return self._search_numpy(project_id, embedding_model, query, k, kinds)

    def _scope(self, stmt, project_id: str, embedding_model: str, kinds):
        stmt = stmt.where(
            Chunk.project_id == project_id, Chunk.embedding_model == embedding_model
        )
        if kinds:
            stmt = stmt.where(Chunk.kind.in_(list(kinds)))
        return stmt

    def _search_pgvector(self, project_id, embedding_model, query, k, kinds):
        distance = Chunk.embedding.op("<=>", return_type=Float)(
            cast(bindparam("query_embedding", query, type_=VECTOR()), VECTOR())
        ).label("distance")
        stmt = self._scope(
            select(
                Chunk.id,
                Chunk.kind,
                Chunk.section,
                Chunk.text,
                Paper.external_id,
                Paper.title,
                distance,
            ).join(Paper, Paper.id == Chunk.paper_id),
            project_id,
            embedding_model,
            kinds,
        ).order_by(distance, Chunk.id).limit(k)

        return [
            ScoredChunk(
                chunk_id=row.id,
                paper_id=row.external_id,
                paper_title=row.title,
                kind=row.kind,
                section=row.section,
                text=row.text,
                score=1.0 - float(row.distance),
            )
            for row in self.session.execute(stmt)
        ]

    def _search_numpy(self, project_id, embedding_model, query, k, kinds):
        rows = self.session.execute(
            self._scope(
                select(Chunk.id, Chunk.embedding), project_id, embedding_model, kinds
            ).order_by(Chunk.id)
        ).all()
        if not rows:
            return []

        matrix = np.vstack([row.embedding for row in rows])
        if matrix.shape[1] != query.shape[0]:
            raise ValueError(
                f"query has {query.shape[0]} dimensions but {embedding_model} "
                f"chunks have {matrix.shape[1]}"
            )

        scores = _cosine(matrix, query)
        # Stable on descending score, so ties keep ascending id order.
        top = np.argsort(-scores, kind="stable")[:k]
        ids = [rows[i].id for i in top]

        details = {
            row.id: row
            for row in self.session.execute(
                select(
                    Chunk.id,
                    Chunk.kind,
                    Chunk.section,
                    Chunk.text,
                    Paper.external_id,
                    Paper.title,
                )
                .join(Paper, Paper.id == Chunk.paper_id)
                .where(Chunk.id.in_(ids))
            )
        }
        return [
            ScoredChunk(
                chunk_id=chunk_id,
                paper_id=details[chunk_id].external_id,
                paper_title=details[chunk_id].title,
                kind=details[chunk_id].kind,
                section=details[chunk_id].section,
                text=details[chunk_id].text,
                score=float(scores[index]),
            )
            for index, chunk_id in zip(top, ids, strict=True)
        ]
