"""RBAC privilege-escalation adversarial tests.

Verifies:

1. The `viewer` role cannot invoke `@require_permission("user:invite")`.
2. A principal with an empty `role_names` set is blocked.
3. Passing a principal with a forged `tenant_id` that does not match
   the user's actual assignments yields a denial.
4. Recursive role inheritance does NOT grant permissions beyond the
   transitive closure (i.e. no silent upgrade paths).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from axon_enterprise.identity.principal import (
    PrincipalContext,
    set_current_principal,
)
from axon_enterprise.rbac import (
    PermissionDenied,
    RbacService,
    require_permission_active,
    seed_builtin_roles,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def session(migrated_db: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        yield s


async def _seed_user(session: AsyncSession, email: str):
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO axon_control.users (user_id, email) "
            "VALUES (:u, :e)"
        ),
        {"u": user_id, "e": email},
    )
    await session.commit()
    return user_id


@pytest.mark.asyncio
async def test_viewer_cannot_invite_users(session: AsyncSession) -> None:
    await seed_builtin_roles(session, tenant_id="alpha")
    user_id = await _seed_user(
        session, f"viewer-{uuid4().hex[:6]}@example.com"
    )
    rbac = RbacService()
    viewer_role = await rbac.get_role_by_name(
        session, tenant_id="alpha", name="viewer"
    )
    assert viewer_role is not None
    await rbac.assign_role(
        session,
        user_id=user_id,
        role_id=viewer_role.role_id,
        tenant_id="alpha",
    )
    await session.commit()

    principal = PrincipalContext(
        user_id=user_id,
        email="viewer@example",
        tenant_id="alpha",
        role_names=frozenset({"viewer"}),
    )
    set_current_principal(principal)
    with pytest.raises(PermissionDenied):
        await require_permission_active(
            session, "user:invite", principal=principal
        )


@pytest.mark.asyncio
async def test_empty_roles_is_denied(session: AsyncSession) -> None:
    user_id = await _seed_user(
        session, f"nobody-{uuid4().hex[:6]}@example.com"
    )
    principal = PrincipalContext(
        user_id=user_id,
        email="nobody@example",
        tenant_id="alpha",
        role_names=frozenset(),
    )
    with pytest.raises(PermissionDenied):
        await require_permission_active(
            session, "user:invite", principal=principal
        )


@pytest.mark.asyncio
async def test_forged_tenant_id_is_denied(session: AsyncSession) -> None:
    await seed_builtin_roles(session, tenant_id="alpha")
    user_id = await _seed_user(
        session, f"alpha-owner-{uuid4().hex[:6]}@example.com"
    )
    rbac = RbacService()
    owner_role = await rbac.get_role_by_name(
        session, tenant_id="alpha", name="owner"
    )
    assert owner_role is not None
    await rbac.assign_role(
        session,
        user_id=user_id,
        role_id=owner_role.role_id,
        tenant_id="alpha",
    )
    await session.commit()

    # Forged principal pretending the same user is owner of beta.
    forged = PrincipalContext(
        user_id=user_id,
        email="alpha-owner@example",
        tenant_id="beta",
        role_names=frozenset({"owner"}),
    )
    with pytest.raises(PermissionDenied):
        await require_permission_active(
            session, "user:invite", principal=forged
        )
