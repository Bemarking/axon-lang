"""ORM models for JWT signing keys + the revocation list.

``axon_control.jwt_signing_keys``
    Tracks every signing key the issuer has seen. Exactly one row
    is ``active`` at any moment (the one ``JwtIssuer`` signs with).
    ``grace`` rows remain valid for verification during the overlap
    window so tokens minted just before rotation keep working.
    ``retired`` rows are kept for audit — never removed by migrations.

    Global table (no RLS): signing keys are the control plane's, not
    any one tenant's. Read freely to build the JWKS response.

``axon_control.jwt_revoked_jtis``
    A row per revoked ``jti`` with an ``expires_at`` mirroring the
    token's ``exp``. Rows are pruned by a cron job once their
    expiry is in the past — attempting to reuse an expired token
    already fails signature-level expiry checks, so blacklisting
    past that point is wasted space.

    Also global (no RLS): a revoked token is revoked cross-tenant.
    The Redis backend is cross-tenant too; the Postgres fallback
    exists for durability when Redis is not deployed (10.i).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from axon_enterprise.db.base import Base, TimestampMixin


class SigningKeyStatus(StrEnum):
    ACTIVE = "active"     # currently used by JwtIssuer to sign
    GRACE = "grace"       # only valid for verification, never signs
    RETIRED = "retired"   # historical; never returned in JWKS


class JwtSigningKey(TimestampMixin, Base):
    """Track-record of a key the issuer has ever used."""

    __tablename__ = "jwt_signing_keys"

    signing_key_id: Mapped[UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    kid: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    algorithm: Mapped[str] = mapped_column(String(16), nullable=False)

    # Where the private key material lives.
    backend: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="'kms' or 'local'",
    )
    # KMS: ARN or alias. Local: identifier for operator log; the
    # actual key is NEVER stored in the DB.
    key_material_ref: Mapped[str] = mapped_column(Text, nullable=False)

    public_key_pem: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="PEM-encoded public key; used to build JWKS responses.",
    )

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=SigningKeyStatus.ACTIVE.value,
        index=True,
    )

    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    grace_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("kid", name="uq_jwt_signing_keys_kid"),
        Index("ix_jwt_signing_keys_status", "status"),
    )


class JwtRevokedJti(Base):
    """Token-level revocation. Persistent fallback for Redis."""

    __tablename__ = "jwt_revoked_jtis"

    jti: Mapped[UUID] = mapped_column(primary_key=True)
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        Index("ix_jwt_revoked_jtis_expires_at", "expires_at"),
    )
