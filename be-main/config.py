import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # Load environment variables from a .env file if present

# Anchored to this file so paths resolve the same regardless of working
# directory. `utils.paths` re-exports the public form of this.
_BASE_DIR = Path(__file__).resolve().parent


def _maybe(key: str) -> str | None:
    val = os.getenv(key)
    if val is None:
        return None
    val = val.strip()
    return val or None


def _truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "on")


def _int(key: str, default: int) -> int:
    """Return an int env var, falling back to `default` when unset or invalid."""
    raw = _maybe(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


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

# Credentialed CORS is only safe against an explicit origin allowlist. Starlette
# responds to `allow_origins=["*"]` + `allow_credentials=True` by echoing back
# whatever Origin it is given, which would let any site make credentialed calls
# once auth exists — so credentials stay off while the wildcard is in play.
CORS_ALLOW_CREDENTIALS = "*" not in CORS_ORIGINS

# Host/port the API server binds to. Defaults preserve the original behavior.
HOST = _maybe("HOST") or "0.0.0.0"
PORT = _int("PORT", 8000)

# --- Logging ---------------------------------------------------------------
LOG_LEVEL = (_maybe("LOG_LEVEL") or "INFO").upper()

# JSON is queryable but unreadable at a terminal, so it is opt-in locally and
# on by default wherever something is collecting logs.
LOG_JSON = _truthy(os.getenv("LOG_JSON"))

# --- Database --------------------------------------------------------------


def _normalize_database_url(url: str) -> str:
    """Point a bare Postgres URL at the driver that is actually installed.

    Every managed provider — Fly, Heroku, Render, Railway — hands out
    `postgres://` or `postgresql://`. SQLAlchemy reads that as a request for
    psycopg2, which is not a dependency here, and fails at connect time with a
    misleading "No module named psycopg2". Only psycopg 3 is installed, so the
    driver is made explicit rather than requiring every deployment to rewrite
    the URL by hand.
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


# SQLite keeps `git clone && make dev` working with no services to install;
# compose and production point this at Postgres. The models and migrations are
# the same either way, so the only difference is the URL.
DATABASE_URL = _normalize_database_url(
    _maybe("DATABASE_URL") or f"sqlite:///{_BASE_DIR / 'data' / 'researchit.db'}"
)

# Pool sizing only applies to Postgres — SQLite ignores it.
DB_POOL_SIZE = _int("DB_POOL_SIZE", 5)
DB_MAX_OVERFLOW = _int("DB_MAX_OVERFLOW", 10)

# Echo every statement. Noisy; useful when tracing an N+1.
DB_ECHO = _truthy(os.getenv("DB_ECHO"))

# Apply migrations on startup. Convenient for local runs and single-container
# deploys; turn off where migrations are an explicit release step, since
# several workers booting at once should not all be driving DDL.
AUTO_MIGRATE = not _truthy(os.getenv("AUTO_MIGRATE_DISABLED"))

# --- Rate limiting ---------------------------------------------------------
# A single /api/research call downloads dozens of PDFs and spends real LLM
# budget, so the write endpoints are capped far tighter than the read ones.
RATE_LIMIT_ENABLED = not _truthy(os.getenv("RATE_LIMIT_DISABLED"))

# "memory://" is per-process and resets on restart — fine for one container,
# but set this to a redis:// URI once more than one worker is serving traffic.
RATE_LIMIT_STORAGE_URI = _maybe("RATE_LIMIT_STORAGE_URI") or "memory://"

RATE_LIMIT_DEFAULT = _maybe("RATE_LIMIT_DEFAULT") or "120/minute"
RATE_LIMIT_RESEARCH = _maybe("RATE_LIMIT_RESEARCH") or "5/hour"
RATE_LIMIT_REVIEW = _maybe("RATE_LIMIT_REVIEW") or "10/hour"
RATE_LIMIT_COMPILE = _maybe("RATE_LIMIT_COMPILE") or "30/minute"

# Off by default: X-Forwarded-For is trivially spoofed unless something in
# front of the app is guaranteed to overwrite it. Turn on when deployed behind
# a proxy that does (Fly.io, most load balancers), or every client will share
# the proxy's address and one caller can exhaust everyone's quota.
TRUST_PROXY_HEADERS = _truthy(os.getenv("TRUST_PROXY_HEADERS"))

NO_LLM_PROVIDER_MESSAGE = (
    "No LLM provider configured. Set LLM_PROVIDER=ollama for local models "
    "(no key needed), or set GEMINI_API_KEY (https://aistudio.google.com/apikey) "
    "or OPENROUTER_API_KEY in your .env file."
)


def has_llm_provider() -> bool:
    """Whether any usable LLM provider is configured.

    Checked when a client is built rather than raised at import. Importing
    config used to fail outright without a key, which meant work that never
    touches an LLM — running migrations, most obviously — could not proceed
    without one.
    """
    if (LLM_PROVIDER or "").strip().lower() == "ollama":
        return True
    return bool(GEMINI_API_KEY or OPENROUTER_API_KEY)


# Back-compat: keep OPENROUTER_API_KEY non-null so existing imports do not crash.
# Modules that only ever used the OpenRouter key will fall back to the Gemini
# pathway through `create_llm_client()` regardless of this value.
if OPENROUTER_API_KEY is None:
    OPENROUTER_API_KEY = ""
