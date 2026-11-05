"""Each provider client reports what its provider measured.

The HTTP layer is replaced with canned responses in each provider's wire
format, so these pin the usage parsing — Gemini's usageMetadata, Ollama's eval
counters, OpenRouter's OpenAI-style usage — without a network or a key.
"""

from __future__ import annotations

import io
import json

import pytest

import core
from core import GeminiClient, OllamaClient, OpenRouterClient
from telemetry import collect_usage

MESSAGES = [
    {"role": "system", "content": "You extract."},
    {"role": "user", "content": "Paper text here."},
]


class TestOllama:
    @staticmethod
    def _client(monkeypatch, response):
        client = OllamaClient(model="qwen2.5:7b")
        monkeypatch.setattr(client, "_post", lambda path, body: response)
        return client

    def test_chat_records_reported_usage_and_decode_time(self, monkeypatch):
        client = self._client(
            monkeypatch,
            {
                "message": {"content": '{"problem": "pose"}'},
                "prompt_eval_count": 812,
                "eval_count": 64,
                "eval_duration": 1_600_000_000,
            },
        )
        with collect_usage() as usage:
            assert client.chat_completion(MESSAGES, response_format=None) == '{"problem": "pose"}'

        [call] = usage.calls
        assert (call.provider, call.model, call.operation) == ("ollama", "qwen2.5:7b", "chat")
        assert (call.input_tokens, call.output_tokens) == (812, 64)
        assert call.generation_ms == pytest.approx(1600)
        assert call.tokens_per_second == pytest.approx(40.0)
        assert call.cost_usd == 0.0
        assert not call.usage_estimated

    def test_an_empty_answer_is_a_failed_call(self, monkeypatch):
        client = self._client(
            monkeypatch, {"message": {"content": "   "}, "prompt_eval_count": 10, "eval_count": 1}
        )
        with collect_usage() as usage, pytest.raises(ValueError, match="Empty content"):
            client.chat_completion(MESSAGES, response_format=None)

        [call] = usage.calls
        assert call.status == "error"
        # It still consumed the prompt, and the provider said so.
        assert call.input_tokens == 10

    def test_batch_embeddings_record_reported_tokens(self, monkeypatch):
        client = self._client(
            monkeypatch, {"embeddings": [[0.1, 0.2], [0.3, 0.4]], "prompt_eval_count": 37}
        )
        with collect_usage() as usage:
            assert client.get_embeddings(["one", "two"]) == [[0.1, 0.2], [0.3, 0.4]]

        [call] = usage.calls
        assert (call.model, call.operation) == ("nomic-embed-text", "embeddings")
        assert call.input_tokens == 37
        assert not call.usage_estimated

    def test_the_legacy_embedding_fallback_estimates_each_text(self, monkeypatch):
        client = OllamaClient(model="qwen2.5:7b")

        def post(path, body):
            if path == "/api/embed":
                raise RuntimeError("Ollama HTTP 404: not found")
            return {"embedding": [0.5]}

        monkeypatch.setattr(client, "_post", post)
        with collect_usage() as usage:
            assert client.get_embeddings(["a" * 40, "b" * 80]) == [[0.5], [0.5]]

        # The failed batch attempt, then one estimated call per text.
        assert [c.status for c in usage.calls] == ["error", "ok", "ok"]
        assert [c.input_tokens for c in usage.calls[1:]] == [10, 20]
        assert all(c.usage_estimated for c in usage.calls[1:])


class TestGemini:
    @staticmethod
    def _response(text="ok", **usage):
        return {
            "candidates": [{"content": {"parts": [{"text": text}]}}],
            "usageMetadata": usage,
        }

    def test_thinking_tokens_are_billed_as_output(self, monkeypatch):
        client = GeminiClient(api_key="k", model="gemini-2.5-flash")
        monkeypatch.setattr(
            client,
            "_post",
            lambda url, body, **kw: self._response(
                promptTokenCount=1000, candidatesTokenCount=200, thoughtsTokenCount=300
            ),
        )
        with collect_usage() as usage:
            assert client.chat_completion(MESSAGES, response_format=None) == "ok"

        [call] = usage.calls
        assert (call.input_tokens, call.output_tokens) == (1000, 500)
        assert call.cost_usd == pytest.approx((1000 * 0.30 + 500 * 2.50) / 1e6)

    def test_a_quota_fallback_records_both_attempts(self, monkeypatch):
        client = GeminiClient(
            api_key="k", model="gemini-2.5-flash-lite", fallback_models=["gemini-2.5-flash"]
        )

        def post(url, body, **kw):
            if "gemini-2.5-flash-lite" in url:
                raise RuntimeError(
                    "Gemini HTTP 429: quota GenerateRequestsPerDayPerProjectPerModel-FreeTier"
                )
            return self._response(promptTokenCount=50, candidatesTokenCount=5)

        monkeypatch.setattr(client, "_post", post)
        with collect_usage() as usage:
            client.chat_completion(MESSAGES, response_format=None)

        assert [(c.model, c.status) for c in usage.calls] == [
            ("gemini-2.5-flash-lite", "error"),
            ("gemini-2.5-flash", "ok"),
        ]

    def test_embeddings_are_estimated_because_none_are_reported(self, monkeypatch):
        monkeypatch.setattr(core, "OPENROUTER_FOR_EMBEDDINGS", False)
        client = GeminiClient(api_key="k")
        monkeypatch.setattr(
            client, "_post", lambda url, body, **kw: {"embeddings": [{"values": [1.0]}]}
        )
        with collect_usage() as usage:
            client.get_embeddings(["x" * 400])

        [call] = usage.calls
        assert (call.model, call.operation) == ("gemini-embedding-001", "embeddings")
        assert call.input_tokens == 100
        assert call.usage_estimated
        assert call.cost_usd == pytest.approx(100 * 0.15 / 1e6)


class _FakeHTTPResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestOpenRouter:
    def test_chat_records_reported_usage(self, monkeypatch):
        body = {
            "choices": [{"message": {"content": "```json\n{}\n```"}}],
            "usage": {"prompt_tokens": 420, "completion_tokens": 17},
        }
        monkeypatch.setattr(
            core.urllib.request,
            "urlopen",
            lambda request, timeout: _FakeHTTPResponse(json.dumps(body).encode()),
        )
        client = OpenRouterClient(api_key="k", model="z-ai/glm-4.5-air:free")
        with collect_usage() as usage:
            assert client.chat_completion(MESSAGES, response_format=None) == "{}"

        [call] = usage.calls
        assert (call.provider, call.input_tokens, call.output_tokens) == ("openrouter", 420, 17)
        assert call.cost_usd == 0.0

    def test_embeddings_record_reported_usage(self, monkeypatch):
        body = {"data": [{"embedding": [0.1]}], "usage": {"prompt_tokens": 9}}
        monkeypatch.setattr(
            core.urllib.request,
            "urlopen",
            lambda request, timeout: _FakeHTTPResponse(json.dumps(body).encode()),
        )
        client = OpenRouterClient(api_key="k", model="unused")
        with collect_usage() as usage:
            client.get_embeddings(["hello"])

        [call] = usage.calls
        assert (call.operation, call.input_tokens) == ("embeddings", 9)
        # Not in the price table, and not a :free variant.
        assert call.cost_usd is None


class TestEmbeddingTaskHints:
    """Documents and queries are embedded differently where the model expects it."""

    @staticmethod
    def _ollama(monkeypatch, embed_model="nomic-embed-text"):
        client = OllamaClient(model="qwen2.5:7b", embed_model=embed_model)
        sent: list[dict] = []

        def post(path, body):
            sent.append(body)
            return {"embeddings": [[0.0]] * len(body["input"])}

        monkeypatch.setattr(client, "_post", post)
        return client, sent

    def test_nomic_gets_its_task_prefixes(self, monkeypatch):
        client, sent = self._ollama(monkeypatch)
        client.get_embeddings(["a passage"], task="document")
        client.get_embeddings(["a question"], task="query")
        assert sent[0]["input"] == ["search_document: a passage"]
        assert sent[1]["input"] == ["search_query: a question"]

    def test_a_tagged_model_name_still_gets_them(self, monkeypatch):
        client, sent = self._ollama(monkeypatch, embed_model="nomic-embed-text:latest")
        client.get_embeddings(["a question"], task="query")
        assert sent[0]["input"] == ["search_query: a question"]

    def test_other_local_models_are_sent_the_text_unchanged(self, monkeypatch):
        client, sent = self._ollama(monkeypatch, embed_model="mxbai-embed-large")
        client.get_embeddings(["a question"], task="query")
        assert sent[0]["input"] == ["a question"]

    def test_no_task_means_no_prefix(self, monkeypatch):
        # Reranking and reviews embed without a task, exactly as before.
        client, sent = self._ollama(monkeypatch)
        client.get_embeddings(["an abstract"])
        assert sent[0]["input"] == ["an abstract"]

    def test_gemini_sends_the_task_type(self, monkeypatch):
        monkeypatch.setattr(core, "OPENROUTER_FOR_EMBEDDINGS", False)
        client = GeminiClient(api_key="k")
        sent: list[dict] = []
        monkeypatch.setattr(
            client,
            "_post",
            lambda url, body, **kw: sent.append(body) or {"embeddings": [{"values": [1.0]}]},
        )
        client.get_embeddings(["which datasets?"], task="query")
        assert sent[0]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"

    def test_gemini_retrieval_never_detours_through_openrouter(self, monkeypatch):
        # A fallback between providers mid-corpus would mix vector spaces.
        monkeypatch.setattr(core, "OPENROUTER_API_KEY", "k")
        monkeypatch.setattr(core, "OPENROUTER_FOR_EMBEDDINGS", True)

        def openrouter_called(*_args, **_kwargs):
            raise AssertionError("retrieval embeddings went to OpenRouter")

        monkeypatch.setattr(OpenRouterClient, "get_embeddings", openrouter_called)
        client = GeminiClient(api_key="k")
        monkeypatch.setattr(
            client, "_post", lambda url, body, **kw: {"embeddings": [{"values": [1.0]}]}
        )
        assert client.get_embeddings(["a passage"], task="document") == [[1.0]]

    def test_an_unknown_task_is_rejected(self, monkeypatch):
        client, _ = self._ollama(monkeypatch)
        with pytest.raises(ValueError, match="Unknown embedding task"):
            client.get_embeddings(["x"], task="classification")

    def test_each_client_names_its_retrieval_model(self):
        assert OllamaClient(model="m", embed_model="nomic-embed-text").embedding_model_id == "nomic-embed-text"
        assert GeminiClient(api_key="k").embedding_model_id == "gemini-embedding-001"
        assert (
            OpenRouterClient(api_key="k", model="m").embedding_model_id
            == "sentence-transformers/all-minilm-l12-v2"
        )
