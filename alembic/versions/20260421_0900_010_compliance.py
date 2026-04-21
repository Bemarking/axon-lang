"""compliance — requests table, legal holds, tenants.data_region

Adds the persistence for Fase 10.l:

- ``axon_control.compliance_requests`` — unified queue for SAR and
  erasure tickets consumed by ``ComplianceWorker`` via
  ``FOR UPDATE SKIP LOCKED``.
- ``axon_control.legal_holds`` — blocks erasure on a subject
  during litigation; partial unique index enforces at most one
  ACTIVE hold per (tenant_id, subject_email).
- ``public.tenants.data_region`` — column consumed by
  ``DataResidencyMiddleware`` to 308-redirect mis-routed requests.

Revision ID: 010
Revises: 009
Create Date: 2026-04-21 09:00:00+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from axon_enterprise.db.rls_policies import full_policy_set_sql

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── tenants.data_region ──────────────────────────────────────────
    # Added to Rust-owned public.tenants. We guard with IF NOT EXISTS
    # so the migration survives a situation where the Rust side has
    # already added the column (Fase 10.m multi-region deploy).
    op.execute(
        "ALTER TABLE public.tenants "
        "ADD COLUMN IF NOT EXISTS data_region TEXT NOT NULL DEFAULT 'us-east-1'"
    )
    op.execute(
        "COMMENT ON COLUMN public.tenants.data_region IS "
        "'Region slug consumed by DataResidencyMiddleware to enforce "
        "GDPR/CCPA data-residency requirements.'"
    )

    # ── compliance_requests ──────────────────────────────────────────
    op.create_table(
        "compliance_requests",
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey(
                "public.tenants.tenant_id",
                ondelete="RESTRICT",
                onupdate="CASCADE",
                name="fk_compliance_requests_tenant_id_tenants",
            ),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column(
            "status",
            sa.String(24),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("subject_email", sa.Text(), nullable=False),
        sa.Column(
            "subject_user_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "requested_by", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "scheduled_for",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "claimed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("claimed_by", sa.String(64), nullable=True),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("artefact_uri", sa.Text(), nullable=True),
        sa.Column("artefact_sha256", sa.String(64), nullable=True),
        sa.Column("artefact_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "kind IN ('sar_export', 'erasure')",
            name="ck_compliance_requests_kind",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'in_progress', 'completed', "
            "'failed', 'cancelled', 'awaiting_purge')",
            name="ck_compliance_requests_status",
        ),
        schema="axon_control",
    )
    op.create_index(
        "ix_compliance_requests_tenant_id",
        "compliance_requests",
        ["tenant_id"],
        schema="axon_control",
    )
    op.create_index(
        "ix_compliance_requests_tenant_id_created_at",
        "compliance_requests",
        ["tenant_id", "created_at"],
        schema="axon_control",
    )
    op.create_index(
        "ix_compliance_requests_subject_email",
        "compliance_requests",
        ["tenant_id", "subject_email"],
        schema="axon_control",
    )
    # Partial index that makes ``SKIP LOCKED`` claim fast regardless
    # of how many historical rows we accumulate.
    op.execute(
        "CREATE INDEX ix_compliance_requests_status_scheduled_for "
        "ON axon_control.compliance_requests (status, scheduled_for) "
        "WHERE status IN ('queued', 'awaiting_purge')"
    )

    for stmt in full_policy_set_sql(
        table="compliance_requests", schema="axon_control"
    ):
        op.execute(stmt)

    # ── legal_holds ──────────────────────────────────────────────────
    op.create_table(
        "legal_holds",
        sa.Column(
            "hold_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey(
                "public.tenants.tenant_id",
                ondelete="RESTRICT",
                onupdate="CASCADE",
                name="fk_legal_holds_tenant_id_tenants",
            ),
            nullable=False,
        ),
        sa.Column("subject_email", sa.Text(), nullable=False),
        sa.Column(
            "subject_user_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("matter", sa.Text(), nullable=False),
        sa.Column(
            "applied_by", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "released_by", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "released_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("released_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="axon_control",
    )
    op.create_index(
        "ix_legal_holds_tenant_id",
        "legal_holds",
        ["tenant_id"],
        schema="axon_control",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_legal_holds_tenant_id_subject_email_active "
        "ON axon_control.legal_holds (tenant_id, subject_email) "
        "WHERE released_at IS NULL"
    )
    for stmt in full_policy_set_sql(
        table="legal_holds", schema="axon_control"
    ):
        op.execute(stmt)


def downgrade() -> None:
    op.drop_table("legal_holds", schema="axon_control")
    op.drop_table("compliance_requests", schema="axon_control")
    op.execute(
        "ALTER TABLE public.tenants DROP COLUMN IF EXISTS data_region"
    )
