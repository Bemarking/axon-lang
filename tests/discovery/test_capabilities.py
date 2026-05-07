"""Tests — ``GET /.well-known/axon-capabilities.json`` (Fase 21.d).

axon-namespaced extension to the standard discovery surface. Public,
unauthenticated. Every advertised value is introspected from a real
source — registry / enum / package metadata. No fabricated values.

Tests verify three properties:

1. **Honest introspection**: when a probe (``axon-lang`` package, Shield
   registry) is unavailable, the field is ``null`` — not a fake value.
   We exercise this via monkeypatch.

2. **Live registry reflection**: when the registry IS available (the
   default in this test env), we get a sane, sorted list with no
   accidental duplication.

3. **Standard well-known doc semantics**: Cache-Control, ETag,
   conditional 304 (matches OIDC + OAuth siblings).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from starlette.applications import Starlette
from starlette.routing import Route

from axon_enterprise.http.discovery import (
    CAPABILITIES_SCHEMA_VERSION,
    capabilities_endpoint,
)
from axon_enterprise.http.discovery import capabilities as caps_module


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = Starlette(
        routes=[
            Route(
                "/.well-known/axon-capabilities.json",
                capabilities_endpoint,
                methods=["GET"],
            )
        ]
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


# ── 1. Endpoint reachability + content type ──────────────────────────


@pytest.mark.asyncio
async def test_endpoint_returns_200_with_json(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/.well-known/axon-capabilities.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert isinstance(resp.json(), dict)


# ── 2. axon_enterprise_version reflects __version__ ─────────────────


@pytest.mark.asyncio
async def test_axon_enterprise_version_matches_package(
    client: httpx.AsyncClient,
) -> None:
    from axon_enterprise import __version__

    body = (await client.get("/.well-known/axon-capabilities.json")).json()
    assert body["axon_enterprise_version"] == __version__


# ── 3. axon_lang_installed_version is a string when installed ────────


@pytest.mark.asyncio
async def test_axon_lang_installed_version_present(
    client: httpx.AsyncClient,
) -> None:
    """axon-lang is a hard dep per pyproject; in this test env we expect
    a string version. The endpoint returns ``null`` only when the package
    is uninstallable — see the negative test below."""
    body = (await client.get("/.well-known/axon-capabilities.json")).json()
    assert body["axon_lang_installed_version"] is not None
    assert isinstance(body["axon_lang_installed_version"], str)
    # Looks like a semver (x.y.z) — not a strict check, just a sanity
    # guard against accidentally returning the package name or a path.
    parts = body["axon_lang_installed_version"].split(".")
    assert len(parts) >= 2
    assert parts[0].isdigit()


# ── 4. axon_lang_installed_version → null on probe failure ───────────


@pytest.mark.asyncio
async def test_axon_lang_version_null_on_probe_failure(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``importlib.metadata.version`` raises (package missing),
    advertise ``null`` rather than a fabricated version. Honest probe."""
    monkeypatch.setattr(
        caps_module,
        "_axon_lang_installed_version",
        lambda: None,
    )
    body = (await client.get("/.well-known/axon-capabilities.json")).json()
    assert body["axon_lang_installed_version"] is None


# ── 5. SSO providers list matches the SsoProviderType enum ───────────


@pytest.mark.asyncio
async def test_sso_providers_supported_matches_enum(
    client: httpx.AsyncClient,
) -> None:
    from axon_enterprise.sso.models import SsoProviderType

    body = (await client.get("/.well-known/axon-capabilities.json")).json()
    expected = sorted(p.value for p in SsoProviderType)
    assert body["sso_providers_supported"] == expected
    # Defensive: enum currently has oidc + saml; if either drops,
    # advertisement should reflect — and the production removal
    # would be the kind of change that needs a deliberate review.
    assert "oidc" in body["sso_providers_supported"]
    assert "saml" in body["sso_providers_supported"]


# ── 6. Shield strategies are sorted, deduplicated, non-empty ─────────


@pytest.mark.asyncio
async def test_shield_strategies_sorted_unique_nonempty(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/.well-known/axon-capabilities.json")).json()
    strategies = body["shield_strategies_supported"]
    # In this test env axon-lang is installed → strategies present.
    assert strategies is not None
    assert len(strategies) > 0
    assert strategies == sorted(strategies)
    assert len(set(strategies)) == len(strategies)
    # Sanity: the Fase 20 OSS baseline strategies must be there.
    for required in ("pattern", "canary"):
        assert required in strategies


# ── 7. Shield categories include the well-known prompt_injection ─────


@pytest.mark.asyncio
async def test_shield_categories_include_core(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/.well-known/axon-capabilities.json")).json()
    cats = body["shield_categories_supported"]
    assert cats is not None
    assert cats == sorted(cats)  # sorted invariant
    # Categories any production install must register (Fase 20 baseline).
    for required in ("prompt_injection", "pii_leak", "capability_validate"):
        assert required in cats


# ── 8. Shield fields → null when registry probe fails ────────────────


@pytest.mark.asyncio
async def test_shield_fields_null_on_registry_failure(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the Shield registry import fails (axon-lang missing), both
    shield fields advertise ``null`` — never a stale or fabricated list."""
    monkeypatch.setattr(caps_module, "_shield_registry_known", lambda: None)
    body = (await client.get("/.well-known/axon-capabilities.json")).json()
    assert body["shield_strategies_supported"] is None
    assert body["shield_categories_supported"] is None


# ── 9. Discovery endpoints lists all 4 well-known docs ───────────────


@pytest.mark.asyncio
async def test_discovery_endpoints_lists_all_published(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/.well-known/axon-capabilities.json")).json()
    eps = body["discovery_endpoints"]
    assert eps["openid_configuration"] == "/.well-known/openid-configuration"
    assert (
        eps["oauth_authorization_server"]
        == "/.well-known/oauth-authorization-server"
    )
    assert eps["jwks"] == "/.well-known/jwks.json"
    assert eps["capabilities"] == "/.well-known/axon-capabilities.json"


# ── 10. Cache-Control public + ETag + If-None-Match → 304 ────────────


@pytest.mark.asyncio
async def test_cache_control_etag_and_conditional_304(
    client: httpx.AsyncClient,
) -> None:
    """Capabilities doc has no tenant-scoped data, so ``public`` cache
    is correct — intermediaries can serve it across consumers."""
    first = await client.get("/.well-known/axon-capabilities.json")
    cache_control = first.headers.get("cache-control", "")
    assert "public" in cache_control
    assert "max-age=" in cache_control
    etag = first.headers.get("etag", "")
    assert etag.startswith('"') and etag.endswith('"')
    assert len(etag) == 66  # "<sha256-hex-64>"

    second = await client.get(
        "/.well-known/axon-capabilities.json",
        headers={"If-None-Match": etag},
    )
    assert second.status_code == 304
    assert second.headers["etag"] == etag
    assert second.content == b""


# ── 11. (bonus) schema version constant exposed ─────────────────────


@pytest.mark.asyncio
async def test_schema_version_present(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/.well-known/axon-capabilities.json")).json()
    assert (
        body["axon_capabilities_schema_version"] == CAPABILITIES_SCHEMA_VERSION
    )
