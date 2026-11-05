"""Research.it as an MCP server.

Any MCP client — Claude Desktop, an IDE assistant, an agent built on Google's
Agent Development Kit — can use a research run's papers as tools: find a run,
search its papers, ask a grounded question, read a paper's structured
record, list research gaps, see what the papers cite. The data comes from
`agents.data`, the same layer the built-in assistant's tools read.

Every tool is read-only. Starting a research run — minutes of arXiv downloads
and LLM calls — is deliberately not one of them.

One definition, two transports: stdio (`python -m mcp_server`) for desktop
clients, and streamable HTTP mounted on the API at /mcp/ behind a bearer
token (see `mount_http`).
"""

from __future__ import annotations

import asyncio
import hmac
import json
from collections.abc import Callable
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.types import ASGIApp, Receive, Scope, Send

from agents import data
from core import create_llm_client
from retrieval.embedder import ClientEmbedder
from retrieval.hybrid import RetrievedChunk
from services.rag import CorpusQA

INSTRUCTIONS = """Research.it holds research runs: each is a set of arXiv papers on one topic, read, structured and indexed.
Start with list_projects to find a run's project_id. search_papers returns matching passages with their paper and section.
ask_papers answers a question from those passages and cites them as [S1], [S2]; trust it only when grounded is true.
get_paper gives one paper's structured record. find_research_gaps lists method/dataset combinations nobody has tried and problems the papers share.
most_cited_works shows what the papers build on."""

# Every tool here reads; none changes anything or reaches outside the corpus.
READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


def _hit(chunk: RetrievedChunk) -> dict[str, Any]:
    return {
        "paper_id": chunk.paper_id,
        "paper_title": chunk.paper_title,
        "section": chunk.section,
        "kind": chunk.kind,
        "text": chunk.text,
        "score": round(chunk.score, 6),
    }


def build_server(
    *,
    llm_client_factory: Callable[[], Any] = create_llm_client,
    streamable_http_path: str = "/mcp",
    json_response: bool = False,
    stateless_http: bool = False,
    transport_security: TransportSecuritySettings | None = None,
) -> FastMCP:
    """The server definition, transport-independent."""
    mcp = FastMCP(
        "research-it",
        instructions=INSTRUCTIONS,
        streamable_http_path=streamable_http_path,
        json_response=json_response,
        stateless_http=stateless_http,
        transport_security=transport_security,
    )

    def project(project_id: str) -> data.ProjectData:
        found = data.ProjectData(project_id, ClientEmbedder(llm_client_factory()))
        if not found.exists():
            raise ValueError(f"No project {project_id!r}; list_projects shows the ones there are.")
        return found

    # Each tool's work runs in a thread: the queries block, and on the HTTP
    # transport the event loop is the API's own.

    @mcp.tool(annotations=READ_ONLY)
    async def list_projects(limit: int = 20) -> list[dict[str, Any]]:
        """Recent research runs: their project_id, topic, papers processed and passages indexed."""
        return await asyncio.to_thread(data.list_projects, max(1, min(limit, 100)))

    @mcp.tool(annotations=READ_ONLY)
    async def search_papers(
        project_id: str,
        query: str,
        k: int = 8,
        strategy: Literal["hybrid", "dense", "lexical"] = "hybrid",
    ) -> list[dict[str, Any]]:
        """Passages from a run's papers that best match the query, best first.

        Hybrid search fuses BM25 and embedding similarity; it ranks the
        answering passage first most often (see evals/retrieval).
        """

        def search() -> list[dict[str, Any]]:
            hits = project(project_id).passages(query, max(1, min(k, 20)), strategy=strategy)
            return [_hit(hit) for hit in hits]

        return await asyncio.to_thread(search)

    @mcp.tool(annotations=READ_ONLY)
    async def ask_papers(project_id: str, question: str) -> dict[str, Any]:
        """Answer a question from a run's papers, citing passages as [S1], [S2].

        `sources` maps each id to its passage. `grounded` is false when the
        answer neither cites a source nor declines; do not rely on it then.
        """

        def ask() -> dict[str, Any]:
            project(project_id)
            client = llm_client_factory()
            result = CorpusQA(client, ClientEmbedder(client)).answer(project_id, question)
            return {
                "answer": result.answer,
                "grounded": result.grounded,
                "insufficient_evidence": result.insufficient_evidence,
                "sources": [
                    {"id": source.id, "cited": source.id in result.cited, **_hit(source.chunk)}
                    for source in result.sources
                ],
            }

        return await asyncio.to_thread(ask)

    @mcp.tool(annotations=READ_ONLY)
    async def get_paper(project_id: str, paper_id: str) -> dict[str, Any]:
        """One paper's structured record — problem, methods, datasets, limitations, future work.

        `paper_id` is its arXiv id, or a few words of its title.
        """

        def read() -> dict[str, Any]:
            paper = project(project_id).paper(paper_id)
            if paper is None:
                raise ValueError(f"No processed paper matches {paper_id!r} in project {project_id}.")
            return {
                "paper_id": paper.paper_id,
                "title": paper.title,
                "published": paper.published,
                "record": paper.record,
                "normalized": paper.normalized,
            }

        return await asyncio.to_thread(read)

    @mcp.tool(annotations=READ_ONLY)
    async def find_research_gaps(
        project_id: str,
        gap_type: Literal[
            "method_transfer", "dataset_transfer", "limitation_gap", "future_work_gap"
        ]
        | None = None,
        top: int = 10,
    ) -> list[dict[str, Any]]:
        """Research gaps across a run's papers, from the symbolic gap finder.

        Transfer gaps are method/dataset pairings no paper has tried; the
        others are limitations several papers share and future work nobody has
        done. Measured precision is 0.72 (evals/README.md): treat these as leads.
        """
        return await asyncio.to_thread(
            lambda: project(project_id).gaps(gap_type, max(1, min(top, 50)))
        )

    @mcp.tool(annotations=READ_ONLY)
    async def most_cited_works(project_id: str, top: int = 10) -> list[dict[str, Any]]:
        """The works a run's papers cite most often, with how many cite each."""
        return await asyncio.to_thread(
            lambda: project(project_id).most_cited(max(1, min(top, 50)))
        )

    return mcp


class BearerTokenGate:
    """Refuse any request without the configured bearer token.

    The token comparison is constant-time, and there is no unauthenticated
    mode: without a token configured, `mount_http` does not mount anything.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            supplied = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(supplied, self._expected):
                body = json.dumps({"detail": "A valid bearer token is required."}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"www-authenticate", b"Bearer"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def mount_http(
    app: Any, token: str, *, path: str = "/mcp", llm_client_factory: Callable[[], Any] = create_llm_client
) -> StreamableHTTPSessionManager:
    """Serve the MCP server over streamable HTTP at `path`/, behind a token.

    Returns the session manager, which the host app must run for its
    lifetime (`async with manager.run():` in its lifespan): Starlette does not
    run a mounted app's own lifespan.
    """
    mcp = build_server(
        llm_client_factory=llm_client_factory,
        streamable_http_path="/",
        # One JSON response per request and no server-side sessions: nothing
        # to lose when the API restarts, and simple for any HTTP client.
        json_response=True,
        stateless_http=True,
        # DNS-rebinding protection guards servers that trust local callers.
        # This one trusts no caller without the token, which a page rebound
        # to it cannot produce.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    app.mount(path, BearerTokenGate(mcp.streamable_http_app(), token))
    return mcp.session_manager
