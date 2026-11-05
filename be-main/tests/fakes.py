"""Deterministic stand-ins shared across test modules."""

from __future__ import annotations

import json
import re
import threading
import zlib
from collections.abc import Callable, Sequence

import numpy as np

from telemetry import track_llm_call


class HashingEmbedder:
    """Embeds text as a hashed bag of words.

    Similarity follows word overlap, which is enough for a retrieval test to
    mean something — a query shares words with the passage it should find —
    while staying offline and identical across processes (crc32, not the
    per-process salted `hash()`).
    """

    def __init__(self, dim: int = 256, model_id: str = "hashing-test-embedder") -> None:
        self.dim = dim
        self.model_id = model_id
        self.document_batches: list[list[str]] = []
        self.queries: list[str] = []

    def vector(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float32)
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            vector[zlib.crc32(token.encode()) % self.dim] += 1.0
        return vector

    def embed_documents(self, texts: Sequence[str]) -> list[np.ndarray]:
        self.document_batches.append(list(texts))
        return [self.vector(text) for text in texts]

    def embed_query(self, text: str) -> np.ndarray:
        self.queries.append(text)
        return self.vector(text)


class FakeLLMClient:
    """A provider client with scripted chat replies and hashed embeddings.

    Replies come from a queue, or from `respond(messages, response_format)`
    when given — the form to use when calls arrive from parallel threads and
    their order is not fixed. Chat calls go through `track_llm_call` exactly as
    a real client's do, so usage attribution is exercised too. With nothing
    scripted, it declines, which is the safe answer.
    """

    def __init__(
        self,
        replies: Sequence[str] = (),
        *,
        respond: Callable[[list[dict], dict | None], str] | None = None,
        embedder: HashingEmbedder | None = None,
    ) -> None:
        self.replies = list(replies)
        self.respond = respond
        self.requests: list[tuple[list[dict], dict | None]] = []
        self.embedder = embedder or HashingEmbedder()
        self.embedding_model_id = self.embedder.model_id
        self._lock = threading.Lock()

    def chat_completion(self, messages, *, response_format):
        with self._lock:
            self.requests.append((messages, response_format))
        with track_llm_call("fake", "fake-chat", "chat") as call:
            if self.respond is not None:
                reply = self.respond(messages, response_format)
            else:
                with self._lock:
                    reply = (
                        self.replies.pop(0)
                        if self.replies
                        else '{"answer": "The sources do not say.", "insufficient_evidence": true}'
                    )
            call.input_tokens = sum(len(m["content"]) for m in messages) // 4
            call.output_tokens = len(reply) // 4
        return reply

    def schema_names(self) -> list[str]:
        """The structured-output schema each request asked for, in order."""
        with self._lock:
            return [
                (response_format or {}).get("json_schema", {}).get("name", "")
                for _, response_format in self.requests
            ]

    def get_embeddings(self, texts, model=None, *, task=None):
        return [self.embedder.vector(text).tolist() for text in texts]


def react_step(action: str, **fields) -> str:
    """One ReAct step as the model would emit it."""
    return json.dumps({"thought": f"use {action}", "action": action, **fields})


def schema_name(response_format: dict | None) -> str:
    return (response_format or {}).get("json_schema", {}).get("name", "")


def agent_responder(*, plan, critiques=("accept",), answer="Hourglass uses rmsprop [E1]."):
    """Replies for the assistant's graph by what is being asked, whichever thread asks.

    `plan` is the supervisor's decision; `critiques` the critic's verdicts in
    turn (accept once they run out); `answer` what the writer drafts.
    """
    verdicts = list(critiques)

    def respond(messages, response_format):
        name = schema_name(response_format)
        system = messages[0]["content"]
        if name == "assistant_plan":
            return json.dumps({"reasoning": "because", **plan})
        if name == "react_step":
            if "Result of" in messages[-1]["content"]:
                return react_step("finish", answer="Found it [E1].")
            if "gaps specialist" in system:
                return react_step("research_gaps", top=2)
            if "citations specialist" in system:
                return react_step("citation_stats", top=2)
            return react_step("search_passages", query="rmsprop learning rate")
        if name == "assistant_answer":
            return json.dumps({"answer": answer, "insufficient_evidence": False})
        if name == "critique":
            verdict = verdicts.pop(0) if verdicts else "accept"
            problems = [] if verdict == "accept" else ["The second claim is unsupported."]
            return json.dumps({"verdict": verdict, "problems": problems})
        raise AssertionError(f"unexpected request for {name!r}")

    return respond
