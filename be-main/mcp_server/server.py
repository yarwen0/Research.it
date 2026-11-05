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
import time
from collections.abc import Callable
from typing import Any, Literal

from limits import parse
from limits.storage import storage_from_string
from limits.strategies import FixedWindowRateLimiter
from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from agents import data
from config import RATE_LIMIT_ENABLED, RATE_LIMIT_MCP, RATE_LIMIT_STORAGE_URI
from core import create_llm_client
from rate_limit import client_identifier
from retrieval.embedder import ClientEmbedder
from retrieval.hybrid import RetrievedChunk
from retrieval.screening import Screening, withhold_instructions
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


def _withheld(chunk: RetrievedChunk, screening: Screening) -> dict[str, Any]:
    return {
        "paper_id": chunk.paper_id,
        "paper_title": chunk.paper_title,
        "section": chunk.section,
        "reasons": screening.reasons,
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
    ) -> dict[str, Any]:
        """Passages from a run's papers that best match the query, best first.

        Hybrid search fuses BM25 and embedding similarity; it ranks the
        answering passage first most often (see evals/retrieval). Passages
        that read as instructions to a model are not returned: they are
        listed under `withheld`, with the reason, instead.
        """

        def search() -> dict[str, Any]:
            hits = project(project_id).passages(query, max(1, min(k, 20)), strategy=strategy)
            kept, withheld = withhold_instructions(hits, lambda hit: hit.text)
            return {
                "passages": [_hit(hit) for hit in kept],
                "withheld": [_withheld(hit, screening) for hit, screening in withheld],
            }

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
                "withheld": [_withheld(chunk, screening) for chunk, screening in result.withheld],
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


async def _send_json(send: Send, status: int, body: dict[str, Any], headers=()) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), *headers],
        }
    )
    await send({"type": "http.response.body", "body": json.dumps(body).encode()})


class RateLimitGate:
    """A per-client request budget for the mounted MCP app.

    The API's rate limiting cannot see it: slowapi's middleware matches each
    request to a route endpoint, finds none for a mounted ASGI app, and treats
    the request as exempt. This applies the same kind of limit, keyed the same
    way, before the token is even checked — so guessing tokens is rate limited
    as well.
    """

    def __init__(self, app: ASGIApp, limit: str, *, storage_uri: str = RATE_LIMIT_STORAGE_URI) -> None:
        self.app = app
        self.limit = parse(limit)
        self._limiter = FixedWindowRateLimiter(storage_from_string(storage_uri))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and RATE_LIMIT_ENABLED:
            client = client_identifier(Request(scope))
            if not self._limiter.hit(self.limit, "mcp", client):
                reset = self._limiter.get_window_stats(self.limit, "mcp", client).reset_time
                await _send_json(
                    send,
                    429,
                    {"detail": f"Rate limit exceeded: {self.limit}"},
                    headers=[(b"retry-after", str(max(1, int(reset - time.time()))).encode())],
                )
                return
        await self.app(scope, receive, send)


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
                await _send_json(
                    send,
                    401,
                    {"detail": "A valid bearer token is required."},
                    headers=[(b"www-authenticate", b"Bearer")],
                )
                return
        await self.app(scope, receive, send)


def mount_http(
    app: Any,
    token: str,
    *,
    path: str = "/mcp",
    rate_limit: str = RATE_LIMIT_MCP,
    llm_client_factory: Callable[[], Any] = create_llm_client,
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
    app.mount(path, RateLimitGate(BearerTokenGate(mcp.streamable_http_app(), token), rate_limit))
    return mcp.session_manager
