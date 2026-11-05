"""Index projects processed before retrieval existed.

    python scripts/index_project.py <project_id> [<project_id> ...]
    python scripts/index_project.py --all

Runs embed with whichever provider is configured, exactly as a new run would.
Full text is not stored, so it is re-extracted from the PDFs a run leaves in
data/tmp; a paper whose PDF has gone is indexed from its structured record
alone, and the output says so.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz  # PyMuPDF
from sqlalchemy import select

from core import create_llm_client
from db.models import Paper, Project
from db.session import session_scope
from retrieval.embedder import ClientEmbedder
from retrieval.indexer import PaperIndexer
from utils.paths import DATA_DIR

# Where ArxivClient.download_pdf caches papers, named by arXiv id.
PDF_DIR = DATA_DIR / "tmp"


def pdf_text(external_id: str, pdf_dir: Path = PDF_DIR) -> str | None:
    """The paper's text, extracted the same way the pipeline does it."""
    path = pdf_dir / f"{external_id}.pdf"
    if not path.is_file():
        return None
    with fitz.open(path) as document:
        return "\n\n".join(page.get_text() for page in document)


def processed_papers(project_id: str) -> list[dict]:
    with session_scope() as session:
        rows = session.scalars(
            select(Paper)
            .where(Paper.project_id == project_id, Paper.is_processed.is_(True))
            .order_by(Paper.id)
        ).all()
        return [
            {
                "paper_id": row.external_id,
                "title": row.title,
                "extraction": row.extraction,
                "normalized": row.normalized,
            }
            for row in rows
        ]


def all_project_ids() -> list[str]:
    with session_scope() as session:
        return list(session.scalars(select(Project.id).order_by(Project.created_at)))


def index_projects(project_ids: list[str], indexer: PaperIndexer) -> int:
    """Index every processed paper of each project; return the chunk total."""
    total = 0
    for project_id in project_ids:
        papers = processed_papers(project_id)
        if not papers:
            print(f"{project_id}: no processed papers")
            continue
        for paper in papers:
            text = pdf_text(paper["paper_id"])
            count = indexer.index_paper(project_id, paper, text or "")
            note = "" if text else "  (structured record only: PDF not found)"
            print(f"{project_id}  {paper['paper_id']:<14} {count:>4} chunks{note}")
            total += count
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("project_ids", nargs="*", help="projects to index")
    parser.add_argument("--all", action="store_true", help="index every project")
    args = parser.parse_args(argv)

    if args.all == bool(args.project_ids):
        parser.error("name one or more projects, or pass --all")

    indexer = PaperIndexer(ClientEmbedder(create_llm_client()))
    total = index_projects(all_project_ids() if args.all else args.project_ids, indexer)
    print(f"Indexed {total} chunks with {indexer.embedder.model_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
