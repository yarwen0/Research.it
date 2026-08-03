"""Locations for generated artifacts, and validation of client-supplied paths.

Several API payloads carry a filepath that the client received from an earlier
response (``saved_filepath``). Those values round-trip through the browser and
must be treated as untrusted: without a containment check, a request could name
any file the server process can read.
"""

from __future__ import annotations

from pathlib import Path

# Anchored to the backend package, not the process working directory, so
# artifacts land in the same place no matter where uvicorn was started from.
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


class UnsafePathError(ValueError):
    """Raised when a client-supplied path points outside the data directory."""


def resolve_data_path(candidate: str | Path) -> Path:
    """Resolve a client-supplied path, refusing anything outside ``DATA_DIR``.

    Relative paths are interpreted against the backend root, so the
    ``data/processed_papers_*.json`` values handed out by the research pipeline
    resolve as-is. Absolute paths are accepted only if they already live inside
    the data directory.

    Symlinks are followed before the check, so a link planted inside ``data/``
    cannot be used to reach outside it.

    Raises:
        UnsafePathError: if the path is blank or escapes ``DATA_DIR``.
    """
    text = str(candidate).strip()
    if not text:
        raise UnsafePathError("path must not be empty")

    raw = Path(text)
    resolved = (raw if raw.is_absolute() else BASE_DIR / raw).resolve()
    data_root = DATA_DIR.resolve()

    if not resolved.is_relative_to(data_root):
        raise UnsafePathError(f"path escapes the data directory: {text}")

    return resolved
