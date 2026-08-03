"""Progress events emitted by long-running pipelines.

Deliberately transport-agnostic. The SSE endpoints turn these into
`data: {...}` frames today; moving the pipeline behind a job queue means
writing them to a store and having the endpoint read from it, with the
pipeline itself unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class StatusType(str, Enum):
    """Fixed status types for progress updates."""

    PROCESSING = "processing"  # Started, reading, initializing, extracting
    SUCCESS = "success"  # Completed successfully
    ERROR = "error"  # Error occurred
    PROGRESS = "progress"  # Intermediate update carrying partial results
    COMPLETED = "completed"  # Final completion with all results


@dataclass
class PipelineEvent:
    """One progress update."""

    status: StatusType
    message: str
    result: Optional[dict[str, Any]] = field(default=None)


def processing(message: str) -> PipelineEvent:
    return PipelineEvent(StatusType.PROCESSING, message)


def progress(message: str, result: Optional[dict[str, Any]] = None) -> PipelineEvent:
    return PipelineEvent(StatusType.PROGRESS, message, result)


def error(message: str) -> PipelineEvent:
    return PipelineEvent(StatusType.ERROR, message)


def completed(message: str, result: dict[str, Any]) -> PipelineEvent:
    return PipelineEvent(StatusType.COMPLETED, message, result)
