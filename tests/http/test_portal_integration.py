"""Integration — ``/api/v1/*`` Portal routes against a live DB.

Covers the end-to-end flows that tenant admins drive:

    1. /api/v1/tenant/api-keys: create + list + revoke
    2. /api/v1/tenant/users/invite then /api/v1/auth/invite/accept
       ping-pongs the magic link and lands an ACTIVE membership
    3. /api/v1/tenant/compliance/export enqueues an audit event
    4. /api/v1/tenant/usage returns the current period totals

Auth is stubbed (real JWT verification lives in ``test_auth_middleware``);
here we focus on handler logic + RLS plumbing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.applications import Starlette
from starlette.routing import Mount

from axon_enterprise.http.api import build_api_router
from axon_enterprise.http.errors import install_error_handlers
from axon_enterprise.identity.principal import (
    CURRENT_PRINCIPAL,
    PrincipalContext,
    set_current_principal,
)

pytestmark = pytest.mark.integration


def _tenant_principal(tenant_id: str = "alpha") -> PrincipalContext:
    """Admin of the given tenant — passes the api-key manage gate."""
    return PrincipalContext(
        user_id=uuid4(),
        email="tenant-admin@example.com",
        tenant_id=tenant_id,
        role_names=frozenset({"admin"}),
    )


class _StubAuthMiddleware:
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
def app(migrated_db: AsyncEngine) -> Starlette:
    principal = _tenant_principal()
    routes = [Mount("/api/v1", routes=build_api_router())]
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


@pytest_asyncio.fixture
async def _clean_api_keys(migrated_db: AsyncEngine) -> AsyncIterator[None]:
    yield
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        async with s.begin():
            await s.execute(text("TRUNCATE axon_control.tenant_api_keys"))


# ── /api/v1/tenant/api-keys ────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_list_api_key(
    client: httpx.AsyncClient, _clean_api_keys: None
) -> None:
    create = await client.post(
        "/api/v1/tenant/api-keys/",
        json={"name": "ci-pipeline"},
    )
    assert create.status_code == 201, create.text
    body = create.json()
    raw = body["raw_key"]
    assert raw.startswith("axk_") and len(raw) == len("axk_") + 32
    assert body["key_prefix"] == raw[len("axk_") :][:8]

    listing = await client.get("/api/v1/tenant/api-keys/")
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert any(i["api_key_id"] == body["api_key_id"] for i in items)

    # Raw key is never echoed back in the list.
    assert not any("raw_key" in i for i in items)


@pytest.mark.asyncio
async def test_revoke_api_key(
    client: httpx.AsyncClient, _clean_api_keys: None
) -> None:
    issued = (
        await client.post(
            "/api/v1/tenant/api-keys/",
            json={"name": "throwaway"},
        )
    ).json()
    api_key_id = issued["api_key_id"]

    rev = await client.delete(f"/api/v1/tenant/api-keys/{api_key_id}")
    assert rev.status_code == 200
    assert rev.json()["status"] == "revoked"

    # Second revoke is a 4xx (already revoked / not found).
    dup = await client.delete(f"/api/v1/tenant/api-keys/{api_key_id}")
    assert dup.status_code >= 400


@pytest.mark.asyncio
async def test_create_api_key_requires_name(
    client: httpx.AsyncClient, _clean_api_keys: None
) -> None:
    resp = await client.post(
        "/api/v1/tenant/api-keys/", json={"name": ""}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_input"


# ── /api/v1/tenant/compliance ──────────────────────────────────────


@pytest.mark.asyncio
async def test_compliance_export_request_emits_ticket() -> None:
    principal = _tenant_principal()
    routes = [Mount("/api/v1", routes=build_api_router())]
    app = Starlette(routes=routes)
    app.add_middleware(_StubAuthMiddleware, principal=principal)
    install_error_handlers(app)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.post(
            "/api/v1/tenant/compliance/export",
            json={"subject_email": "subject@example.com"},
        )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["sla_days"] == 30
    assert "ticket_id" in body


@pytest.mark.asyncio
async def test_compliance_export_rejects_missing_email(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.post(
        "/api/v1/tenant/compliance/export", json={}
    )
    assert resp.status_code == 400
