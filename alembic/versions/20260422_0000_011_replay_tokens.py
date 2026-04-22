"""replay_tokens — §λ-L-E Fase 11.c deterministic replay persistence

Adds ``axon_control.replay_tokens``: every effect invocation emitted
by the Axon runtime parks a canonical-hashed receipt here. Tokens
are immutable — enforced by the BEFORE UPDATE/DELETE triggers so
tampering with a receipt after the fact requires a DBA-level role
and leaves a chain-level signal.

Anchors to ``axon_control.audit_events`` via ``audit_event_id``
so the token's emission is itself chain-hashed.

Revision ID: 011
Revises: 010
Create Date: 2026-04-22 00:00:00+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from axon_enterprise.db.rls_policies import full_policy_set_sql

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_APPEND_ONLY_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION axon_control.replay_tokens_append_only()
    RETURNS trigger
    LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        '% on axon_control.replay_tokens is forbidden — replay receipts are append-only',
        TG_OP
        USING ERRCODE = '42501';
END;
$$;

COMMENT ON FUNCTION axon_control.replay_tokens_append_only() IS
    'Rejects UPDATE/DELETE/TRUNCATE on replay_tokens. Receipts are '
    'load-bearing audit evidence; retention is enforced at the '
    'migration layer, not by row modification.';
"""


_CREATE_TRIGGERS = """
DROP TRIGGER IF EXISTS replay_tokens_no_update ON axon_control.replay_tokens;
CREATE TRIGGER replay_tokens_no_update
    BEFORE UPDATE ON axon_control.replay_tokens
    FOR EACH ROW
    EXECUTE FUNCTION axon_control.replay_tokens_append_only();

DROP TRIGGER IF EXISTS replay_tokens_no_delete ON axon_control.replay_tokens;
CREATE TRIGGER replay_tokens_no_delete
    BEFORE DELETE ON axon_control.replay_tokens
    FOR EACH ROW
    EXECUTE FUNCTION axon_control.replay_tokens_append_only();

DROP TRIGGER IF EXISTS replay_tokens_no_truncate ON axon_control.replay_tokens;
CREATE TRIGGER replay_tokens_no_truncate
    BEFORE TRUNCATE ON axon_control.replay_tokens
    FOR EACH STATEMENT
    EXECUTE FUNCTION axon_control.replay_tokens_append_only();
"""


def upgrade() -> None:
    op.create_table(
        "replay_tokens",
        sa.Column(
            "token_id",
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
                name="fk_replay_tokens_tenant_id_tenants",
            ),
            nullable=False,
        ),
        sa.Column("flow_id", sa.String(128), nullable=True),
        sa.Column("effect_name", sa.String(128), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("inputs_hash_hex", sa.String(64), nullable=False),
        sa.Column("outputs_hash_hex", sa.String(64), nullable=False),
        sa.Column(
            "token_hash_hex",
            sa.String(64),
            nullable=False,
            unique=True,
        ),
        sa.Column("nonce_hex", sa.String(32), nullable=False),
        sa.Column(
            "inputs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "outputs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "sampling",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("legal_basis", sa.String(64), nullable=True),
        sa.Column(
            "audit_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "axon_control.audit_events.event_id",
                ondelete="RESTRICT",
                onupdate="CASCADE",
                name="fk_replay_tokens_audit_event_id_audit_events",
            ),
            nullable=True,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
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
        schema="axon_control",
    )

    op.create_index(
        "ix_replay_tokens_tenant_id",
        "replay_tokens",
        ["tenant_id"],
        schema="axon_control",
    )
    op.create_index(
        "ix_replay_tokens_flow_id",
        "replay_tokens",
        ["flow_id"],
        schema="axon_control",
    )
    op.create_index(
        "ix_replay_tokens_tenant_id_flow_id_recorded_at",
        "replay_tokens",
        ["tenant_id", "flow_id", "recorded_at"],
        schema="axon_control",
    )
    op.create_index(
        "ix_replay_tokens_tenant_id_effect_name_recorded_at",
        "replay_tokens",
        ["tenant_id", "effect_name", "recorded_at"],
        schema="axon_control",
    )
    op.create_index(
        "ix_replay_tokens_tenant_id_legal_basis",
        "replay_tokens",
        ["tenant_id", "legal_basis"],
        schema="axon_control",
    )

    # Append-only enforcement — mirrors the audit_events posture.
    op.execute(_APPEND_ONLY_TRIGGER_FN)
    op.execute(_CREATE_TRIGGERS)

    # RLS + admin_bypass — same shape as every other tenant-scoped
    # table in the control plane.
    for stmt in full_policy_set_sql(
        table="replay_tokens", schema="axon_control"
    ):
        op.execute(stmt)


def downgrade() -> None:
    # Drop triggers first, then function, then table so the
    # ordering is safe even when another migration accidentally
    # references the function.
    op.execute(
        "DROP TRIGGER IF EXISTS replay_tokens_no_truncate "
        "ON axon_control.replay_tokens"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS replay_tokens_no_delete "
        "ON axon_control.replay_tokens"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS replay_tokens_no_update "
        "ON axon_control.replay_tokens"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS axon_control.replay_tokens_append_only()"
    )
    op.drop_table("replay_tokens", schema="axon_control")
