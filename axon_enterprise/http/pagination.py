"""Pagination helpers — cursor-based for high-volume, offset for small.

Two shapes:

- ``CursorPage`` for tables where rows arrive faster than a UI can
  paginate — usage_events, audit_events. The cursor is the
  ``(created_at, id)`` pair of the last row; clients pass
  ``?cursor=<b64>`` to continue. Stable across inserts because the
  WHERE clause uses ``(created_at, id) < (cursor.created_at, cursor.id)``.

- ``OffsetPage`` for admin tables where total counts matter (users,
  roles, tenants) and the dataset fits in memory. Standard
  ``?limit=&offset=`` semantics.

Both return envelopes with a ``next`` field (None on last page)
and ``items`` the route handler populates.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

T = TypeVar("T")


# ── Cursor ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Cursor:
    """Encodes the last ``(timestamp, id)`` pair the client has seen."""

    last_created_at: datetime
    last_id: str

    def encode(self) -> str:
        payload = json.dumps(
            {
                "t": self.last_created_at.astimezone(timezone.utc).isoformat(),
                "i": self.last_id,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def parse_cursor(raw: str | None) -> Cursor | None:
    """Decode a base64url cursor or return ``None`` for the first page."""
    if not raw:
        return None
    pad = "=" * (-len(raw) % 4)
    try:
        decoded = base64.urlsafe_b64decode(raw + pad)
        obj = json.loads(decoded)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"invalid cursor: {exc}") from exc
    try:
        return Cursor(
            last_created_at=datetime.fromisoformat(obj["t"]),
            last_id=str(obj["i"]),
        )
    except (KeyError, ValueError) as exc:
        raise ValueError(f"malformed cursor payload: {exc}") from exc


@dataclass(slots=True)
class CursorPage(Generic[T]):
    """Cursor-based page envelope."""

    items: list[T] = field(default_factory=list)
    next: str | None = None

    def to_dict(self, item_serializer) -> dict[str, Any]:
        return {
            "items": [item_serializer(i) for i in self.items],
            "next": self.next,
        }


# ── Offset ─────────────────────────────────────────────────────────


@dataclass(slots=True)
class OffsetPage(Generic[T]):
    """Offset-based page envelope with a total count."""

    items: list[T] = field(default_factory=list)
    total: int = 0
    limit: int = 0
    offset: int = 0

    def to_dict(self, item_serializer) -> dict[str, Any]:
        return {
            "items": [item_serializer(i) for i in self.items],
            "total": self.total,
            "limit": self.limit,
            "offset": self.offset,
        }


# ── Query-string parser ───────────────────────────────────────────


def parse_pagination_params(
    query: dict[str, list[str]] | dict[str, str],
    *,
    default_limit: int = 50,
    max_limit: int = 500,
) -> tuple[int, int, str | None]:
    """Normalise ``limit``, ``offset``, ``cursor`` from a query-string mapping.

    Accepts either ``dict[str, str]`` (already unique-valued) or
    ``dict[str, list[str]]`` (starlette's parse_qs style).
    """
    def _first(key: str) -> str | None:
        v = query.get(key)
        if isinstance(v, list):
            return v[0] if v else None
        return v

    raw_limit = _first("limit")
    raw_offset = _first("offset")
    cursor = _first("cursor")

    try:
        limit = int(raw_limit) if raw_limit is not None else default_limit
    except ValueError as exc:
        raise ValueError(f"limit must be integer; got {raw_limit!r}") from exc
    if not 1 <= limit <= max_limit:
        raise ValueError(f"limit must be in [1, {max_limit}]; got {limit}")

    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except ValueError as exc:
        raise ValueError(f"offset must be integer; got {raw_offset!r}") from exc
    if offset < 0:
        raise ValueError(f"offset must be >= 0; got {offset}")

    return limit, offset, cursor
