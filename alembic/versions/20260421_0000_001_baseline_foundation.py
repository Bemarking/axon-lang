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
    -- §Fase 38.x.b (axon-lang v1.38.2+) — the M1 tenants table moved
    -- from `public.tenants` to `axon_admin.tenants`. This precondition
    -- accepts EITHER location: a v1.38.2+ fresh install satisfies via
    -- axon_admin; a legacy deploy on v1.38.1 or earlier (or a deploy
    -- mid-upgrade where the v1.29.1 alembic 013 has not yet run)
    -- satisfies via public. The check passes if at least one of the
    -- two exists.
    --
    -- A v1.29.1+ enterprise deploy that has run BOTH alembic 013 and
    -- the v1.38.2+ Rust M1 will see axon_admin.tenants exist; the
    -- legacy public.tenants is left alive but never written to by axon.
    IF NOT EXISTS (
        SELECT 1 FROM pg_tables
        WHERE (schemaname = 'public' AND tablename = 'tenants')
           OR (schemaname = 'axon_admin' AND tablename = 'tenants')
    ) THEN
        RAISE EXCEPTION
            'Required tenants table is missing. Run the Rust data-plane migrations first: axon-rs/migrations/003_add_tenants.sql. v1.38.2+ creates axon_admin.tenants; v1.38.1 and earlier created public.tenants. Either one satisfies this precondition.';
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
