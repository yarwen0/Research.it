"""The MCP server: its tools through a real client session, and the HTTP mount.

Tools are called through the MCP SDK's in-memory transport, so these exercise
the protocol — tool listing, argument validation, structured results, error
results — not just the Python functions behind it.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_server.server import build_server, mount_http
from tests.fakes import FakeLLMClient
from tests.seeds import seed_pose_project

TOOLS = {
    "list_projects",
    "search_papers",
    "ask_papers",
    "get_paper",
    "find_research_gaps",
    "most_cited_works",
}


@pytest.fixture(scope="module")
def project_id() -> str:
    return seed_pose_project()


def _server(llm=None):
    client = llm or FakeLLMClient()
    return build_server(llm_client_factory=lambda: client)


async def _call(tool, llm=None, **arguments):
    async with create_connected_server_and_client_session(_server(llm)) as client:
        return await client.call_tool(tool, arguments)


def _content(result):
    """A tool's structured result, unwrapped from FastMCP's {"result": ...}."""
    assert not result.isError, result.content
    structured = result.structuredContent
    return structured.get("result", structured)


@pytest.mark.asyncio
class TestTools:
    async def test_every_tool_is_listed_and_read_only(self):
        async with create_connected_server_and_client_session(_server()) as client:
            tools = (await client.list_tools()).tools
        assert {tool.name for tool in tools} == TOOLS
        assert all(tool.annotations.readOnlyHint for tool in tools)

    async def test_list_projects(self, project_id):
        projects = _content(await _call("list_projects", limit=100))
        entry = next(p for p in projects if p["project_id"] == project_id)
        assert entry["processed_papers"] == 2
        assert entry["indexed_passages"] > 0

    async def test_search_papers(self, project_id):
        hits = _content(
            await _call("search_papers", project_id=project_id, query="rmsprop learning rate", k=2)
        )
        assert "2.5e-4" in hits[0]["text"]
        assert hits[0]["paper_id"] == "1603.06937"

    async def test_ask_papers_returns_a_grounded_answer(self, project_id):
        llm = FakeLLMClient(['{"answer": "It uses rmsprop at 2.5e-4 [S1].", "insufficient_evidence": false}'])
        answer = _content(
            await _call("ask_papers", llm=llm, project_id=project_id, question="Which learning rate?")
        )
        assert answer["grounded"] is True
        assert answer["answer"] == "It uses rmsprop at 2.5e-4 [S1]."
        assert answer["sources"][0]["id"] == "S1"
        assert answer["sources"][0]["cited"] is True

    async def test_get_paper_by_title_words(self, project_id):
        paper = _content(await _call("get_paper", project_id=project_id, paper_id="DreamPose3D"))
        assert paper["paper_id"] == "2511.09502"
        assert "Human3.6M" in paper["record"]

    async def test_find_research_gaps(self, project_id):
        gaps = _content(
            await _call("find_research_gaps", project_id=project_id, gap_type="limitation_gap")
        )
        assert gaps
        assert all(gap["gap_type"] == "limitation_gap" for gap in gaps)
        assert all(gap["description"] for gap in gaps)

    async def test_most_cited_works(self, project_id):
        [top] = _content(await _call("most_cited_works", project_id=project_id, top=1))
        assert top["title"].startswith("Deep Residual Learning")
        assert top["cited_by"] == 2

    async def test_an_unknown_project_is_a_tool_error(self):
        result = await _call("search_papers", project_id="nope", query="x")
        assert result.isError
        assert "list_projects" in result.content[0].text

    async def test_an_unknown_paper_is_a_tool_error(self, project_id):
        result = await _call("get_paper", project_id=project_id, paper_id="not a paper")
        assert result.isError

    async def test_arguments_are_validated_against_the_schema(self, project_id):
        result = await _call("find_research_gaps", project_id=project_id, gap_type="made_up")
        assert result.isError


TOKEN = "test-token"
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "tests", "version": "0"},
    },
}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture
def http_client():
    """An app with the MCP endpoint mounted, its session manager running."""
    holder = {}

    @asynccontextmanager
    async def lifespan(_app):
        async with holder["sessions"].run():
            yield

    app = FastAPI(lifespan=lifespan)
    holder["sessions"] = mount_http(app, TOKEN, llm_client_factory=FakeLLMClient)
    with TestClient(app) as client:
        yield client


def _post(client, body, token=TOKEN):
    headers = dict(HEADERS)
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/mcp/", content=json.dumps(body), headers=headers)


class TestHttpTransport:
    def test_a_request_without_a_token_is_refused(self, http_client):
        response = _post(http_client, INITIALIZE, token=None)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"

    def test_a_wrong_token_is_refused(self, http_client):
        assert _post(http_client, INITIALIZE, token="guess").status_code == 401

    def test_initialize_with_the_token(self, http_client):
        response = _post(http_client, INITIALIZE)
        assert response.status_code == 200
        assert response.json()["result"]["serverInfo"]["name"] == "research-it"

    def test_tools_are_listed_over_http(self, http_client):
        _post(http_client, INITIALIZE)
        response = _post(http_client, LIST_TOOLS)
        assert response.status_code == 200
        assert {tool["name"] for tool in response.json()["result"]["tools"]} == TOOLS

    def test_requests_are_rate_limited_per_client(self):
        # The API's own limiter exempts mounted apps; this gate must not.
        holder = {}

        @asynccontextmanager
        async def lifespan(_app):
            async with holder["sessions"].run():
                yield

        app = FastAPI(lifespan=lifespan)
        holder["sessions"] = mount_http(
            app, TOKEN, rate_limit="2/minute", llm_client_factory=FakeLLMClient
        )
        with TestClient(app) as client:
            statuses = [_post(client, INITIALIZE).status_code for _ in range(3)]
            guessing = _post(client, INITIALIZE, token="guess")
        assert statuses == [200, 200, 429]
        # Token guesses spend the same budget; they get no free attempts.
        assert guessing.status_code == 429
        assert int(guessing.headers["retry-after"]) >= 1

    def test_nothing_is_mounted_without_a_key(self):
        import main

        assert main.mcp_sessions is None
        response = TestClient(main.app).post("/mcp/", json=INITIALIZE)
        assert response.status_code == 404
