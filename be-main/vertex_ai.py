"""Gemini on Vertex AI, authorized with Application Default Credentials.

Vertex serves the same `generateContent` request and response bodies as the
Gemini API, so chat reuses GeminiClient wholesale; what changes is where
requests go and how they are authorized. Instead of an API key in the URL,
each request carries a short-lived OAuth token for the runtime's identity —
on Cloud Run the service account, locally whatever
`gcloud auth application-default login` set up. There is no secret to store,
rotate or leak.

Embeddings use Vertex's own `predict` API (text-embedding-005 by default),
which also reports a token count per text, so its usage is measured rather
than estimated.
"""

from __future__ import annotations

import threading
from typing import Any

import google.auth
import google.auth.transport.requests

from core import GeminiClient, _check_task
from telemetry import track_llm_call

SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)

_TASK_TYPES = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}


class VertexAIClient(GeminiClient):
    """A GeminiClient that talks to Vertex AI as a service identity."""

    provider = "vertex"
    display_name = "Vertex AI"

    # text-embedding-005 takes up to 250 texts and 20,000 tokens per request.
    # 32 passages of ~300 tokens stays well inside both.
    EMBED_BATCH = 32

    def __init__(
        self,
        *,
        model: str,
        embed_model: str,
        location: str = "us-central1",
        project: str | None = None,
        timeout: int = 120,
        credentials: Any = None,
    ) -> None:
        # The fallback chain exists for the Gemini API's free-tier daily
        # quotas. Vertex bills per request and has none, so one model only.
        super().__init__(api_key="", model=model, timeout=timeout)
        self.model_chain = [model]

        if credentials is None:
            credentials, detected_project = google.auth.default(scopes=SCOPES)
            project = project or detected_project
        if not project:
            raise RuntimeError(
                "LLM_PROVIDER=vertex needs a Google Cloud project: set GOOGLE_CLOUD_PROJECT, "
                "or run `gcloud config set project` before `gcloud auth application-default login`."
            )

        self.project = project
        self.location = location
        self.embed_model = embed_model
        self.embedding_model_id = embed_model
        self._credentials = credentials
        self._refresh_lock = threading.Lock()

        # "global" has no regional prefix; every other location does.
        host = (
            "aiplatform.googleapis.com"
            if location == "global"
            else f"{location}-aiplatform.googleapis.com"
        )
        self.base_url = (
            f"https://{host}/v1/projects/{project}/locations/{location}/publishers/google/models"
        )

    def _headers(self) -> dict[str, str]:
        # Tokens last about an hour; refresh only when the current one has
        # lapsed. Worker threads share the client, hence the lock.
        with self._refresh_lock:
            if not self._credentials.valid:
                self._credentials.refresh(google.auth.transport.requests.Request())
            token = self._credentials.token
        return {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}

    def _generate_url(self, model: str) -> str:
        return f"{self.base_url}/{model}:generateContent"

    def get_embeddings(
        self, texts: list[str], model: str | None = None, *, task: str | None = None
    ) -> list[list[float]]:
        """Embed with the configured Vertex model; `model` is ignored.

        Callers written for other providers pass their own model ids, which
        mean nothing here — the same reason OllamaClient ignores them.
        """
        _check_task(task)
        url = f"{self.base_url}/{self.embed_model}:predict"
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.EMBED_BATCH):
            # The API rejects empty content; keep positions aligned instead.
            batch = [text or " " for text in texts[start : start + self.EMBED_BATCH]]
            body = {
                "instances": [
                    {"content": text, **({"task_type": _TASK_TYPES[task]} if task else {})}
                    for text in batch
                ],
                # Truncate an overlong text rather than fail the whole batch.
                "parameters": {"autoTruncate": True},
            }
            with track_llm_call(
                self.provider,
                self.embed_model,
                "embeddings",
                prompt_chars=sum(len(text) for text in batch),
            ) as call:
                predictions = self._post(url, body).get("predictions") or []
                counts = [
                    prediction.get("embeddings", {}).get("statistics", {}).get("token_count")
                    for prediction in predictions
                ]
                if counts and all(count is not None for count in counts):
                    call.input_tokens = int(sum(counts))
                if len(predictions) != len(batch):
                    raise ValueError(
                        f"Vertex AI returned {len(predictions)} embeddings for {len(batch)} texts"
                    )
            vectors.extend(prediction["embeddings"]["values"] for prediction in predictions)
        return vectors
