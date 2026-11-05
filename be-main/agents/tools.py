"""What the assistant's specialists can do with one project.

Each tool is a plain function of data the pipeline already produced —
retrieved passages, structured paper records, the ontology, the symbolic gap
finder, the citation graph. A tool returns text for the model to read, and
registers every fact it returns as evidence under an id (E1, E2, ...) that a
final answer has to cite. Evidence is the boundary between what the corpus
says and what a model writes, so it is recorded by the tools, never by the
model.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from db.models import Citation, OntologyTerm, Paper
from db.session import session_scope
from retrieval.chunking import render_profile
from retrieval.embedder import Embedder
from retrieval.hybrid import HybridRetriever
from services.gaps import find_gaps, to_gap_finder_papers

# Observations go back into a model's context on every later step; a local
# 7B model with an 8k window cannot afford whole passages.
MAX_PASSAGE_CHARS = 600


@dataclass(frozen=True)
class Evidence:
    """One fact a tool returned, under the id an answer cites it by."""

    id: str
    kind: str  # passage | record | gap | citation
    text: str
    paper_id: str | None = None
    paper_title: str | None = None
    section: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "paper_id": self.paper_id,
            "paper_title": self.paper_title,
            "section": self.section,
        }


class EvidenceLog:
    """Evidence gathered during one turn, shared by every specialist.

    Specialists run in parallel threads, hence the lock. The same passage
    found by two specialists keeps one id, so the writer sees one fact once.
    """

    def __init__(self) -> None:
        self._items: dict[str, Evidence] = {}
        self._ids_by_key: dict[tuple[Any, ...], str] = {}
        self._lock = threading.Lock()

    def add(
        self,
        kind: str,
        text: str,
        *,
        key: tuple[Any, ...],
        paper_id: str | None = None,
        paper_title: str | None = None,
        section: str | None = None,
    ) -> Evidence:
        with self._lock:
            existing = self._ids_by_key.get(key)
            if existing is not None:
                return self._items[existing]
            evidence = Evidence(
                id=f"E{len(self._items) + 1}",
                kind=kind,
                text=text,
                paper_id=paper_id,
                paper_title=paper_title,
                section=section,
            )
            self._items[evidence.id] = evidence
            self._ids_by_key[key] = evidence.id
            return evidence

    def get(self, evidence_id: str) -> Evidence | None:
        with self._lock:
            return self._items.get(evidence_id)

    def ids(self) -> set[str]:
        with self._lock:
            return set(self._items)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    # Argument name -> what it means. All tools share one flat argument
    # schema (see agents.react), so these are documentation for the model.
    arguments: dict[str, str]
    run: Callable[[dict[str, Any]], str]


def _clip(text: str, limit: int = MAX_PASSAGE_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _as_int(value: Any, default: int, *, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


class ProjectTools:
    """The tools, bound to one project and one turn's evidence log."""

    def __init__(self, project_id: str, embedder: Embedder, evidence: EvidenceLog) -> None:
        self.project_id = project_id
        self.embedder = embedder
        self.evidence = evidence

    # -- tools ---------------------------------------------------------------

    def search_passages(self, args: dict[str, Any]) -> str:
        query = str(args.get("query") or "").strip()
        if not query:
            return "search_passages needs a query."
        k = _as_int(args.get("top"), 5, low=1, high=8)
        with session_scope() as session:
            hits = HybridRetriever(session, self.embedder).retrieve(self.project_id, query, k=k)
        lines = []
        for hit in hits:
            evidence = self.evidence.add(
                "passage",
                hit.text,
                key=("passage", hit.chunk_id),
                paper_id=hit.paper_id,
                paper_title=hit.paper_title,
                section=hit.section,
            )
            lines.append(
                f"[{evidence.id}] {hit.paper_title} — {hit.section or 'untitled section'}: "
                f"{_clip(hit.text)}"
            )
        return "\n".join(lines) or f"No passages matched {query!r}."

    def paper_record(self, args: dict[str, Any]) -> str:
        """A processed paper's structured record, found by id or title words."""
        wanted = str(args.get("paper_id") or args.get("query") or "").strip()
        if not wanted:
            return "paper_record needs a paper_id or a few words of the title."
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
                return f"No processed paper matches {wanted!r}."
            record = render_profile(paper.title, paper.extraction, paper.normalized)
            external_id, title = paper.external_id, paper.title

        if not record:
            return f"{title} ({external_id}) has no structured record."
        evidence = self.evidence.add(
            "record", record, key=("record", external_id), paper_id=external_id, paper_title=title
        )
        return f"[{evidence.id}] {_clip(record, 1200)}"

    def papers_using(self, args: dict[str, Any]) -> str:
        """Papers whose structured record lists a method or dataset."""
        term = str(args.get("term") or args.get("query") or "").strip()
        field = str(args.get("field") or "methods").strip().lower()
        if field not in ("methods", "datasets"):
            field = "methods"
        if not term:
            return "papers_using needs a term."
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

        matched: dict[str, tuple[str, list[str]]] = {}
        for external_id, title, original in rows:
            entry = matched.setdefault(external_id, (title, []))
            if original and original not in entry[1]:
                entry[1].append(original)
        if not matched:
            return f"No paper lists {term!r} among its {field}."

        lines = []
        for external_id, (title, surface_forms) in matched.items():
            fact = f"{title} lists among its {field}: {'; '.join(surface_forms) or term}"
            evidence = self.evidence.add(
                "record",
                fact,
                key=("uses", field, term.lower(), external_id),
                paper_id=external_id,
                paper_title=title,
            )
            lines.append(f"[{evidence.id}] {fact}")
        return "\n".join(lines)

    def research_gaps(self, args: dict[str, Any]) -> str:
        """Gaps the symbolic gap finder detects across the project's papers."""
        gap_type = str(args.get("gap_type") or "").strip()
        top = _as_int(args.get("top"), 6, low=1, high=12)
        with session_scope() as session:
            rows = session.execute(
                select(Paper.external_id, Paper.normalized).where(
                    Paper.project_id == self.project_id, Paper.is_processed.is_(True)
                )
            ).all()
        gaps = find_gaps(
            to_gap_finder_papers(
                [{"paper_id": external_id, "normalized": normalized or {}} for external_id, normalized in rows]
            )
        )
        if gap_type:
            gaps = [gap for gap in gaps if gap["gap_type"] == gap_type]
        if not gaps:
            return "The gap finder found no gaps" + (f" of type {gap_type}." if gap_type else ".")

        lines = []
        for gap in gaps[:top]:
            fact = _describe_gap(gap)
            evidence = self.evidence.add("gap", fact, key=("gap", fact))
            lines.append(f"[{evidence.id}] {fact}")
        return "\n".join(lines)

    def citation_stats(self, args: dict[str, Any]) -> str:
        """The works this project's papers cite most."""
        top = _as_int(args.get("top"), 5, low=1, high=15)
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
        if not rows:
            return "No citations are recorded for this project."

        lines = []
        for external_id, title, count in rows:
            fact = f"{title!r} is cited by {count} of the project's papers"
            evidence = self.evidence.add(
                "citation", fact, key=("cited", external_id), paper_id=external_id, paper_title=title
            )
            lines.append(f"[{evidence.id}] {fact}")
        return "\n".join(lines)

    # -- registry ------------------------------------------------------------

    def all(self) -> dict[str, Tool]:
        return {
            tool.name: tool
            for tool in (
                Tool(
                    "search_passages",
                    "Search the papers' full text and structured records. Use for any question about what the papers say.",
                    {"query": "what to look for", "top": "passages to return, 1-8"},
                    self.search_passages,
                ),
                Tool(
                    "paper_record",
                    "One paper's structured record: problem, methods, datasets, limitations, future work.",
                    {"paper_id": "the paper's id, or a few words of its title"},
                    self.paper_record,
                ),
                Tool(
                    "papers_using",
                    "Which papers list a method or dataset in their structured records.",
                    {"term": "the method or dataset", "field": "methods or datasets"},
                    self.papers_using,
                ),
                Tool(
                    "research_gaps",
                    "Research gaps found by comparing the papers' methods, datasets, limitations and future work.",
                    {
                        "gap_type": "optional: method_transfer, dataset_transfer, limitation_gap or future_work_gap",
                        "top": "gaps to return, 1-12",
                    },
                    self.research_gaps,
                ),
                Tool(
                    "citation_stats",
                    "The works this project's papers cite most often.",
                    {"top": "how many, 1-15"},
                    self.citation_stats,
                ),
            )
        }


def _describe_gap(gap: dict[str, Any]) -> str:
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
