"""Row-Level Security policy helpers.

Alembic migrations embed these SQL fragments via ``op.execute(...)`` so
the exact same policy shape is applied to every tenant-scoped table.

Policy model
------------
Two policies are created per table:

1. ``tenant_isolation`` — uses the GUC set by the session factory
   (``axon.current_tenant``) to restrict SELECT/UPDATE/DELETE to the
   active tenant's rows.

2. ``admin_bypass`` — a permissive ALL policy for a role tagged
   ``BYPASSRLS`` (e.g. ``axon_admin``). This is used by the Admin API
   and Alembic itself, both of which need cross-tenant visibility.

The GUC name must match the Rust side — ``axon.current_tenant`` — so
the same policy works whether the session was opened by Python or by
the Rust runtime.
"""

from __future__ import annotations


def enable_rls_sql(
    *,
    table: str,
    schema: str = "axon_control",
    force: bool = True,
) -> list[str]:
    """SQL to enable (and optionally FORCE) RLS on a table.

    ``FORCE ROW LEVEL SECURITY`` applies the policy even to the table
    owner. We enable it by default because the Python service connects
    as the schema owner and would otherwise bypass its own policies.
    """
    fq = f'"{schema}"."{table}"'
    stmts = [f"ALTER TABLE {fq} ENABLE ROW LEVEL SECURITY;"]
    if force:
        stmts.append(f"ALTER TABLE {fq} FORCE ROW LEVEL SECURITY;")
    return stmts


def tenant_isolation_policy_sql(
    *,
    table: str,
    schema: str = "axon_control",
    tenant_column: str = "tenant_id",
    guc_name: str = "axon.current_tenant",
    policy_name: str = "tenant_isolation",
) -> list[str]:
    """SQL for the per-tenant isolation policy.

    ``current_setting(..., true)`` returns NULL instead of erroring when
    the GUC is unset — paired with the NULL check below, queries without
    a tenant context see zero rows rather than all rows.
    """
    fq = f'"{schema}"."{table}"'
    condition = (
        f"{tenant_column} = current_setting('{guc_name}', true) "
        f"AND current_setting('{guc_name}', true) IS NOT NULL"
    )
    return [
        f"DROP POLICY IF EXISTS {policy_name} ON {fq};",
        (
            f"CREATE POLICY {policy_name} ON {fq} "
            f"FOR ALL "
            f"USING ({condition}) "
            f"WITH CHECK ({condition});"
        ),
    ]


def admin_bypass_policy_sql(
    *,
    table: str,
    schema: str = "axon_control",
    admin_role: str = "axon_admin",
    policy_name: str = "admin_bypass",
) -> list[str]:
    """SQL granting a cross-tenant role unconditional access.

    Consumed by the Admin API and by Alembic (which connects as
    ``axon_admin`` to avoid needing a tenant context during migrations).
    """
    fq = f'"{schema}"."{table}"'
    return [
        f"DROP POLICY IF EXISTS {policy_name} ON {fq};",
        (
            f"CREATE POLICY {policy_name} ON {fq} "
            f"FOR ALL TO {admin_role} "
            f"USING (true) "
            f"WITH CHECK (true);"
        ),
    ]


def full_policy_set_sql(
    *,
    table: str,
    schema: str = "axon_control",
    tenant_column: str = "tenant_id",
    guc_name: str = "axon.current_tenant",
    admin_role: str = "axon_admin",
    force: bool = True,
) -> list[str]:
    """Convenience: emit enable + tenant_isolation + admin_bypass in order.

    Use this in migrations so every tenant-scoped table gets the same
    treatment without copy-paste drift.
    """
    return [
        *enable_rls_sql(table=table, schema=schema, force=force),
        *tenant_isolation_policy_sql(
            table=table,
            schema=schema,
            tenant_column=tenant_column,
            guc_name=guc_name,
        ),
        *admin_bypass_policy_sql(
            table=table,
            schema=schema,
            admin_role=admin_role,
        ),
    ]
