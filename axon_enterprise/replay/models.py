"""ORM for ``axon_control.replay_tokens``.

Tenant-scoped + RLS-protected. Every row anchors to exactly one
``audit_events`` row so divergences + replays are themselves
auditable (``compliance:replay_*`` event types).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from axon_enterprise.db.base import Base, TimestampMixin


class ReplayTokenRecord(TimestampMixin, Base):
    """One replay receipt — immutable once inserted."""

    __tablename__ = "replay_tokens"

    token_id: Mapped[UUID] = mapped_column(
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
    flow_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
        comment=(
            "Opaque flow-execution identifier supplied by the "
            "recorder. Nullable because some one-shot effects are "
            "invoked outside a flow scope."
        ),
    )

    effect_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment=(
            "Canonical identifier, e.g. 'call_tool:send_slack', "
            "'llm_infer:claude-opus-4-7', 'db_read:customers'."
        ),
    )
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)

    # Canonical hashes — the load-bearing cryptographic evidence.
    inputs_hash_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    outputs_hash_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hash_hex: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    nonce_hex: Mapped[str] = mapped_column(String(32), nullable=False)

    # Structured originals — retained for replay executors that need
    # the full input/output to re-invoke. Sampling parameters live
    # in their own column so indexing on e.g. `(seed, model)` stays
    # cheap for audit queries like "every replay of model X with
    # seed Y".
    inputs: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    outputs: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    sampling: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # The legal-basis attached to this emission. ``NULL`` for effects
    # that are not ``@sensitive`` (e.g. a purely internal call that
    # doesn't touch regulated data). The slug matches the closed
    # catalogue in `axon.compiler.legal_basis.LEGAL_BASIS_CATALOG`.
    legal_basis: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )

    # Anchor — every token links to the audit-chain event that
    # recorded its emission. NULL only for bootstrap scenarios; the
    # service layer always fills this in production.
    audit_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "axon_control.audit_events.event_id",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        nullable=True,
    )

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_replay_tokens_tenant_id_flow_id_recorded_at",
            "tenant_id",
            "flow_id",
            "recorded_at",
        ),
        Index(
            "ix_replay_tokens_tenant_id_effect_name_recorded_at",
            "tenant_id",
            "effect_name",
            "recorded_at",
        ),
        Index(
            "ix_replay_tokens_tenant_id_legal_basis",
            "tenant_id",
            "legal_basis",
        ),
    )
