"""Read access to one project's papers, as structured data.

Two kinds of agent use this: the research assistant's own specialists, which
see it as text tools that record evidence (`agents.tools`), and outside agents
over MCP (`mcp_server`), which get the structures as they are. Keeping the
queries here means both see the same project the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from db.models import Chunk, Citation, OntologyTerm, Paper, Project
from db.session import session_scope
from retrieval.chunking import render_profile
from retrieval.embedder import Embedder
from retrieval.hybrid import HybridRetriever, RetrievedChunk
from services.gaps import find_gaps, to_gap_finder_papers

GAP_TYPES = ("method_transfer", "dataset_transfer", "limitation_gap", "future_work_gap")


@dataclass(frozen=True)
class PaperRecord:
    paper_id: str
    title: str
    published: str | None
    record: str  # the structured extraction rendered as text; "" if there is none
    normalized: dict[str, Any] | None


def describe_gap(gap: dict[str, Any]) -> str:
    """One gap from the finder as a sentence a model can reason over."""
    kind = gap["gap_type"]
    problem = gap.get("problem") or "this problem"
    if kind == "method_transfer":
        sentence = f"Method {gap['method']} has not been tried on dataset {gap['dataset']} for {problem}"
    elif kind == "dataset_transfer":
        sentence = f"Dataset {gap['dataset']} has not been used with method {gap['method']} for {problem}"
    elif kind == "limitation_gap":
        sentence = f"Limitation {gap['limitation']} recurs across papers on {problem}"
    elif kind == "future_work_gap":
        sentence = f"Future work {gap['future_work']} is proposed for {problem} but no paper does it"
    else:
        sentence = f"{kind} gap for {problem}"
    return f"{sentence} (gap type {kind}, score {gap.get('score', 0)})"


def list_projects(limit: int = 20) -> list[dict[str, Any]]:
    """Recent research runs, with how much of each is processed and indexed."""
    with session_scope() as session:
        projects = session.scalars(
            select(Project).order_by(Project.created_at.desc()).limit(limit)
        ).all()
        processed = dict(
            session.execute(
                select(Paper.project_id, func.count())
                .where(Paper.is_processed.is_(True))
                .group_by(Paper.project_id)
            )
            .tuples()
            .all()
        )
        passages = dict(
            session.execute(select(Chunk.project_id, func.count()).group_by(Chunk.project_id))
            .tuples()
            .all()
        )
        return [
            {
                "project_id": project.id,
                "prompt": project.user_prompt,
                "created_at": project.created_at.isoformat(),
                "processed_papers": processed.get(project.id, 0),
                "indexed_passages": passages.get(project.id, 0),
            }
            for project in projects
        ]


class ProjectData:
    """Queries over one project. Every method opens its own short session."""

    def __init__(self, project_id: str, embedder: Embedder) -> None:
        self.project_id = project_id
        self.embedder = embedder

    def exists(self) -> bool:
        with session_scope() as session:
            return session.get(Project, self.project_id) is not None

    def passages(self, query: str, k: int = 5, *, strategy: str = "hybrid") -> list[RetrievedChunk]:
        with session_scope() as session:
            retriever = HybridRetriever(session, self.embedder, strategy=strategy)
            return retriever.retrieve(self.project_id, query, k=k)

    def paper(self, wanted: str) -> PaperRecord | None:
        """A processed paper by its id, or else by words of its title."""
        with session_scope() as session:
            base = select(Paper).where(
                Paper.project_id == self.project_id, Paper.is_processed.is_(True)
            )
            paper = session.scalars(base.where(Paper.external_id == wanted)).first()
            if paper is None:
                paper = session.scalars(
                    base.where(func.lower(Paper.title).contains(wanted.lower())).order_by(Paper.id)
                ).first()
            if paper is None:
                return None
            return PaperRecord(
                paper_id=paper.external_id,
                title=paper.title,
                published=paper.published,
                record=render_profile(paper.title, paper.extraction, paper.normalized),
                normalized=paper.normalized,
            )

    def papers_using(self, term: str, field: str = "methods") -> list[dict[str, Any]]:
        """Papers whose structured record lists `term` among its methods or datasets."""
        if field not in ("methods", "datasets"):
            raise ValueError("field must be 'methods' or 'datasets'")
        pattern = f"%{term.lower()}%"
        with session_scope() as session:
            rows = session.execute(
                select(Paper.external_id, Paper.title, OntologyTerm.original_text)
                .join(
                    OntologyTerm,
                    (OntologyTerm.paper_external_id == Paper.external_id)
                    & (OntologyTerm.project_id == Paper.project_id),
                )
                .where(
                    Paper.project_id == self.project_id,
                    OntologyTerm.parameter == field,
                    func.lower(OntologyTerm.canonical_term).like(pattern)
                    | func.lower(OntologyTerm.original_text).like(pattern),
                )
                .order_by(Paper.id)
            ).all()

        papers: dict[str, dict[str, Any]] = {}
        for external_id, title, original in rows:
            entry = papers.setdefault(
                external_id, {"paper_id": external_id, "title": title, "matches": []}
            )
            if original and original not in entry["matches"]:
                entry["matches"].append(original)
        return list(papers.values())

    def gaps(self, gap_type: str | None = None, top: int = 6) -> list[dict[str, Any]]:
        """Gaps the symbolic gap finder detects across the project's papers."""
        if gap_type and gap_type not in GAP_TYPES:
            raise ValueError(f"gap_type must be one of {', '.join(GAP_TYPES)}")
        with session_scope() as session:
            rows = session.execute(
                select(Paper.external_id, Paper.normalized).where(
                    Paper.project_id == self.project_id, Paper.is_processed.is_(True)
                )
            ).all()
        gaps = find_gaps(
            to_gap_finder_papers(
                [
                    {"paper_id": external_id, "normalized": normalized or {}}
                    for external_id, normalized in rows
                ]
            )
        )
        if gap_type:
            gaps = [gap for gap in gaps if gap["gap_type"] == gap_type]
        return [{**gap, "description": describe_gap(gap)} for gap in gaps[:top]]

    def most_cited(self, top: int = 5) -> list[dict[str, Any]]:
        """The works this project's papers cite most."""
        with session_scope() as session:
            citing = func.count(Citation.source_paper_id).label("citing")
            rows = session.execute(
                select(Paper.external_id, Paper.title, citing)
                .join(Citation, Citation.target_paper_id == Paper.id)
                .where(Citation.project_id == self.project_id)
                .group_by(Paper.id, Paper.external_id, Paper.title)
                .order_by(citing.desc(), Paper.title)
                .limit(top)
            ).all()
        return [
            {"paper_id": external_id, "title": title, "cited_by": count}
            for external_id, title, count in rows
        ]
