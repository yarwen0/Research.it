"""Scoring grounded answers: facts, citations, refusals, latency.

Pure functions over recorded answers, so the scoring is testable without a
model; `run.py` produces the answers with one.

An answer to an answerable question is *correct* when it states the expected
fact (any of the listed spellings, or every one of them for `expect_all`),
and *supported* when a passage it cites contains that question's evidence. An
unanswerable question is handled correctly when the answer declines.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from telemetry.rollup import percentile

EVAL_DIR = Path(__file__).resolve().parent
QUESTIONS_PATH = EVAL_DIR / "questions.json"
RESULTS_PATH = EVAL_DIR / "results.json"


def _fold(text: str) -> str:
    return " ".join(text.lower().split())


def states_fact(answer: str, question: dict[str, Any]) -> bool:
    folded = _fold(answer)
    if "expect_all" in question:
        return all(_fold(fact) in folded for fact in question["expect_all"])
    return any(_fold(fact) in folded for fact in question.get("expect_any", []))


def cites_evidence(cited_texts: Sequence[str], question: dict[str, Any]) -> bool:
    """Whether any cited passage contains one of the question's evidence phrases."""
    phrases = [_fold(item["text"]) for item in question.get("evidence", [])]
    return any(phrase in _fold(text) for text in cited_texts for phrase in phrases)


def score(question: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    """One question's verdicts, from what the pipeline returned."""
    declined = bool(answer["insufficient_evidence"])
    verdict: dict[str, Any] = {
        "id": question["id"],
        "answerable": question["answerable"],
        "declined": declined,
        "grounded": answer["grounded"],
        "dropped_citations": len(answer["dropped_citations"]),
        # How widely it cited. "Supported" is trivially true for an answer
        # that cites every passage it was given, so the breadth is reported
        # beside it.
        "sources_cited": len(answer["cited_texts"]),
        "sources_supplied": answer.get("sources_supplied", 0),
        "latency_ms": answer["latency_ms"],
        "input_tokens": answer["usage"].get("input_tokens", 0),
        "output_tokens": answer["usage"].get("output_tokens", 0),
    }
    if question["answerable"]:
        verdict["correct"] = not declined and states_fact(answer["answer"], question)
        verdict["supported"] = cites_evidence(answer["cited_texts"], question)
    else:
        verdict["correct"] = declined
    return verdict


def summarize(verdicts: Sequence[dict[str, Any]]) -> dict[str, Any]:
    answerable = [v for v in verdicts if v["answerable"]]
    unanswerable = [v for v in verdicts if not v["answerable"]]
    latencies = [v["latency_ms"] for v in verdicts]

    def rate(items: Sequence[dict[str, Any]], key: str) -> float:
        return round(sum(1 for v in items if v[key]) / len(items), 3) if items else 0.0

    return {
        "questions": len(verdicts),
        "answerable": {
            "count": len(answerable),
            "correct": rate(answerable, "correct"),
            "supported_by_citation": rate(answerable, "supported"),
            "declined_wrongly": rate(answerable, "declined"),
        },
        "unanswerable": {
            "count": len(unanswerable),
            "declined": rate(unanswerable, "correct"),
        },
        "grounded": rate(verdicts, "grounded"),
        "dropped_citations": sum(v["dropped_citations"] for v in verdicts),
        "citations": {
            "mean_sources_cited": round(sum(v["sources_cited"] for v in verdicts) / len(verdicts), 2)
            if verdicts
            else 0.0,
            "cited_every_source": round(
                sum(1 for v in verdicts if v["sources_supplied"] > 1 and v["sources_cited"] >= v["sources_supplied"])
                / len(verdicts),
                3,
            )
            if verdicts
            else 0.0,
        },
        "latency_ms_p50": round(percentile(latencies, 50) or 0, 1),
        "latency_ms_p95": round(percentile(latencies, 95) or 0, 1),
        "mean_input_tokens": round(sum(v["input_tokens"] for v in verdicts) / len(verdicts)) if verdicts else 0,
    }


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))
