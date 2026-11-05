"""Span export.

Spans are created unconditionally — OpenTelemetry's API is a no-op until a
provider is installed — so turning export on is configuration, not code:

    OTEL_TRACES_EXPORTER=none     the default; spans are discarded
    OTEL_TRACES_EXPORTER=console  finished spans printed to stdout
    OTEL_TRACES_EXPORTER=otlp     OTLP over HTTP, configured by the standard
                                  OTEL_EXPORTER_OTLP_* variables (Jaeger,
                                  Tempo, an OpenTelemetry Collector, ...)
"""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)

from config import OTEL_SERVICE_NAME, OTEL_TRACES_EXPORTER

logger = logging.getLogger(__name__)

EXPORTERS = ("none", "console", "otlp")

_provider: TracerProvider | None = None


def _build_exporter(name: str) -> SpanExporter | None:
    if name == "console":
        return ConsoleSpanExporter()
    if name == "otlp":
        # Imported here so the protobuf stack loads only when it is used.
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        return OTLPSpanExporter()
    return None


def build_tracer_provider(
    exporter_name: str, *, service_name: str = OTEL_SERVICE_NAME
) -> TracerProvider | None:
    """A provider exporting to `exporter_name`, or None when export is off."""
    if exporter_name == "none":
        return None

    exporter = _build_exporter(exporter_name)
    if exporter is None:
        logger.warning(
            "Unknown OTEL_TRACES_EXPORTER %r (expected one of %s); tracing stays off",
            exporter_name,
            ", ".join(EXPORTERS),
        )
        return None

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    # Console output is for reading along locally, so print each span as it
    # ends. Anything going over the network is batched.
    processor = (
        SimpleSpanProcessor(exporter)
        if exporter_name == "console"
        else BatchSpanProcessor(exporter)
    )
    provider.add_span_processor(processor)
    return provider


def configure_tracing() -> None:
    """Install the configured provider globally. Called once, at startup."""
    global _provider
    _provider = build_tracer_provider(OTEL_TRACES_EXPORTER)
    if _provider is not None:
        trace.set_tracer_provider(_provider)
        logger.info("Exporting traces via %s", OTEL_TRACES_EXPORTER)


def shutdown_tracing() -> None:
    """Flush spans still buffered for export. Called once, at shutdown."""
    if _provider is not None:
        _provider.shutdown()
