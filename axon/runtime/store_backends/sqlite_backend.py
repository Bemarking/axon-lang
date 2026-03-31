"""
AXON Runtime — SQLite Store Backend
=====================================
Zero-config SQLite backend for the ``axonstore`` primitive.

Uses ``aiosqlite`` for true async I/O when available.  Falls back
to synchronous ``sqlite3`` when ``aiosqlite`` is not installed,
ensuring the test suite always passes without optional deps.

Formal guarantees:
  - HoTT schema isomorphism:  CREATE TABLE ↔ IRStoreSchema
  - Linear Logic tokens:      BEGIN IMMEDIATE → single-use UUID
  - ACID isolation:            WAL mode + IMMEDIATE transactions
  - SQL injection protection:  All WHERE clauses are parameterized
"""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from typing import Any

from axon.runtime.store_backends.filter_parser import build_sqlite_where

logger = logging.getLogger(__name__)

# Try async SQLite — fall back to sync if unavailable
try:
    import aiosqlite
    _HAS_AIOSQLITE = True
except ImportError:
    _HAS_AIOSQLITE = False


# ═══════════════════════════════════════════════════════════════════
#  SQL TYPE MAPPING — HoTT fiber projection
# ═══════════════════════════════════════════════════════════════════

_AXON_TO_SQL: dict[str, str] = {
    "integer": "INTEGER",
    "text": "TEXT",
    "real": "REAL",
    "decimal": "REAL",
    "timestamp": "TEXT",
    "boolean": "INTEGER",
    "float": "REAL",
    "string": "TEXT",
}


# ═══════════════════════════════════════════════════════════════════
#  SQLITE STORE BACKEND
# ═══════════════════════════════════════════════════════════════════


class SQLiteStoreBackend:
    """SQLite-backed persistence for ``axonstore``.

    When ``connection`` is empty, uses ``:memory:`` for zero-config
    operation — perfect for tests and single-process agents.

    Security:
      All WHERE clauses are parameterized — no string interpolation
      of user-supplied values into SQL.

    Linear Logic enforcement:
      Each ``begin_transaction()`` generates a UUID token.
      The token is single-use: ``commit()`` or ``rollback()``
      consumes it and removes it from the active set.

    Async I/O:
      When ``aiosqlite`` is installed, all operations run on a
      background thread (true async).  Otherwise falls back to
      synchronous ``sqlite3`` with async-compatible wrappers.
    """

    def __init__(
        self,
        connection: str = "",
        isolation: str = "serializable",
    ) -> None:
        self._connection_str = connection or ":memory:"
        self._isolation = isolation
        self._conn: Any = None
        self._is_async = False
        # Linear Logic token registry: token_id → bool (consumed?)
        self._active_tokens: dict[str, bool] = {}
        # Metrics counters
        self._op_count: int = 0
        self._error_count: int = 0
        self._last_op_time: float = 0.0

    async def _ensure_connection(self) -> Any:
        """Lazy-init the SQLite connection (async or sync fallback)."""
        if self._conn is None:
            if _HAS_AIOSQLITE:
                self._conn = await aiosqlite.connect(
                    self._connection_str, isolation_level=None,
                )
                self._conn.row_factory = sqlite3.Row
                await self._conn.execute("PRAGMA journal_mode=WAL")
                await self._conn.execute("PRAGMA foreign_keys=ON")
                self._is_async = True
            else:
                self._conn = sqlite3.connect(
                    self._connection_str, isolation_level=None,
                )
                self._conn.row_factory = sqlite3.Row
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA foreign_keys=ON")
                self._is_async = False
        return self._conn

    # ── Schema Management (HoTT path construction) ────────────────

    async def initialize(
        self,
        table_name: str,
        columns: list[dict[str, Any]],
    ) -> None:
        """Create table from IRStoreSchema columns.

        Constructs the HoTT univalence path:
          (AxonType ≃ SQLiteSchema) ≃ (AxonType = SQLiteSchema)
        """
        conn = await self._ensure_connection()

        col_defs: list[str] = []
        for col in columns:
            sql_type = _AXON_TO_SQL.get(col["col_type"], "TEXT")
            parts = [f'"{col["col_name"]}" {sql_type}']
            if col.get("primary_key"):
                parts.append("PRIMARY KEY")
            if col.get("auto_increment"):
                parts.append("AUTOINCREMENT")
            if col.get("not_null"):
                parts.append("NOT NULL")
            if col.get("unique"):
                parts.append("UNIQUE")
            if col.get("default_value"):
                dv = col["default_value"]
                if dv == "now":
                    parts.append("DEFAULT (datetime('now'))")
                else:
                    parts.append(f"DEFAULT {dv}")
            col_defs.append(" ".join(parts))

        ddl = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(col_defs)})'
        if self._is_async:
            await conn.execute(ddl)
        else:
            conn.execute(ddl)

    # ── CRUD Operations (parameterized) ──────────────────────────

    async def insert(
        self,
        table_name: str,
        data: dict[str, Any],
        token_id: str | None = None,
    ) -> dict[str, Any]:
        """INSERT a row with fully parameterized values."""
        conn = await self._ensure_connection()
        self._op_count += 1
        self._last_op_time = time.monotonic()

        cols = list(data.keys())
        placeholders = ", ".join("?" for _ in cols)
        col_names = ", ".join(f'"{c}"' for c in cols)
        values = [data[c] for c in cols]

        sql = f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})'
        if self._is_async:
            cursor = await conn.execute(sql, values)
            lastrowid = cursor.lastrowid
        else:
            cursor = conn.execute(sql, values)
            lastrowid = cursor.lastrowid
        return {"rowid": lastrowid, **data}

    async def query(
        self,
        table_name: str,
        where_expr: str = "",
    ) -> list[dict[str, Any]]:
        """SELECT rows with parameterized WHERE clause (SQL-injection safe)."""
        conn = await self._ensure_connection()
        self._op_count += 1
        self._last_op_time = time.monotonic()

        clause, params = build_sqlite_where(where_expr)
        sql = f'SELECT * FROM "{table_name}" WHERE {clause}'

        if self._is_async:
            cursor = await conn.execute(sql, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        else:
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    async def update(
        self,
        table_name: str,
        where_expr: str,
        data: dict[str, Any],
        token_id: str | None = None,
    ) -> int:
        """UPDATE rows with parameterized SET and WHERE (SQL-injection safe)."""
        conn = await self._ensure_connection()
        self._op_count += 1
        self._last_op_time = time.monotonic()

        clause, where_params = build_sqlite_where(where_expr)
        set_parts = ", ".join(f'"{k}" = ?' for k in data)
        values = list(data.values()) + where_params
        sql = f'UPDATE "{table_name}" SET {set_parts} WHERE {clause}'

        if self._is_async:
            cursor = await conn.execute(sql, values)
            return cursor.rowcount
        else:
            cursor = conn.execute(sql, values)
            return cursor.rowcount

    async def delete(
        self,
        table_name: str,
        where_expr: str,
        token_id: str | None = None,
    ) -> int:
        """DELETE rows with parameterized WHERE (SQL-injection safe)."""
        conn = await self._ensure_connection()
        self._op_count += 1
        self._last_op_time = time.monotonic()

        clause, params = build_sqlite_where(where_expr)
        sql = f'DELETE FROM "{table_name}" WHERE {clause}'

        if self._is_async:
            cursor = await conn.execute(sql, params)
            return cursor.rowcount
        else:
            cursor = conn.execute(sql, params)
            return cursor.rowcount

    # ── Transaction Management (Linear Logic ⊸) ─────────────────

    async def begin_transaction(self) -> str:
        """Begin an IMMEDIATE transaction, issue a single-use token."""
        conn = await self._ensure_connection()
        token_id = uuid.uuid4().hex[:16]
        if self._is_async:
            await conn.execute("BEGIN IMMEDIATE")
        else:
            conn.execute("BEGIN IMMEDIATE")
        self._active_tokens[token_id] = False
        return token_id

    async def commit(self, token_id: str) -> None:
        """Commit and consume the linear token."""
        if token_id not in self._active_tokens:
            raise RuntimeError(
                f"Linear Logic violation: token '{token_id}' does not exist "
                f"or has already been consumed (no duplication, no weakening)"
            )
        conn = await self._ensure_connection()
        if self._is_async:
            await conn.execute("COMMIT")
        else:
            conn.execute("COMMIT")
        del self._active_tokens[token_id]

    async def rollback(self, token_id: str) -> None:
        """Rollback and consume the linear token."""
        if token_id not in self._active_tokens:
            raise RuntimeError(
                f"Linear Logic violation: token '{token_id}' does not exist "
                f"or has already been consumed"
            )
        conn = await self._ensure_connection()
        if self._is_async:
            await conn.execute("ROLLBACK")
        else:
            conn.execute("ROLLBACK")
        del self._active_tokens[token_id]

    # ── Schema Migration ─────────────────────────────────────────

    async def migrate(
        self,
        table_name: str,
        new_columns: list[dict[str, Any]],
    ) -> list[str]:
        """Add missing columns via ALTER TABLE ADD COLUMN.

        Returns list of column names that were added.
        """
        conn = await self._ensure_connection()

        if self._is_async:
            cursor = await conn.execute(f'PRAGMA table_info("{table_name}")')
            rows = await cursor.fetchall()
        else:
            cursor = conn.execute(f'PRAGMA table_info("{table_name}")')
            rows = cursor.fetchall()

        existing = {row[1] for row in rows}
        added: list[str] = []

        for col in new_columns:
            col_name = col["col_name"]
            if col_name not in existing:
                sql_type = _AXON_TO_SQL.get(col["col_type"], "TEXT")
                parts = [f'"{col_name}" {sql_type}']
                if col.get("not_null") and col.get("default_value"):
                    parts.append(f"NOT NULL DEFAULT {col['default_value']}")
                elif col.get("default_value"):
                    parts.append(f"DEFAULT {col['default_value']}")

                ddl = f'ALTER TABLE "{table_name}" ADD COLUMN {" ".join(parts)}'
                if self._is_async:
                    await conn.execute(ddl)
                else:
                    conn.execute(ddl)
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
        conn = await self._ensure_connection()
        unique_kw = "UNIQUE " if unique else ""
        cols = ", ".join(f'"{c}"' for c in columns)
        ddl = (
            f'CREATE {unique_kw}INDEX IF NOT EXISTS '
            f'"{index_name}" ON "{table_name}" ({cols})'
        )
        if self._is_async:
            await conn.execute(ddl)
        else:
            conn.execute(ddl)

    # ── Health Check ─────────────────────────────────────────────

    async def ping(self) -> bool:
        """Check if the database connection is alive."""
        try:
            conn = await self._ensure_connection()
            if self._is_async:
                cursor = await conn.execute("SELECT 1")
                await cursor.fetchone()
            else:
                conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    async def is_healthy(self) -> dict[str, Any]:
        """Return health status with operational metrics."""
        reachable = await self.ping()
        return {
            "healthy": reachable,
            "backend": "sqlite",
            "async": self._is_async,
            "connection": self._connection_str,
            "active_transactions": len(self._active_tokens),
            "total_operations": self._op_count,
            "error_count": self._error_count,
        }

    # ── Lifecycle ────────────────────────────────────────────────

    async def close(self) -> None:
        """Close the connection and release resources."""
        if self._conn is not None:
            if self._is_async:
                await self._conn.close()
            else:
                self._conn.close()
            self._conn = None
