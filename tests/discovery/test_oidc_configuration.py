"""Tests — ``GET /.well-known/openid-configuration`` (Fase 21.a).

Public OIDC Connect Discovery 1.0 endpoint. No auth required, derives
its document entirely from ``get_settings()``. The tests build a
minimal Starlette app with just the discovery route mounted — no DB,
no JWKS fetch, no middleware.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from starlette.applications import Starlette
from starlette.routing import Route

from axon_enterprise.config import get_settings
from axon_enterprise.http.discovery import (
    DISCOVERY_SCHEMA_VERSION,
    openid_configuration_endpoint,
)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = Starlette(
        routes=[
            Route(
                "/.well-known/openid-configuration",
                openid_configuration_endpoint,
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
    resp = await client.get("/.well-known/openid-configuration")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert isinstance(body, dict)


# ── 2. OIDC Connect Discovery 1.0 mandatory fields ───────────────────


@pytest.mark.asyncio
async def test_doc_has_all_oidc_required_fields(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/.well-known/openid-configuration")
    body = resp.json()
    # OIDC Connect Discovery 1.0 §3 mandatory metadata
    required = {
        "issuer",
        "authorization_endpoint",
        "token_endpoint",
        "jwks_uri",
        "response_types_supported",
        "subject_types_supported",
        "id_token_signing_alg_values_supported",
    }
    missing = required - body.keys()
    assert not missing, f"OIDC mandatory fields missing: {missing}"


# ── 3. Issuer reflects settings ──────────────────────────────────────


@pytest.mark.asyncio
async def test_issuer_matches_settings(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/.well-known/openid-configuration")
    body = resp.json()
    expected = get_settings().jwt.issuer.rstrip("/")
    assert body["issuer"] == expected


# ── 4. JWKS URI is derived from issuer ───────────────────────────────


@pytest.mark.asyncio
async def test_jwks_uri_derived_from_issuer(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/.well-known/openid-configuration")
    body = resp.json()
    issuer = get_settings().jwt.issuer.rstrip("/")
    assert body["jwks_uri"] == f"{issuer}/.well-known/jwks.json"


# ── 5. Signing algorithm reflects settings ───────────────────────────


@pytest.mark.asyncio
async def test_signing_algorithm_reflects_settings(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/.well-known/openid-configuration")
    body = resp.json()
    algs = body["id_token_signing_alg_values_supported"]
    assert algs == [get_settings().jwt.algorithm]


# ── 6. Audience supported reflects settings ──────────────────────────


@pytest.mark.asyncio
async def test_audience_supported_reflects_settings(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/.well-known/openid-configuration")
    body = resp.json()
    auds = body["audience_supported"]
    assert auds == [get_settings().jwt.audience]


# ── 7. Cache-Control + ETag headers ──────────────────────────────────


@pytest.mark.asyncio
async def test_cache_control_and_etag_headers_present(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/.well-known/openid-configuration")
    cache_control = resp.headers.get("cache-control", "")
    assert "public" in cache_control
    assert "max-age=" in cache_control
    etag = resp.headers.get("etag", "")
    # Strong ETag — sha256 hex inside double quotes (64 hex chars + 2 quotes)
    assert etag.startswith('"') and etag.endswith('"')
    assert len(etag) == 66


# ── 8. Conditional request: If-None-Match → 304 ──────────────────────


@pytest.mark.asyncio
async def test_if_none_match_returns_304(
    client: httpx.AsyncClient,
) -> None:
    first = await client.get("/.well-known/openid-configuration")
    etag = first.headers["etag"]
    second = await client.get(
        "/.well-known/openid-configuration",
        headers={"If-None-Match": etag},
    )
    assert second.status_code == 304
    assert second.headers["etag"] == etag
    assert "max-age=" in second.headers.get("cache-control", "")
    # 304 must have empty body
    assert second.content == b""


# ── 9. (bonus) Axon-specific extension fields present ────────────────


@pytest.mark.asyncio
async def test_axon_extension_fields_present(
    client: httpx.AsyncClient,
) -> None:
    """Adopters / SDKs use these to detect server version + discovery
    schema version, enabling forward-compatible behaviour."""
    resp = await client.get("/.well-known/openid-configuration")
    body = resp.json()
    assert "axon_enterprise_version" in body
    assert isinstance(body["axon_enterprise_version"], str)
    assert body["axon_discovery_schema_version"] == DISCOVERY_SCHEMA_VERSION
