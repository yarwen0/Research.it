"""Per-call accounting for LLM requests.

Every provider client wraps its HTTP request in :func:`track_llm_call`, which
makes it the one place tokens, latency, throughput and cost are measured. A
call is counted the same way whichever provider served it and whichever module
made it — there is no second path that could forget to.

Attribution is ambient rather than passed through arguments, because the calls
happen several layers below anything that knows which job or stage they belong
to. :func:`llm_stage` names the pipeline step and :func:`collect_usage` gathers
the calls made during a unit of work. Both are context variables, and context
only reaches a worker thread when it is copied there — which is why blocking
work goes through ``asyncio.to_thread`` rather than ``run_in_executor``.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind

from logging_config import get_logger
from telemetry.pricing import estimate_cost

logger = get_logger(__name__)
_tracer = trace.get_tracer(__name__)

# Characters per token for English prose under the tokenizers in use. Applied
# only when a provider reports no usage, and every call it touches is flagged,
# so an estimate is never mistaken for a measurement.
CHARS_PER_TOKEN = 4

# Long provider error bodies are useful in a log line and noise in a table.
_MAX_ERROR_CHARS = 500


@dataclass
class LLMCall:
    """One request to a model: a chat completion or a batch of embeddings."""

    provider: str
    model: str
    operation: str  # "chat" | "embeddings"
    stage: str | None = None

    input_tokens: int | None = None
    output_tokens: int | None = None
    usage_estimated: bool = False

    latency_ms: float = 0.0
    # Time the model itself spent generating, when the provider reports it
    # (Ollama's eval_duration). Excludes the network, queueing and prompt
    # processing that latency_ms includes.
    generation_ms: float | None = None

    cost_usd: float | None = None
    status: str = "ok"
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # What was sent and received, for estimating usage a provider does not
    # report. Not persisted.
    prompt_chars: int = 0
    response_chars: int = 0

    @property
    def tokens_per_second(self) -> float | None:
        """Output tokens per second.

        Measured over the model's own generation time where the provider
        reports it — decode throughput — and over end-to-end latency
        otherwise. The second also counts the network and prompt processing,
        so it reads lower for the same model; the rollups keep the two apart.
        """
        if not self.output_tokens:
            return None
        elapsed_ms = self.generation_ms if self.generation_ms else self.latency_ms
        if elapsed_ms <= 0:
            return None
        return self.output_tokens / (elapsed_ms / 1000)

    def as_record(self) -> dict[str, Any]:
        """The fields worth keeping once the call is over."""
        return {
            "provider": self.provider,
            "model": self.model,
            "operation": self.operation,
            "stage": self.stage,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usage_estimated": self.usage_estimated,
            "latency_ms": self.latency_ms,
            "generation_ms": self.generation_ms,
            "cost_usd": self.cost_usd,
            "status": self.status,
            "error": self.error,
            "created_at": self.started_at,
        }


class UsageCollector:
    """The calls made within one unit of work — a research job, a question.

    Calls arrive from worker threads while the event loop reads, hence the
    lock.
    """

    def __init__(self) -> None:
        self._calls: list[LLMCall] = []
        self._drained = 0
        self._lock = threading.Lock()

    def add(self, call: LLMCall) -> None:
        with self._lock:
            self._calls.append(call)

    @property
    def calls(self) -> list[LLMCall]:
        with self._lock:
            return list(self._calls)

    def drain(self) -> list[LLMCall]:
        """Calls recorded since the previous drain.

        Lets a long job persist its calls as it goes rather than all at the
        end, so a crash mid-run still leaves the calls it paid for on record.
        """
        with self._lock:
            fresh = self._calls[self._drained :]
            self._drained = len(self._calls)
            return fresh


_stage: ContextVar[str | None] = ContextVar("llm_stage", default=None)
_collector: ContextVar[UsageCollector | None] = ContextVar(
    "llm_usage_collector", default=None
)


def current_stage() -> str | None:
    return _stage.get()


@contextmanager
def collect_usage(collector: UsageCollector | None = None) -> Iterator[UsageCollector]:
    """Attribute every LLM call made inside the block to one collector."""
    active = collector if collector is not None else UsageCollector()
    token = _collector.set(active)
    try:
        yield active
    finally:
        _collector.reset(token)


@contextmanager
def llm_stage(name: str) -> Iterator[None]:
    """Label the LLM calls made inside the block with a pipeline stage.

    Works as a decorator as well. Opens a span too, so a trace groups each
    stage's calls beneath it. Innermost wins when stages nest.
    """
    token = _stage.set(name)
    try:
        with _tracer.start_as_current_span(name, attributes={"researchit.stage": name}):
            yield
    finally:
        _stage.reset(token)


def estimate_tokens(chars: int) -> int:
    return math.ceil(chars / CHARS_PER_TOKEN)


@contextmanager
def track_llm_call(
    provider: str, model: str, operation: str, *, prompt_chars: int = 0
) -> Iterator[LLMCall]:
    """Measure one model request.

    The caller fills in whatever the provider reported — token counts,
    generation time, the size of the response. Everything derivable from
    those (latency, estimates, cost, throughput) is computed here on the way
    out, on success and on failure alike: a failed call still took time and
    is still worth seeing.
    """
    call = LLMCall(
        provider=provider,
        model=model,
        operation=operation,
        stage=_stage.get(),
        prompt_chars=prompt_chars,
    )
    started = time.perf_counter()

    # Span name and attributes follow the OpenTelemetry GenAI conventions.
    with _tracer.start_as_current_span(
        f"{operation} {model}", kind=SpanKind.CLIENT
    ) as span:
        try:
            yield call
        except BaseException as exc:
            call.status = "error"
            call.error = f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_CHARS]
            raise
        finally:
            call.latency_ms = (time.perf_counter() - started) * 1000
            _finalize(call)
            _annotate(span, call)
            _publish(call)


def _finalize(call: LLMCall) -> None:
    """Fill in estimates and cost from what the provider reported."""
    if call.status == "ok":
        if call.input_tokens is None and call.prompt_chars:
            call.input_tokens = estimate_tokens(call.prompt_chars)
            call.usage_estimated = True
        if (
            call.operation == "chat"
            and call.output_tokens is None
            and call.response_chars
        ):
            call.output_tokens = estimate_tokens(call.response_chars)
            call.usage_estimated = True

    # A failed call is costed on whatever usage the provider reported, which
    # is usually none: a rejected or timed-out request is not billed.
    call.cost_usd = estimate_cost(
        call.provider, call.model, call.input_tokens, call.output_tokens
    )


def _annotate(span: Span, call: LLMCall) -> None:
    span.set_attribute("gen_ai.operation.name", call.operation)
    span.set_attribute("gen_ai.provider.name", call.provider)
    # Superseded by gen_ai.provider.name, but still what many backends key on.
    span.set_attribute("gen_ai.system", call.provider)
    span.set_attribute("gen_ai.request.model", call.model)
    if call.input_tokens is not None:
        span.set_attribute("gen_ai.usage.input_tokens", call.input_tokens)
    if call.output_tokens is not None:
        span.set_attribute("gen_ai.usage.output_tokens", call.output_tokens)

    span.set_attribute("researchit.usage_estimated", call.usage_estimated)
    if call.stage:
        span.set_attribute("researchit.stage", call.stage)
    if call.cost_usd is not None:
        span.set_attribute("researchit.cost_usd", call.cost_usd)
    tokens_per_second = call.tokens_per_second
    if tokens_per_second is not None:
        span.set_attribute("researchit.output_tokens_per_second", tokens_per_second)
    if call.error:
        span.set_attribute("error.type", call.error.split(":", 1)[0])


def _publish(call: LLMCall) -> None:
    collector = _collector.get()
    if collector is not None:
        collector.add(call)

    tokens_per_second = call.tokens_per_second
    logger.info(
        "llm_call",
        provider=call.provider,
        model=call.model,
        operation=call.operation,
        stage=call.stage,
        status=call.status,
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
        usage_estimated=call.usage_estimated,
        latency_ms=round(call.latency_ms, 1),
        tokens_per_second=(
            round(tokens_per_second, 1) if tokens_per_second is not None else None
        ),
        cost_usd=call.cost_usd,
    )
