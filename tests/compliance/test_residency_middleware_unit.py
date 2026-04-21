"""Unit tests for ``DataResidencyMiddleware``.

The middleware depends on ``admin_session()`` for the region
lookup; we monkey-patch ``TenantRegionCache.region_for`` to return
a fixed value so the tests don't require a DB.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from axon_enterprise.compliance.residency import (
    DataResidencyMiddleware,
    TenantRegionCache,
)
from axon_enterprise.config import get_settings
from axon_enterprise.identity.principal import (
    CURRENT_PRINCIPAL,
    PrincipalContext,
    set_current_principal,
)


async def _hello(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


class _StubPrincipalMiddleware:
    """Installs a fixed principal on every request for the test app."""

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


class _StaticCache(TenantRegionCache):
    def __init__(self, *, region: str | None) -> None:
        super().__init__()
        self._static = region

    async def region_for(self, tenant_id: str) -> str | None:
        return self._static


def _build_app(*, region: str | None) -> Starlette:
    app = Starlette(routes=[Route("/", _hello, methods=["GET"])])
    app.add_middleware(
        DataResidencyMiddleware, cache=_StaticCache(region=region)
    )
    app.add_middleware(
        _StubPrincipalMiddleware,
        principal=PrincipalContext(
            user_id=uuid4(),
            email="operator@example.com",
            tenant_id="alpha",
            role_names=frozenset({"admin"}),
        ),
    )
    return app


@pytest.mark.asyncio
async def test_region_match_passes_through(monkeypatch) -> None:
    monkeypatch.setenv("AXON_COMPLIANCE_SERVER_REGION", "us-east-1")
    get_settings.cache_clear()
    app = _build_app(region="us-east-1")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.get("/")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_missing_region_passes_through(monkeypatch) -> None:
    """Tenants without a region (pre-10.l rows) are not blocked."""
    monkeypatch.setenv("AXON_COMPLIANCE_SERVER_REGION", "us-east-1")
    get_settings.cache_clear()
    app = _build_app(region=None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.get("/")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_mismatch_without_redirect_base_returns_421(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AXON_COMPLIANCE_SERVER_REGION", "us-east-1")
    monkeypatch.delenv(
        "AXON_COMPLIANCE_RESIDENCY_REDIRECT_BASE", raising=False
    )
    get_settings.cache_clear()
    app = _build_app(region="eu-west-1")

    async def _noop(self, **kwargs) -> None:
        return None

    # Don't actually write audit — DB-free test.
    monkeypatch.setattr(
        "axon_enterprise.compliance.residency.DataResidencyMiddleware._record_violation",
        _noop,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.get("/")
    assert resp.status_code == 421
    assert resp.json()["error"]["code"] == "compliance.residency_violation"
    assert resp.json()["error"]["tenant_region"] == "eu-west-1"


@pytest.mark.asyncio
async def test_mismatch_with_redirect_base_redirects_308(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AXON_COMPLIANCE_SERVER_REGION", "us-east-1")
    monkeypatch.setenv(
        "AXON_COMPLIANCE_RESIDENCY_REDIRECT_BASE",
        "https://{region}.auth.example",
    )
    get_settings.cache_clear()
    app = _build_app(region="eu-west-1")

    async def _noop(self, **kwargs) -> None:
        return None

    monkeypatch.setattr(
        "axon_enterprise.compliance.residency.DataResidencyMiddleware._record_violation",
        _noop,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        resp = await c.get("/?x=1")
    assert resp.status_code == 308
    assert resp.headers["location"] == "https://eu-west-1.auth.example/?x=1"
