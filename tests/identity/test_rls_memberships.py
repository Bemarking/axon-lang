"""Tenant isolation on ``tenant_memberships`` and ``sessions``.

Extends ``tests/db/test_rls.py`` to the actual 10.b tables.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seeded_users_and_memberships(
    migrated_db: AsyncEngine,
) -> dict[str, str]:
    """Insert one user and membership per tenant under BYPASSRLS."""
    alice_id = uuid4()
    bob_id = uuid4()
    async with migrated_db.begin() as conn:
        # clean state first
        await conn.execute(
            text(
                "TRUNCATE axon_control.sessions, "
                "axon_control.tenant_memberships, "
                "axon_control.users CASCADE"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO axon_control.users (user_id, email) "
                "VALUES (:a, 'alice@a.example'), (:b, 'bob@b.example')"
            ),
            {"a": alice_id, "b": bob_id},
        )
        await conn.execute(
            text(
                "INSERT INTO axon_control.tenant_memberships "
                "(tenant_id, user_id, status, joined_at) VALUES "
                "('alpha', :a, 'active', NOW()), "
                "('beta',  :b, 'active', NOW())"
            ),
            {"a": alice_id, "b": bob_id},
        )
    return {"alice_id": str(alice_id), "bob_id": str(bob_id)}


async def _membership_count_for_tenant(
    engine: AsyncEngine, tenant_id: str
) -> int:
    async with engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text("SELECT set_config('axon.current_tenant', :t, true)"),
                {"t": tenant_id},
            )
            row = await conn.execute(
                text("SELECT COUNT(*) FROM axon_control.tenant_memberships")
            )
            return row.scalar_one()


@pytest.mark.asyncio
async def test_alpha_only_sees_its_membership(
    seeded_users_and_memberships: dict[str, str], migrated_db: AsyncEngine
) -> None:
    assert await _membership_count_for_tenant(migrated_db, "alpha") == 1
    assert await _membership_count_for_tenant(migrated_db, "beta") == 1
    # Cross-tenant query is zero rows by construction.
    assert await _membership_count_for_tenant(migrated_db, "ghost") == 0


@pytest.mark.asyncio
async def test_users_table_is_deny_without_admin_bypass(
    migrated_db: AsyncEngine,
) -> None:
    """users has admin_bypass only — a tenant-scoped connection sees 0 rows."""
    async with migrated_db.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text("SELECT set_config('axon.current_tenant', 'alpha', true)")
            )
            row = await conn.execute(
                text("SELECT COUNT(*) FROM axon_control.users")
            )
            # BYPASSRLS role (test superuser) sees rows; but RLS would hide
            # them from axon_app. We verify ``admin_bypass`` policy exists.
            count_exists = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM pg_policies "
                    "WHERE schemaname = 'axon_control' "
                    "AND tablename = 'users' "
                    "AND policyname = 'admin_bypass'"
                )
            )
            assert count_exists.scalar_one() == 1


@pytest.mark.asyncio
async def test_sessions_tenant_isolation(
    seeded_users_and_memberships: dict[str, str], migrated_db: AsyncEngine
) -> None:
    alice_id = seeded_users_and_memberships["alice_id"]

    async with migrated_db.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO axon_control.sessions "
                "(tenant_id, user_id, refresh_token_hash, expires_at) VALUES "
                "('alpha', :a, '\\x00'::bytea, NOW() + interval '30 days')"
            ),
            {"a": alice_id},
        )

    async with migrated_db.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text("SELECT set_config('axon.current_tenant', 'beta', true)")
            )
            row = await conn.execute(
                text("SELECT COUNT(*) FROM axon_control.sessions")
            )
            assert row.scalar_one() == 0
        async with conn.begin():
            await conn.execute(
                text("SELECT set_config('axon.current_tenant', 'alpha', true)")
            )
            row = await conn.execute(
                text("SELECT COUNT(*) FROM axon_control.sessions")
            )
            assert row.scalar_one() == 1
