"""ComplianceService — high-level façade used by HTTP + CLI.

Composes TicketService + SarExporter + ErasureService +
EvidenceBundleService + LegalHoldService so callers file one
module-level import and get the full surface. The worker runs
the same pieces independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.audit.events import AuditEventType
from axon_enterprise.audit.service import AuditService, AuditWriteRequest
from axon_enterprise.compliance.blob_store import BlobStore
from axon_enterprise.compliance.erasure import ErasureService
from axon_enterprise.compliance.evidence import EvidenceBundleService
from axon_enterprise.compliance.legal_holds import LegalHoldService
from axon_enterprise.compliance.models import ComplianceRequestKind
from axon_enterprise.compliance.s3_blob_store import build_blob_store
from axon_enterprise.compliance.tickets import TicketIssued, TicketService

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.compliance.service"
)


@dataclass
class ComplianceService:
    """Unified API for portal handlers + CLI subcommands."""

    tickets: TicketService
    exporter_blob: BlobStore
    erasure: ErasureService
    evidence: EvidenceBundleService
    legal_holds: LegalHoldService
    audit: AuditService

    @classmethod
    def default(cls) -> ComplianceService:
        blob = build_blob_store()
        return cls(
            tickets=TicketService.default(),
            exporter_blob=blob,
            erasure=ErasureService.default(blob),
            evidence=EvidenceBundleService.default(blob),
            legal_holds=LegalHoldService.default(),
            audit=AuditService(),
        )

    # ── SAR Export ────────────────────────────────────────────────────

    async def file_export(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        subject_email: str,
        requested_by: UUID | None = None,
    ) -> TicketIssued:
        ticket = await self.tickets.issue(
            db,
            tenant_id=tenant_id,
            kind=ComplianceRequestKind.SAR_EXPORT,
            subject_email=subject_email,
            requested_by=requested_by,
        )
        await self.audit.record(
            db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=AuditEventType.COMPLIANCE_EXPORT_REQUESTED,
                resource_type="user",
                resource_id=subject_email.strip().lower(),
                action="export_request",
                actor_user_id=requested_by,
                details={"request_id": str(ticket.request_id)},
            ),
        )
        return ticket

    # ── Erasure ───────────────────────────────────────────────────────

    async def file_erasure(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        subject_email: str,
        reason: str | None,
        requested_by: UUID | None = None,
    ) -> TicketIssued:
        # Early legal-hold check so callers get an immediate reject.
        await self.erasure.assert_no_legal_hold(
            db, tenant_id=tenant_id, subject_email=subject_email
        )
        ticket = await self.tickets.issue(
            db,
            tenant_id=tenant_id,
            kind=ComplianceRequestKind.ERASURE,
            subject_email=subject_email,
            requested_by=requested_by,
            reason=reason,
        )
        await self.audit.record(
            db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=AuditEventType.COMPLIANCE_ERASURE_REQUESTED,
                resource_type="user",
                resource_id=subject_email.strip().lower(),
                action="erasure_request",
                actor_user_id=requested_by,
                details={
                    "request_id": str(ticket.request_id),
                    "reason": reason,
                },
            ),
        )
        return ticket

    # ── Evidence bundle ──────────────────────────────────────────────

    async def generate_evidence_bundle(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        period_start: datetime,
        period_end: datetime,
        requested_by: UUID | None = None,
    ):
        return await self.evidence.generate(
            db,
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
            requested_by=requested_by,
        )
