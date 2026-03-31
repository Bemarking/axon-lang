"""
AXON Runtime — PostgreSQL Store Backend
=========================================
Production-grade PostgreSQL backend for the ``axonstore`` primitive.

Uses ``asyncpg`` for async I/O (optional dependency).
When ``asyncpg`` is not installed, importing this module raises
``ImportError`` at instantiation time — the factory in
``__init__.py`` catches this gracefully.

Formal guarantees mirror the SQLite backend:
  - HoTT schema isomorphism:  CREATE TABLE ↔ IRStoreSchema
  - Linear Logic tokens:      BEGIN → single-use UUID
  - ACID isolation:            configurable per-transaction
  - SQL injection protection:  All WHERE clauses are parameterized
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from axon.runtime.store_backends.filter_parser import build_pg_where

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  SQL TYPE MAPPING
# ═══════════════════════════════════════════════════════════════════

_AXON_TO_PG: dict[str, str] = {
    "integer": "INTEGER",
    "text": "TEXT",
    "decimal": "NUMERIC",
    "timestamp": "TIMESTAMPTZ",
    "boolean": "BOOLEAN",
    "float": "DOUBLE PRECISION",
    "string": "TEXT",
}

_ISOLATION_MAP: dict[str, str] = {
    "read_committed": "READ COMMITTED",
    "repeatable_read": "REPEATABLE READ",
    "serializable": "SERIALIZABLE",
}


# ═══════════════════════════════════════════════════════════════════
#  POSTGRESQL STORE BACKEND
# ═══════════════════════════════════════════════════════════════════


class PostgreSQLStoreBackend:
    """PostgreSQL-backed persistence for ``axonstore``.

    Requires the ``asyncpg`` package (``pip install axon-lang[postgresql]``).

    Security:
      All WHERE clauses are parameterized — no string interpolation
      of user-supplied values into SQL.

    Transaction lifecycle:
      ``begin_transaction()`` acquires a connection from the pool
      and starts a Transaction object.  Both the connection and
      the Transaction are stored together so that ``commit()``
      and ``rollback()`` operate on the SAME transaction.
      The connection is released back to the pool after
      commit/rollback (even on error, via try/finally).
    """

    def __init__(
        self,
        connection: str = "",
        isolation: str = "serializable",
        pool_min_size: int = 2,
        pool_max_size: int = 10,
        ssl: Any = None,
    ) -> None:
        self._dsn = connection
        self._isolation = _ISOLATION_MAP.get(isolation, "SERIALIZABLE")
        self._pool: Any = None
        self._pool_min_size = pool_min_size
        self._pool_max_size = pool_max_size
        self._ssl = ssl
        # token_id → (connection, transaction) — both stored to avoid leak
        self._active_txns: dict[str, tuple[Any, Any]] = {}
        # Metrics
        self._op_count: int = 0
        self._error_count: int = 0
        self._last_op_time: float = 0.0

    async def _ensure_pool(self) -> Any:
        if self._pool is None:
            try:
                import asyncpg
            except ImportError as exc:
                raise ImportError(
                    "PostgreSQL backend requires asyncpg. "
                    "Install with: pip install axon-lang[postgresql]"
                ) from exc
            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=self._pool_min_size,
                max_size=self._pool_max_size,
                ssl=self._ssl,
            )
        return self._pool

    # ── Schema Management ────────────────────────────────────────

    async def initialize(
        self,
        table_name: str,
        columns: list[dict[str, Any]],
    ) -> None:
        pool = await self._ensure_pool()

        col_defs: list[str] = []
        for col in columns:
            pg_type = _AXON_TO_PG.get(col["col_type"], "TEXT")
            parts = [f'"{col["col_name"]}" {pg_type}']
            if col.get("primary_key") and col.get("auto_increment"):
                parts = [f'"{col["col_name"]}" SERIAL PRIMARY KEY']
            else:
                if col.get("primary_key"):
                    parts.append("PRIMARY KEY")
                if col.get("not_null"):
                    parts.append("NOT NULL")
                if col.get("unique"):
                    parts.append("UNIQUE")
                if col.get("default_value"):
                    dv = col["default_value"]
                    if dv == "now":
                        parts.append("DEFAULT NOW()")
                    else:
                        parts.append(f"DEFAULT {dv}")
            col_defs.append(" ".join(parts))

        ddl = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(col_defs)})'
        async with pool.acquire() as conn:
            await conn.execute(ddl)

    # ── CRUD Operations (parameterized) ──────────────────────────

    async def insert(
        self, table_name: str, data: dict[str, Any],
        token_id: str | None = None,
    ) -> dict[str, Any]:
        self._op_count += 1
        self._last_op_time = time.monotonic()

        conn_txn = self._active_txns.get(token_id) if token_id else None
        conn = conn_txn[0] if conn_txn else None
        cols = list(data.keys())
        placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
        col_names = ", ".join(f'"{c}"' for c in cols)
        values = [data[c] for c in cols]
        sql = f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders}) RETURNING *'
        if conn:
            row = await conn.fetchrow(sql, *values)
        else:
            pool = await self._ensure_pool()
            async with pool.acquire() as c:
                row = await c.fetchrow(sql, *values)
        return dict(row) if row else data

    async def query(
        self, table_name: str, where_expr: str = "",
    ) -> list[dict[str, Any]]:
        self._op_count += 1
        self._last_op_time = time.monotonic()

        pool = await self._ensure_pool()
        clause, params = build_pg_where(where_expr)
        sql = f'SELECT * FROM "{table_name}" WHERE {clause}'
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]

    async def update(
        self, table_name: str, where_expr: str,
        data: dict[str, Any], token_id: str | None = None,
    ) -> int:
        self._op_count += 1
        self._last_op_time = time.monotonic()

        conn_txn = self._active_txns.get(token_id) if token_id else None
        conn = conn_txn[0] if conn_txn else None
        cols = list(data.keys())
        set_parts = ", ".join(f'"{k}" = ${i+1}' for i, k in enumerate(cols))
        values = list(data.values())
        # WHERE params start after SET params
        clause, where_params = build_pg_where(where_expr, param_offset=len(cols))
        values = values + where_params
        sql = f'UPDATE "{table_name}" SET {set_parts} WHERE {clause}'
        if conn:
            result = await conn.execute(sql, *values)
        else:
            pool = await self._ensure_pool()
            async with pool.acquire() as c:
                result = await c.execute(sql, *values)
        # asyncpg returns "UPDATE N"
        return int(result.split()[-1]) if isinstance(result, str) else 0

    async def delete(
        self, table_name: str, where_expr: str,
        token_id: str | None = None,
    ) -> int:
        self._op_count += 1
        self._last_op_time = time.monotonic()

        conn_txn = self._active_txns.get(token_id) if token_id else None
        conn = conn_txn[0] if conn_txn else None
        clause, params = build_pg_where(where_expr)
        sql = f'DELETE FROM "{table_name}" WHERE {clause}'
        if conn:
            result = await conn.execute(sql, *params)
        else:
            pool = await self._ensure_pool()
            async with pool.acquire() as c:
                result = await c.execute(sql, *params)
        return int(result.split()[-1]) if isinstance(result, str) else 0

    # ── Transaction Management (Fixed: stores Transaction object) ─

    async def begin_transaction(self) -> str:
        """Begin a transaction — acquires connection + starts Transaction.

        The (connection, transaction) pair is stored together so that
        commit/rollback operate on the CORRECT transaction object,
        and the connection is always released back to the pool.
        """
        pool = await self._ensure_pool()
        token_id = uuid.uuid4().hex[:16]
        conn = await pool.acquire()
        try:
            txn = conn.transaction(isolation=self._isolation)
            await txn.start()
            self._active_txns[token_id] = (conn, txn)
        except Exception:
            await pool.release(conn)
            raise
        return token_id

    async def commit(self, token_id: str) -> None:
        """Commit the transaction and release the connection."""
        entry = self._active_txns.pop(token_id, None)
        if entry is None:
            raise RuntimeError(
                f"Linear Logic violation: token '{token_id}' does not exist "
                f"or has already been consumed"
            )
        conn, txn = entry
        try:
            await txn.commit()
        finally:
            # Always release connection back to pool
            await self._pool.release(conn)

    async def rollback(self, token_id: str) -> None:
        """Rollback the transaction and release the connection."""
        entry = self._active_txns.pop(token_id, None)
        if entry is None:
            raise RuntimeError(
                f"Linear Logic violation: token '{token_id}' does not exist "
                f"or has already been consumed"
            )
        conn, txn = entry
        try:
            await txn.rollback()
        finally:
            # Always release connection back to pool
            await self._pool.release(conn)

    # ── Schema Migration ─────────────────────────────────────────

    async def migrate(
        self,
        table_name: str,
        new_columns: list[dict[str, Any]],
    ) -> list[str]:
        """Add missing columns via ALTER TABLE ADD COLUMN."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            # Get existing columns from information_schema
            rows = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = $1",
                table_name,
            )
            existing = {row["column_name"] for row in rows}
            added: list[str] = []

            for col in new_columns:
                col_name = col["col_name"]
                if col_name not in existing:
                    pg_type = _AXON_TO_PG.get(col["col_type"], "TEXT")
                    parts = [f'"{col_name}" {pg_type}']
                    if col.get("default_value"):
                        dv = col["default_value"]
                        if dv == "now":
                            parts.append("DEFAULT NOW()")
                        else:
                            parts.append(f"DEFAULT {dv}")
                    ddl = (
                        f'ALTER TABLE "{table_name}" '
                        f'ADD COLUMN {" ".join(parts)}'
                    )
                    await conn.execute(ddl)
                    added.append(col_name)

        return added

    # ── Index Management ─────────────────────────────────────────

    async def create_index(
        self,
        table_name: str,
        index_name: str,
        columns: list[str],
        unique: bool = False,
    ) -> None:
        """Create an index on the specified columns."""
        pool = await self._ensure_pool()
        unique_kw = "UNIQUE " if unique else ""
        cols = ", ".join(f'"{c}"' for c in columns)
        ddl = (
            f'CREATE {unique_kw}INDEX IF NOT EXISTS '
            f'"{index_name}" ON "{table_name}" ({cols})'
        )
        async with pool.acquire() as conn:
            await conn.execute(ddl)

    # ── Health Check ─────────────────────────────────────────────

    async def ping(self) -> bool:
        """Check if the database is reachable."""
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    async def is_healthy(self) -> dict[str, Any]:
        """Return health status with operational metrics."""
        reachable = await self.ping()
        pool_size = self._pool.get_size() if self._pool else 0
        pool_free = self._pool.get_idle_size() if self._pool else 0
        return {
            "healthy": reachable,
            "backend": "postgresql",
            "pool_size": pool_size,
            "pool_free": pool_free,
            "active_transactions": len(self._active_txns),
            "total_operations": self._op_count,
            "error_count": self._error_count,
        }

    # ── Lifecycle ────────────────────────────────────────────────

    async def close(self) -> None:
        """Close the pool, releasing all connections."""
        # Rollback any active transactions first
        for token_id in list(self._active_txns.keys()):
            try:
                await self.rollback(token_id)
            except Exception:
                pass
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
