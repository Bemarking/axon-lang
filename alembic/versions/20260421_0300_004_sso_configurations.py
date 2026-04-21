"""sso_configurations + sso_states + sso_assertion_seen

Adds the SSO subsystem tables introduced in Fase 10.d.

    sso_configurations  — tenant-scoped IdP configs, envelope-encrypted
    sso_states          — short-lived state+nonce+PKCE verifier
    sso_assertion_seen  — SAML assertion ID replay defence (48h window)

All three carry tenant_isolation + admin_bypass RLS.

Revision ID: 004
Revises: 003
Create Date: 2026-04-21 03:00:00+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from axon_enterprise.db.rls_policies import full_policy_set_sql

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── sso_configurations ────────────────────────────────────────────
    op.create_table(
        "sso_configurations",
        sa.Column(
            "sso_config_id",
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
                name="fk_sso_configurations_tenant_id_tenants",
            ),
            nullable=False,
        ),
        sa.Column("provider_type", sa.String(16), nullable=False),
        sa.Column("config_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column(
            "attribute_map",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "role_map",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "auto_provision",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "default_role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "axon_control.roles.role_id",
                ondelete="SET NULL",
                onupdate="CASCADE",
                name="fk_sso_configurations_default_role_id_roles",
            ),
            nullable=True,
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
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
            "provider_type IN ('oidc','saml')",
            name="ck_sso_configurations_provider_type",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "provider_type",
            name="uq_sso_configurations_tenant_id_provider_type",
        ),
        schema="axon_control",
    )
    op.create_index(
        "ix_sso_configurations_tenant_id",
        "sso_configurations",
        ["tenant_id"],
        schema="axon_control",
    )
    op.create_index(
        "ix_sso_configurations_tenant_id_created_at",
        "sso_configurations",
        ["tenant_id", "created_at"],
        schema="axon_control",
    )
    for stmt in full_policy_set_sql(
        table="sso_configurations", schema="axon_control"
    ):
        op.execute(stmt)

    # ── sso_states ────────────────────────────────────────────────────
    op.create_table(
        "sso_states",
        sa.Column(
            "state_id",
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
                name="fk_sso_states_tenant_id_tenants",
            ),
            nullable=False,
        ),
        sa.Column("provider_type", sa.String(16), nullable=False),
        sa.Column("state", sa.String(128), nullable=False),
        sa.Column("nonce", sa.String(128), nullable=True),
        sa.Column("code_verifier", sa.String(128), nullable=True),
        sa.Column("return_url", sa.String(2048), nullable=True),
        sa.Column("issuer", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider_type IN ('oidc','saml')",
            name="ck_sso_states_provider_type",
        ),
        sa.UniqueConstraint(
            "tenant_id", "state", name="uq_sso_states_tenant_id_state"
        ),
        schema="axon_control",
    )
    op.create_index(
        "ix_sso_states_tenant_id",
        "sso_states",
        ["tenant_id"],
        schema="axon_control",
    )
    op.create_index(
        "ix_sso_states_tenant_id_created_at",
        "sso_states",
        ["tenant_id", "created_at"],
        schema="axon_control",
    )
    op.create_index(
        "ix_sso_states_expires_at",
        "sso_states",
        ["expires_at"],
        schema="axon_control",
    )
    for stmt in full_policy_set_sql(table="sso_states", schema="axon_control"):
        op.execute(stmt)

    # ── sso_assertion_seen ────────────────────────────────────────────
    op.create_table(
        "sso_assertion_seen",
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey(
                "public.tenants.tenant_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
                name="fk_sso_assertion_seen_tenant_id_tenants",
            ),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "assertion_id",
            sa.String(256),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="axon_control",
    )
    op.create_index(
        "ix_sso_assertion_seen_created_at",
        "sso_assertion_seen",
        ["created_at"],
        schema="axon_control",
    )
    for stmt in full_policy_set_sql(
        table="sso_assertion_seen", schema="axon_control"
    ):
        op.execute(stmt)


def downgrade() -> None:
    op.drop_table("sso_assertion_seen", schema="axon_control")
    op.drop_table("sso_states", schema="axon_control")
    op.drop_table("sso_configurations", schema="axon_control")
