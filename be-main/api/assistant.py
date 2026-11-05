"""The research assistant's routes: conversations about one project.

A turn starts a job and streams its events, so the same resume endpoint that
serves research runs (GET /api/jobs/{id}/events?after=n) serves the
assistant, and the same metrics endpoint reports what a turn cost.

No `from __future__ import annotations`: see api/retrieval.py.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.api import job_event_stream
from api.schemas import AssistantRequest, ThreadListResponse, ThreadResponse
from config import RATE_LIMIT_ASSISTANT
from core import create_llm_client
from db.repositories import ProjectRepository
from db.session import session_scope
from rate_limit import limiter
from retrieval.embedder import ClientEmbedder
from retrieval.store import ChunkStore
from services.assistant import (
    AssistantTurn,
    ThreadNotFoundError,
    create_thread,
    get_thread,
    list_threads,
    require_thread,
)
from services.jobs import start_job

router = APIRouter()


def _require_indexed_project(project_id: str) -> None:
    with session_scope() as session:
        if not ProjectRepository(session).exists(project_id):
            raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
        model = ClientEmbedder(create_llm_client()).model_id
        if ChunkStore(session).count(project_id, model) == 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Project {project_id} has no passages indexed with {model}; "
                    "index it with scripts/index_project.py first"
                ),
            )


@router.post("/projects/{project_id}/assistant")
@limiter.limit(RATE_LIMIT_ASSISTANT)
async def assistant_endpoint(request: Request, project_id: str, payload: AssistantRequest):
    """Ask the research assistant a question about a project (SSE).

    A supervisor delegates to specialists — literature, research gaps,
    citations — that use the project's tools; a writer answers from what they
    found, citing evidence as [E1], [E2]; a critic checks the answer against
    that evidence and may send it back once. Every step streams as it
    happens. The final event carries the answer, its citations, the plan and
    the critique.

    Pass `thread_id` to continue a conversation; follow-up questions see the
    recent history.

    Status codes:
        404: no such project, or no such thread in it
        409: the project has no indexed passages
    """
    _require_indexed_project(project_id)
    if payload.thread_id:
        try:
            require_thread(payload.thread_id, project_id)
        except ThreadNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail=f"Thread not found: {payload.thread_id}"
            ) from exc
        thread_id = payload.thread_id
    else:
        thread_id = create_thread(project_id, payload.message)

    turn = AssistantTurn(project_id=project_id, thread_id=thread_id, message=payload.message)
    job_id = start_job(
        payload.message,
        {"kind": "assistant", "project_id": project_id, "thread_id": thread_id},
        turn,
    )
    # The job's task is scheduled but cannot start until this handler yields
    # control, so the id is set before the turn records its first message.
    turn.job_id = job_id

    return StreamingResponse(
        job_event_stream(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/projects/{project_id}/threads", response_model=ThreadListResponse)
async def list_threads_endpoint(project_id: str):
    """A project's assistant conversations, most recently active first."""
    with session_scope() as session:
        if not ProjectRepository(session).exists(project_id):
            raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return {"threads": list_threads(project_id)}


@router.get("/threads/{thread_id}", response_model=ThreadResponse)
async def get_thread_endpoint(thread_id: str):
    """One conversation, every message in order, answers with their evidence."""
    thread = get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail=f"Thread not found: {thread_id}")
    return thread
