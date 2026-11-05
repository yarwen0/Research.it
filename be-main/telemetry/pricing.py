"""Estimated cost of an LLM call.

Prices are list prices in USD per million tokens, copied from the provider's
pricing page on the date in `PRICES_CHECKED`. They drift, so `LLM_PRICES`
(a JSON object, see `.env.example`) overrides or extends the table without a
code change.

Two deliberate choices:

* **Local inference costs nothing here.** Ollama runs on the operator's own
  hardware; there is no API spend to attribute, and inventing an electricity
  figure would be a guess presented as a measurement.
* **An unknown model has no cost, not a guessed one.** `None` propagates to the
  rollups as an unpriced call, so a total is never quietly understated by a
  model nobody looked up.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from config import LLM_PRICES

logger = logging.getLogger(__name__)

# https://ai.google.dev/gemini-api/docs/pricing (paid tier). Gemini output
# prices include thinking tokens, which is why the clients count them as
# output. Vertex AI bills the same models per token and is costed from the same
# rows, unchecked against Vertex's own price list; LLM_PRICES corrects either.
# Vertex's text-embedding models are not in the table, so they report no cost.
PRICES_CHECKED = "2026-11-05"


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input_per_mtok: float
    output_per_mtok: float = 0.0


# Text input, prompts up to 200k tokens — the review prompt, the largest this
# app sends, is far below that. The 2.0 models in the Gemini client's fallback
# chain are no longer listed, so they are left unpriced rather than carried
# forward from a page that has moved on.
_DEFAULT_PRICES: dict[str, Price] = {
    "gemini-2.5-pro": Price(1.25, 10.00),
    "gemini-2.5-flash": Price(0.30, 2.50),
    "gemini-2.5-flash-lite": Price(0.10, 0.40),
    "gemini-embedding-001": Price(0.15),
}

# Providers whose calls cost nothing to make.
_FREE_PROVIDERS = frozenset({"ollama"})

# Vertex publishes some models under a dated suffix ("gemini-2.0-flash-001")
# and the Gemini API under a path ("models/gemini-embedding-001"). Both name
# the same priced model.
_VERSION_SUFFIX = re.compile(r"-\d{3}$")


def _parse_overrides(raw: str | None) -> dict[str, Price]:
    """Read `LLM_PRICES`, ignoring (and logging) anything malformed.

    A bad override should cost the operator their override, not the server.
    """
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Ignoring LLM_PRICES: not valid JSON (%s)", exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("Ignoring LLM_PRICES: expected a JSON object")
        return {}

    prices: dict[str, Price] = {}
    for model, entry in data.items():
        try:
            prices[normalize_model(model)] = Price(
                float(entry["input"]), float(entry.get("output", 0.0))
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            logger.warning("Ignoring LLM_PRICES entry for %r: %r", model, entry)
    return prices


def normalize_model(model: str) -> str:
    """Reduce a provider's model id to the key the price table uses."""
    return model.strip().lower().rsplit("/", 1)[-1]


PRICES: dict[str, Price] = {**_DEFAULT_PRICES, **_parse_overrides(LLM_PRICES)}


def price_for(model: str) -> Price | None:
    """Look a model up exactly, then without a dated version suffix.

    Exact first, because some ids end in digits that are part of the name
    rather than a version ("gemini-embedding-001").
    """
    name = normalize_model(model)
    return PRICES.get(name) or PRICES.get(_VERSION_SUFFIX.sub("", name))


def estimate_cost(
    provider: str,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    """USD cost of one call, or None when the model is not priced.

    OpenRouter's `:free` variants cost nothing by definition; any other
    OpenRouter model is priced only if the table names it.
    """
    if provider in _FREE_PROVIDERS:
        return 0.0
    if provider == "openrouter" and model.endswith(":free"):
        return 0.0

    price = price_for(model)
    if price is None:
        return None

    return (
        (input_tokens or 0) * price.input_per_mtok
        + (output_tokens or 0) * price.output_per_mtok
    ) / 1_000_000
