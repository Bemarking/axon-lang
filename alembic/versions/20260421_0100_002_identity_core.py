"""identity_core

Creates the identity subsystem tables:

    - axon_control.users              (global, admin_bypass only)
    - axon_control.tenant_memberships (tenant-scoped, full RLS)
    - axon_control.sessions           (tenant-scoped, full RLS)

Plus the ``citext`` and ``pgcrypto`` extensions.

Users is deliberately NOT covered by ``tenant_isolation``: a user can
belong to many tenants. Access control is enforced in the service
layer — callers open an ``admin_session()`` after gate-checking a
``tenant_memberships`` row under a ``tenant_session()``. The FORCE +
admin_bypass pair prevents accidental reads from a tenant-scoped
connection.

Revision ID: 002
Revises: 001
Create Date: 2026-04-21 01:00:00+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from axon_enterprise.db.rls_policies import (
    admin_bypass_policy_sql,
    enable_rls_sql,
    full_policy_set_sql,
)

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Extensions ────────────────────────────────────────────────────
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')
    op.execute('CREATE EXTENSION IF NOT EXISTS "citext";')

    # ── users (global) ────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", postgresql.CITEXT(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column(
            "password_algo",
            sa.String(32),
            nullable=False,
            server_default="argon2id",
        ),
        sa.Column(
            "password_updated_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("totp_secret_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column(
            "totp_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "totp_verified_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "email_verified_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "failed_logins",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_login_ip", postgresql.INET(), nullable=True
        ),
        sa.Column(
            "attributes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
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
            "status IN ('active','locked','suspended','deleted')",
            name="ck_users_status",
        ),
        schema="axon_control",
    )
    op.create_index(
        "ix_users_status",
        "users",
        ["status"],
        schema="axon_control",
    )
    # users: RLS with admin_bypass only — global table, no tenant scoping.
    for stmt in enable_rls_sql(table="users", schema="axon_control"):
        op.execute(stmt)
    for stmt in admin_bypass_policy_sql(table="users", schema="axon_control"):
        op.execute(stmt)

    # Cross-references & composite indexes that sqlalchemy creates on
    # the ``users`` table's CITEXT email — we keep them here for clarity.
    op.create_index(
        "ix_users_email",
        "users",
        ["email"],
        schema="axon_control",
    )

    # ── tenant_memberships (tenant-scoped) ────────────────────────────
    op.create_table(
        "tenant_memberships",
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey(
                "public.tenants.tenant_id",
                ondelete="RESTRICT",
                onupdate="CASCADE",
                name="fk_tenant_memberships_tenant_id_tenants",
            ),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "axon_control.users.user_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
                name="fk_tenant_memberships_user_id_users",
            ),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="invited",
        ),
        sa.Column(
            "invited_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "axon_control.users.user_id",
                ondelete="SET NULL",
                onupdate="CASCADE",
                name="fk_tenant_memberships_invited_by_users",
            ),
            nullable=True,
        ),
        sa.Column("invitation_token_hash", sa.LargeBinary(), nullable=True),
        sa.Column(
            "invitation_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('invited','active','suspended')",
            name="ck_tenant_memberships_status",
        ),
        schema="axon_control",
    )
    op.create_index(
        "ix_tenant_memberships_tenant_id_created_at",
        "tenant_memberships",
        ["tenant_id", "created_at"],
        schema="axon_control",
    )
    op.create_index(
        "ix_tenant_memberships_user_id",
        "tenant_memberships",
        ["user_id"],
        schema="axon_control",
    )
    op.create_index(
        "ix_tenant_memberships_invitation_token_hash",
        "tenant_memberships",
        ["invitation_token_hash"],
        unique=True,
        postgresql_where=sa.text("invitation_token_hash IS NOT NULL"),
        schema="axon_control",
    )
    for stmt in full_policy_set_sql(
        table="tenant_memberships", schema="axon_control"
    ):
        op.execute(stmt)

    # ── sessions (tenant-scoped) ──────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column(
            "session_id",
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
                name="fk_sessions_tenant_id_tenants",
            ),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "axon_control.users.user_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
                name="fk_sessions_user_id_users",
            ),
            nullable=False,
        ),
        sa.Column(
            "refresh_token_hash", sa.LargeBinary(), nullable=False
        ),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(64), nullable=True),
        sa.Column(
            "rotated_to_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "axon_control.sessions.session_id",
                ondelete="SET NULL",
                onupdate="CASCADE",
                name="fk_sessions_rotated_to_session_id_sessions",
            ),
            nullable=True,
        ),
        sa.Column(
            "sequence",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.UniqueConstraint(
            "refresh_token_hash", name="uq_sessions_refresh_token_hash"
        ),
        schema="axon_control",
    )
    op.create_index(
        "ix_sessions_tenant_id",
        "sessions",
        ["tenant_id"],
        schema="axon_control",
    )
    op.create_index(
        "ix_sessions_tenant_id_user_id_created_at",
        "sessions",
        ["tenant_id", "user_id", "created_at"],
        schema="axon_control",
    )
    op.create_index(
        "ix_sessions_user_id",
        "sessions",
        ["user_id"],
        schema="axon_control",
    )
    op.create_index(
        "ix_sessions_refresh_token_hash",
        "sessions",
        ["refresh_token_hash"],
        schema="axon_control",
    )
    for stmt in full_policy_set_sql(table="sessions", schema="axon_control"):
        op.execute(stmt)


def downgrade() -> None:
    # Sessions first (FK to users), then memberships, then users.
    op.drop_table("sessions", schema="axon_control")
    op.drop_table("tenant_memberships", schema="axon_control")
    op.drop_table("users", schema="axon_control")
    # Leave extensions installed — they may be shared by other schemas.
