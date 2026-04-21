"""LegalHoldService — apply / release holds that block erasure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.audit.events import AuditEventType
from axon_enterprise.audit.service import AuditService, AuditWriteRequest
from axon_enterprise.compliance.errors import ComplianceRequestNotFound
from axon_enterprise.compliance.models import LegalHold

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.compliance.legal_holds"
)


@dataclass
class LegalHoldService:
    """Thin CRUD layer; only meaningful operation is applying a hold."""

    audit: AuditService

    @classmethod
    def default(cls) -> LegalHoldService:
        return cls(audit=AuditService())

    async def apply(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        subject_email: str,
        matter: str,
        applied_by: UUID | None = None,
        subject_user_id: UUID | None = None,
    ) -> LegalHold:
        """Create a new active hold. Partial unique index prevents dupes."""
        subject_email = subject_email.strip().lower()
        row = LegalHold(
            hold_id=uuid4(),
            tenant_id=tenant_id,
            subject_email=subject_email,
            subject_user_id=subject_user_id,
            matter=matter,
            applied_by=applied_by,
        )
        db.add(row)
        await db.flush()

        await self.audit.record(
            db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=AuditEventType.COMPLIANCE_LEGAL_HOLD_APPLIED,
                resource_type="user",
                resource_id=subject_email,
                action="legal_hold_apply",
                actor_user_id=applied_by,
                details={"hold_id": str(row.hold_id), "matter": matter},
            ),
        )
        _logger.info(
            "compliance_legal_hold_applied",
            hold_id=str(row.hold_id),
            subject_email=subject_email,
            matter=matter,
        )
        return row

    async def release(
        self,
        db: AsyncSession,
        *,
        hold_id: UUID,
        released_by: UUID | None = None,
        reason: str | None = None,
    ) -> LegalHold:
        row = await db.get(LegalHold, hold_id)
        if row is None:
            raise ComplianceRequestNotFound(f"legal hold {hold_id}")
        if row.released_at is not None:
            return row  # idempotent
        row.released_at = datetime.now(timezone.utc)
        row.released_by = released_by
        row.released_reason = reason
        await db.flush()

        await self.audit.record(
            db,
            AuditWriteRequest(
                tenant_id=row.tenant_id,
                event_type=AuditEventType.COMPLIANCE_LEGAL_HOLD_RELEASED,
                resource_type="user",
                resource_id=row.subject_email,
                action="legal_hold_release",
                actor_user_id=released_by,
                details={
                    "hold_id": str(row.hold_id),
                    "reason": reason,
                },
            ),
        )
        return row

    async def list_active(
        self, db: AsyncSession, *, tenant_id: str
    ) -> list[LegalHold]:
        res = await db.execute(
            select(LegalHold).where(
                LegalHold.tenant_id == tenant_id,
                LegalHold.released_at.is_(None),
            )
        )
        return list(res.scalars())
