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
LLM_PROVIDER = _maybe("LLM_PROVIDER")  # 'gemini' or 'openrouter'; auto-detected when unset

# When using Gemini chat, embeddings still default to Gemini. Set OPENROUTER_FOR_EMBEDDINGS=1
# to route high-volume embeddings through OpenRouter instead (needs a paid / non-exhausted key).
OPENROUTER_FOR_EMBEDDINGS = _truthy(os.getenv("OPENROUTER_FOR_EMBEDDINGS"))

if not GEMINI_API_KEY and not OPENROUTER_API_KEY:
    raise RuntimeError(
        "No LLM provider configured. Set GEMINI_API_KEY (recommended; "
        "https://aistudio.google.com/apikey) or OPENROUTER_API_KEY in your .env file."
    )

# Back-compat: keep OPENROUTER_API_KEY non-null so existing imports do not crash.
# Modules that only ever used the OpenRouter key will fall back to the Gemini
# pathway through `create_llm_client()` regardless of this value.
if OPENROUTER_API_KEY is None:
    OPENROUTER_API_KEY = ""
