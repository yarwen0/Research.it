"""Assistant turns on the job runner, conversation storage, and the routes."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from db.models import AgentMessage
from db.session import session_scope
from main import app
from services import assistant as assistant_module
from services.assistant import (
    AssistantTurn,
    _record,
    create_thread,
    get_thread,
    history_for,
    list_threads,
)
from services.jobs import create_job, get_job_metrics, run_job, tail_events
from tests.fakes import FakeLLMClient, HashingEmbedder, agent_responder
from tests.seeds import seed_pose_project

QUESTION = "What learning rate does the hourglass network use?"


@pytest.fixture(scope="module")
def project_id() -> str:
    return seed_pose_project()


def _llm(**kwargs):
    return FakeLLMClient(respond=agent_responder(plan={"literature": "find the learning rate"}, **kwargs))


async def _turn(project_id, *, thread_id=None, message=QUESTION, llm=None):
    thread_id = thread_id or create_thread(project_id, message)
    job_id = create_job(message, {"kind": "assistant"})
    turn = AssistantTurn(
        project_id=project_id,
        thread_id=thread_id,
        message=message,
        llm_client=llm or _llm(),
        embedder=HashingEmbedder(),
    )
    turn.job_id = job_id
    await run_job(job_id, turn)
    events = [event async for event in tail_events(job_id)]
    return thread_id, job_id, events


class TestHistory:
    def test_newest_messages_within_budget(self, project_id, monkeypatch):
        monkeypatch.setattr(assistant_module, "HISTORY_MESSAGES", 3)
        thread_id = create_thread(project_id, "first")
        for index in range(5):
            _record(thread_id, "user" if index % 2 == 0 else "assistant", f"message {index}")
        assert history_for(thread_id) == "User: message 2\nAssistant: message 3\nUser: message 4"

    def test_the_oldest_is_cut_when_the_budget_runs_out(self, project_id, monkeypatch):
        monkeypatch.setattr(assistant_module, "HISTORY_CHARS", 30)
        thread_id = create_thread(project_id, "first")
        _record(thread_id, "user", "an old and rather long question")
        _record(thread_id, "assistant", "short reply")
        assert history_for(thread_id) == "Assistant: short reply"

    def test_a_long_opening_question_makes_a_short_title(self, project_id):
        thread_id = create_thread(project_id, "word " * 50)
        assert len(get_thread(thread_id)["title"]) == 80


@pytest.mark.asyncio
class TestTurn:
    async def test_streams_steps_then_the_cited_answer(self, project_id):
        _, _, events = await _turn(project_id)

        messages = [event["message"] for event in events]
        assert messages[0] == "Planning how to answer..."
        assert "Delegating to literature" in messages
        assert any(m.startswith("literature → search_passages") for m in messages)
        final = events[-1]
        assert final["status"] == "completed"
        assert final["result"]["answer"] == "Hourglass uses rmsprop [E1]."
        assert final["result"]["grounded"] is True
        assert final["result"]["citations"][0]["id"] == "E1"

    async def test_both_sides_of_the_turn_are_kept(self, project_id):
        thread_id, job_id, _ = await _turn(project_id)

        thread = get_thread(thread_id)
        assert [m["role"] for m in thread["messages"]] == ["user", "assistant"]
        assert thread["messages"][0]["content"] == QUESTION
        assert thread["messages"][1]["payload"]["citations"][0]["id"] == "E1"
        assert {m["job_id"] for m in thread["messages"]} == {job_id}

    async def test_a_follow_up_sees_the_conversation(self, project_id):
        llm = _llm()
        thread_id, _, _ = await _turn(project_id, llm=llm)
        await _turn(project_id, thread_id=thread_id, message="And on which dataset?", llm=llm)

        plan_prompts = [
            messages[-1]["content"]
            for messages, fmt in llm.requests
            if fmt and fmt["json_schema"]["name"] == "assistant_plan"
        ]
        assert "Conversation so far" not in plan_prompts[0]
        assert f"User: {QUESTION}" in plan_prompts[1]
        assert "Assistant: Hourglass uses rmsprop [E1]." in plan_prompts[1]

    async def test_what_a_turn_cost_is_recorded_per_agent_stage(self, project_id):
        _, job_id, _ = await _turn(project_id)
        stages = {row["stage"] for row in get_job_metrics(job_id)["by_stage"]}
        assert {"agent.plan", "agent.literature", "agent.write", "agent.critique"} <= stages

    async def test_a_failing_model_fails_the_job_with_a_message(self, project_id):
        def broken(*_args):
            raise RuntimeError("Cannot reach Ollama")

        _, job_id, events = await _turn(project_id, llm=FakeLLMClient(respond=broken))
        assert events[-1]["status"] == "error"
        assert "Cannot reach Ollama" in events[-1]["message"]
        assert get_job_metrics(job_id)["status"] == "failed"


@pytest.fixture
def api(monkeypatch):
    llm = _llm()
    monkeypatch.setattr("api.assistant.create_llm_client", lambda: llm)
    monkeypatch.setattr("services.assistant.create_llm_client", lambda: llm)
    return TestClient(app)


def _frames(response) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


class TestRoutes:
    def test_a_turn_streams_to_completion(self, api, project_id):
        response = api.post(f"/api/projects/{project_id}/assistant", json={"message": QUESTION})

        assert response.status_code == 200
        frames = _frames(response)
        assert frames[0]["result"]["job_id"]
        assert frames[-1]["status"] == "completed"
        assert frames[-1]["result"]["answer"] == "Hourglass uses rmsprop [E1]."

    def test_continuing_a_thread(self, api, project_id):
        first = _frames(api.post(f"/api/projects/{project_id}/assistant", json={"message": QUESTION}))
        thread_id = first[-1]["result"]["thread_id"]

        api.post(
            f"/api/projects/{project_id}/assistant",
            json={"message": "And the dataset?", "thread_id": thread_id},
        )
        thread = api.get(f"/api/threads/{thread_id}").json()
        assert [m["role"] for m in thread["messages"]] == ["user", "assistant", "user", "assistant"]

    def test_threads_are_listed_most_recent_first(self, api, project_id):
        api.post(f"/api/projects/{project_id}/assistant", json={"message": "older question"})
        api.post(f"/api/projects/{project_id}/assistant", json={"message": "newer question"})
        titles = [t["title"] for t in api.get(f"/api/projects/{project_id}/threads").json()["threads"]]
        assert titles.index("newer question") < titles.index("older question")

    def test_unknown_project_is_404(self, api):
        assert api.post("/api/projects/nope/assistant", json={"message": "x"}).status_code == 404
        assert api.get("/api/projects/nope/threads").status_code == 404

    def test_unknown_thread_is_404(self, api, project_id):
        response = api.post(
            f"/api/projects/{project_id}/assistant", json={"message": "x", "thread_id": "missing"}
        )
        assert response.status_code == 404
        assert api.get("/api/threads/missing").status_code == 404

    def test_an_unindexed_project_is_409(self, api):
        from tests.test_rag import _empty_project

        response = api.post(f"/api/projects/{_empty_project()}/assistant", json={"message": "x"})
        assert response.status_code == 409

    def test_a_blank_message_is_422(self, api, project_id):
        response = api.post(f"/api/projects/{project_id}/assistant", json={"message": "  "})
        assert response.status_code == 422

    def test_a_thread_lists_with_its_message_count(self, api, project_id):
        _frames(api.post(f"/api/projects/{project_id}/assistant", json={"message": "count me"}))
        [entry] = [t for t in list_threads(project_id) if t["title"] == "count me"]
        assert entry["messages"] == 2
        with session_scope() as session:
            assert session.query(AgentMessage).filter_by(thread_id=entry["thread_id"]).count() == 2
