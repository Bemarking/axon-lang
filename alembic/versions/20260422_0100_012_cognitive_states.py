"""cognitive_states — §λ-L-E Fase 11.d stateful PEM persistence

Adds ``axon_control.cognitive_states`` for the envelope-encrypted
snapshots of an agent's cognitive posture across WebSocket
reconnects. Tenant-scoped + RLS; unlike replay_tokens (Fase 11.c)
this table IS mutable — snapshots rewrite in place during a
session's lifetime. Eviction happens via an eviction worker, not
append-only triggers, because TTL expiry requires DELETE.

Revision ID: 012
Revises: 011
Create Date: 2026-04-22 01:00:00+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from axon_enterprise.db.rls_policies import full_policy_set_sql

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cognitive_states",
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
                name="fk_cognitive_states_tenant_id_tenants",
            ),
            nullable=False,
        ),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("flow_id", sa.String(128), nullable=False),
        sa.Column(
            "subject_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "state_ciphertext",
            sa.LargeBinary(),
            nullable=False,
        ),
        sa.Column(
            "state_format_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("state_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_restored_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "restore_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
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
        sa.UniqueConstraint(
            "tenant_id",
            "session_id",
            name="uq_cognitive_states_tenant_id_session_id",
        ),
        schema="axon_control",
    )

    op.create_index(
        "ix_cognitive_states_tenant_id",
        "cognitive_states",
        ["tenant_id"],
        schema="axon_control",
    )
    op.create_index(
        "ix_cognitive_states_expires_at",
        "cognitive_states",
        ["expires_at"],
        schema="axon_control",
    )
    op.create_index(
        "ix_cognitive_states_tenant_id_subject_user_id",
        "cognitive_states",
        ["tenant_id", "subject_user_id"],
        schema="axon_control",
    )
    op.create_index(
        "ix_cognitive_states_tenant_id_flow_id",
        "cognitive_states",
        ["tenant_id", "flow_id"],
        schema="axon_control",
    )
    op.create_index(
        "ix_cognitive_states_tenant_id_expires_at",
        "cognitive_states",
        ["tenant_id", "expires_at"],
        schema="axon_control",
    )

    for stmt in full_policy_set_sql(
        table="cognitive_states", schema="axon_control"
    ):
        op.execute(stmt)


def downgrade() -> None:
    op.drop_table("cognitive_states", schema="axon_control")
