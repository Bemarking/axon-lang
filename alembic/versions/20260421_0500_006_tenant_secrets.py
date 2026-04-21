"""tenant_secrets metadata table

Stores only metadata. Values live in AWS Secrets Manager under
``axon/tenants/{tenant_id}/{key}`` — Postgres never sees plaintext.

Full ``tenant_isolation + admin_bypass`` RLS is applied: tenant A's
secrets are invisible to a session scoped to tenant B even via a
crafted SELECT. The admin_bypass policy lets the Admin API (10.j)
and reconciliation jobs see every row.

Revision ID: 006
Revises: 005
Create Date: 2026-04-21 05:00:00+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from axon_enterprise.db.rls_policies import full_policy_set_sql

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_secrets",
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey(
                "public.tenants.tenant_id",
                ondelete="RESTRICT",
                onupdate="CASCADE",
                name="fk_tenant_secrets_tenant_id_tenants",
            ),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("key", sa.String(128), primary_key=True, nullable=False),
        sa.Column("backend", sa.String(16), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("storage_arn", sa.Text(), nullable=True),
        sa.Column("current_version", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "deleted_pending_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "axon_control.users.user_id",
                ondelete="SET NULL",
                onupdate="CASCADE",
                name="fk_tenant_secrets_created_by_users",
            ),
            nullable=True,
        ),
        sa.Column(
            "last_rotated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "axon_control.users.user_id",
                ondelete="SET NULL",
                onupdate="CASCADE",
                name="fk_tenant_secrets_last_rotated_by_users",
            ),
            nullable=True,
        ),
        sa.Column(
            "last_rotated_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "last_accessed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "accessed_count",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
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
            "status IN ('active','deleted_pending','deleted')",
            name="ck_tenant_secrets_status",
        ),
        sa.CheckConstraint(
            "backend IN ('aws_sm','memory')",
            name="ck_tenant_secrets_backend",
        ),
        schema="axon_control",
    )
    op.create_index(
        "ix_tenant_secrets_tenant_id_status",
        "tenant_secrets",
        ["tenant_id", "status"],
        schema="axon_control",
    )
    for stmt in full_policy_set_sql(
        table="tenant_secrets", schema="axon_control"
    ):
        op.execute(stmt)


def downgrade() -> None:
    op.drop_table("tenant_secrets", schema="axon_control")
