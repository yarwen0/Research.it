"""Turning a processed paper into stored, embedded chunks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select

from db.models import Paper
from db.session import session_scope
from retrieval.chunking import OVERLAP_CHARS, TARGET_CHARS, chunk_paper_text, render_profile
from retrieval.embedder import Embedder
from retrieval.store import ChunkStore, PreparedChunk
from telemetry import llm_stage


class PaperIndexer:
    """Chunks, embeds and stores papers for one embedding model.

    With `contextual_headers` (the default), each text chunk is embedded with
    its paper title and section heading in front of it, while the stored text
    stays as written. A passage that says "our method outperforms the
    baseline" is otherwise embedded with no idea which method it means.
    """

    def __init__(
        self,
        embedder: Embedder,
        *,
        contextual_headers: bool = True,
        target_chars: int = TARGET_CHARS,
        overlap_chars: int = OVERLAP_CHARS,
    ) -> None:
        self.embedder = embedder
        self.contextual_headers = contextual_headers
        self.target_chars = target_chars
        self.overlap_chars = overlap_chars

    def _embedding_input(self, title: str, kind: str, section: str | None, text: str) -> str:
        # The profile already opens with the title.
        if kind == "profile" or not self.contextual_headers:
            return text
        header = " — ".join(part for part in (title.strip(), section or "") if part)
        return f"{header}\n{text}" if header else text

    def prepare(
        self,
        *,
        title: str,
        text: str,
        extraction: Mapping[str, Any] | None = None,
        normalized: Mapping[str, Any] | None = None,
    ) -> list[PreparedChunk]:
        """Chunk and embed a paper, without touching the database.

        Kept apart from storing because embedding is the slow part — seconds
        to minutes on a local model — and no transaction should be held open
        across it.
        """
        pieces: list[tuple[str, int, str | None, str]] = []
        profile = render_profile(title, extraction, normalized)
        if profile:
            pieces.append(("profile", 0, None, profile))
        pieces.extend(
            ("text", chunk.ordinal, chunk.section, chunk.text)
            for chunk in chunk_paper_text(
                text, target_chars=self.target_chars, overlap_chars=self.overlap_chars
            )
        )
        if not pieces:
            return []

        vectors = self.embedder.embed_documents(
            [
                self._embedding_input(title, kind, section, body)
                for kind, _ordinal, section, body in pieces
            ]
        )
        return [
            PreparedChunk(kind=kind, ordinal=ordinal, section=section, text=body, embedding=vector)
            for (kind, ordinal, section, body), vector in zip(pieces, vectors, strict=True)
        ]

    @llm_stage("indexing")
    def index_paper(self, project_id: str, paper: Mapping[str, Any], text: str) -> int:
        """Embed one processed paper and store its chunks; return how many.

        `paper` is the pipeline's processed-paper record. Its row must already
        exist, which is why indexing runs after the graph is saved.
        """
        prepared = self.prepare(
            title=paper.get("title") or "",
            text=text,
            extraction=paper.get("extraction"),
            normalized=paper.get("normalized"),
        )
        with session_scope() as session:
            paper_pk = session.scalar(
                select(Paper.id).where(
                    Paper.project_id == project_id,
                    Paper.external_id == paper["paper_id"],
                )
            )
            if paper_pk is None:
                raise LookupError(f"paper {paper['paper_id']} is not in project {project_id}")
            return ChunkStore(session).replace_paper_chunks(
                project_id=project_id,
                paper_pk=paper_pk,
                embedding_model=self.embedder.model_id,
                chunks=prepared,
            )
