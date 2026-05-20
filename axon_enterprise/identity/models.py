"""ORM models for the identity subsystem.

Tables
------

``axon_control.users`` — global. A single natural person can belong to
    several tenants; their login credentials live once on this row and
    the link to each tenant lives in ``tenant_memberships``. RLS is
    enabled and defaults to deny; access is mediated by the service
    layer which opens an ``admin_session()`` after verifying a
    membership under a ``tenant_session()``.

``axon_control.tenant_memberships`` — tenant-scoped. Associates a
    ``user_id`` with a ``tenant_id`` and records invitation / join
    state. Carries ``status`` and invitation token metadata so 10.k
    (self-service portal) can wire up the invite flow without
    re-shaping the schema.

``axon_control.sessions`` — tenant-scoped. One row per active refresh
    token. The stored ``refresh_token_hash`` is SHA-256 of the raw
    token; the token itself is only ever held in memory and sent to
    the client in the response body. Rotation replaces the hash on
    every refresh; the old session row is marked revoked.

Postgres features used
----------------------
- ``citext`` extension for case-insensitive email uniqueness.
- ``gen_random_uuid()`` (pgcrypto) for server-side ID generation.
- ``BYTEA`` for ciphertexts and hashes (never TEXT for non-UTF-8 bytes).
- ``INET`` for IP addresses (indexable, supports CIDR operators).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from axon_enterprise.db.base import Base, TenantScopedMixin, TimestampMixin

if TYPE_CHECKING:  # pragma: no cover
    pass


# ── Enums ──────────────────────────────────────────────────────────────


class UserStatus(StrEnum):
    ACTIVE = "active"
    LOCKED = "locked"            # permanent lock (admin must reactivate)
    SUSPENDED = "suspended"      # temporarily disabled (policy / payment)
    DELETED = "deleted"          # soft-deleted (GDPR erasure pending)


class MembershipStatus(StrEnum):
    INVITED = "invited"          # invite pending acceptance
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ERASED_PENDING = "erased_pending"  # soft-delete inside reversion window
    ERASED = "erased"                  # anonymized — PII irrevocably scrubbed


class SessionStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


# ── User (global) ──────────────────────────────────────────────────────


class User(TimestampMixin, Base):
    """A natural person. Globally unique by email."""

    __tablename__ = "users"

    user_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    email: Mapped[str] = mapped_column(
        CITEXT(),
        nullable=False,
        unique=True,
        index=True,
    )
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Credentials
    password_hash: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="NULL for SSO-only accounts.",
    )
    password_algo: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="argon2id",
    )
    password_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # TOTP
    totp_secret_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    totp_enabled: Mapped[bool] = mapped_column(
        nullable=False, server_default="false"
    )
    totp_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Email verification (flow lives in 10.k)
    email_verified: Mapped[bool] = mapped_column(
        nullable=False, server_default="false"
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Status + lockout
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=UserStatus.ACTIVE.value,
        index=True,
    )
    failed_logins: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_ip: Mapped[str | None] = mapped_column(INET, nullable=True)

    # Free-form for operator notes. NOT for tenant-scoped data.
    attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Relationships
    memberships: Mapped[list[TenantMembership]] = relationship(
        "TenantMembership",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="TenantMembership.user_id",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<User user_id={self.user_id} email={self.email} status={self.status}>"


# ── TenantMembership (tenant-scoped) ───────────────────────────────────


class TenantMembership(TimestampMixin, Base):
    """A user's link to a tenant. Role assignment comes in 10.c.

    Does NOT use ``TenantScopedMixin`` because ``tenant_id`` is part of
    the composite primary key here; redeclaring a mapped column from
    a mixin is awkward in SQLAlchemy 2. The FK and index semantics are
    reproduced inline.
    """

    __tablename__ = "tenant_memberships"

    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "axon_admin.tenants.tenant_id",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        primary_key=True,
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "axon_control.users.user_id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        primary_key=True,
    )

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=MembershipStatus.INVITED.value,
    )

    invited_by: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "axon_control.users.user_id",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        nullable=True,
    )
    invitation_token_hash: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    invitation_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(
        "User",
        back_populates="memberships",
        foreign_keys=[user_id],
    )

    # Composite PK: (tenant_id, user_id). Override mixin __table_args__.
    __table_args__ = (
        Index(
            "ix_tenant_memberships_tenant_id_created_at",
            "tenant_id",
            "created_at",
        ),
        # Index to find all tenants a user belongs to.
        Index("ix_tenant_memberships_user_id", "user_id"),
        Index(
            "ix_tenant_memberships_invitation_token_hash",
            "invitation_token_hash",
            unique=True,
            postgresql_where=(
                # Only non-null invitations need to be unique; joined
                # memberships have NULL and are allowed to collide.
                "invitation_token_hash IS NOT NULL"
            ),
        ),
    )


# ── Session (tenant-scoped) ────────────────────────────────────────────


class Session(TenantScopedMixin, Base):
    """Server-side refresh-token session."""

    __tablename__ = "sessions"

    session_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "axon_control.users.user_id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    refresh_token_hash: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False, unique=True, index=True
    )

    # Binding information for audit + anomaly detection.
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)

    # Lifecycle
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Rotation chain — points to the successor session when this one is
    # rotated away. Useful for forensics: "which session replaced which?"
    rotated_to_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "axon_control.sessions.session_id",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        nullable=True,
    )

    # Strictly monotonic event counter; useful for rate-limit ordering
    # and to detect replayed refresh attempts.
    sequence: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )

    __table_args__ = (
        Index(
            "ix_sessions_tenant_id_user_id_created_at",
            "tenant_id",
            "user_id",
            "created_at",
        ),
        UniqueConstraint(
            "refresh_token_hash", name="uq_sessions_refresh_token_hash"
        ),
    )
