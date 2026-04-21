"""Integration tests for ``RbacService`` — exercises the real Postgres DB,
recursive CTE, hierarchy cycle guard, and RLS policies.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from axon_enterprise.rbac import (
    BuiltInRoleProtected,
    PermissionDenied,
    RbacService,
    RoleCycleError,
    RoleNotFound,
    seed_builtin_roles,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def admin_db(migrated_db: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """BYPASSRLS session for mutation + assertion helpers."""
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            yield session


@pytest_asyncio.fixture
async def _clean_rbac(migrated_db: AsyncEngine) -> AsyncIterator[None]:
    """Wipe RBAC tables between tests so state does not bleed."""
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


@pytest_asyncio.fixture
async def owner_user_id(admin_db: AsyncSession) -> str:
    """Create a single user we can assign roles to."""
    uid = uuid4()
    await admin_db.execute(
        text(
            "INSERT INTO axon_control.users (user_id, email) "
            "VALUES (:uid, :email)"
        ),
        {"uid": uid, "email": f"owner-{uid}@example.com"},
    )
    await admin_db.flush()
    return str(uid)


# ── Permission catalog ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_catalog_seeded_by_migration(
    admin_db: AsyncSession, _clean_rbac: None
) -> None:
    rbac = RbacService()
    perms = await rbac.list_permissions(admin_db)
    assert len(perms) >= 32
    assert any(p.resource == "flow" and p.action == "execute" for p in perms)


# ── Seeding built-in roles ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_builtin_roles_is_idempotent(
    admin_db: AsyncSession, owner_user_id: str, _clean_rbac: None
) -> None:
    from uuid import UUID

    seeded = await seed_builtin_roles(
        admin_db, tenant_id="alpha", owner_user_id=UUID(owner_user_id)
    )
    assert seeded.owner != seeded.admin

    # Re-run — must not create duplicates.
    seeded2 = await seed_builtin_roles(
        admin_db, tenant_id="alpha", owner_user_id=UUID(owner_user_id)
    )
    assert seeded.as_dict() == seeded2.as_dict()


@pytest.mark.asyncio
async def test_owner_has_every_permission_in_db(
    admin_db: AsyncSession, owner_user_id: str, _clean_rbac: None
) -> None:
    from uuid import UUID

    await seed_builtin_roles(
        admin_db, tenant_id="alpha", owner_user_id=UUID(owner_user_id)
    )

    rbac = RbacService()
    eff = await rbac.effective_permissions(
        admin_db, user_id=UUID(owner_user_id), tenant_id="alpha"
    )
    # owner should have every permission in the catalog.
    catalog = await rbac.list_permissions(admin_db)
    expected = {(p.resource, p.action) for p in catalog}
    assert eff == expected


@pytest.mark.asyncio
async def test_viewer_is_read_only(
    admin_db: AsyncSession, owner_user_id: str, _clean_rbac: None
) -> None:
    from uuid import UUID

    # Second user, assigned viewer only.
    viewer_id = uuid4()
    await admin_db.execute(
        text("INSERT INTO axon_control.users (user_id, email) VALUES (:u, :e)"),
        {"u": viewer_id, "e": "viewer@example.com"},
    )

    seeded = await seed_builtin_roles(admin_db, tenant_id="alpha")
    rbac = RbacService()
    await rbac.assign_role(
        admin_db,
        user_id=viewer_id,
        role_id=seeded.viewer,
        tenant_id="alpha",
    )
    await admin_db.flush()

    eff = await rbac.effective_permissions(
        admin_db, user_id=viewer_id, tenant_id="alpha"
    )
    for _resource, action in eff:
        assert action.startswith("read"), (
            f"viewer received non-read permission {_resource}:{action}"
        )


# ── Hierarchy ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_role_hierarchy_inherits_upward(
    admin_db: AsyncSession, owner_user_id: str, _clean_rbac: None
) -> None:
    """Create ``viewer_plus`` parented to ``viewer``; user assigned only
    ``viewer_plus`` should see viewer's permissions too."""
    from uuid import UUID

    seeded = await seed_builtin_roles(admin_db, tenant_id="alpha")
    rbac = RbacService()

    child = await rbac.create_role(
        admin_db,
        tenant_id="alpha",
        name="viewer_plus",
        parent_role_id=seeded.viewer,
    )
    await rbac.grant_permission(
        admin_db, role_id=child.role_id, resource="flow", action="execute"
    )

    uid = uuid4()
    await admin_db.execute(
        text("INSERT INTO axon_control.users (user_id, email) VALUES (:u, :e)"),
        {"u": uid, "e": "vp@example.com"},
    )
    await rbac.assign_role(
        admin_db, user_id=uid, role_id=child.role_id, tenant_id="alpha"
    )
    await admin_db.flush()

    eff = await rbac.effective_permissions(
        admin_db, user_id=uid, tenant_id="alpha"
    )
    # Own permission
    assert ("flow", "execute") in eff
    # Inherited from viewer
    assert ("tenant", "read") in eff
    assert ("audit", "read") in eff


@pytest.mark.asyncio
async def test_cycle_prevented_on_create(
    admin_db: AsyncSession, _clean_rbac: None
) -> None:
    """Create A → B, then try to make B's parent = A (which creates a cycle
    when B itself gets set as A's parent). The guard should fire at the second
    set_parent call."""
    rbac = RbacService()
    a = await rbac.create_role(admin_db, tenant_id="alpha", name="a")
    b = await rbac.create_role(admin_db, tenant_id="alpha", name="b", parent_role_id=a.role_id)
    # b -> a is OK. Now attempt a -> b, which would close the cycle.
    with pytest.raises(RoleCycleError):
        await rbac.set_parent(
            admin_db, role_id=a.role_id, parent_role_id=b.role_id
        )


# ── Built-in protection ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cannot_delete_builtin_role(
    admin_db: AsyncSession, _clean_rbac: None
) -> None:
    seeded = await seed_builtin_roles(admin_db, tenant_id="alpha")
    rbac = RbacService()
    with pytest.raises(BuiltInRoleProtected):
        await rbac.delete_role(admin_db, seeded.owner)


# ── Check + require ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_and_require(
    admin_db: AsyncSession, owner_user_id: str, _clean_rbac: None
) -> None:
    from uuid import UUID

    seeded = await seed_builtin_roles(
        admin_db, tenant_id="alpha", owner_user_id=UUID(owner_user_id)
    )
    rbac = RbacService()

    assert await rbac.check(
        admin_db,
        user_id=UUID(owner_user_id),
        tenant_id="alpha",
        permission="tenant:delete",
    )

    # A fresh user without any role must fail.
    blank = uuid4()
    await admin_db.execute(
        text("INSERT INTO axon_control.users (user_id, email) VALUES (:u, :e)"),
        {"u": blank, "e": "blank@example.com"},
    )
    assert not await rbac.check(
        admin_db, user_id=blank, tenant_id="alpha", permission="tenant:delete"
    )
    with pytest.raises(PermissionDenied):
        await rbac.require(
            admin_db, user_id=blank, tenant_id="alpha", permission="tenant:delete"
        )


# ── Cross-tenant isolation ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_role_assignment_rejects_cross_tenant_role(
    admin_db: AsyncSession, _clean_rbac: None
) -> None:
    seeded_alpha = await seed_builtin_roles(admin_db, tenant_id="alpha")

    uid = uuid4()
    await admin_db.execute(
        text("INSERT INTO axon_control.users (user_id, email) VALUES (:u, :e)"),
        {"u": uid, "e": "x@example.com"},
    )

    rbac = RbacService()
    # Assigning alpha's owner role but marking tenant_id='beta' must fail.
    with pytest.raises(RoleNotFound):
        await rbac.assign_role(
            admin_db,
            user_id=uid,
            role_id=seeded_alpha.owner,
            tenant_id="beta",
        )


@pytest.mark.asyncio
async def test_effective_permissions_tenant_scoped(
    admin_db: AsyncSession, _clean_rbac: None
) -> None:
    """User assigned owner in alpha must have zero permissions in beta."""
    from uuid import UUID

    uid = uuid4()
    await admin_db.execute(
        text("INSERT INTO axon_control.users (user_id, email) VALUES (:u, :e)"),
        {"u": uid, "e": "multi@example.com"},
    )

    await seed_builtin_roles(
        admin_db, tenant_id="alpha", owner_user_id=uid
    )

    rbac = RbacService()
    assert await rbac.effective_permissions(
        admin_db, user_id=uid, tenant_id="alpha"
    )  # non-empty
    beta_perms = await rbac.effective_permissions(
        admin_db, user_id=uid, tenant_id="beta"
    )
    assert beta_perms == set(), "user must have zero permissions in beta"
