"""tenant_api_keys — M2M API keys with Argon2id at-rest storage

Adds the per-tenant API key table used by the self-service portal
(§Fase 10.k). The raw key only exists in-memory at creation time;
the row stores Argon2id(hash) + the first 8 hex chars as a fast
lookup prefix.

Revision ID: 009
Revises: 008
Create Date: 2026-04-21 08:00:00+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from axon_enterprise.db.rls_policies import full_policy_set_sql

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_api_keys",
        sa.Column(
            "api_key_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey(
                "public.tenants.tenant_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
                name="fk_tenant_api_keys_tenant_id_tenants",
            ),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_prefix", sa.String(8), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column(
            "hash_algo",
            sa.String(16),
            nullable=False,
            server_default="argon2id",
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "axon_control.users.user_id",
                ondelete="SET NULL",
                onupdate="CASCADE",
                name="fk_tenant_api_keys_created_by_users",
            ),
            nullable=True,
        ),
        sa.Column(
            "last_used_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("last_used_ip", sa.Text(), nullable=True),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "revoked_at", sa.DateTime(timezone=True), nullable=True
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
        sa.UniqueConstraint(
            "tenant_id",
            "key_prefix",
            name="uq_tenant_api_keys_tenant_id_key_prefix",
        ),
        schema="axon_control",
    )
    op.create_index(
        "ix_tenant_api_keys_tenant_id",
        "tenant_api_keys",
        ["tenant_id"],
        schema="axon_control",
    )
    op.create_index(
        "ix_tenant_api_keys_tenant_id_revoked_at",
        "tenant_api_keys",
        ["tenant_id", "revoked_at"],
        schema="axon_control",
    )
    op.create_index(
        "ix_tenant_api_keys_key_prefix",
        "tenant_api_keys",
        ["key_prefix"],
        schema="axon_control",
    )
    for stmt in full_policy_set_sql(
        table="tenant_api_keys", schema="axon_control"
    ):
        op.execute(stmt)


def downgrade() -> None:
    op.drop_table("tenant_api_keys", schema="axon_control")
