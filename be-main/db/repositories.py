"""Repositories over the ORM models.

These replace the JSON-file storage classes in ``core``. Each takes a session
and leaves transaction control to the caller, so a whole research run commits
once rather than rewriting a document per write.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from db.models import Author, Citation, OntologyTerm, Paper, PaperAuthor, Project, Review

logger = logging.getLogger(__name__)

# Titles shorter than this are almost always parse noise from the reference
# extractor rather than a real citation.
MIN_REFERENCE_TITLE_LENGTH = 6


def author_node_id(name: str) -> str:
    """Stable per-run identifier for an author.

    Matches the id format the frontend already renders, so graphs generated
    before and after the storage change look the same.
    """
    return f"author_{name.replace(' ', '_').replace('.', '').lower()}"


def _normalize_title(title: str) -> str:
    """Fold a title for dedup: case, punctuation and whitespace insensitive."""
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


class ProjectRepository:
    """Creates and looks up research runs."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        project_id: str,
        user_prompt: str,
        topics: Optional[list[str]] = None,
    ) -> Project:
        project = Project(
            id=project_id,
            user_prompt=user_prompt,
            topics=list(topics) if topics else None,
        )
        self.session.add(project)
        self.session.flush()
        return project

    def get(self, project_id: str) -> Optional[Project]:
        return self.session.get(Project, project_id)

    def exists(self, project_id: str) -> bool:
        return (
            self.session.scalar(
                select(func.count()).select_from(Project).where(Project.id == project_id)
            )
            or 0
        ) > 0


class GraphRepository:
    """Builds and reads the citation + authorship graph for one project.

    Replaces ``core.ReferenceGraph``, which held the whole graph as a dict and
    rewrote ``data/{project_id}/reference_graph.json`` on every sync.
    """

    def __init__(self, session: Session, project_id: str) -> None:
        self.session = session
        self.project_id = project_id
        # Per-run caches so a bibliography of a few hundred references does not
        # become a few hundred SELECTs.
        self._author_cache: dict[str, Author] = {}
        self._reference_cache: dict[str, Paper] = {}

    # -- writes ------------------------------------------------------------

    def _get_or_create_author(self, name: str) -> Author:
        slug = author_node_id(name)
        cached = self._author_cache.get(slug)
        if cached is not None:
            return cached

        author = self.session.scalar(
            select(Author).where(
                Author.project_id == self.project_id, Author.slug == slug
            )
        )
        if author is None:
            author = Author(project_id=self.project_id, slug=slug, name=name)
            self.session.add(author)
            self.session.flush()

        self._author_cache[slug] = author
        return author

    def _attach_authors(self, paper: Paper, names: Iterable[Any]) -> None:
        for name in names or []:
            if not name or not isinstance(name, str):
                continue
            author = self._get_or_create_author(name)
            # Explicit join-row insert rather than list append, so the caller
            # is not forced to have the collection loaded.
            exists = self.session.scalar(
                select(func.count())
                .select_from(PaperAuthor)
                .where(
                    PaperAuthor.paper_id == paper.id,
                    PaperAuthor.author_id == author.id,
                )
            )
            if not exists:
                self.session.add(
                    PaperAuthor(paper_id=paper.id, author_id=author.id)
                )

    def add_processed_paper(self, paper_data: dict[str, Any]) -> Paper:
        """Insert (or update) a paper the pipeline actually fetched and read."""
        external_id = paper_data["paper_id"]

        paper = self.session.scalar(
            select(Paper).where(
                Paper.project_id == self.project_id,
                Paper.external_id == external_id,
            )
        )
        if paper is None:
            paper = Paper(project_id=self.project_id, external_id=external_id)
            self.session.add(paper)

        paper.title = paper_data.get("title", "") or ""
        paper.published = paper_data.get("published")
        paper.pdf_url = paper_data.get("pdf_url")
        paper.topic = paper_data.get("topic")
        paper.is_processed = True
        paper.extraction = paper_data.get("extraction")
        paper.normalized = paper_data.get("normalized")
        self.session.flush()

        self._attach_authors(paper, paper_data.get("authors", []))
        return paper

    def add_reference(self, source: Paper, reference: dict[str, Any]) -> Optional[Paper]:
        """Record a work cited by ``source``, returning the target node.

        References are deduplicated by normalized title within the project. The
        file-based version minted a fresh uuid per reference, so two papers
        citing the same work produced two disconnected nodes — which defeats
        the point of a citation graph, since shared citations are exactly the
        signal it exists to show.
        """
        title = (reference.get("title") or "").strip()
        if len(title) <= MIN_REFERENCE_TITLE_LENGTH:
            return None

        key = _normalize_title(title)
        target = self._reference_cache.get(key)

        if target is None:
            target = self.session.scalar(
                select(Paper).where(
                    Paper.project_id == self.project_id,
                    Paper.external_id == f"ref_{key[:200]}",
                )
            )

        if target is None:
            target = Paper(
                project_id=self.project_id,
                # Derived from the title so the same work reached from a
                # different paper lands on the same row.
                external_id=f"ref_{key[:200]}",
                title=title,
                published=reference.get("published"),
                is_processed=False,
            )
            self.session.add(target)
            self.session.flush()
            self._attach_authors(target, reference.get("authors", []))

        self._reference_cache[key] = target

        already_linked = self.session.scalar(
            select(func.count())
            .select_from(Citation)
            .where(
                Citation.source_paper_id == source.id,
                Citation.target_paper_id == target.id,
            )
        )
        if not already_linked:
            self.session.add(
                Citation(
                    project_id=self.project_id,
                    source_paper_id=source.id,
                    target_paper_id=target.id,
                )
            )

        return target

    def build_from_processed_papers(self, papers: list[dict[str, Any]]) -> None:
        """Persist a whole run's papers, authors and citation edges."""
        for paper_data in papers:
            paper = self.add_processed_paper(paper_data)
            for reference in paper_data.get("references", []) or []:
                self.add_reference(paper, reference)

        logger.info(
            "Persisted graph for project %s: %s papers", self.project_id, len(papers)
        )

    # -- reads -------------------------------------------------------------

    def to_cytoscape(self) -> dict[str, list[dict[str, Any]]]:
        """Render the graph in the shape the frontend renderer consumes."""
        papers = (
            self.session.scalars(
                select(Paper)
                .where(Paper.project_id == self.project_id)
                .options(selectinload(Paper.authors))
                .order_by(Paper.id)
            )
            .unique()
            .all()
        )
        citations = self.session.scalars(
            select(Citation)
            .where(Citation.project_id == self.project_id)
            .order_by(Citation.id)
        ).all()

        by_pk = {paper.id: paper for paper in papers}

        # refs_to / refs_from are precomputed here rather than queried per node.
        refs_to: dict[str, list[str]] = {p.external_id: [] for p in papers}
        refs_from: dict[str, list[str]] = {p.external_id: [] for p in papers}
        for citation in citations:
            source = by_pk.get(citation.source_paper_id)
            target = by_pk.get(citation.target_paper_id)
            if source is None or target is None:
                continue
            refs_to[source.external_id].append(target.external_id)
            refs_from[target.external_id].append(source.external_id)

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        seen_authors: set[str] = set()

        for paper in papers:
            author_names = [a.name for a in paper.authors]
            nodes.append(
                {
                    "data": {
                        "id": paper.external_id,
                        "title": paper.title,
                        "authors": author_names,
                        "published": paper.published or "",
                        "is_processed": paper.is_processed,
                        "refs_to": refs_to.get(paper.external_id, []),
                        "refs_from": refs_from.get(paper.external_id, []),
                        "node_type": "paper",
                        "label": paper.title,
                    }
                }
            )

            for author in paper.authors:
                if author.slug not in seen_authors:
                    seen_authors.add(author.slug)
                    nodes.append(
                        {
                            "data": {
                                "id": author.slug,
                                "title": author.name,
                                "authors": [],
                                "published": "",
                                "is_processed": False,
                                "refs_to": [],
                                "refs_from": [],
                                "node_type": "author",
                                "label": author.name,
                            }
                        }
                    )
                edges.append(
                    {
                        "data": {
                            "id": f"authorship_{paper.external_id}_{author.slug}",
                            "source": paper.external_id,
                            "target": author.slug,
                            "edge_type": "authorship",
                        }
                    }
                )

        for citation in citations:
            source = by_pk.get(citation.source_paper_id)
            target = by_pk.get(citation.target_paper_id)
            if source is None or target is None:
                continue
            edges.append(
                {
                    "data": {
                        "id": f"citation_{citation.id}",
                        "source": source.external_id,
                        "target": target.external_id,
                        "edge_type": "citation",
                    }
                }
            )

        return {"nodes": nodes, "edges": edges}

    def is_empty(self) -> bool:
        count = self.session.scalar(
            select(func.count())
            .select_from(Paper)
            .where(Paper.project_id == self.project_id)
        )
        return not count


class OntologyRepository:
    """Per-project term ontology.

    Replaces ``core.OntologyStorage``, which kept one global
    ``data/ontology.json``: every mapped parameter rewrote and re-read the
    entire file, and two concurrent runs overwrote each other's terms.
    """

    def __init__(self, session: Session, project_id: str) -> None:
        self.session = session
        self.project_id = project_id

    def terms_for(self, parameters: list[str]) -> dict[str, list[str]]:
        """Canonical terms per parameter, for grounding the normalizer prompt."""
        if not parameters:
            return {}

        rows = self.session.execute(
            select(OntologyTerm.parameter, OntologyTerm.canonical_term)
            .where(
                OntologyTerm.project_id == self.project_id,
                OntologyTerm.parameter.in_(parameters),
            )
            .distinct()
        ).all()

        grouped: dict[str, list[str]] = {}
        for parameter, term in rows:
            grouped.setdefault(parameter, []).append(term)
        return grouped

    def map_paper(
        self, normalized_parameters: dict[str, Any], paper_external_id: str
    ) -> None:
        """Record every (parameter, canonical term) this paper contributed."""
        pending: list[OntologyTerm] = []

        for parameter, value in normalized_parameters.items():
            # `problem` is free text, not a term to be folded into an ontology.
            if parameter == "problem" or not isinstance(value, list):
                continue

            for item in value:
                # The normalizer emits [canonical_term, original_surface_form].
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    logger.debug("Skipping malformed ontology item: %r", item)
                    continue
                canonical_term, original = item
                if not canonical_term:
                    continue
                pending.append(
                    OntologyTerm(
                        project_id=self.project_id,
                        parameter=parameter,
                        canonical_term=str(canonical_term),
                        paper_external_id=paper_external_id,
                        original_text=str(original or ""),
                    )
                )

        if pending:
            # One flush for the paper, versus the previous full-document
            # rewrite per parameter key.
            self.session.add_all(pending)
            self.session.flush()

    def as_dict(self) -> dict[str, dict[str, list[dict[str, str]]]]:
        """Rebuild the nested shape the trends code still expects."""
        rows = self.session.scalars(
            select(OntologyTerm)
            .where(OntologyTerm.project_id == self.project_id)
            .order_by(OntologyTerm.id)
        ).all()

        ontology: dict[str, dict[str, list[dict[str, str]]]] = {}
        for row in rows:
            ontology.setdefault(row.parameter, {}).setdefault(
                row.canonical_term, []
            ).append(
                {"paper_id": row.paper_external_id, "original": row.original_text}
            )
        return ontology


class ReviewRepository:
    """Generated literature reviews."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(
        self,
        review_id: str,
        latex_content: str,
        *,
        title: str = "",
        project_id: Optional[str] = None,
        source_filepath: Optional[str] = None,
        bibliography: Optional[list[Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Review:
        review = self.session.scalar(
            select(Review).where(Review.review_id == review_id)
        )
        if review is None:
            review = Review(review_id=review_id)
            self.session.add(review)

        review.project_id = project_id
        review.source_filepath = source_filepath
        review.title = title
        review.latex_content = latex_content
        review.bibliography = bibliography
        review.review_metadata = metadata
        review.created_at = datetime.now(timezone.utc)
        self.session.flush()
        return review

    def get(self, review_id: str) -> Optional[Review]:
        return self.session.scalar(
            select(Review).where(Review.review_id == review_id)
        )

    def list(self, source_filepath: Optional[str] = None) -> list[Review]:
        stmt = select(Review).order_by(Review.created_at.desc())
        if source_filepath:
            stmt = stmt.where(Review.source_filepath == source_filepath)
        return list(self.session.scalars(stmt).all())

    def delete(self, review_id: str) -> bool:
        result = self.session.execute(
            delete(Review).where(Review.review_id == review_id)
        )
        return bool(result.rowcount)
