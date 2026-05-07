"""Tests — ``GET /api/v1/tenant/me/integration-context`` (Fase 21.c).

Authenticated tenant introspection. The handler reads ``require_principal()``
and the current ``TenantContext`` to derive the response, so the test
fixtures install both ContextVars via a stub middleware modeled on the
admin-integration test pattern (no DB, no real JWT verification).

RLS verification is structural: we never query "give me data for
tenant X" with X coming from the request body. The principal's
``tenant_id`` is the only key used. The "different principals see
different responses" test pins this invariant.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import ASGIApp, Receive, Scope, Send

from axon_enterprise.config import get_settings
from axon_enterprise.http.api.integration_context import (
    INTEGRATION_CONTEXT_SCHEMA_VERSION,
    routes as integration_context_routes,
)
from axon_enterprise.http.errors import install_error_handlers
from axon_enterprise.identity.errors import AuthenticationError
from axon_enterprise.identity.principal import (
    CURRENT_PRINCIPAL,
    PrincipalContext,
    set_current_principal,
)
from axon_enterprise.tenant import (
    CURRENT_TENANT,
    TenantContext,
    TenantPlan,
    set_current_tenant,
)


def _make_principal(tenant_id: str) -> PrincipalContext:
    return PrincipalContext(
        user_id=uuid4(),
        email=f"admin@{tenant_id}.example",
        tenant_id=tenant_id,
        role_names=frozenset({"owner"}),
    )


class _StubAuthMiddleware:
    """Installs PrincipalContext + TenantContext on every request.

    Mirrors the production AuthMiddleware contract minus the actual JWT
    verification — handlers see the same ContextVars set.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        principal: PrincipalContext | None,
        plan: TenantPlan = TenantPlan.ENTERPRISE,
    ) -> None:
        self.app = app
        self.principal = principal
        self.plan = plan

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if self.principal is None:
            # Mimic real auth-failure path: no principal → 401.
            from axon_enterprise.http.errors import json_error

            response = json_error(AuthenticationError("Bearer token required"))
            body = response.body
            await send(
                {
                    "type": "http.response.start",
                    "status": response.status_code,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        ptoken = set_current_principal(self.principal)
        ttoken = set_current_tenant(
            TenantContext(tenant_id=self.principal.tenant_id, plan=self.plan)
        )
        try:
            await self.app(scope, receive, send)
        finally:
            CURRENT_PRINCIPAL.reset(ptoken)
            CURRENT_TENANT.reset(ttoken)


def _make_app(
    *,
    principal: PrincipalContext | None,
    plan: TenantPlan = TenantPlan.ENTERPRISE,
) -> Starlette:
    app = Starlette(
        routes=[
            Mount(
                "/api/v1/tenant/me/integration-context",
                routes=integration_context_routes(),
            )
        ]
    )
    app.add_middleware(_StubAuthMiddleware, principal=principal, plan=plan)
    install_error_handlers(app)
    return app


@pytest_asyncio.fixture
async def authed_client() -> AsyncIterator[httpx.AsyncClient]:
    app = _make_app(principal=_make_principal("acme"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


@pytest_asyncio.fixture
async def unauthed_client() -> AsyncIterator[httpx.AsyncClient]:
    app = _make_app(principal=None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


URL = "/api/v1/tenant/me/integration-context/"


# ── 1. Happy path: 200 + JSON ────────────────────────────────────────


@pytest.mark.asyncio
async def test_endpoint_returns_200_with_json(
    authed_client: httpx.AsyncClient,
) -> None:
    resp = await authed_client.get(URL)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert isinstance(resp.json(), dict)


# ── 2. Requires auth — 401 without principal ─────────────────────────


@pytest.mark.asyncio
async def test_unauthenticated_returns_401(
    unauthed_client: httpx.AsyncClient,
) -> None:
    resp = await unauthed_client.get(URL)
    assert resp.status_code == 401


# ── 3. tenant_id reflects the principal ──────────────────────────────


@pytest.mark.asyncio
async def test_tenant_id_matches_principal(
    authed_client: httpx.AsyncClient,
) -> None:
    body = (await authed_client.get(URL)).json()
    assert body["tenant_id"] == "acme"


# ── 4. plan reflects the TenantContext ───────────────────────────────


@pytest.mark.asyncio
async def test_plan_reflects_tenant_context() -> None:
    """A tenant on the PRO plan must see ``"plan": "pro"`` in its context."""
    app = _make_app(principal=_make_principal("beta"), plan=TenantPlan.PRO)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        body = (await c.get(URL)).json()
    assert body["plan"] == "pro"


# ── 5. auth.issuer matches settings ──────────────────────────────────


@pytest.mark.asyncio
async def test_auth_issuer_matches_settings(
    authed_client: httpx.AsyncClient,
) -> None:
    body = (await authed_client.get(URL)).json()
    assert body["auth"]["issuer"] == get_settings().jwt.issuer.rstrip("/")


# ── 6. auth.audience matches settings ────────────────────────────────


@pytest.mark.asyncio
async def test_auth_audience_matches_settings(
    authed_client: httpx.AsyncClient,
) -> None:
    body = (await authed_client.get(URL)).json()
    assert body["auth"]["audience"] == get_settings().jwt.audience


# ── 7. auth.expected_signing_alg matches settings ────────────────────


@pytest.mark.asyncio
async def test_signing_alg_matches_settings(
    authed_client: httpx.AsyncClient,
) -> None:
    body = (await authed_client.get(URL)).json()
    assert body["auth"]["expected_signing_alg"] == get_settings().jwt.algorithm


# ── 8. discovery URLs are derived from issuer ────────────────────────


@pytest.mark.asyncio
async def test_discovery_urls_derived_from_issuer(
    authed_client: httpx.AsyncClient,
) -> None:
    body = (await authed_client.get(URL)).json()
    issuer = get_settings().jwt.issuer.rstrip("/")
    assert (
        body["discovery"]["openid_configuration"]
        == f"{issuer}/.well-known/openid-configuration"
    )
    assert (
        body["discovery"]["oauth_authorization_server"]
        == f"{issuer}/.well-known/oauth-authorization-server"
    )
    assert body["discovery"]["jwks"] == f"{issuer}/.well-known/jwks.json"


# ── 9. Versioning fields present ─────────────────────────────────────


@pytest.mark.asyncio
async def test_versioning_fields_present(
    authed_client: httpx.AsyncClient,
) -> None:
    body = (await authed_client.get(URL)).json()
    assert isinstance(body["axon_enterprise_version"], str)
    assert (
        body["axon_integration_context_schema_version"]
        == INTEGRATION_CONTEXT_SCHEMA_VERSION
    )


# ── 10. RLS — different principal yields different tenant_id ─────────


@pytest.mark.asyncio
async def test_multi_tenant_isolation() -> None:
    """Two clients with different principals must see different tenant_ids
    in their response — verifies the handler keys off the principal,
    never off any request-supplied tenant identifier."""
    for slug in ("acme", "beta", "default"):
        app = _make_app(principal=_make_principal(slug))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as c:
            body = (await c.get(URL)).json()
        assert body["tenant_id"] == slug


# ── 11. Cache-Control is *private* + ETag present ────────────────────


@pytest.mark.asyncio
async def test_cache_control_private_and_etag_present(
    authed_client: httpx.AsyncClient,
) -> None:
    """Tenant-scoped responses must NOT be cached by intermediaries
    across tenants; ``private`` directive prevents shared caches from
    storing the response keyed only by URL."""
    resp = await authed_client.get(URL)
    cache_control = resp.headers.get("cache-control", "")
    assert "private" in cache_control
    assert "public" not in cache_control
    assert "max-age=" in cache_control
    etag = resp.headers.get("etag", "")
    assert etag.startswith('"') and etag.endswith('"')
    assert len(etag) == 66  # "<sha256-hex-64>"


# ── 12. Conditional read — If-None-Match returns 304 ─────────────────


@pytest.mark.asyncio
async def test_if_none_match_returns_304(
    authed_client: httpx.AsyncClient,
) -> None:
    first = await authed_client.get(URL)
    etag = first.headers["etag"]
    second = await authed_client.get(URL, headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.headers["etag"] == etag
    assert second.content == b""
    # 304 must still flag private + max-age so well-behaved clients
    # respect freshness rules.
    assert "private" in second.headers.get("cache-control", "")
