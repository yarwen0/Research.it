"""Column types that differ by database.

`EmbeddingVector` stores an embedding as pgvector's `vector` on Postgres, where
similarity search runs inside the database, and as packed float32 bytes on
SQLite, where it runs in numpy. Python only ever sees a float32 array, in and
out, so nothing above the model layer has to know which database it is on.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from pgvector.sqlalchemy import VECTOR
from sqlalchemy import LargeBinary
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine


def _is_postgres(dialect: Dialect) -> bool:
    return dialect.name == "postgresql"


class EmbeddingVector(TypeDecorator[np.ndarray]):
    """A one-dimensional float32 embedding.

    Dimensionless on purpose: the width depends on the embedding model (768
    for nomic-embed-text, 3072 for gemini-embedding-001), and every query is
    scoped to one model, so the column never has to hold a single width.
    """

    impl = LargeBinary
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if _is_postgres(dialect):
            return dialect.type_descriptor(VECTOR())
        return dialect.type_descriptor(LargeBinary())

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        array = np.asarray(value, dtype=np.float32)
        if array.ndim != 1:
            raise ValueError(f"an embedding must be one-dimensional, got shape {array.shape}")
        # pgvector's own bind processor serializes the array for Postgres.
        return array if _is_postgres(dialect) else array.tobytes()

    def process_result_value(self, value: Any, dialect: Dialect) -> np.ndarray | None:
        if value is None:
            return None
        if _is_postgres(dialect):
            return np.asarray(value, dtype=np.float32)
        return np.frombuffer(value, dtype=np.float32)
