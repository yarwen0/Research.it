"""Tests for background job execution and stream resumption.

The property under test is that a run survives losing its reader — previously
the pipeline ran inside the SSE generator, so a disconnect killed it.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from db.models import Job, JobStatus
from db.repositories import ProjectRepository
from db.session import session_scope
from services import jobs as jobs_module
from services.events import PipelineEvent, StatusType, completed, processing, progress
from services.jobs import (
    JobNotFoundError,
    create_job,
    get_job,
    run_job,
    tail_events,
)


class FakePipeline:
    """Stands in for ResearchPipeline: emits a scripted event sequence.

    Creates its project row on the first event, exactly like the real
    pipeline — the job cannot be linked to a project before then.
    """

    def __init__(self, events=None, *, delay=0.0, raises=None, creates_project=True):
        self.project_id = uuid.uuid4().hex
        self._events = events or [
            processing("Starting"),
            progress("Halfway", {"paper_count": 2}),
            completed("Done", {"total_papers": 2}),
        ]
        self._delay = delay
        self._raises = raises
        self._creates_project = creates_project
        self.emitted = 0

    async def run(self):
        for index, event in enumerate(self._events):
            if self._delay:
                await asyncio.sleep(self._delay)
            if index == 0 and self._creates_project:
                with session_scope() as session:
                    ProjectRepository(session).create(self.project_id, "prompt")
            self.emitted += 1
            yield event
        if self._raises:
            raise self._raises


@pytest.mark.asyncio
class TestJobLifecycle:
    async def test_records_every_event_in_order(self):
        job_id = create_job("prompt", {})
        await run_job(job_id, FakePipeline())

        seen = [event async for event in tail_events(job_id)]
        assert [e["message"] for e in seen] == ["Starting", "Halfway", "Done"]
        assert [e["sequence"] for e in seen] == [0, 1, 2]

    async def test_marks_completed_on_success(self):
        job_id = create_job("prompt", {})
        await run_job(job_id, FakePipeline())
        assert get_job(job_id)["status"] == JobStatus.COMPLETED.value

    async def test_links_the_project_it_created(self):
        job_id = create_job("prompt", {})
        pipeline = FakePipeline()
        await run_job(job_id, pipeline)
        assert get_job(job_id)["project_id"] == pipeline.project_id

    async def test_leaves_project_unlinked_if_the_run_never_created_one(self):
        # The pipeline picks its project id up front but inserts the row a
        # stage or two in; linking eagerly would break the foreign key.
        job_id = create_job("prompt", {})
        await run_job(job_id, FakePipeline(creates_project=False))
        assert get_job(job_id)["project_id"] is None

    async def test_preserves_event_payloads(self):
        job_id = create_job("prompt", {})
        await run_job(job_id, FakePipeline())

        seen = [event async for event in tail_events(job_id)]
        assert seen[1]["result"] == {"paper_count": 2}
        assert seen[2]["result"] == {"total_papers": 2}

    async def test_crash_is_recorded_rather_than_lost(self):
        job_id = create_job("prompt", {})
        await run_job(job_id, FakePipeline(raises=RuntimeError("boom")))

        job = get_job(job_id)
        assert job["status"] == JobStatus.FAILED.value
        assert "boom" in job["error"]

    async def test_pipeline_error_event_fails_the_job(self):
        events = [
            processing("Starting"),
            PipelineEvent(StatusType.ERROR, "Pipeline error: arXiv unreachable"),
        ]
        job_id = create_job("prompt", {})
        await run_job(job_id, FakePipeline(events))

        assert get_job(job_id)["status"] == JobStatus.FAILED.value

    async def test_per_paper_error_does_not_fail_the_job(self):
        # A single unreadable paper is reported and skipped; the run is fine.
        events = [
            PipelineEvent(StatusType.ERROR, "Error processing paper Foo: bad JSON"),
            completed("Done", {"total_papers": 1}),
        ]
        job_id = create_job("prompt", {})
        await run_job(job_id, FakePipeline(events))

        assert get_job(job_id)["status"] == JobStatus.COMPLETED.value


@pytest.mark.asyncio
class TestResumption:
    async def test_replays_from_the_beginning_by_default(self):
        job_id = create_job("prompt", {})
        await run_job(job_id, FakePipeline())

        seen = [event async for event in tail_events(job_id)]
        assert len(seen) == 3

    async def test_resumes_after_a_given_sequence(self):
        job_id = create_job("prompt", {})
        await run_job(job_id, FakePipeline())

        # A client that saw sequence 0 gets only what it missed.
        seen = [event async for event in tail_events(job_id, after=0)]
        assert [e["sequence"] for e in seen] == [1, 2]

    async def test_run_survives_its_reader_disconnecting(self):
        """The point of the whole design."""
        job_id = create_job("prompt", {})
        pipeline = FakePipeline(delay=0.01)

        task = asyncio.create_task(run_job(job_id, pipeline))

        # Read one event, then walk away mid-run.
        stream = tail_events(job_id)
        await stream.__anext__()
        await stream.aclose()

        await task

        # The run finished anyway, and everything it produced is still there.
        assert get_job(job_id)["status"] == JobStatus.COMPLETED.value
        replayed = [event async for event in tail_events(job_id)]
        assert len(replayed) == 3
        assert pipeline.emitted == 3

    async def test_tailing_a_live_job_yields_events_as_they_land(self):
        job_id = create_job("prompt", {})
        task = asyncio.create_task(run_job(job_id, FakePipeline(delay=0.01)))

        seen = [event async for event in tail_events(job_id)]
        await task

        assert [e["message"] for e in seen] == ["Starting", "Halfway", "Done"]

    async def test_unknown_job_raises(self):
        with pytest.raises(JobNotFoundError):
            [event async for event in tail_events("nope")]

    async def test_get_unknown_job_raises(self):
        with pytest.raises(JobNotFoundError):
            get_job("nope")

    async def test_tail_gives_up_on_a_wedged_job(self, monkeypatch):
        # A job stuck RUNNING must not hold a connection open forever.
        monkeypatch.setattr(jobs_module, "IDLE_TIMEOUT_SECONDS", 0.05)
        monkeypatch.setattr(jobs_module, "POLL_INTERVAL_SECONDS", 0.01)

        job_id = create_job("prompt", {})
        with session_scope() as session:
            session.get(Job, job_id).status = JobStatus.RUNNING

        seen = await asyncio.wait_for(
            _collect(tail_events(job_id)), timeout=5
        )
        assert seen == []


async def _collect(agen):
    return [item async for item in agen]
