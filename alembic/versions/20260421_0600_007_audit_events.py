"""audit_events — hash-chained, append-only audit log

Creates ``axon_control.audit_events`` plus the trigger functions
that block UPDATE + DELETE. Retention is never achieved by row
modification — only by migration-level table replacement, and even
that requires a reviewer to accept the destructive DROP TABLE.

The ``tenant_isolation + admin_bypass`` RLS pair scopes reads to the
caller's tenant. The Admin API (10.j) connects as ``axon_admin`` for
cross-tenant compliance exports.

Revision ID: 007
Revises: 006
Create Date: 2026-04-21 06:00:00+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from axon_enterprise.db.rls_policies import full_policy_set_sql

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_APPEND_ONLY_FN = """
CREATE OR REPLACE FUNCTION axon_control.audit_events_append_only()
    RETURNS trigger
    LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        '% on axon_control.audit_events is forbidden — table is append-only',
        TG_OP
        USING ERRCODE = '42501';  -- insufficient_privilege
END;
$$;

COMMENT ON FUNCTION axon_control.audit_events_append_only() IS
    'Rejects every UPDATE or DELETE on audit_events. Retention is '
    'enforced at the migration layer, not by row modification.';
"""

_CREATE_TRIGGERS = """
DROP TRIGGER IF EXISTS audit_events_no_update ON axon_control.audit_events;
CREATE TRIGGER audit_events_no_update
    BEFORE UPDATE ON axon_control.audit_events
    FOR EACH ROW
    EXECUTE FUNCTION axon_control.audit_events_append_only();

DROP TRIGGER IF EXISTS audit_events_no_delete ON axon_control.audit_events;
CREATE TRIGGER audit_events_no_delete
    BEFORE DELETE ON axon_control.audit_events
    FOR EACH ROW
    EXECUTE FUNCTION axon_control.audit_events_append_only();

DROP TRIGGER IF EXISTS audit_events_no_truncate ON axon_control.audit_events;
CREATE TRIGGER audit_events_no_truncate
    BEFORE TRUNCATE ON axon_control.audit_events
    FOR EACH STATEMENT
    EXECUTE FUNCTION axon_control.audit_events_append_only();
"""


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column(
            "event_id",
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
                name="fk_audit_events_tenant_id_tenants",
            ),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column(
            "actor_user_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("actor_email", sa.Text(), nullable=True),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="success",
        ),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("prev_hash", sa.LargeBinary(), nullable=False),
        sa.Column("event_hash", sa.LargeBinary(), nullable=False),
        sa.Column("esk_stitch", sa.LargeBinary(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('success','failure','denied')",
            name="ck_audit_events_status",
        ),
        sa.CheckConstraint(
            "sequence_number > 0",
            name="ck_audit_events_sequence_positive",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "sequence_number",
            name="uq_audit_events_tenant_id_sequence_number",
        ),
        schema="axon_control",
    )

    op.create_index(
        "ix_audit_events_tenant_id",
        "audit_events",
        ["tenant_id"],
        schema="axon_control",
    )
    op.create_index(
        "ix_audit_events_tenant_id_created_at",
        "audit_events",
        ["tenant_id", "created_at"],
        schema="axon_control",
    )
    op.create_index(
        "ix_audit_events_tenant_id_event_type_created_at",
        "audit_events",
        ["tenant_id", "event_type", "created_at"],
        schema="axon_control",
    )
    op.create_index(
        "ix_audit_events_actor_user_id",
        "audit_events",
        ["actor_user_id"],
        schema="axon_control",
    )

    # RLS.
    for stmt in full_policy_set_sql(table="audit_events", schema="axon_control"):
        op.execute(stmt)

    # Append-only triggers.
    op.execute(_APPEND_ONLY_FN)
    op.execute(_CREATE_TRIGGERS)


def downgrade() -> None:
    # Triggers are dropped implicitly when the table is dropped, but
    # removing the function keeps the schema tidy on rollback.
    op.drop_table("audit_events", schema="axon_control")
    op.execute(
        "DROP FUNCTION IF EXISTS axon_control.audit_events_append_only();"
    )
