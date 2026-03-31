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
"""

from __future__ import annotations

import re
import uuid
from typing import Any


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


# Safe where expression pattern
_SAFE_WHERE_RE = re.compile(r"^[\w\s.=<>!'+\-*/(),\"]+$", re.ASCII)


def _translate_where(expr: str) -> str:
    if not expr:
        return "TRUE"
    if not _SAFE_WHERE_RE.match(expr):
        raise ValueError(f"Unsafe where expression: {expr!r}")
    return expr.replace("==", "=")


# ═══════════════════════════════════════════════════════════════════
#  POSTGRESQL STORE BACKEND
# ═══════════════════════════════════════════════════════════════════


class PostgreSQLStoreBackend:
    """PostgreSQL-backed persistence for ``axonstore``.

    Requires the ``asyncpg`` package (``pip install axon-lang[postgresql]``).
    """

    def __init__(
        self,
        connection: str = "",
        isolation: str = "serializable",
    ) -> None:
        self._dsn = connection
        self._isolation = _ISOLATION_MAP.get(isolation, "SERIALIZABLE")
        self._pool: Any = None
        self._active_txns: dict[str, Any] = {}  # token_id → connection

    async def _ensure_pool(self) -> Any:
        if self._pool is None:
            try:
                import asyncpg
            except ImportError as exc:
                raise ImportError(
                    "PostgreSQL backend requires asyncpg. "
                    "Install with: pip install axon-lang[postgresql]"
                ) from exc
            self._pool = await asyncpg.create_pool(dsn=self._dsn)
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

    # ── CRUD Operations ──────────────────────────────────────────

    async def insert(
        self, table_name: str, data: dict[str, Any],
        token_id: str | None = None,
    ) -> dict[str, Any]:
        conn = self._active_txns.get(token_id) if token_id else None
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
        pool = await self._ensure_pool()
        clause = _translate_where(where_expr)
        sql = f'SELECT * FROM "{table_name}" WHERE {clause}'
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)
        return [dict(r) for r in rows]

    async def update(
        self, table_name: str, where_expr: str,
        data: dict[str, Any], token_id: str | None = None,
    ) -> int:
        conn = self._active_txns.get(token_id) if token_id else None
        clause = _translate_where(where_expr)
        cols = list(data.keys())
        set_parts = ", ".join(f'"{k}" = ${i+1}' for i, k in enumerate(cols))
        values = list(data.values())
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
        conn = self._active_txns.get(token_id) if token_id else None
        clause = _translate_where(where_expr)
        sql = f'DELETE FROM "{table_name}" WHERE {clause}'
        if conn:
            result = await conn.execute(sql)
        else:
            pool = await self._ensure_pool()
            async with pool.acquire() as c:
                result = await c.execute(sql)
        return int(result.split()[-1]) if isinstance(result, str) else 0

    # ── Transaction Management ───────────────────────────────────

    async def begin_transaction(self) -> str:
        pool = await self._ensure_pool()
        token_id = uuid.uuid4().hex[:16]
        conn = await pool.acquire()
        txn = conn.transaction(isolation=self._isolation)
        await txn.start()
        self._active_txns[token_id] = conn
        return token_id

    async def commit(self, token_id: str) -> None:
        conn = self._active_txns.pop(token_id, None)
        if conn is None:
            raise RuntimeError(
                f"Linear Logic violation: token '{token_id}' does not exist "
                f"or has already been consumed"
            )
        await conn.transaction().commit()
        await self._pool.release(conn)

    async def rollback(self, token_id: str) -> None:
        conn = self._active_txns.pop(token_id, None)
        if conn is None:
            raise RuntimeError(
                f"Linear Logic violation: token '{token_id}' does not exist "
                f"or has already been consumed"
            )
        await conn.transaction().rollback()
        await self._pool.release(conn)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
