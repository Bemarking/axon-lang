"""§Fase 29.e — In-memory recent-diagnostics store.

D4 + D8 + D9 ratificadas 2026-05-12.

## What this module ships

A per-process, per-tenant ring buffer of recently-emitted parser
diagnostics, fed by the 29.c telemetry sink and consumed by the
29.e HTTP endpoint `/api/v1/tenant/diagnostics/recent`.

The store is the **in-tree foundation** for the diagnostic
dashboard surface. Production deployments swap with a DB-backed
implementation in v1.15.x without changing the public API; the
:class:`RecentDiagnosticsStore` protocol surface stays stable.

## D-letter trace

- **D4 ratificada** — entries carry only structural fields
  (file path + line/col + error code + vertical + severity +
  timestamp). NO source text in any record.
- **D8 ratificada** — every record is keyed on `tenant_id`;
  retrieval is per-tenant by construction. Cross-tenant
  read paths simply do not exist in this API.
- **D9 ratificada** — generic tenants never reach the store
  (telemetry-disabled per D9 default in 29.b); the store stays
  empty for them.

## Privacy boundary baked into the type

The :class:`DiagnosticRecord` dataclass mirrors the 29.c
:class:`ParserDiagnostic` field set + tenant + vertical + timestamp.
**No source text field exists.** Adding one breaks the D4 audit and
the failing test in `test_fase29_dashboard_endpoint.py`.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque

# ──────────────────────────────────────────────────────────────────
#  Record shape (D4 privacy boundary baked into the type)
# ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DiagnosticRecord:
    """One captured diagnostic ready for dashboard retrieval.

    **D4 boundary**: this dataclass exposes no `source` / `snippet` /
    `content` / `text` / `body` field. The 29.c
    :class:`ParserDiagnostic` doesn't carry one either, so the
    privacy guarantee transits from emit-time to retrieval-time
    without any sink translation that could leak text.
    """

    tenant_id: str
    vertical: str
    code: str
    file_path: str
    line: int
    column: int
    severity: str
    timestamp: datetime


# ──────────────────────────────────────────────────────────────────
#  Aggregated view (group by file + code + line-bucket)
# ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AggregatedDiagnostic:
    """Aggregated view: how many times was this (file, code, line-bucket)
    triple hit recently? Surfaced via the HTTP endpoint as the
    grouped response shape.

    `line_bucket` is the floor-to-10s grouping: lines 1-10 → 0,
    11-20 → 10, etc. Adopter dashboards can drill from a bucket to
    the underlying source via repo access controls (D4 — server
    surface NEVER returns source text).
    """

    file_path: str
    code: str
    line_bucket: int
    vertical: str
    count: int
    first_seen: datetime
    last_seen: datetime


# ──────────────────────────────────────────────────────────────────
#  Store
# ──────────────────────────────────────────────────────────────────


class RecentDiagnosticsStore:
    """Per-tenant ring buffer of :class:`DiagnosticRecord` instances.

    Process-local; production deployments wrap with a DB-backed
    implementation. The public API is:

    - :meth:`record` — append one diagnostic.
    - :meth:`recent_for_tenant` — fetch raw records since a cursor.
    - :meth:`aggregated_for_tenant` — fetch grouped/counted records.
    - :meth:`clear` / :meth:`clear_tenant` — used by tests.

    Per-tenant bound on memory: `capacity_per_tenant` records each
    (default 500). Older records evicted FIFO when the bound is hit.
    The total per-process memory scales with tenants × capacity.
    """

    def __init__(self, capacity_per_tenant: int = 500) -> None:
        self._capacity = capacity_per_tenant
        # Per-tenant deque keyed by tenant_id. Defaultdict simplifies
        # the "first record for a tenant" path; cleanup happens on
        # explicit clear/clear_tenant rather than per-record TTL
        # (TTL is a DB-backed concern, not in-memory bootstrap).
        self._buffers: dict[str, Deque[DiagnosticRecord]] = defaultdict(
            lambda: deque(maxlen=capacity_per_tenant)
        )
        self._lock = threading.RLock()

    def record(self, record: DiagnosticRecord) -> None:
        """Append a record. Bounded by `capacity_per_tenant` per tenant.
        Thread-safe.
        """
        with self._lock:
            self._buffers[record.tenant_id].append(record)

    def recent_for_tenant(
        self,
        tenant_id: str,
        *,
        since: datetime | None = None,
        limit: int = 50,
        file_path: str | None = None,
        code: str | None = None,
    ) -> list[DiagnosticRecord]:
        """Return raw records for `tenant_id`, optionally filtered.

        Returns newest-first; `limit` clamps the result size.
        `since`: only records with `timestamp > since` are returned
        (strict — used as the pagination cursor).
        `file_path` / `code`: optional equality filters.
        """
        limit = max(1, min(limit, self._capacity))
        with self._lock:
            buf = self._buffers.get(tenant_id)
            if buf is None:
                return []
            # Snapshot under lock; iterate outside.
            snapshot = list(buf)

        # Filter + order newest-first. Records appended in time order;
        # walking the snapshot from the right gives newest-first.
        out: list[DiagnosticRecord] = []
        for rec in reversed(snapshot):
            if since is not None and rec.timestamp <= since:
                continue
            if file_path is not None and rec.file_path != file_path:
                continue
            if code is not None and rec.code != code:
                continue
            out.append(rec)
            if len(out) >= limit:
                break
        return out

    def aggregated_for_tenant(
        self,
        tenant_id: str,
        *,
        since: datetime | None = None,
        limit: int = 50,
        bucket_size: int = 10,
    ) -> list[AggregatedDiagnostic]:
        """Return aggregated view grouped by (file_path, code, line-bucket).

        `bucket_size`: line numbers are floored to this multiple
        (default 10 → lines 1-10 → bucket 0, 11-20 → bucket 10, etc.).
        Results sorted by `count` descending, then `last_seen`
        descending.
        """
        if bucket_size < 1:
            bucket_size = 1
        records = self.recent_for_tenant(
            tenant_id,
            since=since,
            limit=self._capacity,  # aggregation pulls everything, then groups
        )
        groups: dict[tuple[str, str, int, str], list[DiagnosticRecord]] = defaultdict(list)
        for rec in records:
            line_bucket = (rec.line // bucket_size) * bucket_size
            key = (rec.file_path, rec.code, line_bucket, rec.vertical)
            groups[key].append(rec)

        aggregated: list[AggregatedDiagnostic] = []
        for (file_path, code, line_bucket, vertical), recs in groups.items():
            timestamps = [r.timestamp for r in recs]
            aggregated.append(
                AggregatedDiagnostic(
                    file_path=file_path,
                    code=code,
                    line_bucket=line_bucket,
                    vertical=vertical,
                    count=len(recs),
                    first_seen=min(timestamps),
                    last_seen=max(timestamps),
                )
            )
        aggregated.sort(key=lambda a: (a.count, a.last_seen), reverse=True)
        return aggregated[:limit]

    def clear_tenant(self, tenant_id: str) -> None:
        """Drop every record for `tenant_id`. Used by tests + by the
        Fase 32.g audit "tenant deletion" cascade.
        """
        with self._lock:
            self._buffers.pop(tenant_id, None)

    def clear(self) -> None:
        """Drop every record across every tenant. Tests only."""
        with self._lock:
            self._buffers.clear()

    def tenant_count(self) -> int:
        """Number of tenants with at least one stored record."""
        with self._lock:
            return sum(1 for buf in self._buffers.values() if buf)


# ──────────────────────────────────────────────────────────────────
#  Module-level default store (swap in production)
# ──────────────────────────────────────────────────────────────────


_DEFAULT_STORE = RecentDiagnosticsStore()


def get_default_store() -> RecentDiagnosticsStore:
    """Return the process-default :class:`RecentDiagnosticsStore`.

    The 29.c telemetry sink writes to this store on every emit (when
    the resolved policy has `telemetry_enabled=True`); the 29.e HTTP
    endpoint reads from it.
    """
    return _DEFAULT_STORE


def set_default_store(store: RecentDiagnosticsStore) -> None:
    """Swap the default store. Used by integration tests + by
    production deployments to install a DB-backed implementation.
    """
    global _DEFAULT_STORE
    _DEFAULT_STORE = store


# ──────────────────────────────────────────────────────────────────
#  Adapter: 29.c InMemoryAuditSink-compatible writer
# ──────────────────────────────────────────────────────────────────


class StoreBackedAuditSink:
    """29.c :class:`AuditSink` Protocol implementation that writes to a
    :class:`RecentDiagnosticsStore`.

    Plug this into :func:`axon_enterprise.diagnostics.set_audit_sink` so
    every parser-error emission feeds the dashboard store
    automatically.
    """

    def __init__(self, store: RecentDiagnosticsStore | None = None) -> None:
        self._store = store or _DEFAULT_STORE

    def write_parser_error(
        self,
        *,
        tenant_id: str,
        vertical: str,
        code: str,
        file_path: str,
        line: int,
        column: int,
        severity: str,
    ) -> None:
        # D4 baked in at the protocol level: no source-text parameter.
        record = DiagnosticRecord(
            tenant_id=tenant_id,
            vertical=vertical,
            code=code,
            file_path=file_path,
            line=line,
            column=column,
            severity=severity,
            timestamp=datetime.now(timezone.utc),
        )
        self._store.record(record)


__all__ = [
    "AggregatedDiagnostic",
    "DiagnosticRecord",
    "RecentDiagnosticsStore",
    "StoreBackedAuditSink",
    "get_default_store",
    "set_default_store",
]
