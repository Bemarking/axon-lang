"""TicketService — file + query + claim compliance requests.

Split from the executor logic (``exporter`` / ``erasure``) so the
HTTP handlers can enqueue a ticket without pulling executor deps.
The worker is the only caller of ``claim`` + ``complete`` + ``fail``.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import NamedTuple
from uuid import UUID, uuid4

import structlog
from sqlalchemy import desc, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.compliance.errors import (
    ComplianceRequestInvalidState,
    ComplianceRequestNotFound,
)
from axon_enterprise.compliance.models import (
    ComplianceRequest,
    ComplianceRequestKind,
    ComplianceRequestStatus,
)

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.compliance.tickets"
)


class TicketIssued(NamedTuple):
    """Returned from ``issue`` — minimal surface for HTTP echoes."""

    request_id: UUID
    scheduled_for: datetime


@dataclass
class TicketService:
    """Issue + worker claim + status queries for compliance requests."""

    worker_id: str = ""

    @classmethod
    def default(cls) -> TicketService:
        return cls(worker_id=platform.node() or "worker")

    # ── Enqueue (HTTP / CLI caller) ───────────────────────────────────

    async def issue(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        kind: ComplianceRequestKind,
        subject_email: str,
        requested_by: UUID | None = None,
        subject_user_id: UUID | None = None,
        reason: str | None = None,
        scheduled_for: datetime | None = None,
        details: dict | None = None,
    ) -> TicketIssued:
        row = ComplianceRequest(
            request_id=uuid4(),
            tenant_id=tenant_id,
            kind=kind.value,
            status=ComplianceRequestStatus.QUEUED.value,
            subject_email=subject_email.strip().lower(),
            subject_user_id=subject_user_id,
            requested_by=requested_by,
            reason=reason,
            scheduled_for=scheduled_for or datetime.now(timezone.utc),
            details=details or {},
        )
        db.add(row)
        await db.flush()
        _logger.info(
            "compliance_ticket_issued",
            request_id=str(row.request_id),
            kind=kind.value,
            tenant_id=tenant_id,
        )
        return TicketIssued(
            request_id=row.request_id,
            scheduled_for=row.scheduled_for,
        )

    # ── Worker claim ──────────────────────────────────────────────────

    async def claim_next(
        self,
        db: AsyncSession,
        *,
        kinds: tuple[ComplianceRequestKind, ...] | None = None,
    ) -> ComplianceRequest | None:
        """Pick one QUEUED request whose ``scheduled_for`` is in the past.

        Uses ``FOR UPDATE SKIP LOCKED`` so N workers running in
        parallel never collide on the same row. Returns ``None``
        when the queue is empty (caller sleeps + retries).
        """
        kind_filter = ""
        params: dict[str, object] = {
            "now": datetime.now(timezone.utc),
            "queued": ComplianceRequestStatus.QUEUED.value,
            "in_progress": ComplianceRequestStatus.IN_PROGRESS.value,
            "worker_id": self.worker_id or "worker",
        }
        if kinds:
            placeholders = ",".join(f":k{i}" for i in range(len(kinds)))
            kind_filter = f"AND kind IN ({placeholders})"
            for i, k in enumerate(kinds):
                params[f"k{i}"] = k.value

        sql = f"""
            WITH claimed AS (
                SELECT request_id
                FROM axon_control.compliance_requests
                WHERE status = :queued
                  AND scheduled_for <= :now
                  {kind_filter}
                ORDER BY scheduled_for ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE axon_control.compliance_requests r
            SET status = :in_progress,
                claimed_at = :now,
                claimed_by = :worker_id
            FROM claimed
            WHERE r.request_id = claimed.request_id
            RETURNING r.request_id
        """
        result = await db.execute(text(sql), params)
        claimed_id = result.scalar_one_or_none()
        if claimed_id is None:
            return None
        await db.flush()
        row = await db.get(ComplianceRequest, claimed_id)
        assert row is not None
        return row

    # ── Worker completion ─────────────────────────────────────────────

    async def complete(
        self,
        db: AsyncSession,
        *,
        request_id: UUID,
        artefact_uri: str | None = None,
        artefact_sha256: str | None = None,
        artefact_size_bytes: int | None = None,
        new_status: ComplianceRequestStatus = ComplianceRequestStatus.COMPLETED,
        details_patch: dict | None = None,
    ) -> None:
        row = await db.get(ComplianceRequest, request_id)
        if row is None:
            raise ComplianceRequestNotFound(str(request_id))
        if row.status not in {
            ComplianceRequestStatus.IN_PROGRESS.value,
            ComplianceRequestStatus.AWAITING_PURGE.value,
        }:
            raise ComplianceRequestInvalidState(
                f"request {request_id} is {row.status}, cannot complete"
            )
        row.status = new_status.value
        row.completed_at = datetime.now(timezone.utc)
        if artefact_uri is not None:
            row.artefact_uri = artefact_uri
            row.artefact_sha256 = artefact_sha256
            row.artefact_size_bytes = artefact_size_bytes
        if details_patch:
            merged = dict(row.details or {})
            merged.update(details_patch)
            row.details = merged
        await db.flush()
        _logger.info(
            "compliance_ticket_completed",
            request_id=str(request_id),
            status=new_status.value,
        )

    async def fail(
        self,
        db: AsyncSession,
        *,
        request_id: UUID,
        error_message: str,
    ) -> None:
        await db.execute(
            update(ComplianceRequest)
            .where(ComplianceRequest.request_id == request_id)
            .values(
                status=ComplianceRequestStatus.FAILED.value,
                completed_at=datetime.now(timezone.utc),
                error_message=error_message,
            )
        )
        await db.flush()
        _logger.warning(
            "compliance_ticket_failed",
            request_id=str(request_id),
            error=error_message,
        )

    async def reschedule(
        self,
        db: AsyncSession,
        *,
        request_id: UUID,
        scheduled_for: datetime,
        new_status: ComplianceRequestStatus = ComplianceRequestStatus.AWAITING_PURGE,
    ) -> None:
        """Parks a ticket until ``scheduled_for``; used by erasure soft-delete
        to wait out the reversion window."""
        await db.execute(
            update(ComplianceRequest)
            .where(ComplianceRequest.request_id == request_id)
            .values(
                status=new_status.value,
                scheduled_for=scheduled_for,
                claimed_at=None,
                claimed_by=None,
            )
        )
        await db.flush()

    # ── Queries (portal / CLI) ────────────────────────────────────────

    async def get(
        self, db: AsyncSession, *, request_id: UUID, tenant_id: str
    ) -> ComplianceRequest:
        row = await db.scalar(
            select(ComplianceRequest).where(
                ComplianceRequest.request_id == request_id,
                ComplianceRequest.tenant_id == tenant_id,
            )
        )
        if row is None:
            raise ComplianceRequestNotFound(str(request_id))
        return row

    async def list_for_tenant(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        limit: int = 100,
    ) -> list[ComplianceRequest]:
        res = await db.execute(
            select(ComplianceRequest)
            .where(ComplianceRequest.tenant_id == tenant_id)
            .order_by(desc(ComplianceRequest.created_at))
            .limit(limit)
        )
        return list(res.scalars())

    async def awaiting_purge_due(
        self, db: AsyncSession, *, now: datetime | None = None
    ) -> list[ComplianceRequest]:
        """Erasure tickets whose soft-delete window has elapsed."""
        cutoff = now or datetime.now(timezone.utc)
        res = await db.execute(
            select(ComplianceRequest).where(
                ComplianceRequest.status
                == ComplianceRequestStatus.AWAITING_PURGE.value,
                ComplianceRequest.scheduled_for <= cutoff,
            )
        )
        return list(res.scalars())
