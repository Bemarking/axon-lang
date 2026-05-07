"""Tests — ``GET /.well-known/oauth-authorization-server`` (Fase 21.b).

OAuth 2.0 Authorization Server Metadata per RFC 8414. Public, no auth.
Document derives from ``get_settings()`` and overlaps with the OIDC
discovery doc on shared fields. Cross-doc consistency is asserted here
at unit level; the full drift gate (sub-fase 21.g) verifies it
end-to-end at app build time.
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
    OAUTH_METADATA_SCHEMA_VERSION,
    oauth_authorization_server_endpoint,
    openid_configuration_endpoint,
)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = Starlette(
        routes=[
            Route(
                "/.well-known/oauth-authorization-server",
                oauth_authorization_server_endpoint,
                methods=["GET"],
            ),
            Route(
                "/.well-known/openid-configuration",
                openid_configuration_endpoint,
                methods=["GET"],
            ),
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
    resp = await client.get("/.well-known/oauth-authorization-server")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")


# ── 2. RFC 8414 required + recommended fields present ────────────────


@pytest.mark.asyncio
async def test_doc_has_rfc8414_required_fields(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/.well-known/oauth-authorization-server")
    body = resp.json()
    # RFC 8414 §2 — issuer + response_types_supported are mandatory
    # for any AS that issues access tokens. We also include the
    # recommended ones a typical M2M client expects.
    required = {
        "issuer",
        "response_types_supported",
        "token_endpoint",
        "grant_types_supported",
        "token_endpoint_auth_methods_supported",
    }
    missing = required - body.keys()
    assert not missing, f"RFC 8414 required fields missing: {missing}"


# ── 3. Cross-doc consistency with OIDC discovery ─────────────────────


@pytest.mark.asyncio
async def test_consistency_with_oidc_discovery(
    client: httpx.AsyncClient,
) -> None:
    """Issuer, jwks_uri, token_endpoint, authorization_endpoint, scopes
    must be byte-identical between the two discovery docs. Adopters
    consuming either standard see the same values."""
    oauth = (await client.get("/.well-known/oauth-authorization-server")).json()
    oidc = (await client.get("/.well-known/openid-configuration")).json()
    for shared in (
        "issuer",
        "jwks_uri",
        "token_endpoint",
        "authorization_endpoint",
        "scopes_supported",
    ):
        assert oauth[shared] == oidc[shared], (
            f"OAuth metadata and OIDC discovery diverge on {shared!r}"
        )


# ── 4. Grant types reflect what the auth flows actually support ──────


@pytest.mark.asyncio
async def test_grant_types_supported(
    client: httpx.AsyncClient,
) -> None:
    """The Portal API exposes /auth/login (password), /auth/refresh
    (refresh_token), and /sso/oidc/* (authorization_code). All three
    must be advertised so OAuth clients know which flows are valid."""
    resp = await client.get("/.well-known/oauth-authorization-server")
    grants = set(resp.json()["grant_types_supported"])
    assert {"password", "refresh_token", "authorization_code"} <= grants


# ── 5. Cache-Control + ETag headers ──────────────────────────────────


@pytest.mark.asyncio
async def test_cache_control_and_etag_headers_present(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/.well-known/oauth-authorization-server")
    cache_control = resp.headers.get("cache-control", "")
    assert "public" in cache_control
    assert "max-age=" in cache_control
    etag = resp.headers.get("etag", "")
    assert etag.startswith('"') and etag.endswith('"')
    assert len(etag) == 66  # "<sha256-hex 64>"


# ── 6. Conditional request: If-None-Match → 304 ──────────────────────


@pytest.mark.asyncio
async def test_if_none_match_returns_304(
    client: httpx.AsyncClient,
) -> None:
    first = await client.get("/.well-known/oauth-authorization-server")
    etag = first.headers["etag"]
    second = await client.get(
        "/.well-known/oauth-authorization-server",
        headers={"If-None-Match": etag},
    )
    assert second.status_code == 304
    assert second.headers["etag"] == etag
    assert second.content == b""


# ── 7. (bonus) Axon-specific extension fields present ────────────────


@pytest.mark.asyncio
async def test_axon_extension_fields_present(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/.well-known/oauth-authorization-server")
    body = resp.json()
    assert "axon_enterprise_version" in body
    assert isinstance(body["axon_enterprise_version"], str)
    assert (
        body["axon_oauth_metadata_schema_version"]
        == OAUTH_METADATA_SCHEMA_VERSION
    )


# ── 8. (bonus) Issuer matches settings ───────────────────────────────


@pytest.mark.asyncio
async def test_issuer_matches_settings(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/.well-known/oauth-authorization-server")
    body = resp.json()
    assert body["issuer"] == get_settings().jwt.issuer.rstrip("/")
