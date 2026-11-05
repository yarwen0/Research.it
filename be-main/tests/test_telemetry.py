"""Tests for LLM telemetry: pricing, per-call tracking, attribution, rollups.

No network and no model. Calls are simulated by entering `track_llm_call`
exactly as the provider clients do; `test_llm_clients.py` covers the clients
themselves.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind, StatusCode

from services.research_pipeline import ResearchPipeline
from telemetry import (
    LLMCall,
    UsageCollector,
    collect_usage,
    current_stage,
    llm_stage,
    pricing,
    rollup,
    track_llm_call,
)
from telemetry.tracing import build_tracer_provider


def _simulated_call(input_tokens: int = 100, output_tokens: int = 10) -> None:
    with track_llm_call("ollama", "qwen2.5:7b", "chat") as call:
        call.input_tokens = input_tokens
        call.output_tokens = output_tokens


class TestEstimateCost:
    def test_prices_a_listed_model(self):
        # A million tokens each way at $0.10 in and $0.40 out.
        cost = pricing.estimate_cost(
            "gemini", "gemini-2.5-flash-lite", 1_000_000, 1_000_000
        )
        assert cost == pytest.approx(0.50)

    def test_local_inference_is_free(self):
        assert pricing.estimate_cost("ollama", "qwen2.5:7b", 50_000, 5_000) == 0.0

    def test_openrouter_free_variants_are_free(self):
        assert pricing.estimate_cost("openrouter", "z-ai/glm-4.5-air:free", 10, 10) == 0.0

    def test_an_unknown_model_is_unpriced_rather_than_free(self):
        assert pricing.estimate_cost("gemini", "gemini-9-ultra", 10, 10) is None

    def test_missing_usage_costs_nothing(self):
        assert pricing.estimate_cost("gemini", "gemini-2.5-flash", None, None) == 0.0

    def test_path_prefix_and_case_are_ignored(self):
        assert pricing.price_for("models/Gemini-Embedding-001") == pricing.Price(0.15)

    def test_a_dated_version_suffix_falls_back_to_the_base_model(self):
        assert pricing.price_for("gemini-2.5-flash-lite-001") == pricing.price_for(
            "gemini-2.5-flash-lite"
        )

    def test_digits_that_are_part_of_the_name_match_exactly(self):
        # "-001" here is the model's name, not a version to strip.
        assert pricing.price_for("gemini-embedding-001") is not None


class TestPriceOverrides:
    def test_parses_input_and_output_prices(self):
        parsed = pricing._parse_overrides('{"my-model": {"input": 1.5, "output": 6}}')
        assert parsed == {"my-model": pricing.Price(1.5, 6.0)}

    def test_output_price_defaults_to_zero(self):
        parsed = pricing._parse_overrides('{"embedder": {"input": 0.02}}')
        assert parsed == {"embedder": pricing.Price(0.02, 0.0)}

    def test_keys_are_normalized_like_lookups(self):
        parsed = pricing._parse_overrides('{"models/My-Model": {"input": 1}}')
        assert "my-model" in parsed

    def test_invalid_json_is_ignored_with_a_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            assert pricing._parse_overrides("{not json") == {}
        assert "LLM_PRICES" in caplog.text

    def test_a_non_object_is_ignored(self):
        assert pricing._parse_overrides("[1, 2]") == {}

    def test_one_malformed_entry_does_not_cost_the_rest(self):
        parsed = pricing._parse_overrides(
            '{"good": {"input": 1}, "bad": {"output": 2}, "worse": "free"}'
        )
        assert set(parsed) == {"good"}


class TestTrackLLMCall:
    def test_reported_usage_is_not_marked_estimated(self):
        with (
            collect_usage() as usage,
            track_llm_call("ollama", "qwen2.5:7b", "chat", prompt_chars=400) as call,
        ):
            call.input_tokens = 120
            call.output_tokens = 30

        [recorded] = usage.calls
        assert (recorded.input_tokens, recorded.output_tokens) == (120, 30)
        assert not recorded.usage_estimated
        assert recorded.status == "ok"
        assert recorded.latency_ms >= 0

    def test_missing_usage_is_estimated_from_text_length(self):
        with (
            collect_usage() as usage,
            track_llm_call("gemini", "gemini-2.5-flash-lite", "chat", prompt_chars=400) as call,
        ):
            call.response_chars = 80

        [recorded] = usage.calls
        assert (recorded.input_tokens, recorded.output_tokens) == (100, 20)
        assert recorded.usage_estimated

    def test_embeddings_estimate_input_only(self):
        with (
            collect_usage() as usage,
            track_llm_call("gemini", "gemini-embedding-001", "embeddings", prompt_chars=4000),
        ):
            pass

        [recorded] = usage.calls
        assert recorded.input_tokens == 1000
        assert recorded.output_tokens is None

    def test_cost_comes_from_the_price_table(self):
        with (
            collect_usage() as usage,
            track_llm_call("gemini", "gemini-2.5-flash-lite", "chat") as call,
        ):
            call.input_tokens = 10_000
            call.output_tokens = 1_000

        [recorded] = usage.calls
        assert recorded.cost_usd == pytest.approx((10_000 * 0.10 + 1_000 * 0.40) / 1e6)

    def test_a_failed_call_is_recorded_and_still_raises(self):
        with (
            collect_usage() as usage,
            pytest.raises(RuntimeError, match="HTTP 503"),
            track_llm_call("gemini", "gemini-2.5-flash", "chat", prompt_chars=400),
        ):
            raise RuntimeError("Gemini HTTP 503: model overloaded")

        [recorded] = usage.calls
        assert recorded.status == "error"
        assert recorded.error == "RuntimeError: Gemini HTTP 503: model overloaded"
        # Nothing reported, nothing estimated: a rejected request is not billed.
        assert recorded.input_tokens is None
        assert recorded.cost_usd == 0.0

    def test_long_provider_errors_are_truncated(self):
        with (
            collect_usage() as usage,
            pytest.raises(RuntimeError),
            track_llm_call("ollama", "qwen2.5:7b", "chat"),
        ):
            raise RuntimeError("x" * 5000)

        assert len(usage.calls[0].error) == 500

    def test_tracking_without_a_collector_is_harmless(self):
        _simulated_call()


class TestTokensPerSecond:
    def test_prefers_the_models_own_generation_time(self):
        call = LLMCall("ollama", "m", "chat", output_tokens=100, latency_ms=10_000, generation_ms=2_000)
        assert call.tokens_per_second == pytest.approx(50.0)

    def test_falls_back_to_end_to_end_latency(self):
        call = LLMCall("gemini", "m", "chat", output_tokens=100, latency_ms=4_000)
        assert call.tokens_per_second == pytest.approx(25.0)

    def test_undefined_without_output(self):
        assert LLMCall("ollama", "m", "embeddings", latency_ms=50).tokens_per_second is None


class TestStageAttribution:
    def test_calls_carry_the_enclosing_stage(self):
        with collect_usage() as usage, llm_stage("extraction"):
            _simulated_call()
        assert usage.calls[0].stage == "extraction"

    def test_the_innermost_stage_wins(self):
        with collect_usage() as usage, llm_stage("search"), llm_stage("rerank"):
            _simulated_call()
        assert usage.calls[0].stage == "rerank"

    def test_the_stage_is_restored_on_exit(self):
        with llm_stage("outer"):
            with llm_stage("inner"):
                pass
            assert current_stage() == "outer"
        assert current_stage() is None

    def test_works_as_a_decorator(self):
        @llm_stage("normalization")
        def normalize():
            _simulated_call()

        with collect_usage() as usage:
            normalize()
            normalize()
        assert [c.stage for c in usage.calls] == ["normalization", "normalization"]

    def test_calls_outside_any_stage_are_unattributed(self):
        with collect_usage() as usage:
            _simulated_call()
        assert usage.calls[0].stage is None


@pytest.mark.asyncio
class TestThreadPropagation:
    """Attribution has to survive the hop onto a worker thread.

    The pipeline makes nearly every LLM call from a worker thread. If the
    context does not follow, the calls happen and are never counted.
    """

    async def test_to_thread_carries_the_collector_and_stage(self):
        def work():
            with llm_stage("extraction"):
                _simulated_call()

        with collect_usage() as usage:
            await asyncio.to_thread(work)
        assert [c.stage for c in usage.calls] == ["extraction"]

    async def test_run_in_executor_loses_them(self):
        """Why the pipeline no longer uses run_in_executor."""
        with collect_usage() as usage:
            await asyncio.get_running_loop().run_in_executor(None, _simulated_call)
        assert usage.calls == []

    async def test_pipeline_blocking_work_is_attributed(self):
        pipeline = ResearchPipeline(user_prompt="diffusion models")
        with collect_usage() as usage:
            await pipeline._run_blocking(_simulated_call)
        assert len(usage.calls) == 1


class TestUsageCollector:
    def test_drain_returns_only_calls_since_the_last_drain(self):
        with collect_usage() as usage:
            _simulated_call()
            first = usage.drain()
            _simulated_call()
            _simulated_call()
            second = usage.drain()
        assert (len(first), len(second), len(usage.drain())) == (1, 2, 0)
        assert len(usage.calls) == 3

    def test_an_explicit_collector_can_be_reused(self):
        shared = UsageCollector()
        with collect_usage(shared):
            _simulated_call()
        with collect_usage(shared):
            _simulated_call()
        assert len(shared.calls) == 2


def _record(**overrides):
    record = {
        "stage": "extraction",
        "provider": "ollama",
        "model": "qwen2.5:7b",
        "operation": "chat",
        "input_tokens": 100,
        "output_tokens": 10,
        "usage_estimated": False,
        "latency_ms": 1000.0,
        "generation_ms": None,
        "cost_usd": 0.0,
        "status": "ok",
    }
    record.update(overrides)
    return record


class TestPercentile:
    def test_interpolates_between_ranks(self):
        assert rollup.percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)
        assert rollup.percentile(list(range(1, 11)), 95) == pytest.approx(9.55)

    def test_order_does_not_matter(self):
        assert rollup.percentile([4, 1, 3, 2], 50) == pytest.approx(2.5)

    def test_single_value(self):
        assert rollup.percentile([7.0], 95) == 7.0

    def test_empty(self):
        assert rollup.percentile([], 50) is None


class TestSummarize:
    def test_totals(self):
        summary = rollup.summarize(
            [
                _record(input_tokens=100, output_tokens=10),
                _record(input_tokens=300, output_tokens=30, usage_estimated=True),
            ]
        )
        assert summary["calls"] == 2
        assert (summary["input_tokens"], summary["output_tokens"]) == (400, 40)
        assert summary["estimated_calls"] == 1
        assert summary["errors"] == 0

    def test_unpriced_calls_are_counted_not_summed(self):
        summary = rollup.summarize(
            [_record(cost_usd=0.002), _record(cost_usd=None), _record(cost_usd=0.001)]
        )
        assert summary["cost_usd"] == pytest.approx(0.003)
        assert summary["unpriced_calls"] == 1

    def test_errors_count_toward_latency_but_not_throughput(self):
        summary = rollup.summarize(
            [
                _record(latency_ms=2000, output_tokens=100),
                _record(latency_ms=8000, output_tokens=None, status="error"),
            ]
        )
        assert summary["errors"] == 1
        assert summary["latency_ms_total"] == 10_000
        assert summary["output_tokens_per_second"] == pytest.approx(50.0)

    def test_decode_and_end_to_end_throughput_are_kept_apart(self):
        summary = rollup.summarize(
            [
                _record(latency_ms=4000, generation_ms=1000, output_tokens=100),
                _record(latency_ms=4000, generation_ms=None, output_tokens=100),
            ]
        )
        # Over decode time, only the call that reported one.
        assert summary["decode_tokens_per_second"] == pytest.approx(100.0)
        # End to end, both calls.
        assert summary["output_tokens_per_second"] == pytest.approx(25.0)

    def test_embeddings_do_not_count_as_throughput(self):
        summary = rollup.summarize([_record(operation="embeddings", output_tokens=None)])
        assert summary["output_tokens_per_second"] is None
        assert summary["decode_tokens_per_second"] is None

    def test_empty(self):
        summary = rollup.summarize([])
        assert summary["calls"] == 0
        assert summary["latency_ms_p95"] is None


class TestBreakdowns:
    def test_by_stage_puts_the_slowest_first(self):
        rows = rollup.by_stage(
            [
                _record(stage="normalization", latency_ms=500),
                _record(stage="reference_extraction", latency_ms=90_000),
                _record(stage=None, latency_ms=10),
            ]
        )
        assert [row["stage"] for row in rows] == [
            "reference_extraction",
            "normalization",
            rollup.UNATTRIBUTED,
        ]

    def test_by_model_separates_operations(self):
        rows = rollup.by_model(
            [
                _record(),
                _record(),
                _record(model="nomic-embed-text", operation="embeddings"),
            ]
        )
        assert [(r["model"], r["operation"], r["calls"]) for r in rows] == [
            ("qwen2.5:7b", "chat", 2),
            ("nomic-embed-text", "embeddings", 1),
        ]


class TestSpans:
    def test_llm_spans_follow_the_genai_conventions(self, spans):
        with (
            llm_stage("extraction"),
            track_llm_call("ollama", "qwen2.5:7b", "chat") as call,
        ):
            call.input_tokens = 812
            call.output_tokens = 64
            call.generation_ms = 1600

        finished = {span.name: span for span in spans.get_finished_spans()}
        llm = finished["chat qwen2.5:7b"]
        assert llm.kind == SpanKind.CLIENT
        assert llm.attributes["gen_ai.operation.name"] == "chat"
        assert llm.attributes["gen_ai.provider.name"] == "ollama"
        assert llm.attributes["gen_ai.request.model"] == "qwen2.5:7b"
        assert llm.attributes["gen_ai.usage.input_tokens"] == 812
        assert llm.attributes["gen_ai.usage.output_tokens"] == 64
        assert llm.attributes["researchit.stage"] == "extraction"
        assert llm.attributes["researchit.output_tokens_per_second"] == pytest.approx(40.0)

    def test_the_stage_span_is_the_parent(self, spans):
        with llm_stage("normalization"):
            _simulated_call()

        finished = {span.name: span for span in spans.get_finished_spans()}
        stage_span = finished["normalization"]
        assert finished["chat qwen2.5:7b"].parent.span_id == stage_span.context.span_id

    def test_a_failed_call_marks_its_span(self, spans):
        with pytest.raises(ValueError), track_llm_call("ollama", "qwen2.5:7b", "chat"):
            raise ValueError("Empty content in Ollama response")

        [span] = spans.get_finished_spans()
        assert span.status.status_code == StatusCode.ERROR
        assert span.attributes["error.type"] == "ValueError"


class TestTracerProvider:
    def test_none_leaves_export_off(self):
        assert build_tracer_provider("none") is None

    def test_console(self):
        assert isinstance(build_tracer_provider("console"), TracerProvider)

    def test_otlp(self):
        # Constructing the exporter opens no connection; export is lazy.
        assert isinstance(build_tracer_provider("otlp"), TracerProvider)

    def test_service_name_is_set_on_the_resource(self):
        provider = build_tracer_provider("console", service_name="researchit-test")
        assert provider.resource.attributes["service.name"] == "researchit-test"

    def test_an_unknown_exporter_is_refused_with_a_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            assert build_tracer_provider("zipkin") is None
        assert "zipkin" in caplog.text
