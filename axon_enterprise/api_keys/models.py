"""ORM for ``axon_control.tenant_api_keys``.

Tenant-scoped + RLS. ``key_hash`` is Argon2id of the raw
``axk_<uuid>`` key. ``key_prefix`` is the first 8 hex chars of the
uuid — indexed + used to narrow the verify-time lookup so we only
Argon2-verify against ONE row per request (constant-time within
that row).
"""

from __future__ import annotations

from datetime import datetime
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
from sqlalchemy.orm import Mapped, mapped_column

from axon_enterprise.db.base import Base, TimestampMixin


class TenantApiKey(TimestampMixin, Base):
    __tablename__ = "tenant_api_keys"

    api_key_id: Mapped[UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "public.tenants.tenant_id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)

    # First 8 hex chars of the raw uuid — used for the narrowed
    # verify-time SELECT. Indexed but NOT unique globally (tenants
    # share the hex space); unique per tenant so lookups stay O(1).
    key_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    hash_algo: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="argon2id"
    )

    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "axon_control.users.user_id",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        nullable=True,
    )

    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_ip: Mapped[str | None] = mapped_column(Text, nullable=True)

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "key_prefix",
            name="uq_tenant_api_keys_tenant_id_key_prefix",
        ),
        Index(
            "ix_tenant_api_keys_tenant_id_revoked_at",
            "tenant_id",
            "revoked_at",
        ),
    )
