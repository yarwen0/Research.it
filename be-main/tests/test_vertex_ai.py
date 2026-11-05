"""The Vertex AI client and Cloud Trace export, with no network and no credentials.

Requests are captured at urlopen, so these pin what would go over the wire:
the endpoint, the bearer token in place of an API key, and the body shapes.
"""

from __future__ import annotations

import io
import json
import urllib.request
from urllib.error import HTTPError

import pytest
from google.auth.credentials import AnonymousCredentials

import config
import core
from telemetry import collect_usage
from telemetry.tracing import GCP_TRACES_ENDPOINT, build_tracer_provider
from vertex_ai import VertexAIClient


class FakeCredentials:
    """Stands in for google.auth credentials: refreshable, countable."""

    def __init__(self):
        self.valid = False
        self.token = None
        self.refreshes = 0

    def refresh(self, _request):
        self.refreshes += 1
        self.valid = True
        self.token = f"token-{self.refreshes}"


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def wire(monkeypatch):
    """Captured requests, and a queue of JSON bodies to answer them with."""
    sent: list[urllib.request.Request] = []
    replies: list[dict] = []

    def urlopen(request, timeout):
        sent.append(request)
        return _Response(json.dumps(replies.pop(0)).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return sent, replies


def _client(**kwargs) -> VertexAIClient:
    defaults = {
        "model": "gemini-2.5-flash-lite",
        "embed_model": "text-embedding-005",
        "project": "demo-project",
        "credentials": FakeCredentials(),
    }
    return VertexAIClient(**{**defaults, **kwargs})


def _chat_reply(text="ok", **usage):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}], "usageMetadata": usage}


MESSAGES = [{"role": "user", "content": "Summarize."}]


class TestChat:
    def test_calls_the_regional_endpoint_with_a_bearer_token(self, wire):
        sent, replies = wire
        replies.append(_chat_reply())
        _client().chat_completion(MESSAGES, response_format=None)

        [request] = sent
        assert request.full_url == (
            "https://us-central1-aiplatform.googleapis.com/v1/projects/demo-project/"
            "locations/us-central1/publishers/google/models/gemini-2.5-flash-lite:generateContent"
        )
        assert request.get_header("Authorization") == "Bearer token-1"
        assert "key=" not in request.full_url

    def test_the_global_location_has_no_regional_prefix(self):
        assert _client(location="global").base_url.startswith(
            "https://aiplatform.googleapis.com/v1/projects/demo-project/locations/global/"
        )

    def test_sends_the_gemini_request_body(self, wire):
        sent, replies = wire
        replies.append(_chat_reply())
        _client().chat_completion(
            [{"role": "system", "content": "Be terse."}, *MESSAGES],
            response_format={"type": "json_schema", "json_schema": {"schema": {"type": "object"}}},
        )

        body = json.loads(sent[0].data)
        assert body["systemInstruction"] == {"parts": [{"text": "Be terse."}]}
        assert body["generationConfig"]["responseMimeType"] == "application/json"

    def test_usage_is_recorded_under_the_vertex_provider(self, wire):
        _, replies = wire
        replies.append(_chat_reply(promptTokenCount=120, candidatesTokenCount=30))
        with collect_usage() as usage:
            _client().chat_completion(MESSAGES, response_format=None)

        [call] = usage.calls
        assert (call.provider, call.model) == ("vertex", "gemini-2.5-flash-lite")
        assert (call.input_tokens, call.output_tokens) == (120, 30)
        assert call.cost_usd == pytest.approx((120 * 0.10 + 30 * 0.40) / 1e6)

    def test_the_token_is_refreshed_only_once_it_lapses(self, wire):
        _, replies = wire
        replies.extend([_chat_reply(), _chat_reply()])
        credentials = FakeCredentials()
        client = _client(credentials=credentials)

        client.chat_completion(MESSAGES, response_format=None)
        client.chat_completion(MESSAGES, response_format=None)
        assert credentials.refreshes == 1

        credentials.valid = False
        replies.append(_chat_reply())
        client.chat_completion(MESSAGES, response_format=None)
        assert credentials.refreshes == 2

    def test_there_is_no_free_tier_fallback_chain(self):
        assert _client().model_chain == ["gemini-2.5-flash-lite"]

    def test_errors_name_vertex(self, monkeypatch):
        def refuse(request, timeout):
            raise HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b"PERMISSION_DENIED"))

        monkeypatch.setattr(urllib.request, "urlopen", refuse)
        with pytest.raises(RuntimeError, match="Vertex AI HTTP 403: PERMISSION_DENIED"):
            _client().chat_completion(MESSAGES, response_format=None)


def _embedding_reply(count, tokens=7):
    return {
        "predictions": [
            {"embeddings": {"values": [float(i)], "statistics": {"token_count": tokens}}}
            for i in range(count)
        ]
    }


class TestEmbeddings:
    def test_batches_with_task_types(self, wire):
        sent, replies = wire
        replies.extend([_embedding_reply(32), _embedding_reply(8)])
        vectors = _client().get_embeddings([f"passage {i}" for i in range(40)], task="document")

        assert len(vectors) == 40
        assert [len(json.loads(r.data)["instances"]) for r in sent] == [32, 8]
        body = json.loads(sent[0].data)
        assert body["instances"][0] == {"content": "passage 0", "task_type": "RETRIEVAL_DOCUMENT"}
        assert body["parameters"] == {"autoTruncate": True}
        assert sent[0].full_url.endswith("/text-embedding-005:predict")

    def test_queries_get_the_query_task_type(self, wire):
        sent, replies = wire
        replies.append(_embedding_reply(1))
        _client().get_embeddings(["which datasets?"], task="query")
        assert json.loads(sent[0].data)["instances"][0]["task_type"] == "RETRIEVAL_QUERY"

    def test_reported_token_counts_are_used(self, wire):
        _, replies = wire
        replies.append(_embedding_reply(3, tokens=11))
        with collect_usage() as usage:
            _client().get_embeddings(["a", "b", "c"], task="document")

        [call] = usage.calls
        assert call.input_tokens == 33
        assert not call.usage_estimated

    def test_an_empty_text_keeps_its_position(self, wire):
        sent, replies = wire
        replies.append(_embedding_reply(2))
        assert len(_client().get_embeddings(["", "text"])) == 2
        assert json.loads(sent[0].data)["instances"][0]["content"] == " "

    def test_a_short_response_raises(self, wire):
        _, replies = wire
        replies.append(_embedding_reply(1))
        with pytest.raises(ValueError, match="1 embeddings for 2 texts"):
            _client().get_embeddings(["a", "b"])

    def test_the_retrieval_model_is_the_configured_one(self):
        assert _client().embedding_model_id == "text-embedding-005"


class TestFactory:
    @pytest.fixture
    def adc(self, monkeypatch):
        """Application Default Credentials that resolve to a given project."""

        def use(project):
            monkeypatch.setattr(
                "google.auth.default", lambda scopes=None: (FakeCredentials(), project)
            )

        monkeypatch.setattr(core, "LLM_PROVIDER", "vertex")
        monkeypatch.setattr(core, "has_llm_provider", lambda: True)
        return use

    def test_builds_a_vertex_client_from_adc(self, adc):
        adc("adc-project")
        client = core.create_llm_client()
        assert isinstance(client, VertexAIClient)
        assert client.project == "adc-project"

    def test_an_explicit_project_wins_over_adc(self, adc, monkeypatch):
        adc("adc-project")
        monkeypatch.setattr(core, "GOOGLE_CLOUD_PROJECT", "configured-project")
        assert core.create_llm_client().project == "configured-project"

    def test_no_project_anywhere_is_a_clear_error(self, adc):
        adc(None)
        with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
            core.create_llm_client()

    def test_vertex_counts_as_configured_without_a_key(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_PROVIDER", "vertex")
        monkeypatch.setattr(config, "GEMINI_API_KEY", None)
        monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
        assert config.has_llm_provider()


class TestCloudTraceExport:
    def test_exports_to_the_telemetry_api_tagged_with_the_project(self, monkeypatch):
        monkeypatch.setattr(
            "google.auth.default", lambda scopes=None: (AnonymousCredentials(), "trace-project")
        )
        provider = build_tracer_provider("gcp", service_name="researchit-api")

        assert provider.resource.attributes["gcp.project_id"] == "trace-project"
        assert provider.resource.attributes["service.name"] == "researchit-api"
        [processor] = provider._active_span_processor._span_processors
        assert processor.span_exporter._endpoint == GCP_TRACES_ENDPOINT
        provider.shutdown()

    def test_needs_a_project(self, monkeypatch):
        monkeypatch.setattr(
            "google.auth.default", lambda scopes=None: (AnonymousCredentials(), None)
        )
        with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
            build_tracer_provider("gcp")
