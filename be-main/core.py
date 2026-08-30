import json
import logging
import os
import re
import time
import urllib
import urllib.error
import urllib.request
from typing import ClassVar
from urllib.error import HTTPError

from pydantic import BaseModel, Field

from config import (
    GEMINI_API_KEY,
    LLM_PROVIDER,
    NO_LLM_PROVIDER_MESSAGE,
    OLLAMA_BASE_URL,
    OLLAMA_EMBED_MODEL,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OPENROUTER_API_KEY,
    OPENROUTER_FOR_EMBEDDINGS,
    has_llm_provider,
)
from constants.prompts.extractor_system_prompt import EXTRACTOR_SYSTEM_PROMPT
from constants.prompts.normalizer_system_prompt import NORMALIZER_SYSTEM_PROMPT
from constants.response_formats.canonical_default import CANONICAL_DEFAULT_RESPONSE_FORMAT
from constants.response_formats.extractor_default import EXTRACTOR_DEFAULT_RESPONSE_FORMAT

logger = logging.getLogger(__name__)


def _strip_unsupported_schema_keys(schema):
    """Recursively strip JSON-Schema fields that Gemini's responseSchema does not accept."""
    if isinstance(schema, dict):
        cleaned = {}
        for k, v in schema.items():
            # Gemini responseSchema is OpenAPI 3.0 subset — drop incompatible keys
            if k in ("additionalProperties", "$schema", "strict", "name"):
                continue
            if k == "type" and isinstance(v, list):
                # Gemini does not allow union types; pick the first non-null.
                non_null = [t for t in v if t != "null"]
                cleaned[k] = non_null[0] if non_null else "string"
                continue
            cleaned[k] = _strip_unsupported_schema_keys(v)
        return cleaned
    if isinstance(schema, list):
        return [_strip_unsupported_schema_keys(item) for item in schema]
    return schema


def _to_gemini_response_schema(response_format):
    """Convert OpenAI-style {type:'json_schema', json_schema:{schema:{...}}} to Gemini responseSchema."""
    if not response_format:
        return None
    if isinstance(response_format, dict) and response_format.get("type") == "json_schema":
        schema = response_format.get("json_schema", {}).get("schema")
    else:
        schema = response_format
    return _strip_unsupported_schema_keys(schema) if schema else None


class GeminiClient:
    """
    Native Google Gemini API client with the same surface as OpenRouterClient
    (chat_completion / get_embeddings) so it is a drop-in replacement.

    `model` is the preferred model. If a request fails with a daily-quota
    exhaustion error and `fallback_models` are configured, the client will
    transparently try the next model. This keeps the demo flowing on the free
    tier even when one model has burnt through its RPD budget.
    """

    # Order matters: cheapest/highest-quota first.
    DEFAULT_FALLBACK_CHAIN: ClassVar[list[str]] = [
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash",
        "gemini-2.5-flash",
        "gemini-flash-latest",
    ]

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash-lite",
        timeout: int = 120,
        fallback_models: list[str] | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        # Build dedup'd fallback list, starting with the preferred model.
        chain = [model] + (fallback_models or self.DEFAULT_FALLBACK_CHAIN)
        seen = set()
        self.model_chain = [m for m in chain if not (m in seen or seen.add(m))]

    def _post(self, url: str, body: dict, *, max_retries: int = 2) -> dict:
        payload = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}

        attempt = 0
        while True:
            request = urllib.request.Request(url, data=payload, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310
                    data = response.read().decode("utf-8")
                return json.loads(data)
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace").strip()
                # Retry on rate limits and transient server errors
                if exc.code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    attempt += 1
                    # Honor Gemini's suggested delay but cap it: the free tier can
                    # ask for ~55s, which would stall the request for minutes across
                    # retries. Cap so a quota error surfaces in the UI within ~40s.
                    delay = min(20, self._extract_retry_delay(detail) or (2 ** attempt))
                    logger.warning(
                        f"Gemini HTTP {exc.code} on attempt {attempt}/{max_retries}, "
                        f"sleeping {delay}s before retry"
                    )
                    time.sleep(delay)
                    continue
                message = detail or exc.reason or "unknown error"
                raise RuntimeError(f"Gemini HTTP {exc.code}: {message}") from exc

    @staticmethod
    def _extract_retry_delay(detail: str) -> int | None:
        """Pull the suggested retryDelay (seconds) out of a Gemini error body."""
        m = re.search(r'"retryDelay"\s*:\s*"(\d+)s"', detail)
        if m:
            return int(m.group(1))
        return None

    def chat_completion(self, messages: list[dict[str, str]], *, response_format: dict | None) -> str:
        system_text_parts: list[str] = []
        contents: list[dict] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_text_parts.append(content)
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})
            else:
                contents.append({"role": "user", "parts": [{"text": content}]})

        body: dict = {"contents": contents}
        if system_text_parts:
            body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_text_parts)}]}

        gen_config: dict = {"temperature": 0.2}
        if response_format:
            schema = _to_gemini_response_schema(response_format)
            if schema:
                gen_config["responseMimeType"] = "application/json"
                gen_config["responseSchema"] = schema
            else:
                gen_config["responseMimeType"] = "application/json"
        body["generationConfig"] = gen_config

        last_err: Exception | None = None
        for model in self.model_chain:
            url = f"{self.base_url}/models/{model}:generateContent?key={self.api_key}"
            try:
                parsed = self._post(url, body)
            except RuntimeError as exc:
                msg = str(exc)
                # If we're out of daily quota for THIS model, try the next one.
                if "429" in msg and ("PerDay" in msg or "RPD" in msg or "free_tier_requests" in msg):
                    logger.warning(
                        f"Gemini model {model} exhausted daily quota; "
                        f"falling back to next model in chain."
                    )
                    last_err = exc
                    continue
                raise
            try:
                candidates = parsed.get("candidates") or []
                if not candidates:
                    raise ValueError(f"Gemini returned no candidates: {parsed}")
                parts = candidates[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts).strip()
                if not text:
                    raise ValueError(f"Empty content in Gemini response: {parsed}")
                if model != self.model_chain[0]:
                    logger.info(f"Used Gemini fallback model: {model}")
                return text
            except (KeyError, IndexError) as exc:  # pragma: no cover - defensive
                raise ValueError(f"Unexpected Gemini response: {parsed}") from exc

        raise last_err or RuntimeError("Gemini chat_completion: all models exhausted")

    # Gemini's batchEmbedContents accepts at most 100 texts per request.
    GEMINI_BATCH_EMBED_LIMIT = 100

    def get_embeddings(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        # Optionally prefer OpenRouter for embeddings (explicit opt-in). Default
        # is Gemini embeddings so a Gemini-first setup works without relying on
        # an OpenRouter quota.
        if OPENROUTER_API_KEY and OPENROUTER_FOR_EMBEDDINGS:
            try:
                openrouter = OpenRouterClient(api_key=OPENROUTER_API_KEY, model="z-ai/glm-4.5-air:free")
                or_model = model if (model and "/" in model) else "sentence-transformers/all-minilm-l12-v2"
                return openrouter.get_embeddings(texts, model=or_model)
            except Exception as e:
                logger.warning(f"OpenRouter embeddings failed ({e}); falling back to Gemini.")

        if model and "/" in model and not model.startswith(("gemini-", "text-", "models/")):
            logger.info(f"Substituting embedding model {model!r} with gemini-embedding-001 (Gemini)")
            model = None
        embed_model = model or "gemini-embedding-001"
        if not embed_model.startswith("models/"):
            embed_model_full = f"models/{embed_model}"
        else:
            embed_model_full = embed_model
        url = f"{self.base_url}/{embed_model_full}:batchEmbedContents?key={self.api_key}"

        max_chars = 8000  # truncate per-text to stay under Gemini token limits
        # Gemini rejects empty Parts; substitute a stand-in for blanks so the
        # output array still aligns with the input order.
        EMPTY_PLACEHOLDER = "[empty]"
        normalised = [(t or "").strip()[:max_chars] or EMPTY_PLACEHOLDER for t in texts]

        all_embeddings: list[list[float]] = []
        total = len(normalised)
        logger.info(f"Gemini embeddings: {total} texts, model={embed_model_full}")

        for offset in range(0, total, self.GEMINI_BATCH_EMBED_LIMIT):
            batch = normalised[offset : offset + self.GEMINI_BATCH_EMBED_LIMIT]
            body = {
                "requests": [
                    {
                        "model": embed_model_full,
                        "content": {"parts": [{"text": t}]},
                    }
                    for t in batch
                ]
            }
            logger.info(
                f"Gemini embeddings batch {offset // self.GEMINI_BATCH_EMBED_LIMIT + 1}: "
                f"{len(batch)} texts (offset {offset})"
            )
            parsed = self._post(url, body)
            try:
                all_embeddings.extend(item["values"] for item in parsed["embeddings"])
            except (KeyError, IndexError) as exc:
                logger.error(f"Failed to parse Gemini embeddings response: {parsed}")
                raise ValueError(f"Unexpected Gemini embeddings response: {parsed}") from exc

        logger.info(f"Successfully received {len(all_embeddings)} Gemini embeddings")
        return all_embeddings


def _to_ollama_format(response_format):
    """Extract a JSON schema for Ollama structured output.

    Ollama accepts a JSON schema object (or the string "json") in the ``format``
    field. We reuse the OpenAI-style {type:'json_schema', json_schema:{schema}}
    shape the rest of the app already produces.
    """
    if not response_format:
        return None
    if isinstance(response_format, dict) and response_format.get("type") == "json_schema":
        schema = response_format.get("json_schema", {}).get("schema")
        return schema or "json"
    if isinstance(response_format, dict):
        return response_format
    return "json"


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_reasoning(text: str) -> str:
    """Remove <think>...</think> blocks some local models emit before answers."""
    return _THINK_RE.sub("", text)


class OllamaClient:
    """Local Ollama client with the same surface as GeminiClient/OpenRouterClient
    (chat_completion / get_embeddings).

    Runs fully offline — no API key, no rate limits. Requires ``ollama serve``
    to be running and the configured chat/embedding models to be pulled.
    """

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "http://localhost:11434",
        embed_model: str = "nomic-embed-text",
        timeout: int = 120,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.embed_model = embed_model
        # Local inference is slower than a hosted API; give long extractions room.
        self.timeout = max(timeout, 300)

    def _post(self, path: str, body: dict) -> dict:
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Ollama HTTP {exc.code}: {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Cannot reach Ollama at {self.base_url} ({exc.reason}). "
                "Start it with `ollama serve` and make sure the model is pulled."
            ) from exc

    def chat_completion(self, messages: list[dict[str, str]], *, response_format: dict | None) -> str:
        body: dict = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            # num_ctx defaults to 4096, which silently truncates a long prompt
            # and makes generation crawl once the window is full. Extraction
            # prompts (paper text, bibliographies) routinely exceed that.
            "options": {"temperature": 0.2, "num_ctx": OLLAMA_NUM_CTX},
        }
        fmt = _to_ollama_format(response_format)
        if fmt is not None:
            body["format"] = fmt

        parsed = self._post("/api/chat", body)
        content = (parsed.get("message") or {}).get("content", "") or ""
        content = _strip_reasoning(content).strip()
        # Strip markdown code fences some models wrap JSON in.
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        if not content:
            raise ValueError(f"Empty content in Ollama response: {parsed}")
        return content

    def get_embeddings(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Embed texts with the local embedding model.

        The ``model`` arg from callers names a hosted model id (OpenRouter/Gemini);
        we ignore it and always use the configured local embedding model.
        """
        logger.info(f"Ollama embeddings: {len(texts)} texts via {self.embed_model}")
        # Newer Ollama supports batch input on /api/embed.
        try:
            parsed = self._post("/api/embed", {"model": self.embed_model, "input": texts})
            embs = parsed.get("embeddings")
            if embs:
                return embs
        except RuntimeError as exc:
            logger.warning(f"/api/embed failed ({exc}); falling back to /api/embeddings")
        # Fallback: one request per text on the legacy endpoint.
        vectors: list[list[float]] = []
        for text in texts:
            parsed = self._post("/api/embeddings", {"model": self.embed_model, "prompt": text})
            vectors.append(parsed.get("embedding"))
        return vectors


def create_llm_client(*, model: str | None = None, timeout: int = 120):
    """
    Factory that returns the configured LLM client.

    Selection order:
      1. LLM_PROVIDER env (gemini | openrouter) — explicit override
      2. GEMINI_API_KEY present → Gemini
      3. OPENROUTER_API_KEY present → OpenRouter
    """
    # Validated here rather than at import, so work that needs no LLM — running
    # migrations, most obviously — does not require a key to be configured.
    if not has_llm_provider():
        raise RuntimeError(NO_LLM_PROVIDER_MESSAGE)

    provider = (LLM_PROVIDER or "").strip().lower()

    if not provider:
        provider = "gemini" if GEMINI_API_KEY else "openrouter"

    if provider == "ollama":
        return OllamaClient(
            model=model or OLLAMA_MODEL,
            base_url=OLLAMA_BASE_URL,
            embed_model=OLLAMA_EMBED_MODEL,
            timeout=timeout,
        )

    if provider == "gemini":
        if not GEMINI_API_KEY:
            raise RuntimeError(
                "LLM_PROVIDER=gemini but GEMINI_API_KEY is not set. "
                "Add GEMINI_API_KEY to your .env (https://aistudio.google.com/apikey)."
            )
        # gemini-2.5-flash-lite has a much higher free-tier daily quota
        # than gemini-2.5-flash (1000 vs 250 RPD) and matches its quality
        # closely for the structured-extraction prompts we use.
        default_model = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash-lite"
        return GeminiClient(api_key=GEMINI_API_KEY, model=model or default_model, timeout=timeout)

    return OpenRouterClient(
        api_key=OPENROUTER_API_KEY,
        model=model or "z-ai/glm-4.5-air:free",
        timeout=timeout,
    )

class OpenRouterClient:
    def __init__(self, api_key: str, model: str, timeout: int = 60) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.endpoint = "https://openrouter.ai/api/v1/chat/completions"
        self.embedding_endpoint = "https://openrouter.ai/api/v1/embeddings"

    def chat_completion(self, messages: list[dict[str, str]], *, response_format: dict | None) -> str:
        payload = json.dumps({"model": self.model, "messages": messages, "response_format": response_format}).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/saphalpdyl/research-gap-discovery-engine",
            "X-Title": "Research Gap Discovery Engine MVP",
        }
        request = urllib.request.Request(self.endpoint, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310
                data = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            message = detail or exc.reason or "unknown error"
            raise RuntimeError(f"OpenRouter HTTP {exc.code}: {message}") from exc
        parsed = json.loads(data)
        try:
            content = parsed["choices"][0]["message"]["content"]
            if content is None or content == "":
                raise ValueError(f"Empty content in OpenRouter response: {parsed}")
            # Strip markdown code fences that some OpenRouter models wrap JSON in.
            stripped = content.strip()
            if stripped.startswith("```"):
                stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped[3:]
                if stripped.endswith("```"):
                    stripped = stripped[:-3]
                stripped = stripped.strip()
            return stripped
        except (KeyError, IndexError) as exc:  # pragma: no cover - defensive
            raise ValueError(f"Unexpected OpenRouter response: {parsed}") from exc
    
    def get_embeddings(self, texts: list[str], model: str = "sentence-transformers/all-minilm-l12-v2") -> list[list[float]]:
        """
        Get embeddings for a list of texts using OpenRouter.
        
        Args:
            texts: List of text strings to embed
            model: Model identifier (default: sentence-transformers/all-minilm-l12-v2)
        
        Returns:
            List of embedding vectors
        """
        # Log input statistics
        logger.info(f"Getting embeddings for {len(texts)} texts using model: {model}")
        text_lengths = [len(t) for t in texts]
        logger.info(f"Text lengths - Min: {min(text_lengths)}, Max: {max(text_lengths)}, Avg: {sum(text_lengths)/len(text_lengths):.0f}")
        
        oversized = [(i, length) for i, length in enumerate(text_lengths) if length > 8000]
        if oversized:
            logger.warning(f"Warning: {len(oversized)} texts exceed 8000 characters")
            for i, length in oversized[:5]:  # Show first 5
                logger.warning(f"  Text {i}: {length} chars (preview: {texts[i][:100]}...)")
        
        payload = json.dumps({
            "model": model,
            "input": texts
        }).encode("utf-8")
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/saphalpdyl/research-gap-discovery-engine",
            "X-Title": "Research Gap Discovery Engine MVP",
        }
        
        request = urllib.request.Request(self.embedding_endpoint, data=payload, headers=headers)
        
        logger.info(f"Sending embedding request to {self.embedding_endpoint}")
        
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310
                data = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            message = detail or exc.reason or "unknown error"
            logger.error(f"OpenRouter Embeddings HTTP error {exc.code}: {message}")
            logger.error(f"Request payload size: {len(payload)} bytes, texts count: {len(texts)}")
            raise RuntimeError(f"OpenRouter Embeddings HTTP {exc.code}: {message}") from exc
        
        parsed = json.loads(data)
        
        try:
            # Extract embeddings from the response
            embeddings = [item["embedding"] for item in parsed["data"]]
            logger.info(f"Successfully received {len(embeddings)} embeddings")
            return embeddings
        except (KeyError, IndexError) as exc:
            logger.error(f"Failed to parse embeddings response. Keys in response: {list(parsed.keys())}")
            if 'error' in parsed:
                logger.error(f"API error details: {parsed['error']}")
            raise ValueError(f"Unexpected OpenRouter embeddings response: {parsed}") from exc
        
class ExtractedReference(BaseModel):
    title: str = Field(description="The title of the paper")
    authors: list[str] | None = Field(None, description="List of authors of the paper")
    year: str | None = Field(None, description="The year of publication")
    arxiv_id: str | None = Field(None, description="The arXiv ID of the paper, if available")
        
class ExtractedReferenceResponse(BaseModel):
    refs: list[ExtractedReference] = Field(description="List of extracted references")
        
class ReferenceParameterExtractorFallback:
    """
    Fallback extractor that uses an LLM to extract title/authors/year/arxiv_id from
    raw reference strings when regex-based extraction fails. Routes through the
    configured provider (Gemini by default; OpenRouter as fallback).
    """

    model: str  # Provider-specific model id

    def __init__(self, model: str | None = None) -> None:
        """
        Initialize the fallback extractor.

        Args:
            model: Provider-specific model id. When None the active provider's
                   default is used (Gemini → gemini-2.5-flash; OpenRouter →
                   z-ai/glm-4.5-air:free).
        """
        self.model = model

    def extract(self, reference: list[str]) -> ExtractedReferenceResponse:
        return self._extract_with_llm(reference)

    def _extract_with_llm(self, reference: list[str]) -> ExtractedReferenceResponse:
        """Extract using the configured LLM client."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert in citations and references. You will be provided with a list of reference strings, "
                    "and you must extract the title, authors, year, and arXiv ID (if available) from each reference in order. "
                    "Return the results in valid JSON format only."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Extract the title and other details from the following reference strings:\n\n"
                    f"{json.dumps(reference, indent=2)}\n\n"
                    "Return JSON only with the extracted information for each reference."
                )
            }
        ]

        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "extracted_references",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "refs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "authors": {
                                        "type": "array",
                                        "items": {"type": "string"}
                                    },
                                    "year": {"type": ["string", "null"]},
                                    "arxiv_id": {"type": ["string", "null"]}
                                },
                                "required": ["title", "authors", "year", "arxiv_id"],
                                "additionalProperties": False
                            }
                        }
                    },
                    "required": ["refs"],
                    "additionalProperties": False
                }
            }
        }

        client = create_llm_client(model=self.model, timeout=60)

        response = client.chat_completion(messages, response_format=response_format)
        result = ExtractedReferenceResponse.model_validate_json(response)

        return result

class PDFExtractor:
    client: "OpenRouterClient | GeminiClient"
    parameters_schema: dict

    def __init__(self, llm_client, parameters_schema: dict | None = None) -> None:
        self.client = llm_client
        # Use provided schema or fall back to the default extraction schema
        self.parameters_schema = parameters_schema or self._generate_default_schema()

    def _generate_default_schema(self) -> dict:
        """Default JSON Schema for extracting research insights from a paper.

        The schema is intentionally simple and LLM-friendly. It focuses on
        capturing key synthesis fields commonly needed for research analysis.
        """
        return EXTRACTOR_DEFAULT_RESPONSE_FORMAT

    def extract_from_raw_text(self, text: str) -> str:
        messages = [
            {
                "role": "system",
                "content": EXTRACTOR_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    "Extract the following structured information from the provided research paper text "
                    f"Research Paper Text:\n{text}\n\n"
                    "Provide the extracted information in valid JSON format adhering to the schema."
                ),
            }
        ]

        response = self.client.chat_completion(messages, response_format=self.parameters_schema)
        return response
    
    def normalize_extracted_parameters(
        self, extracted_response: dict, existing_ontology: dict | None = None
    ):
        # Normalized here rather than defaulted in the signature: a shared
        # mutable default is one accidental mutation away from leaking one
        # paper's ontology into the next call. `{}` keeps the prompt text
        # identical to before, where `null` would not.
        existing_ontology = existing_ontology if existing_ontology is not None else {}

        messages = [
            {
                "role": "system",
                "content": NORMALIZER_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    "Normalize the following extracted research parameters into a canonical format "
                    f"Existing Ontology:\n{json.dumps(existing_ontology, indent=2)}\n\n"
                    f"Extracted Parameters:\n{json.dumps(extracted_response, indent=2)}\n\n"
                    "Provide the normalized information in valid JSON format adhering to the canonical schema and tie to existing ontology as much as possible."
                ),
            } 
        ]

        response = self.client.chat_completion(messages, response_format=CANONICAL_DEFAULT_RESPONSE_FORMAT)
        return response
