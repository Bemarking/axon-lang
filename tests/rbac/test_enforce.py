"""Tests for the ``@require_permission`` decorator + helpers.

Verifies that the decorator parses the permission at decoration time
(so typos fail fast) and wires the PrincipalContext + DB session
correctly at call time.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from axon_enterprise.db.session import TenantSession
from axon_enterprise.identity import (
    CURRENT_PRINCIPAL,
    PrincipalContext,
    set_current_principal,
)
from axon_enterprise.rbac import (
    InvalidPermissionString,
    PermissionDenied,
    check_permission,
    require_permission,
    seed_builtin_roles,
)


def test_decorator_rejects_bad_permission_string_at_decoration_time() -> None:
    """Typos must fail at import, not at request time."""
    with pytest.raises(InvalidPermissionString):

        @require_permission("flow:teleport")  # not in catalog
        async def handler(db):  # pragma: no cover
            return db


def test_decorator_requires_asyncsession_param() -> None:
    """Function signatures without an AsyncSession are rejected at call time."""
    import asyncio

    uid = uuid4()

    @require_permission("tenant:read")
    async def bad_handler(value: int) -> int:  # no db param
        return value

    set_current_principal(
        PrincipalContext(user_id=uid, email="x@y.z", tenant_id="alpha")
    )
    try:
        with pytest.raises(TypeError, match="AsyncSession"):
            asyncio.run(bad_handler(1))
    finally:
        CURRENT_PRINCIPAL.set(None)


# ── Integration: decorator actually enforces against the DB ───────────


pytestmark_integration = pytest.mark.integration


@pytest_asyncio.fixture
async def admin_db(migrated_db: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            yield session


@pytest_asyncio.fixture
async def _clean_rbac(migrated_db: AsyncEngine) -> AsyncIterator[None]:
    yield
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "TRUNCATE axon_control.user_roles, "
                    "axon_control.role_permissions, "
                    "axon_control.roles CASCADE"
                )
            )
            await session.execute(
                text(
                    "TRUNCATE axon_control.sessions, "
                    "axon_control.tenant_memberships, "
                    "axon_control.users CASCADE"
                )
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_decorator_permits_when_user_has_permission(
    admin_db: AsyncSession, _clean_rbac: None
) -> None:
    uid = uuid4()
    await admin_db.execute(
        text("INSERT INTO axon_control.users (user_id, email) VALUES (:u, :e)"),
        {"u": uid, "e": "owner@a.example"},
    )
    seeded = await seed_builtin_roles(
        admin_db, tenant_id="alpha", owner_user_id=uid
    )
    assert seeded.owner

    @require_permission("tenant:read")
    async def handler(db: AsyncSession) -> str:
        return "ok"

    token = set_current_principal(
        PrincipalContext(user_id=uid, email="owner@a.example", tenant_id="alpha")
    )
    try:
        assert await handler(admin_db) == "ok"
    finally:
        CURRENT_PRINCIPAL.reset(token)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_decorator_denies_when_user_lacks_permission(
    admin_db: AsyncSession, _clean_rbac: None
) -> None:
    uid = uuid4()
    await admin_db.execute(
        text("INSERT INTO axon_control.users (user_id, email) VALUES (:u, :e)"),
        {"u": uid, "e": "viewer@a.example"},
    )
    seeded = await seed_builtin_roles(admin_db, tenant_id="alpha")
    # Assign viewer, not owner
    from axon_enterprise.rbac import RbacService

    await RbacService().assign_role(
        admin_db, user_id=uid, role_id=seeded.viewer, tenant_id="alpha"
    )
    await admin_db.flush()

    @require_permission("tenant:delete")
    async def handler(db: AsyncSession) -> str:  # pragma: no cover
        return "should-not-reach"

    token = set_current_principal(
        PrincipalContext(user_id=uid, email="viewer@a.example", tenant_id="alpha")
    )
    try:
        with pytest.raises(PermissionDenied) as exc:
            await handler(admin_db)
        assert exc.value.permission == "tenant:delete"
    finally:
        CURRENT_PRINCIPAL.reset(token)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_check_permission_helper(
    admin_db: AsyncSession, _clean_rbac: None
) -> None:
    uid = uuid4()
    await admin_db.execute(
        text("INSERT INTO axon_control.users (user_id, email) VALUES (:u, :e)"),
        {"u": uid, "e": "owner@a.example"},
    )
    await seed_builtin_roles(
        admin_db, tenant_id="alpha", owner_user_id=uid
    )

    token = set_current_principal(
        PrincipalContext(user_id=uid, email="owner@a.example", tenant_id="alpha")
    )
    try:
        assert await check_permission(admin_db, "secret:write")
        assert not await check_permission(
            admin_db, "tenant:read",
            principal=PrincipalContext(
                user_id=uuid4(), email="nobody@x.y", tenant_id="alpha"
            ),
        )
    finally:
        CURRENT_PRINCIPAL.reset(token)
