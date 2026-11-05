"""Response models.

Declaring these does two things beyond documentation: FastAPI validates what
goes out, and the OpenAPI schema becomes complete enough to generate the
frontend's types from. Without them the spec describes only request bodies,
and every response is `any` on the other side.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

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


class UsageSummary(BaseModel):
    """LLM usage over a set of calls."""

    calls: int
    errors: int
    input_tokens: int
    output_tokens: int
    estimated_calls: int = Field(
        description=(
            "Calls whose token counts were estimated from text length because "
            "the provider reported none."
        )
    )
    cost_usd: float = Field(
        description="Estimated cost of the priced calls, in USD, at list prices."
    )
    unpriced_calls: int = Field(
        description="Calls to models missing from the price table; not in cost_usd."
    )
    latency_ms_total: float
    latency_ms_p50: float | None = None
    latency_ms_p95: float | None = None
    output_tokens_per_second: float | None = Field(
        default=None,
        description="End to end: output tokens over request latency, chat calls only.",
    )
    decode_tokens_per_second: float | None = Field(
        default=None,
        description=(
            "Output tokens over the model's own generation time, for providers "
            "that report it (Ollama)."
        ),
    )


class StageUsage(UsageSummary):
    """Usage for one pipeline stage, e.g. extraction or reference_extraction."""

    stage: str


class ModelUsage(UsageSummary):
    """Usage for one model and operation."""

    provider: str
    model: str
    operation: Literal["chat", "embeddings"]


class JobMetricsResponse(BaseModel):
    """What a research job's LLM calls cost, overall and broken down."""

    job_id: str
    status: Literal["pending", "running", "completed", "failed"]
    prices_checked: str = Field(
        description="Date the price table behind cost_usd was last checked."
    )
    totals: UsageSummary
    by_stage: list[StageUsage] = Field(default_factory=list)
    by_model: list[ModelUsage] = Field(default_factory=list)


class SearchHit(BaseModel):
    """A retrieved passage and where it came from."""

    chunk_id: int
    paper_id: str = Field(description="The paper's external id, e.g. its arXiv id.")
    paper_title: str
    section: str | None = None
    kind: Literal["text", "profile"] = Field(
        description="A slice of the paper's text, or its structured record rendered as prose."
    )
    text: str
    score: float = Field(
        description="Fused RRF score in hybrid mode; cosine similarity or BM25 otherwise."
    )
    dense_rank: int | None = Field(default=None, description="1-based rank in the dense list.")
    lexical_rank: int | None = Field(default=None, description="1-based rank in the BM25 list.")
    flagged: bool = Field(
        default=False,
        description="Reads as instructions to a model; withheld whenever passages go to an LLM.",
    )
    flag_reasons: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    project_id: str
    query: str
    strategy: Literal["hybrid", "dense", "lexical"]
    embedding_model: str
    hits: list[SearchHit] = Field(default_factory=list)


class IndexStatusResponse(BaseModel):
    """Whether a project can be searched with the configured embedding model."""

    project_id: str
    embedding_model: str = Field(description="The embedding model this server is configured with.")
    indexed_chunks: int = Field(description="Passages indexed with that model.")
    ready: bool
    models: dict[str, int] = Field(
        default_factory=dict, description="Passages per embedding model the project was indexed with."
    )


class AskRequest(BaseModel):
    """A question about a project's papers."""

    question: str = Field(min_length=1, max_length=1000)
    k: int = Field(default=8, ge=1, le=20, description="Passages to answer from.")

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("question must not be empty")
        return stripped


class AnswerSource(SearchHit):
    """A passage the answer was allowed to cite."""

    id: str = Field(description="The id the answer cites it by, e.g. S1.")
    cited: bool


class WithheldSource(BaseModel):
    """A retrieved passage kept out of the prompt because it reads as instructions."""

    paper_id: str
    paper_title: str
    section: str | None = None
    reasons: list[str] = Field(default_factory=list)


class AskResponse(BaseModel):
    """A grounded answer and the evidence behind it."""

    project_id: str
    question: str
    answer: str = Field(description="Cites sources inline as [S1], [S2].")
    insufficient_evidence: bool = Field(
        description="The model found no answer in the sources and said so."
    )
    grounded: bool = Field(
        description="Declined, or cited at least one real source. False means do not trust it."
    )
    sources: list[AnswerSource] = Field(default_factory=list)
    cited: list[str] = Field(default_factory=list)
    dropped_citations: list[str] = Field(
        default_factory=list,
        description="Citations of sources the model was never given, removed from the answer.",
    )
    withheld: list[WithheldSource] = Field(
        default_factory=list,
        description="Retrieved passages withheld from the model as possible prompt injection.",
    )
    strategy: str
    embedding_model: str
    usage: UsageSummary
    latency_ms: float


class AssistantRequest(BaseModel):
    """A message to the research assistant."""

    message: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = Field(
        default=None, description="Continue this conversation; omit to start a new one."
    )

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("message must not be empty")
        return stripped


class ThreadSummary(BaseModel):
    thread_id: str
    title: str
    messages: int
    created_at: str
    updated_at: str


class ThreadListResponse(BaseModel):
    threads: list[ThreadSummary] = Field(default_factory=list)


class ThreadMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    payload: dict[str, Any] | None = Field(
        default=None,
        description="For an answer: its citations, the plan, the findings and the critique.",
    )
    job_id: str | None = Field(
        default=None, description="The job whose events and LLM usage recorded this turn."
    )
    created_at: str


class ThreadResponse(BaseModel):
    thread_id: str
    project_id: str
    title: str
    messages: list[ThreadMessage] = Field(default_factory=list)


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
