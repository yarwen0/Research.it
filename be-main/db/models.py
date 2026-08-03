"""SQLAlchemy models for the research pipeline.

Shape notes:

* A **project** is one research run. Everything else hangs off it, which is
  what makes concurrent runs independent — the previous JSON layout kept a
  single global ontology file that every run rewrote in place.
* **Papers** cover both the papers actually processed (`is_processed=True`,
  carrying extraction/normalization payloads) and the bare references
  discovered in their bibliographies. Keeping them in one table is what lets
  the citation edge be a plain foreign key on both ends.
* **Authors** are per-project rather than global. Author names in bibliographies
  are not reliable identity, so deduplicating across projects would silently
  merge different people; the slug only has to be stable within a run.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base. `type_annotation_map` keeps column types portable."""

    type_annotation_map: ClassVar[dict] = {
        dict[str, Any]: JSON,
        list[Any]: JSON,
    }


class Project(Base):
    """One research run."""

    __tablename__ = "projects"

    # uuid4().hex, matching the project_id already handed to the frontend.
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_prompt: Mapped[str] = mapped_column(Text)
    topics: Mapped[list[Any] | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    papers: Mapped[list[Paper]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    authors: Mapped[list[Author]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    citations: Mapped[list[Citation]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    ontology_terms: Mapped[list[OntologyTerm]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Project {self.id} {self.user_prompt[:32]!r}>"


class PaperAuthor(Base):
    """Join table between papers and authors."""

    __tablename__ = "paper_authors"

    paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    author_id: Mapped[int] = mapped_column(
        ForeignKey("authors.id", ondelete="CASCADE"), primary_key=True
    )


class Paper(Base):
    """A paper node: either one the pipeline processed, or a cited reference."""

    __tablename__ = "papers"
    __table_args__ = (
        # External ids are only unique within a run — two projects can both
        # process arXiv:2301.00001 and must not collide.
        UniqueConstraint("project_id", "external_id", name="uq_papers_project_external"),
        Index("ix_papers_project_processed", "project_id", "is_processed"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )

    # arXiv id for processed papers; a generated hex id for bare references.
    external_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(Text, default="")
    published: Mapped[str | None] = mapped_column(String(64), default=None)
    pdf_url: Mapped[str | None] = mapped_column(Text, default=None)
    topic: Mapped[str | None] = mapped_column(Text, default=None)

    # False for references discovered in a bibliography but never fetched.
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Raw LLM pipeline output. Kept as JSON on purpose: the schema is set by
    # the extraction prompt and changes with it, so columns would be churn.
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    normalized: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    project: Mapped[Project] = relationship(back_populates="papers")
    authors: Mapped[list[Author]] = relationship(
        secondary="paper_authors", back_populates="papers"
    )
    cites: Mapped[list[Citation]] = relationship(
        back_populates="source",
        foreign_keys="Citation.source_paper_id",
        cascade="all, delete-orphan",
    )
    cited_by: Mapped[list[Citation]] = relationship(
        back_populates="target",
        foreign_keys="Citation.target_paper_id",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Paper {self.external_id} {self.title[:32]!r}>"


class Author(Base):
    """An author node, scoped to a project."""

    __tablename__ = "authors"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_authors_project_slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )

    # Normalized form used for dedup within a run; `name` keeps the original.
    slug: Mapped[str] = mapped_column(String(512))
    name: Mapped[str] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="authors")
    papers: Mapped[list[Paper]] = relationship(
        secondary="paper_authors", back_populates="authors"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Author {self.name!r}>"


class Citation(Base):
    """A directed citation edge between two papers in the same project."""

    __tablename__ = "citations"
    __table_args__ = (
        UniqueConstraint(
            "source_paper_id", "target_paper_id", name="uq_citations_source_target"
        ),
        Index("ix_citations_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    source_paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )
    target_paper_id: Mapped[int] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), index=True
    )

    project: Mapped[Project] = relationship(back_populates="citations")
    source: Mapped[Paper] = relationship(
        back_populates="cites", foreign_keys=[source_paper_id]
    )
    target: Mapped[Paper] = relationship(
        back_populates="cited_by", foreign_keys=[target_paper_id]
    )


class OntologyTerm(Base):
    """One (parameter, canonical term) observation contributed by a paper.

    The JSON layout nested this as ``{parameter: {term: [{paper_id, original}]}}``
    in a single global file, so every write rewrote the whole document and
    concurrent runs overwrote each other. One row per observation makes writes
    independent and the term lookup an indexed query.
    """

    __tablename__ = "ontology_terms"
    __table_args__ = (
        Index("ix_ontology_project_parameter", "project_id", "parameter"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )

    # e.g. "methods", "datasets", "limitations_explicit"
    parameter: Mapped[str] = mapped_column(String(128))
    # The normalized term the LLM mapped onto, e.g. "high_computation".
    canonical_term: Mapped[str] = mapped_column(String(512))
    # The paper's external id, and the surface form it used.
    paper_external_id: Mapped[str] = mapped_column(String(255))
    original_text: Mapped[str] = mapped_column(Text, default="")

    project: Mapped[Project] = relationship(back_populates="ontology_terms")


class JobStatus(str, Enum):
    """Lifecycle of a background research run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(Base):
    """A research run executing in the background.

    Previously the pipeline *was* the HTTP response: a client that navigated
    away killed the run mid-flight, losing every paper already processed. The
    run now outlives the connection, and a reconnecting client resumes from
    the events recorded here.
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), default=None, index=True
    )

    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus, native_enum=False, length=16),
        default=JobStatus.PENDING,
        index=True,
    )
    user_prompt: Mapped[str] = mapped_column(Text, default="")
    # Request parameters, so a run can be described (or replayed) after the
    # fact without the original request.
    params: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    events: Mapped[list[JobEvent]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobEvent.sequence",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Job {self.id} {self.status}>"


class JobEvent(Base):
    """One progress event from a job, in order.

    `sequence` is what makes reconnection work: a client resumes by asking for
    everything after the last sequence number it saw.
    """

    __tablename__ = "job_events"
    __table_args__ = (
        UniqueConstraint("job_id", "sequence", name="uq_job_events_job_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    job: Mapped[Job] = relationship(back_populates="events")


class Review(Base):
    """A generated literature review."""

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Timestamp-derived public identifier, used in URLs.
    review_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # Nullable: reviews predating project tracking, and reviews generated from
    # an uploaded dataset rather than a run.
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), default=None, index=True
    )
    source_filepath: Mapped[str | None] = mapped_column(Text, default=None)

    title: Mapped[str] = mapped_column(Text, default="")
    latex_content: Mapped[str] = mapped_column(Text, default="")
    bibliography: Mapped[list[Any] | None] = mapped_column(JSON, default=None)
    # `metadata` is reserved on the declarative base.
    review_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, default=None
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Review {self.review_id} {self.title[:32]!r}>"
