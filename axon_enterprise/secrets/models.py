"""ORM for ``axon_control.tenant_secrets`` — metadata only.

Persisted metadata
------------------
    tenant_id + key     composite PK
    backend             'aws_sm' | 'memory'
    storage_path        full backend path (axon/tenants/<tid>/<key>)
    storage_arn         ARN from the backend (nullable for mem)
    current_version     opaque version id of the AWSCURRENT secret
    description         operator-supplied human-readable note
    status              'active' | 'deleted_pending' | 'deleted'
    created_by          UUID of the user who originally created it
    last_rotated_by     nullable UUID of the last rotator
    last_accessed_at    updated on every successful read
    accessed_count      monotonically increasing counter

    Values NEVER land in this table. Only metadata.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from axon_enterprise.db.base import Base, TimestampMixin


class SecretStatus(StrEnum):
    ACTIVE = "active"
    DELETED_PENDING = "deleted_pending"  # soft-delete; recovery window still open
    DELETED = "deleted"                   # recovery window past, unrecoverable


class TenantSecret(TimestampMixin, Base):
    """Metadata row — one per ``(tenant_id, key)``.

    Does NOT use ``TenantScopedMixin`` because ``tenant_id`` is part
    of the composite primary key (same pattern as ``TenantMembership``
    and ``SsoAssertionSeen``).
    """

    __tablename__ = "tenant_secrets"

    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "public.tenants.tenant_id",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        primary_key=True,
        nullable=False,
    )
    key: Mapped[str] = mapped_column(
        String(128), primary_key=True, nullable=False
    )

    backend: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    storage_arn: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_version: Mapped[str] = mapped_column(String(128), nullable=False)

    description: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=SecretStatus.ACTIVE.value
    )
    deleted_pending_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "axon_control.users.user_id",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        nullable=True,
    )
    last_rotated_by: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "axon_control.users.user_id",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        nullable=True,
    )
    last_rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accessed_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )

    __table_args__ = (
        Index(
            "ix_tenant_secrets_tenant_id_status",
            "tenant_id",
            "status",
        ),
    )
