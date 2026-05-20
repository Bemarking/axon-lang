"""Integration tests for the tenant-aware session context managers."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from axon_enterprise.db.engine import get_primary_session_factory
from axon_enterprise.db.rls_policies import full_policy_set_sql
from axon_enterprise.db.session import admin_session, tenant_session
from axon_enterprise.tenant import TenantContext, TenantPlan

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def session_probe(migrated_db: AsyncEngine) -> AsyncIterator[str]:
    """Throwaway tenant-scoped table for session-level tests."""
    table = "session_probe_items"
    async with migrated_db.begin() as conn:
        await conn.execute(
            text(
                f"""
                CREATE TABLE axon_control.{table} (
                    item_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tenant_id TEXT NOT NULL REFERENCES axon_admin.tenants(tenant_id),
                    payload TEXT NOT NULL
                );
                """
            )
        )
        for stmt in full_policy_set_sql(table=table, schema="axon_control"):
            await conn.execute(text(stmt))
    try:
        yield table
    finally:
        async with migrated_db.begin() as conn:
            await conn.execute(
                text(f"DROP TABLE IF EXISTS axon_control.{table} CASCADE;")
            )


@pytest.mark.asyncio
async def test_tenant_session_sets_guc_and_isolates(
    session_probe: str,
    migrated_db: AsyncEngine,
) -> None:
    # Force the session factory to re-bind to the ephemeral engine.
    import axon_enterprise.db.engine as engine_mod

    engine_mod.primary_session_factory = None
    engine_mod._engines.clear()
    # The settings-loaded engine will be created on first access; we want
    # it to use the test container URL which conftest put in env.

    alpha = TenantContext(tenant_id="alpha", plan=TenantPlan.ENTERPRISE)
    beta = TenantContext(tenant_id="beta", plan=TenantPlan.ENTERPRISE)

    # Insert via tenant_session for alpha
    async with tenant_session(alpha) as session:
        await session.execute(
            text(
                f"INSERT INTO axon_control.{session_probe} (tenant_id, payload) "
                "VALUES (:tid, :p)"
            ),
            {"tid": "alpha", "p": "a1"},
        )
        await session.execute(
            text(
                f"INSERT INTO axon_control.{session_probe} (tenant_id, payload) "
                "VALUES (:tid, :p)"
            ),
            {"tid": "alpha", "p": "a2"},
        )

    # Insert via tenant_session for beta
    async with tenant_session(beta) as session:
        await session.execute(
            text(
                f"INSERT INTO axon_control.{session_probe} (tenant_id, payload) "
                "VALUES (:tid, :p)"
            ),
            {"tid": "beta", "p": "b1"},
        )

    # Alpha reads → only alpha rows
    async with tenant_session(alpha) as session:
        row = await session.execute(
            text(f"SELECT COUNT(*) FROM axon_control.{session_probe}")
        )
        assert row.scalar_one() == 2

    # Beta reads → only beta row
    async with tenant_session(beta) as session:
        row = await session.execute(
            text(f"SELECT COUNT(*) FROM axon_control.{session_probe}")
        )
        assert row.scalar_one() == 1


@pytest.mark.asyncio
async def test_tenant_session_rollback_on_exception(
    session_probe: str,
    migrated_db: AsyncEngine,
) -> None:
    import axon_enterprise.db.engine as engine_mod

    engine_mod.primary_session_factory = None
    engine_mod._engines.clear()

    alpha = TenantContext(tenant_id="alpha", plan=TenantPlan.ENTERPRISE)

    class Boom(Exception):
        pass

    before = await _count_for_tenant(migrated_db, session_probe, "alpha")

    with pytest.raises(Boom):
        async with tenant_session(alpha) as session:
            await session.execute(
                text(
                    f"INSERT INTO axon_control.{session_probe} (tenant_id, payload) "
                    "VALUES ('alpha', 'should-not-land')"
                )
            )
            raise Boom()

    after = await _count_for_tenant(migrated_db, session_probe, "alpha")
    assert after == before, "tenant_session must roll back writes on exception"


async def _count_for_tenant(
    engine: AsyncEngine,
    table: str,
    tenant_id: str,
) -> int:
    async with engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text("SELECT set_config('axon.current_tenant', :t, true)"),
                {"t": tenant_id},
            )
            row = await conn.execute(
                text(f"SELECT COUNT(*) FROM axon_control.{table}")
            )
            return row.scalar_one()
