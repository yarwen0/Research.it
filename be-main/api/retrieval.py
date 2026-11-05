"""Search and grounded question answering over a project's papers.

Thin like the other routes: validate, delegate to `services.rag`, shape the
response. Blocking work runs through `asyncio.to_thread`, which also carries
the telemetry context into the thread.

No `from __future__ import annotations` here: the rate-limit decorator wraps
the handlers, and FastAPI would resolve string annotations against the
decorator's module, misreading the request body as a query parameter.
"""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response

from api.schemas import (
    AskRequest,
    AskResponse,
    IndexStatusResponse,
    SearchResponse,
)
from config import RATE_LIMIT_ASK
from core import create_llm_client
from db.repositories import ProjectRepository
from db.session import session_scope
from rate_limit import limiter
from retrieval.embedder import ClientEmbedder
from retrieval.hybrid import RetrievedChunk
from retrieval.screening import screen
from retrieval.store import ChunkStore
from services.rag import CorpusQA, GroundedAnswer, NotIndexedError

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_project(project_id: str) -> None:
    with session_scope() as session:
        if not ProjectRepository(session).exists(project_id):
            raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")


def _qa(**kwargs) -> CorpusQA:
    client = create_llm_client()
    return CorpusQA(client, ClientEmbedder(client), **kwargs)


def _hit(chunk: RetrievedChunk) -> dict:
    return {
        "chunk_id": chunk.chunk_id,
        "paper_id": chunk.paper_id,
        "paper_title": chunk.paper_title,
        "section": chunk.section,
        "kind": chunk.kind,
        "text": chunk.text,
        "score": chunk.score,
        "dense_rank": chunk.dense_rank,
        "lexical_rank": chunk.lexical_rank,
    }


def _screened_hit(chunk: RetrievedChunk) -> dict:
    screening = screen(chunk.text)
    return {**_hit(chunk), "flagged": screening.flagged, "flag_reasons": screening.reasons}


def _answer(project_id: str, result: GroundedAnswer) -> dict:
    cited = set(result.cited)
    return {
        "project_id": project_id,
        "question": result.question,
        "answer": result.answer,
        "insufficient_evidence": result.insufficient_evidence,
        "grounded": result.grounded,
        "sources": [
            {**_hit(source.chunk), "id": source.id, "cited": source.id in cited}
            for source in result.sources
        ],
        "cited": result.cited,
        "dropped_citations": result.dropped_citations,
        "withheld": [
            {
                "paper_id": chunk.paper_id,
                "paper_title": chunk.paper_title,
                "section": chunk.section,
                "reasons": screening.reasons,
            }
            for chunk, screening in result.withheld
        ],
        "strategy": result.strategy,
        "embedding_model": result.embedding_model,
        "usage": result.usage,
        "latency_ms": result.latency_ms,
    }


@router.get("/projects/{project_id}/index", response_model=IndexStatusResponse)
async def index_status_endpoint(project_id: str):
    """Whether a project's papers can be searched with the configured model.

    A project indexed under a different embedding model is not searchable
    until it is re-indexed: vectors from two models are not comparable.
    """
    _require_project(project_id)
    model = ClientEmbedder(create_llm_client()).model_id
    with session_scope() as session:
        models = ChunkStore(session).models(project_id)
    count = models.get(model, 0)
    return {
        "project_id": project_id,
        "embedding_model": model,
        "indexed_chunks": count,
        "ready": count > 0,
        "models": models,
    }


@router.get("/projects/{project_id}/search", response_model=SearchResponse)
async def search_endpoint(
    project_id: str,
    q: str = Query(min_length=1, max_length=1000, description="What to search for."),
    k: int = Query(default=10, ge=1, le=50),
    strategy: Literal["hybrid", "dense", "lexical"] = "hybrid",
):
    """Passages from a project's papers, best first, with no LLM involved.

    Status codes:
        404: no such project
        409: the project has no passages for the configured embedding model
    """
    _require_project(project_id)
    qa = _qa(strategy=strategy)
    try:
        hits = await asyncio.to_thread(qa.retrieve, project_id, q, k=k)
    except NotIndexedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "project_id": project_id,
        "query": q,
        "strategy": strategy,
        "embedding_model": qa.embedder.model_id,
        # Search results go to a person, so suspicious passages are shown and
        # marked rather than withheld; every path to a model withholds them.
        "hits": [_screened_hit(hit) for hit in hits],
    }


@router.post("/projects/{project_id}/ask", response_model=AskResponse)
@limiter.limit(RATE_LIMIT_ASK)
async def ask_endpoint(
    request: Request, response: Response, project_id: str, payload: AskRequest
):
    """Answer a question from a project's papers, citing the passages used.

    The answer cites sources inline as [S1], [S2]; `sources` maps each id to
    its passage. Citations of sources the model was never shown are removed
    and listed in `dropped_citations`. `grounded` is false when the answer
    neither cites a source nor declines — return it to a user with a warning,
    or not at all.

    Status codes:
        404: no such project
        409: the project has no passages for the configured embedding model
        502: the language model provider failed
    """
    # `response` is unused here but required: the rate limiter writes its
    # X-RateLimit-* headers into it, since this handler returns a model.
    _require_project(project_id)
    try:
        result = await asyncio.to_thread(_qa(k=payload.k).answer, project_id, payload.question)
    except NotIndexedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        # Provider clients raise RuntimeError for HTTP failures and timeouts.
        logger.error("Answering failed for project %s: %s", project_id, exc)
        raise HTTPException(
            status_code=502, detail=f"The language model request failed: {exc}"
        ) from exc
    return _answer(project_id, result)
