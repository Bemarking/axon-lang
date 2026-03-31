"""
AXON Runtime — Store Backends
==============================
Pluggable persistence backends for the ``axonstore`` primitive.

Each backend implements the ``StoreBackend`` protocol, providing
ACID-compliant CRUD operations under HoTT schema validation and
Linear Logic transactional guarantees.

Available backends:
  - ``sqlite``      — Zero-config SQLite via ``aiosqlite`` (default)
  - ``postgresql``  — Production PostgreSQL via ``asyncpg``
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ═══════════════════════════════════════════════════════════════════
#  RESULT CONTAINER
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class StoreResult:
    """Result of executing a store CRUD operation.

    Attributes:
        success:    Whether the operation completed without error.
        operation:  The operation name (persist, retrieve, mutate, purge, transact).
        data:       The output data (varies by operation).
        error:      Error message if the operation failed.
        metadata:   Additional information (token_id, rows_affected, etc.).
    """
    success: bool = True
    operation: str = ""
    data: Any = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════
#  STORE BACKEND PROTOCOL
# ═══════════════════════════════════════════════════════════════════


@runtime_checkable
class StoreBackend(Protocol):
    """Protocol for axonstore persistence backends.

    Each method corresponds to one ACID-compliant operation.
    Transaction support uses ephemeral token IDs (Linear Logic ⊸).

    Implementations must guarantee:
      - Atomicity:   begin/commit/rollback lifecycle
      - Consistency: schema enforcement before mutation
      - Isolation:   configurable via ``isolation`` parameter
      - Durability:  writes survive process restart
    """

    async def initialize(self, table_name: str, columns: list[dict[str, Any]]) -> None:
        """Create or validate the table schema (HoTT path construction)."""
        ...

    async def insert(self, table_name: str, data: dict[str, Any],
                     token_id: str | None = None) -> dict[str, Any]:
        """INSERT a row — consumes a linear write token."""
        ...

    async def query(self, table_name: str, where_expr: str = "") -> list[dict[str, Any]]:
        """SELECT rows matching the filter expression."""
        ...

    async def update(self, table_name: str, where_expr: str,
                     data: dict[str, Any], token_id: str | None = None) -> int:
        """UPDATE rows — atomic mutation, returns affected count."""
        ...

    async def delete(self, table_name: str, where_expr: str,
                     token_id: str | None = None) -> int:
        """DELETE rows — controlled purge, returns affected count."""
        ...

    async def begin_transaction(self) -> str:
        """Begin a transaction, return ephemeral token ID."""
        ...

    async def commit(self, token_id: str) -> None:
        """Commit a transaction by token ID."""
        ...

    async def rollback(self, token_id: str) -> None:
        """Rollback a transaction by token ID."""
        ...

    async def close(self) -> None:
        """Release DB connections."""
        ...


# ═══════════════════════════════════════════════════════════════════
#  STORE BACKEND FACTORY
# ═══════════════════════════════════════════════════════════════════


def create_store_backend(
    backend_type: str,
    connection: str = "",
    isolation: str = "serializable",
) -> StoreBackend:
    """Factory for creating store backends.

    Args:
        backend_type: ``"sqlite"`` | ``"postgresql"``
        connection:   Connection string or ``"env:VAR"``
        isolation:    ACID isolation level

    Returns:
        A backend instance implementing ``StoreBackend``.
    """
    if backend_type == "sqlite":
        from axon.runtime.store_backends.sqlite_backend import SQLiteStoreBackend
        return SQLiteStoreBackend(connection=connection, isolation=isolation)
    elif backend_type == "postgresql":
        from axon.runtime.store_backends.postgresql_backend import PostgreSQLStoreBackend
        return PostgreSQLStoreBackend(connection=connection, isolation=isolation)
    else:
        raise ValueError(f"Unknown store backend: {backend_type!r}")
