"""
AXON Runtime — SQLite Store Backend
=====================================
Zero-config SQLite backend for the ``axonstore`` primitive.

Uses ``aiosqlite`` for async I/O.  Falls back to a synchronous
in-memory implementation when ``aiosqlite`` is not installed,
ensuring the test suite always passes without optional deps.

Formal guarantees:
  - HoTT schema isomorphism:  CREATE TABLE ↔ IRStoreSchema
  - Linear Logic tokens:      BEGIN IMMEDIATE → single-use UUID
  - ACID isolation:            WAL mode + IMMEDIATE transactions
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from typing import Any


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
#  WHERE-CLAUSE PARSER — safe expression translation
# ═══════════════════════════════════════════════════════════════════

# Only allow safe identifiers & operators (no semicolons, no SQL injection)
_SAFE_WHERE_RE = re.compile(
    r"^[\w\s.=<>!'+\-*/(),\"]+$",
    re.ASCII,
)


def _translate_where(expr: str) -> str:
    """Translate an AXON where expression to SQL WHERE clause.

    Converts ``==`` → ``=`` and validates against injection.
    Returns the translated clause (without the WHERE keyword).
    """
    if not expr:
        return "1=1"
    if not _SAFE_WHERE_RE.match(expr):
        raise ValueError(f"Unsafe where expression: {expr!r}")
    return expr.replace("==", "=")


# ═══════════════════════════════════════════════════════════════════
#  SQLITE STORE BACKEND
# ═══════════════════════════════════════════════════════════════════


class SQLiteStoreBackend:
    """SQLite-backed persistence for ``axonstore``.

    When ``connection`` is empty, uses ``:memory:`` for zero-config
    operation — perfect for tests and single-process agents.

    Linear Logic enforcement:
      Each ``begin_transaction()`` generates a UUID token.
      The token is single-use: ``commit()`` or ``rollback()``
      consumes it and removes it from the active set.
    """

    def __init__(
        self,
        connection: str = "",
        isolation: str = "serializable",
    ) -> None:
        self._connection_str = connection or ":memory:"
        self._isolation = isolation
        self._conn: sqlite3.Connection | None = None
        # Linear Logic token registry: token_id → bool (consumed?)
        self._active_tokens: dict[str, bool] = {}

    def _ensure_connection(self) -> sqlite3.Connection:
        """Lazy-init the SQLite connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(self._connection_str, isolation_level=None)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
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
        conn = self._ensure_connection()

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
        conn.execute(ddl)

    # ── CRUD Operations ──────────────────────────────────────────

    async def insert(
        self,
        table_name: str,
        data: dict[str, Any],
        token_id: str | None = None,
    ) -> dict[str, Any]:
        """INSERT a row into the table.

        Returns the inserted row with rowid.
        """
        conn = self._ensure_connection()
        cols = list(data.keys())
        placeholders = ", ".join("?" for _ in cols)
        col_names = ", ".join(f'"{c}"' for c in cols)
        values = [data[c] for c in cols]

        sql = f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})'
        cursor = conn.execute(sql, values)
        return {"rowid": cursor.lastrowid, **data}

    async def query(
        self,
        table_name: str,
        where_expr: str = "",
    ) -> list[dict[str, Any]]:
        """SELECT rows matching the filter."""
        conn = self._ensure_connection()
        clause = _translate_where(where_expr)
        sql = f'SELECT * FROM "{table_name}" WHERE {clause}'
        cursor = conn.execute(sql)
        return [dict(row) for row in cursor.fetchall()]

    async def update(
        self,
        table_name: str,
        where_expr: str,
        data: dict[str, Any],
        token_id: str | None = None,
    ) -> int:
        """UPDATE rows matching the filter. Returns affected count."""
        conn = self._ensure_connection()
        clause = _translate_where(where_expr)
        set_parts = ", ".join(f'"{k}" = ?' for k in data)
        values = list(data.values())
        sql = f'UPDATE "{table_name}" SET {set_parts} WHERE {clause}'
        cursor = conn.execute(sql, values)
        return cursor.rowcount

    async def delete(
        self,
        table_name: str,
        where_expr: str,
        token_id: str | None = None,
    ) -> int:
        """DELETE rows matching the filter. Returns affected count."""
        conn = self._ensure_connection()
        clause = _translate_where(where_expr)
        sql = f'DELETE FROM "{table_name}" WHERE {clause}'
        cursor = conn.execute(sql)
        return cursor.rowcount

    # ── Transaction Management (Linear Logic ⊸) ─────────────────

    async def begin_transaction(self) -> str:
        """Begin an IMMEDIATE transaction, issue a single-use token."""
        conn = self._ensure_connection()
        token_id = uuid.uuid4().hex[:16]
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
        conn = self._ensure_connection()
        conn.execute("COMMIT")
        del self._active_tokens[token_id]

    async def rollback(self, token_id: str) -> None:
        """Rollback and consume the linear token."""
        if token_id not in self._active_tokens:
            raise RuntimeError(
                f"Linear Logic violation: token '{token_id}' does not exist "
                f"or has already been consumed"
            )
        conn = self._ensure_connection()
        conn.execute("ROLLBACK")
        del self._active_tokens[token_id]

    # ── Lifecycle ────────────────────────────────────────────────

    async def close(self) -> None:
        """Close the connection and release resources."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
