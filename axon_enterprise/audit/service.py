"""AuditService — append events + read history + verify the chain.

Writer concurrency
------------------
Per-tenant audit writes serialise via
``pg_advisory_xact_lock(hashtext(tenant_id))``. The lock auto-releases
at transaction end. Reads are never blocked. Cross-tenant writers
interleave freely because each tenant hashes to a different advisory
key space.

The writer computes:

    seq       = max(sequence_number) + 1 for the tenant, 1 if none
    prev_hash = event_hash of the predecessor, or genesis_hash(tenant)
    event_hash = compute_event_hash(prev_hash, tenant, seq, type, payload)

Reader
------
Queries return events as ORM rows plus helper methods to decode
hashes as base64 for SIEM export. Tenant scoping is enforced by
callers passing ``tenant_id`` explicitly; admin_session bypasses
RLS for cross-tenant compliance exports.

Verifier
--------
``verify_chain(db, tenant_id)`` walks the entire per-tenant chain,
recomputes every ``event_hash``, and asserts ``prev_hash``
continuity. Returns an ``AuditChainReport`` — caller decides whether
a divergence is a 500 (runtime glitch) or a pager-worthy incident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, NamedTuple
from uuid import UUID

import structlog
from sqlalchemy import desc, select, text
from sqlalchemy.exc import IntegrityError as SAIntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.audit.canonical import (
    compute_event_hash,
    genesis_hash,
)
from axon_enterprise.audit.errors import (
    AuditChainBroken,
    AuditEventMalformed,
    AuditSequenceConflict,
)
from axon_enterprise.audit.events import AuditEventType
from axon_enterprise.audit.models import AuditEvent

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.audit.service"
)


# ── Request / response ───────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AuditWriteRequest:
    """What callers pass to ``AuditService.record``.

    Keep this narrow — required fields are mandatory, optional fields
    carry sensible defaults so services don't have to remember every
    column.
    """

    tenant_id: str
    event_type: AuditEventType
    resource_type: str
    action: str
    actor_user_id: UUID | None = None
    actor_email: str | None = None
    resource_id: str | None = None
    status: str = "success"
    ip_address: str | None = None
    user_agent: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    esk_stitch: bytes | None = None


class WrittenAuditEvent(NamedTuple):
    """Return value of ``record``. Exposes enough for callers to quote
    the event_id + hash in their response / log."""

    event_id: UUID
    sequence_number: int
    event_hash: bytes
    prev_hash: bytes
    created_at: datetime


# ── Chain verification ──────────────────────────────────────────────


@dataclass(frozen=True)
class AuditChainReport:
    """Outcome of ``verify_chain``."""

    tenant_id: str
    checked: int
    broken_at: int | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.broken_at is None


# ── Service ─────────────────────────────────────────────────────────


@dataclass
class AuditService:
    """Canonical writer + reader + verifier for audit events."""

    @classmethod
    def default(cls) -> AuditService:
        return cls()

    # ── Writer ─────────────────────────────────────────────────────────

    async def record(
        self, db: AsyncSession, request: AuditWriteRequest
    ) -> WrittenAuditEvent:
        """Append one event to the tenant's chain."""
        _validate_request(request)

        tenant_id = request.tenant_id
        # Serialise writers on the same tenant.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:t))"),
            {"t": tenant_id},
        )

        last = await db.scalar(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == tenant_id)
            .order_by(desc(AuditEvent.sequence_number))
            .limit(1)
        )
        if last is None:
            seq = 1
            prev_hash = genesis_hash(tenant_id)
        else:
            seq = last.sequence_number + 1
            prev_hash = last.event_hash

        payload = _payload_for_hash(request)
        ev_hash = compute_event_hash(
            prev_hash=prev_hash,
            tenant_id=tenant_id,
            sequence_number=seq,
            event_type=request.event_type.value,
            payload=payload,
        )

        row = AuditEvent(
            tenant_id=tenant_id,
            sequence_number=seq,
            event_type=request.event_type.value,
            actor_user_id=request.actor_user_id,
            actor_email=request.actor_email,
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            action=request.action,
            status=request.status,
            ip_address=request.ip_address,
            user_agent=request.user_agent,
            details=request.details,
            prev_hash=prev_hash,
            event_hash=ev_hash,
            esk_stitch=request.esk_stitch,
        )
        db.add(row)
        try:
            await db.flush()
        except SAIntegrityError as exc:
            # Unique (tenant_id, sequence_number) violation — another
            # writer beat us despite the advisory lock. Surface as a
            # typed error so operators pager on this specifically.
            raise AuditSequenceConflict(
                f"tenant={tenant_id} seq={seq}"
            ) from exc

        _logger.debug(
            "audit_event_written",
            tenant_id=tenant_id,
            event_id=str(row.event_id),
            event_type=row.event_type,
            sequence_number=seq,
        )
        return WrittenAuditEvent(
            event_id=row.event_id,
            sequence_number=seq,
            event_hash=ev_hash,
            prev_hash=prev_hash,
            created_at=row.created_at,
        )

    # ── Reader ─────────────────────────────────────────────────────────

    async def list_events(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        event_types: Iterable[AuditEventType] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Return events matching the filter, newest first."""
        stmt = select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
        if event_types:
            stmt = stmt.where(
                AuditEvent.event_type.in_([t.value for t in event_types])
            )
        if since is not None:
            stmt = stmt.where(AuditEvent.created_at >= since)
        if until is not None:
            stmt = stmt.where(AuditEvent.created_at <= until)
        stmt = stmt.order_by(desc(AuditEvent.sequence_number)).limit(limit)
        res = await db.execute(stmt)
        return list(res.scalars())

    # ── Verifier ──────────────────────────────────────────────────────

    async def verify_chain(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
    ) -> AuditChainReport:
        """Walk the tenant's chain and recompute every hash.

        Returns an ``AuditChainReport``. The verifier never raises on
        divergence — operators prefer a structured result they can
        pipe into dashboards + pager.
        """
        expected_prev = genesis_hash(tenant_id)
        expected_seq = 1

        stream = await db.execute(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == tenant_id)
            .order_by(AuditEvent.sequence_number.asc())
        )
        rows = list(stream.scalars())

        checked = 0
        for row in rows:
            if row.sequence_number != expected_seq:
                return AuditChainReport(
                    tenant_id=tenant_id,
                    checked=checked,
                    broken_at=row.sequence_number,
                    reason=(
                        f"expected sequence_number={expected_seq}, "
                        f"got {row.sequence_number}"
                    ),
                )
            if bytes(row.prev_hash) != expected_prev:
                return AuditChainReport(
                    tenant_id=tenant_id,
                    checked=checked,
                    broken_at=row.sequence_number,
                    reason="prev_hash does not match predecessor's event_hash",
                )
            recomputed = compute_event_hash(
                prev_hash=expected_prev,
                tenant_id=tenant_id,
                sequence_number=row.sequence_number,
                event_type=row.event_type,
                payload=_row_payload(row),
            )
            if recomputed != bytes(row.event_hash):
                return AuditChainReport(
                    tenant_id=tenant_id,
                    checked=checked,
                    broken_at=row.sequence_number,
                    reason="event_hash mismatch — event body tampered?",
                )
            expected_prev = bytes(row.event_hash)
            expected_seq += 1
            checked += 1

        return AuditChainReport(tenant_id=tenant_id, checked=checked)

    async def require_chain_healthy(
        self, db: AsyncSession, *, tenant_id: str
    ) -> None:
        """Raise ``AuditChainBroken`` on divergence. Convenience wrapper."""
        report = await self.verify_chain(db, tenant_id=tenant_id)
        if not report.ok:
            raise AuditChainBroken(
                tenant_id=report.tenant_id,
                sequence_number=report.broken_at or 0,
                reason=report.reason or "unknown",
            )


# ── Helpers ─────────────────────────────────────────────────────────


def _validate_request(req: AuditWriteRequest) -> None:
    """Cheap invariants that beat a trigger + hash recompute."""
    if not req.tenant_id:
        raise AuditEventMalformed("tenant_id is required")
    if not req.resource_type:
        raise AuditEventMalformed("resource_type is required")
    if not req.action:
        raise AuditEventMalformed("action is required")
    if req.status not in {"success", "failure", "denied"}:
        raise AuditEventMalformed(
            f"status must be success|failure|denied, got {req.status!r}"
        )


def _payload_for_hash(req: AuditWriteRequest) -> dict[str, Any]:
    """Subset of a request fed into the hash — matches ``_row_payload``."""
    return {
        "actor_user_id": req.actor_user_id,
        "actor_email": req.actor_email,
        "resource_type": req.resource_type,
        "resource_id": req.resource_id,
        "action": req.action,
        "status": req.status,
        "ip_address": req.ip_address,
        "user_agent": req.user_agent,
        "details": req.details,
    }


def _row_payload(row: AuditEvent) -> dict[str, Any]:
    """Reconstruct the payload dict for hash recomputation during verify."""
    return {
        "actor_user_id": row.actor_user_id,
        "actor_email": row.actor_email,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "action": row.action,
        "status": row.status,
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
        "details": dict(row.details),
    }
