"""Persistence layer.

Replaces the JSON files that previously backed the citation graph, the
ontology and generated reviews. The models and migrations are portable: SQLite
for a zero-config local run, Postgres in compose and production.
"""

from db.models import (
    Author,
    Base,
    Citation,
    OntologyTerm,
    Paper,
    Project,
    Review,
)
from db.session import get_session, init_engine, session_scope

__all__ = [
    "Author",
    "Base",
    "Citation",
    "OntologyTerm",
    "Paper",
    "Project",
    "Review",
    "get_session",
    "init_engine",
    "session_scope",
]
