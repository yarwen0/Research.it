import os
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from a .env file if present


def _maybe(key: str) -> str | None:
    val = os.getenv(key)
    if val is None:
        return None
    val = val.strip()
    return val or None


def _truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "on")


GEMINI_API_KEY = _maybe("GEMINI_API_KEY")
OPENROUTER_API_KEY = _maybe("OPENROUTER_API_KEY")
LLM_PROVIDER = _maybe("LLM_PROVIDER")  # 'gemini' | 'openrouter' | 'ollama'; auto-detected when unset

# Ollama (local models; no API key, no rate limits). Enable with LLM_PROVIDER=ollama.
OLLAMA_BASE_URL = _maybe("OLLAMA_BASE_URL") or "http://localhost:11434"
OLLAMA_MODEL = _maybe("OLLAMA_MODEL") or "qwen2.5:7b"
OLLAMA_EMBED_MODEL = _maybe("OLLAMA_EMBED_MODEL") or "nomic-embed-text"

# When using Gemini chat, embeddings still default to Gemini. Set OPENROUTER_FOR_EMBEDDINGS=1
# to route high-volume embeddings through OpenRouter instead (needs a paid / non-exhausted key).
OPENROUTER_FOR_EMBEDDINGS = _truthy(os.getenv("OPENROUTER_FOR_EMBEDDINGS"))

# Allowed browser origins for CORS, comma-separated (e.g. "https://app.example.com").
# Defaults to "*" (any origin) for local development.
CORS_ORIGINS = [o.strip() for o in (_maybe("CORS_ORIGINS") or "*").split(",") if o.strip()]

if (LLM_PROVIDER or "").strip().lower() != "ollama" and not GEMINI_API_KEY and not OPENROUTER_API_KEY:
    raise RuntimeError(
        "No LLM provider configured. Set LLM_PROVIDER=ollama for local models "
        "(no key needed), or set GEMINI_API_KEY (https://aistudio.google.com/apikey) "
        "or OPENROUTER_API_KEY in your .env file."
    )

# Back-compat: keep OPENROUTER_API_KEY non-null so existing imports do not crash.
# Modules that only ever used the OpenRouter key will fall back to the Gemini
# pathway through `create_llm_client()` regardless of this value.
if OPENROUTER_API_KEY is None:
    OPENROUTER_API_KEY = ""
