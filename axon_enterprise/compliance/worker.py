"""ComplianceWorker — polls compliance_requests, dispatches executors.

Single-process loop intended to run as its own Kubernetes Deployment
(``axon-enterprise compliance run-worker``). Steps per tick:

    1. ``SELECT ... FOR UPDATE SKIP LOCKED`` the next QUEUED request.
    2. Dispatch on ``kind``:
         - sar_export → SarExporter.export → complete ticket
         - erasure    → if QUEUED:  ErasureService.soft_delete
                                     + park in awaiting_purge
                        if AWAITING_PURGE + due: anonymize + complete
    3. Sleep ``worker_poll_interval_seconds``.

Every step is wrapped in a try/except that writes ``fail`` on the
ticket if anything raises, so a crashing request never blocks the
queue. Workers identify themselves via hostname so duplicate
claims (rare — SKIP LOCKED should prevent this) surface in audit.
"""

from __future__ import annotations

import asyncio
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.audit.events import AuditEventType
from axon_enterprise.audit.service import AuditService, AuditWriteRequest
from axon_enterprise.compliance.blob_store import BlobStore
from axon_enterprise.compliance.erasure import ErasureService
from axon_enterprise.compliance.errors import LegalHoldActive
from axon_enterprise.compliance.exporter import SarExporter
from axon_enterprise.compliance.models import (
    ComplianceRequest,
    ComplianceRequestKind,
    ComplianceRequestStatus,
)
from axon_enterprise.compliance.s3_blob_store import build_blob_store
from axon_enterprise.compliance.tickets import TicketService
from axon_enterprise.config import ComplianceSettings, get_settings
from axon_enterprise.db.session import admin_session

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.compliance.worker"
)


@dataclass
class ComplianceWorker:
    """Runnable polling loop."""

    tickets: TicketService
    exporter: SarExporter
    erasure: ErasureService
    audit: AuditService
    settings: ComplianceSettings
    blob: BlobStore

    @classmethod
    def default(cls) -> ComplianceWorker:
        blob = build_blob_store()
        return cls(
            tickets=TicketService(worker_id=platform.node() or "worker"),
            exporter=SarExporter.default(blob),
            erasure=ErasureService.default(blob),
            audit=AuditService(),
            settings=get_settings().compliance,
            blob=blob,
        )

    async def run_forever(self, *, stop: asyncio.Event | None = None) -> None:
        _logger.info(
            "compliance_worker_started",
            worker_id=self.tickets.worker_id,
            poll_interval_s=self.settings.worker_poll_interval_seconds,
        )
        while stop is None or not stop.is_set():
            processed = await self.run_once()
            if not processed:
                try:
                    await asyncio.wait_for(
                        (stop or asyncio.Event()).wait(),
                        timeout=self.settings.worker_poll_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass

    async def run_once(self) -> bool:
        """One pass of the loop; returns True if it did work."""
        async with admin_session() as db:
            row = await self.tickets.claim_next(db)
            if row is None:
                return False
            try:
                await self._dispatch(db, row)
            except LegalHoldActive as exc:
                await self.tickets.complete(
                    db,
                    request_id=row.request_id,
                    new_status=ComplianceRequestStatus.CANCELLED,
                    details_patch={"cancelled_reason": str(exc)},
                )
                await self.audit.record(
                    db,
                    AuditWriteRequest(
                        tenant_id=row.tenant_id,
                        event_type=AuditEventType.COMPLIANCE_ERASURE_FAILED,
                        resource_type="user",
                        resource_id=row.subject_email,
                        action="erasure_blocked_by_hold",
                        status="denied",
                        details={"request_id": str(row.request_id)},
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                _logger.exception(
                    "compliance_worker_job_failed",
                    request_id=str(row.request_id),
                    kind=row.kind,
                )
                await self.tickets.fail(
                    db,
                    request_id=row.request_id,
                    error_message=f"{type(exc).__name__}: {exc}",
                )
                await self.audit.record(
                    db,
                    AuditWriteRequest(
                        tenant_id=row.tenant_id,
                        event_type=_failure_event(row.kind),
                        resource_type="user",
                        resource_id=row.subject_email,
                        action="worker_failure",
                        status="failure",
                        details={
                            "request_id": str(row.request_id),
                            "error": str(exc),
                        },
                    ),
                )
            return True

    # ── Dispatch ──────────────────────────────────────────────────────

    async def _dispatch(
        self, db: AsyncSession, row: ComplianceRequest
    ) -> None:
        if row.kind == ComplianceRequestKind.SAR_EXPORT.value:
            result = await self.exporter.export(
                db,
                tenant_id=row.tenant_id,
                subject_email=row.subject_email,
                subject_user_id=row.subject_user_id,
                request_id=row.request_id,
            )
            await self.tickets.complete(
                db,
                request_id=row.request_id,
                artefact_uri=result.uri,
                artefact_sha256=result.sha256_hex,
                artefact_size_bytes=result.size_bytes,
                new_status=ComplianceRequestStatus.COMPLETED,
            )
            await self.audit.record(
                db,
                AuditWriteRequest(
                    tenant_id=row.tenant_id,
                    event_type=AuditEventType.COMPLIANCE_EXPORT_COMPLETED,
                    resource_type="user",
                    resource_id=row.subject_email,
                    action="export_completed",
                    details={
                        "request_id": str(row.request_id),
                        "bundle_uri": result.uri,
                        "bundle_sha256": result.sha256_hex,
                    },
                ),
            )
            return

        if row.kind == ComplianceRequestKind.ERASURE.value:
            # details.soft_deleted_at is the stage discriminator:
            # absent → run soft_delete, present → run anonymize.
            if "soft_deleted_at" in (row.details or {}):
                await self._run_anonymize(db, row)
            else:
                await self._run_soft_delete(db, row)
            return

        raise ValueError(f"unknown ticket kind {row.kind!r}")

    async def _run_soft_delete(
        self, db: AsyncSession, row: ComplianceRequest
    ) -> None:
        soft = await self.erasure.soft_delete(
            db,
            tenant_id=row.tenant_id,
            subject_email=row.subject_email,
            requested_by=row.requested_by,
            request_id=row.request_id,
        )
        details_patch = {
            "soft_deleted_at": datetime.now(timezone.utc).isoformat(),
            "sessions_revoked": soft.sessions_revoked,
            "api_keys_revoked": soft.api_keys_revoked,
            "subject_user_id": str(soft.user_id) if soft.user_id else None,
        }
        # Merge + park — the ticket goes to AWAITING_PURGE and will be
        # picked up by ``awaiting_purge_due`` after the window.
        merged = dict(row.details or {})
        merged.update(details_patch)
        row.details = merged
        await self.tickets.reschedule(
            db,
            request_id=row.request_id,
            scheduled_for=soft.scheduled_anonymize_at,
            new_status=ComplianceRequestStatus.AWAITING_PURGE,
        )

    async def _run_anonymize(
        self, db: AsyncSession, row: ComplianceRequest
    ) -> None:
        result = await self.erasure.anonymize(
            db,
            tenant_id=row.tenant_id,
            subject_email=row.subject_email,
            request_id=row.request_id,
            requested_by=row.requested_by,
        )
        await self.tickets.complete(
            db,
            request_id=row.request_id,
            artefact_uri=result.uri,
            artefact_sha256=result.sha256_hex,
            artefact_size_bytes=result.size_bytes,
            new_status=ComplianceRequestStatus.COMPLETED,
        )

    # ── Purge stage ticker ───────────────────────────────────────────

    async def promote_due_purges(self) -> int:
        """Flip AWAITING_PURGE rows whose window elapsed → QUEUED.

        Called periodically from the same loop so anonymize jobs
        get re-claimed by the standard ``claim_next`` path.
        """
        async with admin_session() as db:
            due = await self.tickets.awaiting_purge_due(db)
            for row in due:
                await self.tickets.reschedule(
                    db,
                    request_id=row.request_id,
                    scheduled_for=datetime.now(timezone.utc),
                    new_status=ComplianceRequestStatus.QUEUED,
                )
            return len(due)


def _failure_event(kind: str) -> AuditEventType:
    if kind == ComplianceRequestKind.SAR_EXPORT.value:
        return AuditEventType.COMPLIANCE_EXPORT_FAILED
    return AuditEventType.COMPLIANCE_ERASURE_FAILED
