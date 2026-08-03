"""Background execution of research runs.

Before this, the pipeline *was* the HTTP response: it ran inside the SSE
generator, so a client that navigated away or lost its connection killed the
run in place. Minutes of arXiv downloads and LLM calls were discarded, and
there was no record that the run had ever happened.

Now a run is a `Job`. It executes as a background task, writes every event to
the database as it goes, and a client tails those events. Disconnecting stops
the reading, not the work — reconnecting resumes from the last sequence
number seen.

Scope: this is an in-process runner, so jobs die with the container and do not
spread across workers. The seam is drawn where it needs to be — the pipeline
emits events and the runner persists them — so replacing this with Celery or
ARQ is a change to this module alone.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, AsyncGenerator, Optional

from sqlalchemy import select

from db.models import Job, JobEvent, JobStatus, Project
from db.session import session_scope
from services.events import PipelineEvent, StatusType
from services.research_pipeline import ResearchPipeline

logger = logging.getLogger(__name__)

# How long a tailing client waits between checks for new events. Short enough
# to feel live, long enough not to hammer the database.
POLL_INTERVAL_SECONDS = 0.25

# Give up tailing a job that has produced nothing for this long. Guards against
# a client holding a connection open forever against a wedged run.
IDLE_TIMEOUT_SECONDS = 900


class JobNotFoundError(LookupError):
    """Raised when a job id does not exist."""


def create_job(user_prompt: str, params: dict[str, Any]) -> str:
    """Record a new job and return its id."""
    job_id = uuid.uuid4().hex
    with session_scope() as session:
        session.add(
            Job(
                id=job_id,
                status=JobStatus.PENDING,
                user_prompt=user_prompt,
                params=params,
            )
        )
    logger.info("Created job %s", job_id)
    return job_id


def _append_event(job_id: str, sequence: int, event: PipelineEvent) -> None:
    with session_scope() as session:
        session.add(
            JobEvent(
                job_id=job_id,
                sequence=sequence,
                status=event.status.value,
                message=event.message,
                result=event.result,
            )
        )


def _mark(job_id: str, status: JobStatus, *, error: Optional[str] = None) -> None:
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status = status
        if error is not None:
            job.error = error


def _try_link_project(job_id: str, project_id: str) -> bool:
    """Point the job at its project, once that project exists.

    The pipeline generates its project id up front but does not insert the row
    until it starts running, so linking eagerly would violate the foreign key.
    Returns whether the link was made, letting the caller stop retrying.
    """
    with session_scope() as session:
        if session.get(Project, project_id) is None:
            return False
        job = session.get(Job, job_id)
        if job is None:
            return False
        job.project_id = project_id
        return True


async def run_job(job_id: str, pipeline: ResearchPipeline) -> None:
    """Execute a pipeline, persisting every event it emits.

    Runs detached from any request, so exceptions have nowhere to propagate —
    they are recorded on the job instead of vanishing into a dead task.
    """
    _mark(job_id, JobStatus.RUNNING)
    sequence = 0
    failed = False
    linked = False

    try:
        async for event in pipeline.run():
            _append_event(job_id, sequence, event)
            sequence += 1

            # The project row appears a stage or two in, so keep trying until
            # it does. Cheap once linked, and the flag stops it after that.
            if not linked:
                linked = _try_link_project(job_id, pipeline.project_id)

            if event.status == StatusType.ERROR and "Pipeline error" in event.message:
                failed = True
    except asyncio.CancelledError:
        # Shutdown, not failure. Record it so a tailing client is not left
        # waiting on a job that will never produce another event.
        logger.warning("Job %s cancelled", job_id)
        _mark(job_id, JobStatus.FAILED, error="Job cancelled")
        raise
    except Exception as exc:
        logger.exception("Job %s crashed", job_id)
        _mark(job_id, JobStatus.FAILED, error=str(exc))
        return

    _mark(job_id, JobStatus.FAILED if failed else JobStatus.COMPLETED)
    logger.info("Job %s finished after %s events", job_id, sequence)


def start_job(
    user_prompt: str, params: dict[str, Any], pipeline: ResearchPipeline
) -> str:
    """Create a job and kick it off in the background."""
    job_id = create_job(user_prompt, params)
    task = asyncio.create_task(run_job(job_id, pipeline))
    # Without a reference the loop may garbage-collect the task mid-run.
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return job_id


_BACKGROUND_TASKS: set[asyncio.Task] = set()


def get_job(job_id: str) -> dict[str, Any]:
    """Return a job's current state."""
    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        return {
            "job_id": job.id,
            "status": job.status.value,
            "project_id": job.project_id,
            "user_prompt": job.user_prompt,
            "error": job.error,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        }


def _fetch_events(job_id: str, after: int) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.sequence > after)
            .order_by(JobEvent.sequence)
        ).all()
        return [
            {
                "sequence": row.sequence,
                "status": row.status,
                "message": row.message,
                "result": row.result,
            }
            for row in rows
        ]


def _is_finished(job_id: str) -> bool:
    with session_scope() as session:
        job = session.get(Job, job_id)
        return job is not None and job.status in (
            JobStatus.COMPLETED,
            JobStatus.FAILED,
        )


async def tail_events(
    job_id: str, *, after: int = -1
) -> AsyncGenerator[dict[str, Any], None]:
    """Yield a job's events, waiting for new ones until it finishes.

    Args:
        after: last sequence number already seen. Defaults to -1, meaning
            replay from the beginning — which is what makes a reconnecting
            client able to catch up on what it missed.
    """
    with session_scope() as session:
        if session.get(Job, job_id) is None:
            raise JobNotFoundError(job_id)

    last_seen = after
    idle_for = 0.0

    while True:
        events = _fetch_events(job_id, last_seen)

        if events:
            idle_for = 0.0
            for event in events:
                last_seen = event["sequence"]
                yield event
            continue

        # Check completion only after draining, so the final events are never
        # dropped by the job finishing between the query and the check.
        if _is_finished(job_id):
            return

        if idle_for >= IDLE_TIMEOUT_SECONDS:
            logger.warning("Stopped tailing job %s after %ss idle", job_id, idle_for)
            return

        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        idle_for += POLL_INTERVAL_SECONDS
