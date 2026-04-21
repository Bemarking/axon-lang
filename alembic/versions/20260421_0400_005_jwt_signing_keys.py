"""jwt_signing_keys + jwt_revoked_jtis

Both tables are global (no RLS): signing keys are the control plane's
and a revoked token is revoked cross-tenant.

Revision ID: 005
Revises: 004
Create Date: 2026-04-21 04:00:00+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── jwt_signing_keys ──────────────────────────────────────────────
    op.create_table(
        "jwt_signing_keys",
        sa.Column(
            "signing_key_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("kid", sa.String(64), nullable=False),
        sa.Column("algorithm", sa.String(16), nullable=False),
        sa.Column(
            "backend",
            sa.String(16),
            nullable=False,
            comment="'kms' or 'local'",
        ),
        sa.Column("key_material_ref", sa.Text(), nullable=False),
        sa.Column("public_key_pem", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="active",
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('active','grace','retired')",
            name="ck_jwt_signing_keys_status",
        ),
        sa.CheckConstraint(
            "backend IN ('kms','local')",
            name="ck_jwt_signing_keys_backend",
        ),
        sa.UniqueConstraint("kid", name="uq_jwt_signing_keys_kid"),
        schema="axon_control",
    )
    op.create_index(
        "ix_jwt_signing_keys_status",
        "jwt_signing_keys",
        ["status"],
        schema="axon_control",
    )

    # Partial unique index: at most one row may be active at a time.
    # Enforces the "one active kid per deployment" invariant in the DB
    # so bugs in application code can't accidentally dual-sign.
    op.execute(
        "CREATE UNIQUE INDEX uq_jwt_signing_keys_one_active "
        "ON axon_control.jwt_signing_keys (status) "
        "WHERE status = 'active';"
    )

    # ── jwt_revoked_jtis ──────────────────────────────────────────────
    op.create_table(
        "jwt_revoked_jtis",
        sa.Column(
            "jti",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(128), nullable=True),
        schema="axon_control",
    )
    op.create_index(
        "ix_jwt_revoked_jtis_expires_at",
        "jwt_revoked_jtis",
        ["expires_at"],
        schema="axon_control",
    )


def downgrade() -> None:
    op.drop_table("jwt_revoked_jtis", schema="axon_control")
    op.execute(
        "DROP INDEX IF EXISTS axon_control.uq_jwt_signing_keys_one_active;"
    )
    op.drop_table("jwt_signing_keys", schema="axon_control")
