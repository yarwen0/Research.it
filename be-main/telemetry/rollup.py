"""Summaries over a set of LLM calls: totals, per stage, per model.

Pure functions over plain records, so the same rollup serves a persisted job
and an in-memory request alike, and tests need no database.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

# Calls made outside any `llm_stage` block.
UNATTRIBUTED = "unattributed"


def percentile(values: list[float], q: float) -> float | None:
    """The q-th percentile, interpolating between closest ranks.

    The same definition as numpy's default, written out so telemetry does not
    pull numpy into every import.
    """
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * q / 100
    low, high = math.floor(rank), math.ceil(rank)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def summarize(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate calls into the shape the metrics endpoint returns.

    Throughput is reported twice because it means two different things.
    ``decode_tokens_per_second`` covers only calls whose provider reported its
    own generation time — the model's speed. ``output_tokens_per_second`` is
    end to end, over every successful chat call — the speed a caller sees.
    """
    calls = list(records)
    ok = [c for c in calls if c["status"] == "ok"]
    chat = [c for c in ok if c["operation"] == "chat" and c["output_tokens"]]
    decoded = [c for c in chat if c["generation_ms"]]
    priced = [c for c in calls if c["cost_usd"] is not None]
    latencies = [c["latency_ms"] for c in calls]

    chat_seconds = sum(c["latency_ms"] for c in chat) / 1000
    decode_seconds = sum(c["generation_ms"] for c in decoded) / 1000

    return {
        "calls": len(calls),
        "errors": len(calls) - len(ok),
        "input_tokens": sum(c["input_tokens"] or 0 for c in calls),
        "output_tokens": sum(c["output_tokens"] or 0 for c in calls),
        "estimated_calls": sum(1 for c in calls if c["usage_estimated"]),
        "cost_usd": round(sum(c["cost_usd"] for c in priced), 6),
        "unpriced_calls": len(calls) - len(priced),
        "latency_ms_total": round(sum(latencies), 1),
        "latency_ms_p50": _round(percentile(latencies, 50), 1),
        "latency_ms_p95": _round(percentile(latencies, 95), 1),
        "output_tokens_per_second": _round(
            sum(c["output_tokens"] for c in chat) / chat_seconds
            if chat_seconds
            else None,
            1,
        ),
        "decode_tokens_per_second": _round(
            sum(c["output_tokens"] for c in decoded) / decode_seconds
            if decode_seconds
            else None,
            1,
        ),
    }


def by_stage(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One summary per stage, most expensive in wall time first."""
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        groups.setdefault(record["stage"] or UNATTRIBUTED, []).append(record)

    rows = [{"stage": stage, **summarize(calls)} for stage, calls in groups.items()]
    return sorted(rows, key=lambda row: (-row["latency_ms_total"], row["stage"]))


def by_model(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One summary per provider, model and operation, busiest first."""
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for record in records:
        key = (record["provider"], record["model"], record["operation"])
        groups.setdefault(key, []).append(record)

    rows = [
        {"provider": provider, "model": model, "operation": operation, **summarize(calls)}
        for (provider, model, operation), calls in groups.items()
    ]
    return sorted(rows, key=lambda row: (-row["calls"], row["model"]))
