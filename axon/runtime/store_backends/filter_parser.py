"""
AXON Runtime — Parameterized WHERE Filter Parser
==================================================
Converts AXON where-expression strings into parameterized SQL
to prevent SQL injection.  All user-supplied values are
separated from the SQL structure and passed as bind parameters.

Input:  ``"id = 1 AND name = 'Alice'"``

Output (SQLite):      ``('"id" = ? AND "name" = ?', [1, 'Alice'])``
Output (PostgreSQL):  ``('"id" = $1 AND "name" = $2', [1, 'Alice'])``

Security model:
  - Column names validated against ``[a-zA-Z_]\\w*``
  - Operators are whitelist-validated
  - Values are ALWAYS parameterized — never interpolated into SQL
  - No sub-queries, function calls, or raw SQL keywords in values
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# ═══════════════════════════════════════════════════════════════════
#  FILTER CONDITION
# ═══════════════════════════════════════════════════════════════════

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_]\w*$")

_VALID_OPS = frozenset({
    "=", "==", "!=", "<>", ">", ">=", "<", "<=", "LIKE", "like",
})

_OP_NORMALIZE: dict[str, str] = {
    "==": "=",
    "<>": "!=",
    "like": "LIKE",
}


@dataclass(frozen=True)
class FilterCondition:
    """A single ``column op value`` predicate."""
    column: str
    op: str        # normalized: =, !=, >, >=, <, <=, LIKE
    value: Any     # Python value (str, int, float, bool, None)


# ═══════════════════════════════════════════════════════════════════
#  TOKENIZER
# ═══════════════════════════════════════════════════════════════════


def _tokenize(expr: str) -> list[str]:
    """Tokenize a filter expression into tokens."""
    tokens: list[str] = []
    i, n = 0, len(expr)

    while i < n:
        c = expr[i]

        # Whitespace
        if c.isspace():
            i += 1
            continue

        # String literal
        if c in ("'", '"'):
            quote = c
            j = i + 1
            while j < n and expr[j] != quote:
                if expr[j] == "\\":
                    j += 1
                j += 1
            if j >= n:
                raise ValueError(f"Unterminated string literal at position {i}")
            tokens.append(expr[i : j + 1])
            i = j + 1
            continue

        # Multi-char operators: ==, !=, >=, <=, <>
        if c in (">", "<", "!", "="):
            if i + 1 < n and expr[i + 1] == "=":
                tokens.append(expr[i : i + 2])
                i += 2
            elif c == "<" and i + 1 < n and expr[i + 1] == ">":
                tokens.append("<>")
                i += 2
            else:
                tokens.append(c)
                i += 1
            continue

        # Numbers (including negatives and decimals)
        if c.isdigit() or (c == "-" and i + 1 < n and expr[i + 1].isdigit()):
            j = i
            if c == "-":
                j += 1
            while j < n and (expr[j].isdigit() or expr[j] == "."):
                j += 1
            tokens.append(expr[i:j])
            i = j
            continue

        # Identifiers / keywords (AND, OR, TRUE, column names, etc.)
        if c.isalpha() or c == "_":
            j = i
            while j < n and (expr[j].isalnum() or expr[j] == "_"):
                j += 1
            tokens.append(expr[i:j])
            i = j
            continue

        raise ValueError(f"Unexpected character in filter expression: {c!r}")

    return tokens


def _parse_value(token: str) -> Any:
    """Convert a token string to a typed Python value."""
    if not token:
        return token

    # String literal
    if len(token) >= 2 and token[0] in ("'", '"') and token[-1] == token[0]:
        return token[1:-1]

    # Boolean / null
    low = token.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "none"):
        return None

    # Integer
    try:
        return int(token)
    except ValueError:
        pass

    # Float
    try:
        return float(token)
    except ValueError:
        pass

    return token


# ═══════════════════════════════════════════════════════════════════
#  PARSER
# ═══════════════════════════════════════════════════════════════════


def parse_filter(
    expr: str,
) -> tuple[list[FilterCondition], list[str]]:
    """Parse a WHERE expression into conditions and connectors.

    Args:
        expr: Expression like ``"id = 1 AND name = 'Alice'"``

    Returns:
        ``(conditions, connectors)`` where ``connectors[i]``
        joins ``conditions[i]`` and ``conditions[i+1]``.

    Raises:
        ValueError: On syntax errors or unsafe column names.
    """
    if not expr or not expr.strip():
        return [], []

    tokens = _tokenize(expr.strip())
    if not tokens:
        return [], []

    conditions: list[FilterCondition] = []
    connectors: list[str] = []
    i, n = 0, len(tokens)

    while i < n:
        # — column —
        col = tokens[i]
        if not _IDENTIFIER_RE.match(col):
            raise ValueError(
                f"Expected column name (identifier), got: {col!r}. "
                f"Column names must match [a-zA-Z_][a-zA-Z0-9_]*"
            )
        i += 1

        # — operator —
        if i >= n:
            raise ValueError(f"Expected operator after column '{col}'")
        op_str = tokens[i]
        if op_str not in _VALID_OPS and op_str.upper() not in ("LIKE",):
            raise ValueError(
                f"Invalid operator: {op_str!r}. "
                f"Valid: {', '.join(sorted(_VALID_OPS))}"
            )
        op = _OP_NORMALIZE.get(op_str, op_str)
        i += 1

        # — value —
        if i >= n:
            raise ValueError(f"Expected value after '{col} {op_str}'")
        value = _parse_value(tokens[i])
        i += 1

        conditions.append(FilterCondition(column=col, op=op, value=value))

        # — AND / OR connector —
        if i < n:
            connector = tokens[i].upper()
            if connector in ("AND", "OR"):
                connectors.append(connector)
                i += 1

    return conditions, connectors


# ═══════════════════════════════════════════════════════════════════
#  SQL BUILDERS — Parameterized output
# ═══════════════════════════════════════════════════════════════════


def build_sqlite_where(expr: str) -> tuple[str, list[Any]]:
    """Convert filter expression → parameterized SQLite SQL.

    Returns:
        ``(sql_clause, params)``
        e.g. ``('"id" = ? AND "name" = ?', [1, 'Alice'])``

    Returns ``("1=1", [])`` for empty expressions.
    """
    if not expr or not expr.strip():
        return "1=1", []

    conditions, connectors = parse_filter(expr)
    if not conditions:
        return "1=1", []

    parts: list[str] = []
    params: list[Any] = []

    for i, cond in enumerate(conditions):
        if cond.value is None:
            if cond.op == "=":
                parts.append(f'"{cond.column}" IS NULL')
            elif cond.op == "!=":
                parts.append(f'"{cond.column}" IS NOT NULL')
            else:
                parts.append(f'"{cond.column}" {cond.op} NULL')
        else:
            parts.append(f'"{cond.column}" {cond.op} ?')
            params.append(cond.value)

        if i < len(connectors):
            parts.append(connectors[i])

    return " ".join(parts), params


def build_pg_where(
    expr: str,
    param_offset: int = 0,
) -> tuple[str, list[Any]]:
    """Convert filter expression → parameterized PostgreSQL SQL.

    Uses ``$1``, ``$2``, … placeholders.  ``param_offset`` shifts
    numbering when earlier parameters exist (e.g. UPDATE SET).

    Returns:
        ``(sql_clause, params)``
        e.g. ``('"id" = $1 AND "name" = $2', [1, 'Alice'])``

    Returns ``("TRUE", [])`` for empty expressions.
    """
    if not expr or not expr.strip():
        return "TRUE", []

    conditions, connectors = parse_filter(expr)
    if not conditions:
        return "TRUE", []

    parts: list[str] = []
    params: list[Any] = []
    idx = param_offset + 1

    for i, cond in enumerate(conditions):
        if cond.value is None:
            if cond.op == "=":
                parts.append(f'"{cond.column}" IS NULL')
            elif cond.op == "!=":
                parts.append(f'"{cond.column}" IS NOT NULL')
            else:
                parts.append(f'"{cond.column}" {cond.op} NULL')
        else:
            parts.append(f'"{cond.column}" {cond.op} ${idx}')
            params.append(cond.value)
            idx += 1

        if i < len(connectors):
            parts.append(connectors[i])

    return " ".join(parts), params
