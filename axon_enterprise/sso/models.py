"""ORM models for the SSO subsystem.

Tables
------
``axon_control.sso_configurations`` — tenant-scoped. One row per
    (tenant, provider_type) with the IdP configuration envelope-
    encrypted at rest. The AAD binds the ciphertext to the tenant_id
    and a constant ``purpose="sso_config"`` so a ciphertext from
    tenant A cannot be silently reused for tenant B.

``axon_control.sso_states`` — tenant-scoped. A short-lived row per
    in-flight SSO request: carries the ``state`` + ``nonce`` +
    ``code_verifier`` (for PKCE) that the callback handler will match
    against the IdP response. Consumed on first successful exchange
    (``consumed_at`` set) — any subsequent hit with the same state is
    treated as a replay attempt.

``axon_control.sso_assertion_seen`` — tenant-scoped. SAML assertion
    ID cache. Rows expire after 48h — inside a replay window well
    past the longest reasonable SAML session issue.

All three tables carry full RLS (tenant_isolation + admin_bypass).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from axon_enterprise.db.base import Base, TenantScopedMixin, TimestampMixin

if TYPE_CHECKING:  # pragma: no cover
    pass


class SsoProviderType(StrEnum):
    OIDC = "oidc"
    SAML = "saml"


# ── sso_configurations ───────────────────────────────────────────────


class SsoConfiguration(TenantScopedMixin, TimestampMixin, Base):
    """Tenant-scoped IdP configuration. One per (tenant, provider_type)."""

    __tablename__ = "sso_configurations"

    sso_config_id: Mapped[UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    provider_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    # Envelope-encrypted JSON blob — IdP-specific fields (client_id,
    # client_secret for OIDC; idp_url, certificate, private_key for
    # SAML). Shape validated by provider-specific config parsers.
    config_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    # Non-sensitive attribute mapping: IdP claim → Axon user field.
    # e.g. {"email": "preferred_email", "display_name": "name"}
    attribute_map: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Optional role mapping for groups/claims → Axon role names.
    # e.g. {"okta-engineers": "developer", "okta-leadership": "admin"}
    role_map: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    auto_provision: Mapped[bool] = mapped_column(
        nullable=False, server_default="false"
    )
    default_role_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "axon_control.roles.role_id",
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        nullable=True,
    )

    enabled: Mapped[bool] = mapped_column(
        nullable=False, server_default="true"
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider_type",
            name="uq_sso_configurations_tenant_id_provider_type",
        ),
        Index(
            "ix_sso_configurations_tenant_id_created_at",
            "tenant_id",
            "created_at",
        ),
    )


# ── sso_states ───────────────────────────────────────────────────────


class SsoState(TenantScopedMixin, Base):
    """Short-lived record tying a login request to its callback.

    Carries every value the callback handler must match against the
    IdP response:

        - ``state``:         URL-safe random token shared with the IdP
        - ``nonce``:         embedded in OIDC auth URL, validated in
                             ID token
        - ``code_verifier``: raw PKCE secret (only the hashed form is
                             sent to the IdP)
        - ``return_url``:    where to redirect the user after success

    A row is inserted at ``initiate()`` and consumed at ``complete()``.
    Presenting the same state twice hits ``consumed_at`` and raises
    ``SsoStateAlreadyConsumed`` — replay defence.
    """

    __tablename__ = "sso_states"

    state_id: Mapped[UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    provider_type: Mapped[str] = mapped_column(String(16), nullable=False)

    # High-entropy opaque tokens (>= 32 bytes of randomness encoded)
    state: Mapped[str] = mapped_column(String(128), nullable=False)
    nonce: Mapped[str | None] = mapped_column(String(128), nullable=True)
    code_verifier: Mapped[str | None] = mapped_column(String(128), nullable=True)

    return_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    issuer: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "state", name="uq_sso_states_tenant_id_state"),
        Index(
            "ix_sso_states_tenant_id_created_at",
            "tenant_id",
            "created_at",
        ),
        Index("ix_sso_states_expires_at", "expires_at"),
    )


# ── sso_assertion_seen (SAML replay defence) ────────────────────────


class SsoAssertionSeen(Base):
    """Record that a SAML assertion ID has been processed.

    Inserting a row with a duplicate ``(tenant_id, assertion_id)``
    fails the UNIQUE constraint → handler maps to ``SamlAssertionReplay``.

    A background cleanup job removes rows whose ``created_at`` is
    older than the replay window (default 48h).

    Does NOT inherit ``TenantScopedMixin`` because ``tenant_id`` is
    part of the composite primary key; redeclaring a mapped column
    from a mixin is awkward in SQLAlchemy 2. FK + index semantics
    are reproduced inline (same pattern as ``TenantMembership`` in
    10.b).
    """

    __tablename__ = "sso_assertion_seen"

    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "public.tenants.tenant_id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        primary_key=True,
        nullable=False,
    )
    assertion_id: Mapped[str] = mapped_column(
        String(256),
        primary_key=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index(
            "ix_sso_assertion_seen_created_at",
            "created_at",
        ),
    )
