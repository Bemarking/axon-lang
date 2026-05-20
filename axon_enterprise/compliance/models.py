"""ORM for ``axon_control.compliance_requests`` + ``legal_holds``.

Design notes
------------
- ``compliance_requests`` is a single table for both SAR exports and
  erasure requests. A ``kind`` column discriminates the two; the
  payload JSONB column carries kind-specific knobs (``reason`` for
  erasure, ``scope`` for SAR).
- Worker dispatch uses ``FOR UPDATE SKIP LOCKED`` against
  ``status='queued'`` rows. The migration creates a partial index
  on ``(status, scheduled_for)`` so the worker's claim query is
  O(log N) even with millions of historical requests.
- ``legal_holds`` blocks erasure of a specific subject. The
  erasure service consults this table before starting; an active
  hold raises ``LegalHoldActive``.
- Both tables are tenant-scoped + RLS-protected. The Admin API
  connects as ``axon_admin`` for cross-tenant evidence bundles.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from axon_enterprise.db.base import Base, TimestampMixin


class ComplianceRequestKind(StrEnum):
    SAR_EXPORT = "sar_export"
    ERASURE = "erasure"


class ComplianceRequestStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    # Erasure-specific intermediate: soft-delete applied, waiting on
    # the reversion window before anonymizing.
    AWAITING_PURGE = "awaiting_purge"


class ComplianceRequest(TimestampMixin, Base):
    """One row per export / erasure request filed against a tenant."""

    __tablename__ = "compliance_requests"

    request_id: Mapped[UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "axon_admin.tenants.tenant_id",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        server_default=ComplianceRequestStatus.QUEUED.value,
    )

    subject_email: Mapped[str] = mapped_column(Text, nullable=False)
    subject_user_id: Mapped[UUID | None] = mapped_column(nullable=True)

    requested_by: Mapped[UUID | None] = mapped_column(nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Scheduling / worker claim
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claimed_by: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Hostname/pod id of the worker currently executing this job.",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Result artefacts
    artefact_uri: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment=(
            "URI of the resulting bundle (SAR export) or purge report. "
            "Shape is backend-dependent: ``s3://bucket/key`` or ``file://path``."
        ),
    )
    artefact_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    artefact_size_bytes: Mapped[int | None] = mapped_column(nullable=True)

    # Kind-specific knobs (scope filters, reason metadata, etc.)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "ix_compliance_requests_status_scheduled_for",
            "status",
            "scheduled_for",
            postgresql_where=(
                "status IN ('queued', 'awaiting_purge')"
            ),
        ),
        Index(
            "ix_compliance_requests_tenant_id_created_at",
            "tenant_id",
            "created_at",
        ),
        Index(
            "ix_compliance_requests_subject_email",
            "tenant_id",
            "subject_email",
        ),
    )


class LegalHold(TimestampMixin, Base):
    """Blocks erasure of a specific subject until released.

    One active hold per (tenant_id, subject_email). A subject can
    have historical holds (released) alongside the active one — the
    table is a full log, not a flag.
    """

    __tablename__ = "legal_holds"

    hold_id: Mapped[UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "axon_admin.tenants.tenant_id",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    subject_email: Mapped[str] = mapped_column(Text, nullable=False)
    subject_user_id: Mapped[UUID | None] = mapped_column(nullable=True)

    matter: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Human-readable litigation / investigation identifier.",
    )
    applied_by: Mapped[UUID | None] = mapped_column(nullable=True)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    released_by: Mapped[UUID | None] = mapped_column(nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    released_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # At most one active hold per subject per tenant. Partial
        # unique index — released holds do not block new ones.
        Index(
            "uq_legal_holds_tenant_id_subject_email_active",
            "tenant_id",
            "subject_email",
            unique=True,
            postgresql_where="released_at IS NULL",
        ),
        UniqueConstraint(
            "hold_id", name="uq_legal_holds_hold_id"
        ),
    )
