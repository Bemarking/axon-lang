"""ORM for ``axon_control.cognitive_states``.

Tenant-scoped + RLS. Payload lives as envelope-encrypted bytes
(AES-256-GCM + wrapped DEK). Metadata fields are indexed for the
worker's eviction sweep + SAR exporter's subject filter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
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

from axon_enterprise.db.base import Base, TimestampMixin


class CognitiveStateSnapshot(TimestampMixin, Base):
    """One row per WebSocket session. Rewritten in place (UPDATE)
    during incremental snapshots; the on-disk envelope is new per
    write so each UPDATE gets a fresh DEK."""

    __tablename__ = "cognitive_states"

    state_id: Mapped[UUID] = mapped_column(
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
    session_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment=(
            "Stable session identifier issued by the WebSocket "
            "transport. One active snapshot per (tenant, session)."
        ),
    )
    flow_id: Mapped[str] = mapped_column(String(128), nullable=False)
    subject_user_id: Mapped[UUID | None] = mapped_column(nullable=True)

    # Envelope-encrypted bytes — the whole CognitiveState.encode()
    # output sealed with ``EnvelopeEncryption``.
    state_ciphertext: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False
    )

    # Surfaced for operator dashboards without decrypting. The
    # plaintext carries deeper structure; these fields stay within
    # what's safe to expose (schema version, byte size).
    state_format_version: Mapped[int] = mapped_column(
        nullable=False, server_default="1"
    )
    state_size_bytes: Mapped[int] = mapped_column(nullable=False)

    # TTL management — the worker's `evict_expired` query filters
    # on this index.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Last-rehydration timestamp, updated on every successful
    # :meth:`CognitiveStateService.restore`. Null until the first
    # reconnect.
    last_restored_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    restore_count: Mapped[int] = mapped_column(
        nullable=False, server_default="0"
    )

    # Free-form metadata consumed by the SAR exporter without
    # decrypting state_ciphertext.
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "session_id",
            name="uq_cognitive_states_tenant_id_session_id",
        ),
        Index(
            "ix_cognitive_states_tenant_id_subject_user_id",
            "tenant_id",
            "subject_user_id",
        ),
        Index(
            "ix_cognitive_states_tenant_id_flow_id",
            "tenant_id",
            "flow_id",
        ),
        Index(
            "ix_cognitive_states_tenant_id_expires_at",
            "tenant_id",
            "expires_at",
        ),
    )
