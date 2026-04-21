"""ORM for ``axon_control.audit_events``.

Append-only at the DB level — triggers raise ``SQLSTATE 42501`` on
any UPDATE or DELETE. The ORM does not expose update helpers; the
Alembic migration 007 is where retention / purge logic would land
if ever needed (it is not, by policy).

Hash chain columns (``prev_hash``, ``event_hash``) are ``BYTEA``, not
TEXT. Base64 encoding happens only at the read boundary when a
human / SIEM consumer needs it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from axon_enterprise.db.base import Base


class AuditEvent(Base):
    """A single audit log entry. Immutable once inserted."""

    __tablename__ = "audit_events"

    event_id: Mapped[UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "public.tenants.tenant_id",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)

    actor_user_id: Mapped[UUID | None] = mapped_column(nullable=True)
    actor_email: Mapped[str | None] = mapped_column(Text, nullable=True)

    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    action: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="success"
    )

    # Stored as plain TEXT (not INET) so Postgres does not canonicalise
    # the representation — the hash recomputation on verify must see
    # byte-identical input.
    ip_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Hash chain
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    event_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Optional ESK provenance_chain stitch.
    esk_stitch: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "sequence_number",
            name="uq_audit_events_tenant_id_sequence_number",
        ),
        Index(
            "ix_audit_events_tenant_id_created_at",
            "tenant_id",
            "created_at",
        ),
        Index(
            "ix_audit_events_tenant_id_event_type_created_at",
            "tenant_id",
            "event_type",
            "created_at",
        ),
        Index(
            "ix_audit_events_actor_user_id",
            "actor_user_id",
        ),
    )
