"""LLM usage recorded while a job runs, and the rollups served from it.

The pipeline is replaced with one that makes simulated LLM calls from worker
threads, the way the real one does, so attribution, persistence and the
endpoint are exercised without a model.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from db.repositories import ProjectRepository
from db.session import session_scope
from main import app
from services.events import completed, processing, progress
from services.jobs import JobNotFoundError, create_job, get_job_metrics, run_job
from telemetry import llm_stage, track_llm_call

client = TestClient(app)


def _call(stage: str, input_tokens: int, output_tokens: int, generation_ms=None):
    with llm_stage(stage), track_llm_call("ollama", "qwen2.5:7b", "chat") as call:
        call.input_tokens = input_tokens
        call.output_tokens = output_tokens
        call.generation_ms = generation_ms


class MeteredPipeline:
    """Emits events while making LLM calls from worker threads."""

    def __init__(self, *, crash_after_first_call=False):
        self.project_id = uuid.uuid4().hex
        self._crash = crash_after_first_call

    async def run(self):
        with session_scope() as session:
            ProjectRepository(session).create(self.project_id, "prompt")
        yield processing("Starting")

        await asyncio.to_thread(_call, "extraction", 1000, 100, 2000)
        yield progress("Extracted", {})
        if self._crash:
            raise RuntimeError("worker died")

        await asyncio.to_thread(_call, "reference_extraction", 2000, 400, 8000)
        yield completed("Done", {})

        # Made after the last event, so only the runner's final flush can
        # record it.
        await asyncio.to_thread(_call, "gap_verbalization", 300, 60)


async def _run(pipeline) -> str:
    job_id = create_job("prompt", {})
    await run_job(job_id, pipeline)
    return job_id


@pytest.mark.asyncio
class TestRecording:
    async def test_every_call_made_during_the_run_is_persisted(self):
        metrics = get_job_metrics(await _run(MeteredPipeline()))

        totals = metrics["totals"]
        assert totals["calls"] == 3
        assert (totals["input_tokens"], totals["output_tokens"]) == (3300, 560)
        assert totals["cost_usd"] == 0.0
        assert totals["unpriced_calls"] == 0

    async def test_calls_are_attributed_to_their_stage(self):
        metrics = get_job_metrics(await _run(MeteredPipeline()))

        stages = {row["stage"]: row for row in metrics["by_stage"]}
        assert set(stages) == {"extraction", "reference_extraction", "gap_verbalization"}
        assert stages["reference_extraction"]["input_tokens"] == 2000
        assert stages["reference_extraction"]["decode_tokens_per_second"] == pytest.approx(50.0)

    async def test_a_crashed_run_keeps_what_it_already_spent(self):
        job_id = await _run(MeteredPipeline(crash_after_first_call=True))

        metrics = get_job_metrics(job_id)
        assert metrics["status"] == "failed"
        assert metrics["totals"]["calls"] == 1
        assert metrics["by_stage"][0]["stage"] == "extraction"

    async def test_calls_from_one_job_do_not_leak_into_another(self):
        first = await _run(MeteredPipeline())
        second = await _run(MeteredPipeline(crash_after_first_call=True))

        assert get_job_metrics(first)["totals"]["calls"] == 3
        assert get_job_metrics(second)["totals"]["calls"] == 1

    async def test_a_job_with_no_calls_reports_zeroes(self):
        job_id = create_job("prompt", {})
        metrics = get_job_metrics(job_id)
        assert metrics["status"] == "pending"
        assert metrics["totals"]["calls"] == 0
        assert metrics["by_stage"] == []

    async def test_unknown_job_raises(self):
        with pytest.raises(JobNotFoundError):
            get_job_metrics("nope")


@pytest.mark.asyncio
class TestTrace:
    async def test_a_job_is_its_own_trace_with_the_calls_beneath_it(self, spans):
        await _run(MeteredPipeline())

        finished = spans.get_finished_spans()
        [job_span] = [s for s in finished if s.name == "research_job"]
        assert job_span.parent is None

        llm_spans = [s for s in finished if s.name == "chat qwen2.5:7b"]
        assert len(llm_spans) == 3
        assert {s.context.trace_id for s in llm_spans} == {job_span.context.trace_id}

    async def test_a_crash_marks_the_job_span(self, spans):
        from opentelemetry.trace import StatusCode

        await _run(MeteredPipeline(crash_after_first_call=True))

        [job_span] = [s for s in spans.get_finished_spans() if s.name == "research_job"]
        assert job_span.status.status_code == StatusCode.ERROR


@pytest.mark.asyncio
class TestEndpoint:
    async def test_returns_the_rollups(self):
        job_id = await _run(MeteredPipeline())

        response = client.get(f"/api/jobs/{job_id}/metrics")
        assert response.status_code == 200
        body = response.json()
        assert body["job_id"] == job_id
        assert body["status"] == "completed"
        assert body["totals"]["calls"] == 3
        assert body["prices_checked"]
        assert {row["model"] for row in body["by_model"]} == {"qwen2.5:7b"}

    async def test_unknown_job_is_404(self):
        assert client.get("/api/jobs/nope/metrics").status_code == 404
