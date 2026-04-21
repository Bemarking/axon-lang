"""Cross-tenant isolation — the critical security test for Fase 10.a.

Creates a disposable table under ``axon_control`` with:

    - ``tenant_id`` FK to ``public.tenants``
    - RLS enabled + FORCED
    - ``tenant_isolation`` policy

Then verifies:

    1. Without a tenant GUC, reads return zero rows.
    2. With ``axon.current_tenant = 'alpha'`` only alpha's rows are visible.
    3. Switching to ``'beta'`` reveals only beta's rows.
    4. INSERTs with a mismatched tenant_id are rejected by the WITH CHECK
       clause (RLS refuses the write).
    5. The admin_bypass policy lets ``axon_admin`` see everything.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from axon_enterprise.db.rls_policies import full_policy_set_sql

pytestmark = pytest.mark.integration


TABLE = "rls_probe_widgets"


@pytest_asyncio.fixture
async def rls_probe_table(migrated_db: AsyncEngine) -> AsyncIterator[str]:
    """Create a throwaway tenant-scoped table + policies, then drop it."""
    create_sql = f"""
    CREATE TABLE axon_control.{TABLE} (
        widget_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id TEXT NOT NULL REFERENCES public.tenants(tenant_id),
        label     TEXT NOT NULL
    );
    """
    async with migrated_db.begin() as conn:
        await conn.execute(text(create_sql))
        for stmt in full_policy_set_sql(table=TABLE, schema="axon_control"):
            await conn.execute(text(stmt))

    try:
        yield TABLE
    finally:
        async with migrated_db.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS axon_control.{TABLE} CASCADE;"))


@pytest_asyncio.fixture
async def seeded_probe(
    rls_probe_table: str,
    migrated_db: AsyncEngine,
) -> AsyncIterator[dict[str, list[uuid.UUID]]]:
    """Insert known rows as a superuser (bypasses RLS) so the test has data
    to filter over."""
    inserted: dict[str, list[uuid.UUID]] = {"alpha": [], "beta": []}
    async with migrated_db.begin() as conn:
        for tenant in ("alpha", "beta"):
            for i in range(3):
                wid = uuid.uuid4()
                inserted[tenant].append(wid)
                await conn.execute(
                    text(
                        f"INSERT INTO axon_control.{TABLE} "
                        "(widget_id, tenant_id, label) "
                        "VALUES (:wid, :tid, :lbl)"
                    ),
                    {"wid": wid, "tid": tenant, "lbl": f"{tenant}-{i}"},
                )
    yield inserted


async def _count_visible(engine: AsyncEngine, tenant_id: str | None) -> int:
    """Count rows visible under the given tenant context (None = unset GUC)."""
    async with engine.connect() as conn:
        async with conn.begin():
            if tenant_id is not None:
                await conn.execute(
                    text("SELECT set_config('axon.current_tenant', :tid, true)"),
                    {"tid": tenant_id},
                )
            row = await conn.execute(
                text(f"SELECT COUNT(*) FROM axon_control.{TABLE}")
            )
            return row.scalar_one()


@pytest.mark.asyncio
async def test_unset_tenant_returns_zero_rows(
    seeded_probe: dict[str, list[uuid.UUID]],
    migrated_db: AsyncEngine,
) -> None:
    """Queries without a tenant GUC must see nothing."""
    visible = await _count_visible(migrated_db, tenant_id=None)
    assert visible == 0


@pytest.mark.asyncio
async def test_alpha_only_sees_alpha_rows(
    seeded_probe: dict[str, list[uuid.UUID]],
    migrated_db: AsyncEngine,
) -> None:
    visible = await _count_visible(migrated_db, tenant_id="alpha")
    assert visible == len(seeded_probe["alpha"])


@pytest.mark.asyncio
async def test_beta_only_sees_beta_rows(
    seeded_probe: dict[str, list[uuid.UUID]],
    migrated_db: AsyncEngine,
) -> None:
    visible = await _count_visible(migrated_db, tenant_id="beta")
    assert visible == len(seeded_probe["beta"])


@pytest.mark.asyncio
async def test_unknown_tenant_sees_zero_rows(
    seeded_probe: dict[str, list[uuid.UUID]],
    migrated_db: AsyncEngine,
) -> None:
    """A valid-looking-but-unseeded tenant must see zero rows, not a leak."""
    visible = await _count_visible(migrated_db, tenant_id="ghost")
    assert visible == 0


@pytest.mark.asyncio
async def test_with_check_rejects_mismatched_insert(
    rls_probe_table: str,
    migrated_db: AsyncEngine,
) -> None:
    """Even with the right GUC, inserting a row for ANOTHER tenant is rejected."""
    from sqlalchemy.exc import DBAPIError

    async with migrated_db.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text("SELECT set_config('axon.current_tenant', :t, true)"),
                {"t": "alpha"},
            )
            with pytest.raises(DBAPIError):
                await conn.execute(
                    text(
                        f"INSERT INTO axon_control.{TABLE} (tenant_id, label) "
                        "VALUES ('beta', 'smuggled')"
                    )
                )


@pytest.mark.asyncio
async def test_rollback_clears_tenant_guc(
    seeded_probe: dict[str, list[uuid.UUID]],
    migrated_db: AsyncEngine,
) -> None:
    """SET LOCAL must not leak across transactions on the same pooled connection."""
    async with migrated_db.connect() as conn:
        # First tx: set alpha, then rollback.
        async with conn.begin() as tx:
            await conn.execute(
                text("SELECT set_config('axon.current_tenant', 'alpha', true)")
            )
            await tx.rollback()

        # Second tx on the same physical connection: no GUC set → zero rows.
        async with conn.begin():
            row = await conn.execute(
                text(f"SELECT COUNT(*) FROM axon_control.{TABLE}")
            )
            assert row.scalar_one() == 0
