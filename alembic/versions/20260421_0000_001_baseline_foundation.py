"""baseline_foundation

Creates the schema, role, and helper function that Fase 10.a depends on.
NO application tables are created here — those land in sub-fases 10.b+
so each sub-fase has a focused, reviewable migration.

Pre-conditions
--------------
- ``public.tenants`` MUST exist (created by axon-rs migration
  ``003_add_tenants.sql`` / Fase M1). We assert this and fail loudly
  if the Rust migrations haven't run yet.

Post-conditions
---------------
- Schema ``axon_control`` exists and is owned by the connecting user.
- Role ``axon_admin`` exists with ``BYPASSRLS`` so the Admin API and
  Alembic itself can operate cross-tenant.
- Function ``axon_control.set_tenant(text)`` lets handlers + stored
  procs set the GUC without knowing its canonical name.

Revision ID: 001
Revises: (none)
Create Date: 2026-04-21 00:00:00+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ASSERT_TENANTS_TABLE = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_tables
        WHERE schemaname = 'public' AND tablename = 'tenants'
    ) THEN
        RAISE EXCEPTION
            'Required table public.tenants is missing. Run the Rust data-plane migrations first: axon-rs/migrations/003_add_tenants.sql (Fase M1).';
    END IF;
END
$$;
"""

_CREATE_ADMIN_ROLE = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'axon_admin') THEN
        CREATE ROLE axon_admin NOLOGIN BYPASSRLS;
    END IF;
END
$$;
"""

_CREATE_SET_TENANT_FN = """
CREATE OR REPLACE FUNCTION axon_control.set_tenant(p_tenant_id text)
    RETURNS void
    LANGUAGE plpgsql
    SECURITY INVOKER
    AS $$
    BEGIN
        -- ``set_config(.., true)`` == ``SET LOCAL``: GUC lives for the
        -- current transaction only, mirroring the runtime session
        -- behaviour and matching the Rust db_pool.rs pattern.
        PERFORM set_config('axon.current_tenant', p_tenant_id, true);
    END;
$$;

COMMENT ON FUNCTION axon_control.set_tenant(text) IS
    'Set the per-transaction tenant GUC (axon.current_tenant). '
    'Used by handlers and stored procedures to scope RLS policies.';
"""

_GRANT_SCHEMA_PRIVS = """
GRANT USAGE ON SCHEMA axon_control TO axon_admin;
GRANT ALL ON SCHEMA axon_control TO CURRENT_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA axon_control
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO axon_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA axon_control
    GRANT USAGE ON SEQUENCES TO axon_admin;
"""


def upgrade() -> None:
    # 1. Pre-condition check: Rust data-plane tables are present.
    op.execute(_ASSERT_TENANTS_TABLE)

    # 2. Python-owned schema.
    op.execute("CREATE SCHEMA IF NOT EXISTS axon_control AUTHORIZATION CURRENT_USER;")

    # 3. Admin role (BYPASSRLS) used by Admin API + Alembic.
    op.execute(_CREATE_ADMIN_ROLE)

    # 4. Grant matrix on the new schema.
    op.execute(_GRANT_SCHEMA_PRIVS)

    # 5. Helper to set the tenant GUC without hard-coding its name at every
    #    call site (handlers can do ``SELECT axon_control.set_tenant(:id)``).
    op.execute(_CREATE_SET_TENANT_FN)


def downgrade() -> None:
    # Drop in reverse order. ``axon_admin`` is NOT dropped — it may be
    # granted to service accounts outside this repo's control. Operator
    # removes the role manually if truly decommissioning.
    op.execute("DROP FUNCTION IF EXISTS axon_control.set_tenant(text);")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA axon_control "
        "REVOKE ALL ON TABLES FROM axon_admin;"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA axon_control "
        "REVOKE ALL ON SEQUENCES FROM axon_admin;"
    )
    op.execute("REVOKE ALL ON SCHEMA axon_control FROM axon_admin;")
    op.execute("DROP SCHEMA IF EXISTS axon_control CASCADE;")
