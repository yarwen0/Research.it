"""Response models.

Declaring these does two things beyond documentation: FastAPI validates what
goes out, and the OpenAPI schema becomes complete enough to generate the
frontend's types from. Without them the spec describes only request bodies,
and every response is `any` on the other side.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from services.events import StatusType


class HealthResponse(BaseModel):
    """Liveness check."""

    status: str = Field(examples=["ok"])
    message: str
    version: str


class DetailedHealthResponse(BaseModel):
    """Health check with the endpoint map."""

    status: str = Field(examples=["healthy"])
    service: str
    endpoints: dict[str, str]


class SSEUpdate(BaseModel):
    """One frame of a progress stream.

    Never a return type — the SSE endpoints stream these as `data:` lines —
    but carried in the schema so the frontend can type what it parses.
    """

    status: StatusType
    message: str
    result: dict[str, Any] | None = None

    def to_sse(self) -> str:
        """Serialize to the SSE wire format."""
        return f"data: {self.model_dump_json()}\n\n"


class JobResponse(BaseModel):
    """A research job's current state."""

    job_id: str
    status: Literal["pending", "running", "completed", "failed"]
    project_id: str | None = None
    user_prompt: str
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class GraphNodeData(BaseModel):
    """A paper or author node, in the shape the graph renderer consumes."""

    id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    published: str = ""
    is_processed: bool = False
    refs_to: list[str] = Field(default_factory=list)
    refs_from: list[str] = Field(default_factory=list)
    node_type: Literal["paper", "author"] = "paper"
    label: str = ""


class GraphNode(BaseModel):
    data: GraphNodeData


class GraphEdgeData(BaseModel):
    id: str
    source: str
    target: str
    edge_type: Literal["citation", "authorship"] = "citation"


class GraphEdge(BaseModel):
    data: GraphEdgeData


class GraphData(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class GraphResponse(BaseModel):
    """A project's citation and authorship graph."""

    status: str = Field(examples=["success"])
    project_id: str
    graph_data: GraphData


class ReviewResponse(BaseModel):
    """A generated literature review."""

    review_id: str
    latex_content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewSummary(BaseModel):
    """One entry in the review list."""

    review_id: str
    topic: str = ""
    keywords: list[str] = Field(default_factory=list)
    timestamp: str = ""
    num_papers: int = 0


class ReviewListResponse(BaseModel):
    reviews: list[ReviewSummary] = Field(default_factory=list)
    total: int
