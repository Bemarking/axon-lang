"""Integration — Admin API routes against a live DB + mocked JWT auth.

The AuthMiddleware reaches out to ``/.well-known/jwks.json`` over the
network to verify tokens. In tests we swap it for a stub middleware
that installs a fixed ``PrincipalContext``, so handlers still see
``require_principal()`` returning a plausible value without needing
a running issuer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.applications import Starlette
from starlette.routing import Mount

from axon_enterprise.http.admin import build_admin_router
from axon_enterprise.http.errors import install_error_handlers
from axon_enterprise.identity.principal import (
    CURRENT_PRINCIPAL,
    PrincipalContext,
    set_current_principal,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def admin_db(migrated_db: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            yield session


@pytest_asyncio.fixture
async def _clean_slate(migrated_db: AsyncEngine) -> AsyncIterator[None]:
    yield
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "TRUNCATE axon_control.tenant_subscriptions, "
                    "axon_control.user_roles, "
                    "axon_control.role_permissions, "
                    "axon_control.roles, "
                    "axon_control.users CASCADE"
                )
            )
            # Remove test tenants (keep the three seeded by Rust fixture).
            await session.execute(
                text(
                    "DELETE FROM public.tenants WHERE tenant_id NOT IN "
                    "('default', 'alpha', 'beta')"
                )
            )


def _make_admin_principal() -> PrincipalContext:
    """Build a principal that passes the ``_require_admin`` gate."""
    return PrincipalContext(
        user_id=uuid4(),
        email="operator@bemarking.com",
        tenant_id="default",
        role_names=frozenset({"owner"}),
    )


class _StubAuthMiddleware:
    """Installs a fixed PrincipalContext on every request."""

    def __init__(self, app, *, principal: PrincipalContext) -> None:
        self.app = app
        self.principal = principal

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = set_current_principal(self.principal)
        try:
            await self.app(scope, receive, send)
        finally:
            CURRENT_PRINCIPAL.reset(token)


@pytest.fixture
def app() -> Starlette:
    principal = _make_admin_principal()
    routes = [Mount("/admin", routes=build_admin_router())]
    app = Starlette(routes=routes)
    app.add_middleware(_StubAuthMiddleware, principal=principal)
    install_error_handlers(app)
    return app


@pytest_asyncio.fixture
async def client(app: Starlette) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


# ── Tenant CRUD ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_then_get_tenant(
    client: httpx.AsyncClient, admin_db: AsyncSession, _clean_slate: None
) -> None:
    response = await client.post(
        "/admin/tenants/",
        json={"slug": "acme", "name": "Acme Corp", "plan_id": "pro"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["tenant_id"] == "acme"

    get_resp = await client.get("/admin/tenants/acme")
    assert get_resp.status_code == 200
    assert get_resp.json()["plan_id"] == "pro"


@pytest.mark.asyncio
async def test_create_tenant_conflict(
    client: httpx.AsyncClient, _clean_slate: None
) -> None:
    await client.post(
        "/admin/tenants/",
        json={"slug": "acme2", "name": "Acme", "plan_id": "starter"},
    )
    dup = await client.post(
        "/admin/tenants/",
        json={"slug": "acme2", "name": "Acme", "plan_id": "starter"},
    )
    assert dup.status_code == 409


@pytest.mark.asyncio
async def test_create_tenant_unknown_plan(
    client: httpx.AsyncClient, _clean_slate: None
) -> None:
    resp = await client.post(
        "/admin/tenants/",
        json={"slug": "ghost", "name": "Ghost", "plan_id": "platinum"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_tenants_paginates(
    client: httpx.AsyncClient, _clean_slate: None
) -> None:
    for i in range(3):
        await client.post(
            "/admin/tenants/",
            json={
                "slug": f"t-{i}",
                "name": f"Tenant {i}",
                "plan_id": "starter",
            },
        )

    resp = await client.get("/admin/tenants/?limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert body["limit"] == 2
    assert body["total"] >= 3


@pytest.mark.asyncio
async def test_suspend_and_resume(
    client: httpx.AsyncClient, _clean_slate: None
) -> None:
    await client.post(
        "/admin/tenants/",
        json={"slug": "susp", "name": "Susp", "plan_id": "starter"},
    )

    s = await client.post("/admin/tenants/susp/suspend", json={"reason": "test"})
    assert s.status_code == 200
    assert s.json()["status"] == "suspended"

    r = await client.post("/admin/tenants/susp/resume")
    assert r.status_code == 200
    assert r.json()["status"] == "active"


@pytest.mark.asyncio
async def test_resume_non_suspended_409(
    client: httpx.AsyncClient, _clean_slate: None
) -> None:
    await client.post(
        "/admin/tenants/",
        json={"slug": "act", "name": "Act", "plan_id": "starter"},
    )
    r = await client.post("/admin/tenants/act/resume")
    assert r.status_code == 409


# ── Keys ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_keys_list_and_rotate_local(
    client: httpx.AsyncClient, admin_db: AsyncSession, _clean_slate: None
) -> None:
    # Rotate (no kms_arn → local generation, matches dev path)
    rotate = await client.post("/admin/keys/rotate", json={})
    assert rotate.status_code == 200
    new_kid = rotate.json()["kid"]

    listing = await client.get("/admin/keys/")
    assert listing.status_code == 200
    kids = [k["kid"] for k in listing.json()["keys"]]
    assert new_kid in kids


# ── Audit verify ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_verify_empty_chain(
    client: httpx.AsyncClient, admin_db: AsyncSession, _clean_slate: None
) -> None:
    # No events recorded for tenant 'default' → chain is vacuously valid.
    resp = await client.post("/admin/audit/default/verify")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["checked"] == 0
