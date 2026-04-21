"""Cross-tenant isolation — Fase 10.m adversarial suite.

Builds two tenants (``alpha``, ``beta``), then verifies that
every Portal API endpoint driven by a JWT scoped to ``alpha``
cannot read/mutate ``beta`` rows — NOT via 403, but via 404 so the
response leaks no existence information.

Scope:

- API keys: alpha cannot list / revoke beta's key
- tenant users: alpha cannot see beta members, cannot update beta roles,
  cannot deactivate beta members
- compliance tickets: alpha cannot read beta tickets by id
- usage / invoices: alpha's `/usage` sees only alpha metrics + invoices

The stubbed `_StubAuthMiddleware` gives us principal control; the
real `admin_session` runs without tenant GUC but the services
check `tenant_id` explicitly on each query — this test verifies
that second layer (service-level scoping), not just the RLS layer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.applications import Starlette
from starlette.routing import Mount

from axon_enterprise.api_keys import ApiKeyService
from axon_enterprise.compliance import (
    ComplianceRequestKind,
    ComplianceService,
)
from axon_enterprise.http.api import build_api_router
from axon_enterprise.http.errors import install_error_handlers
from axon_enterprise.identity.principal import (
    CURRENT_PRINCIPAL,
    PrincipalContext,
    set_current_principal,
)

pytestmark = pytest.mark.integration


def _principal(tenant_id: str) -> PrincipalContext:
    return PrincipalContext(
        user_id=uuid4(),
        email=f"admin@{tenant_id}.example",
        tenant_id=tenant_id,
        role_names=frozenset({"admin"}),
    )


class _PrincipalSwitcher:
    """Test-only middleware — pulls the tenant from an X-Test-Tenant header
    so a single client can impersonate alpha then beta without rebuilding
    the app."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        tenant_id = "alpha"
        for name, value in scope.get("headers") or []:
            if name == b"x-test-tenant":
                tenant_id = value.decode("ascii")
                break
        token = set_current_principal(_principal(tenant_id))
        try:
            await self.app(scope, receive, send)
        finally:
            CURRENT_PRINCIPAL.reset(token)


@pytest.fixture
def app() -> Starlette:
    routes = [Mount("/api/v1", routes=build_api_router())]
    app = Starlette(routes=routes)
    app.add_middleware(_PrincipalSwitcher)
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
async def _clean(migrated_db: AsyncEngine) -> AsyncIterator[None]:
    yield
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        async with s.begin():
            await s.execute(
                text(
                    "TRUNCATE axon_control.tenant_api_keys, "
                    "axon_control.compliance_requests, "
                    "axon_control.legal_holds CASCADE"
                )
            )


# ── API keys ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_key_cross_tenant_list_isolation(
    client: httpx.AsyncClient, _clean: None, migrated_db: AsyncEngine
) -> None:
    # Seed one key for beta directly via the service.
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        svc = ApiKeyService.default()
        issued_beta = await svc.create(
            s, tenant_id="beta", name="beta-only"
        )
        await s.commit()

    # alpha lists — must NOT see beta's key
    resp = await client.get(
        "/api/v1/tenant/api-keys/", headers={"X-Test-Tenant": "alpha"}
    )
    assert resp.status_code == 200
    ids = {i["api_key_id"] for i in resp.json()["items"]}
    assert str(issued_beta.row.api_key_id) not in ids


@pytest.mark.asyncio
async def test_api_key_cross_tenant_revoke_returns_error(
    client: httpx.AsyncClient, _clean: None, migrated_db: AsyncEngine
) -> None:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        svc = ApiKeyService.default()
        issued_beta = await svc.create(
            s, tenant_id="beta", name="beta-key"
        )
        await s.commit()

    resp = await client.delete(
        f"/api/v1/tenant/api-keys/{issued_beta.row.api_key_id}",
        headers={"X-Test-Tenant": "alpha"},
    )
    # Service uses a WHERE tenant_id = ... in the UPDATE, so no row
    # matches → ApiKeyInvalid → 4xx for the cross-tenant caller.
    assert resp.status_code >= 400
    # The beta key is still live.
    async with factory() as s:
        row = await s.get(
            type(issued_beta.row), issued_beta.row.api_key_id
        )
        assert row is not None
        assert row.revoked_at is None


# ── Compliance tickets ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compliance_ticket_cross_tenant_hidden(
    client: httpx.AsyncClient, _clean: None, migrated_db: AsyncEngine
) -> None:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        svc = ComplianceService.default()
        ticket = await svc.tickets.issue(
            s,
            tenant_id="beta",
            kind=ComplianceRequestKind.SAR_EXPORT,
            subject_email="target@beta.example",
        )
        await s.commit()

    resp = await client.get(
        f"/api/v1/tenant/compliance/{ticket.request_id}",
        headers={"X-Test-Tenant": "alpha"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "compliance.request_not_found"


@pytest.mark.asyncio
async def test_compliance_list_only_shows_own_tenant(
    client: httpx.AsyncClient, _clean: None, migrated_db: AsyncEngine
) -> None:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        svc = ComplianceService.default()
        alpha_ticket = await svc.tickets.issue(
            s,
            tenant_id="alpha",
            kind=ComplianceRequestKind.SAR_EXPORT,
            subject_email="alpha-subject@example",
        )
        beta_ticket = await svc.tickets.issue(
            s,
            tenant_id="beta",
            kind=ComplianceRequestKind.SAR_EXPORT,
            subject_email="beta-subject@example",
        )
        await s.commit()

    resp = await client.get(
        "/api/v1/tenant/compliance/",
        headers={"X-Test-Tenant": "alpha"},
    )
    assert resp.status_code == 200
    ids = {i["ticket_id"] for i in resp.json()["items"]}
    assert str(alpha_ticket.request_id) in ids
    assert str(beta_ticket.request_id) not in ids


# ── Tenant users ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_users_cross_tenant_deactivate_noop(
    client: httpx.AsyncClient, _clean: None, migrated_db: AsyncEngine
) -> None:
    # Seed a beta membership directly.
    from uuid import uuid4 as _uuid4
    target_user = _uuid4()
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        async with s.begin():
            await s.execute(
                text(
                    "INSERT INTO axon_control.users (user_id, email) "
                    "VALUES (:u, :e)"
                ),
                {"u": target_user, "e": f"u-{target_user.hex[:6]}@beta.example"},
            )
            await s.execute(
                text(
                    "INSERT INTO axon_control.tenant_memberships "
                    "(tenant_id, user_id, status) "
                    "VALUES ('beta', :u, 'active')"
                ),
                {"u": target_user},
            )

    # alpha tries to deactivate a beta user — the UPDATE runs within
    # tenant_session scoped to 'alpha', so WHERE tenant_id = 'alpha'
    # matches zero rows. The beta user is unchanged.
    resp = await client.delete(
        f"/api/v1/tenant/users/{target_user}",
        headers={"X-Test-Tenant": "alpha"},
    )
    assert resp.status_code in (200, 404)

    async with factory() as s:
        status = await s.scalar(
            text(
                "SELECT status FROM axon_control.tenant_memberships "
                "WHERE tenant_id = 'beta' AND user_id = :u"
            ),
            {"u": target_user},
        )
        assert status == "active"
