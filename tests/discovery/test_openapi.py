"""Tests — ``GET /openapi.json``, ``/docs``, ``/redoc`` (Fase 21.e).

Hand-built OpenAPI 3.1.0 spec. Tests verify:

- Top-level OpenAPI 3.x structure is valid (root keys present).
- info.version reflects ``axon_enterprise.__version__`` (drift gate).
- Fase 21 endpoints have first-class Path Item entries with schemas.
- The bearer auth security scheme is defined and applied to the
  authenticated endpoint.
- Swagger UI and ReDoc renderer pages return 200 HTML.

The OpenAPI spec is hand-built rather than auto-generated (axon-enterprise
uses pure Starlette, no FastAPI). Drift between code and spec is the
primary risk; sub-fase 21.g (drift gate) will assert that every mounted
route appears in the spec and vice-versa.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from starlette.applications import Starlette
from starlette.routing import Route

from axon_enterprise.http.discovery import (
    OPENAPI_VERSION,
    openapi_endpoint,
    redoc_endpoint,
    swagger_ui_endpoint,
)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = Starlette(
        routes=[
            Route("/openapi.json", openapi_endpoint, methods=["GET"]),
            Route("/docs", swagger_ui_endpoint, methods=["GET"]),
            Route("/redoc", redoc_endpoint, methods=["GET"]),
        ]
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


# ── 1. /openapi.json returns 200 + JSON ──────────────────────────────


@pytest.mark.asyncio
async def test_openapi_returns_200_json(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    spec = resp.json()
    assert isinstance(spec, dict)


# ── 2. Valid OpenAPI 3.x root structure ──────────────────────────────


@pytest.mark.asyncio
async def test_openapi_root_keys_valid(
    client: httpx.AsyncClient,
) -> None:
    spec = (await client.get("/openapi.json")).json()
    # OpenAPI 3.x mandates: openapi (version string), info, paths.
    # components is optional but we publish it.
    assert spec["openapi"] == OPENAPI_VERSION
    assert "info" in spec and isinstance(spec["info"], dict)
    assert "paths" in spec and isinstance(spec["paths"], dict)
    assert "components" in spec
    assert "securitySchemes" in spec["components"]
    assert "schemas" in spec["components"]
    # Tags are optional but we publish a curated list — verify structure.
    assert isinstance(spec.get("tags", []), list)


# ── 3. info.version reflects axon-enterprise __version__ ─────────────


@pytest.mark.asyncio
async def test_info_version_matches_package(
    client: httpx.AsyncClient,
) -> None:
    from axon_enterprise import __version__

    spec = (await client.get("/openapi.json")).json()
    assert spec["info"]["version"] == __version__
    assert "axon-enterprise" in spec["info"]["title"].lower()


# ── 4. Fase 21 endpoints documented as first-class paths ─────────────


@pytest.mark.asyncio
async def test_fase21_endpoints_documented_with_schemas(
    client: httpx.AsyncClient,
) -> None:
    """Each Fase 21-owned endpoint must (a) appear in ``paths``, (b) have
    a documented 200 response, and (c) reference its component schema.
    Stub paths from other fases are excluded — only Fase 21's contract."""
    spec = (await client.get("/openapi.json")).json()
    paths = spec["paths"]

    expectations = [
        ("/.well-known/openid-configuration", "OidcDiscoveryDocument"),
        ("/.well-known/oauth-authorization-server", "OAuthServerMetadata"),
        ("/.well-known/axon-capabilities.json", "AxonCapabilities"),
        ("/.well-known/jwks.json", "JwksDocument"),
        ("/api/v1/tenant/me/integration-context/", "IntegrationContext"),
    ]
    for path, schema_name in expectations:
        assert path in paths, f"missing path: {path}"
        get_op = paths[path]["get"]
        assert "200" in get_op["responses"]
        ref = get_op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        assert ref == f"#/components/schemas/{schema_name}", (
            f"{path} 200 response should reference {schema_name}, got {ref}"
        )
        # Component schema must actually exist in components.
        assert schema_name in spec["components"]["schemas"], (
            f"referenced schema {schema_name} missing from components.schemas"
        )


# ── 5. Bearer auth scheme defined + applied to authenticated route ──


@pytest.mark.asyncio
async def test_bearer_auth_defined_and_applied(
    client: httpx.AsyncClient,
) -> None:
    spec = (await client.get("/openapi.json")).json()
    schemes = spec["components"]["securitySchemes"]
    assert "bearerAuth" in schemes
    assert schemes["bearerAuth"]["type"] == "http"
    assert schemes["bearerAuth"]["scheme"] == "bearer"
    assert schemes["bearerAuth"]["bearerFormat"] == "JWT"

    # The integration-context endpoint is authenticated — must declare
    # bearerAuth in its security requirements + a 401 response.
    op = spec["paths"]["/api/v1/tenant/me/integration-context/"]["get"]
    assert {"bearerAuth": []} in op["security"]
    assert "401" in op["responses"]


# ── 6. Public discovery endpoints DON'T declare security ────────────


@pytest.mark.asyncio
async def test_public_endpoints_have_no_security(
    client: httpx.AsyncClient,
) -> None:
    """Discovery endpoints must NOT declare security — they're public.
    Falsely declaring security on a public endpoint would cause SDK
    auto-generators to insert auth where none is needed."""
    spec = (await client.get("/openapi.json")).json()
    for path in (
        "/.well-known/openid-configuration",
        "/.well-known/oauth-authorization-server",
        "/.well-known/axon-capabilities.json",
        "/.well-known/jwks.json",
    ):
        op = spec["paths"][path]["get"]
        assert "security" not in op, f"{path} should not declare security"


# ── 7. /docs serves Swagger UI HTML referencing /openapi.json ───────


@pytest.mark.asyncio
async def test_swagger_ui_serves_html(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/docs")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    assert "swagger-ui" in body.lower()
    assert "/openapi.json" in body
    # Pinned version constants from docs_ui.py — pinning stops accidental
    # transitive bumps via the CDN's "latest" tag.
    assert "swagger-ui-dist@" in body


# ── 8. /redoc serves ReDoc HTML referencing /openapi.json ───────────


@pytest.mark.asyncio
async def test_redoc_serves_html(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/redoc")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    assert "<redoc" in body
    assert "/openapi.json" in body
    assert "redoc@" in body
