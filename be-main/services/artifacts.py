"""On-disk artifacts produced by a research run.

The papers dump is still a file rather than a row: it is a whole run's raw
extraction output, read back verbatim by the review pipeline and never queried
field-by-field. The graph, ontology and reviews all moved to the database
because they *are* queried.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from utils.paths import BASE_DIR, DATA_DIR

logger = logging.getLogger(__name__)

# Keeps filenames bounded regardless of prompt length.
MAX_PROMPT_SLUG_LENGTH = 50


def _slugify_prompt(user_prompt: str) -> str:
    """Reduce a prompt to something safe to embed in a filename."""
    cleaned = "".join(
        c if c.isalnum() or c in (" ", "_") else "_" for c in user_prompt
    )
    return cleaned.replace(" ", "_")[:MAX_PROMPT_SLUG_LENGTH]


def save_processed_papers(
    processed_papers: list[dict[str, Any]], user_prompt: str
) -> str:
    """Write a run's processed papers to JSON.

    Returns:
        The path relative to the backend root. The client echoes this back on
        /api/create_review, so it stays relative to survive restarts, deploys
        and a different working directory.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"processed_papers_{_slugify_prompt(user_prompt)}_{timestamp}.json"
    filepath = DATA_DIR / filename

    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "user_prompt": user_prompt,
                "timestamp": datetime.now().isoformat(),
                "total_papers": len(processed_papers),
                "papers": processed_papers,
            },
            handle,
            indent=2,
            ensure_ascii=False,
        )

    logger.info("Saved %s processed papers to %s", len(processed_papers), filepath)
    return str(filepath.relative_to(BASE_DIR))
