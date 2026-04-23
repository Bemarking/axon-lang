"""Unit test — ``GET /api/v1/primitives`` returns every catalogue.

No auth required (the endpoint is in the PORTAL_PUBLIC_PATHS set)
so the test builds a minimal Starlette app + calls it directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from starlette.applications import Starlette
from starlette.routing import Mount

from axon_enterprise.http.api import build_api_router


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = Starlette(routes=[Mount("/api/v1", routes=build_api_router())])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_primitives_endpoint_lists_every_catalog(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/api/v1/primitives/")
    assert resp.status_code == 200
    body = resp.json()

    assert body["service"] == "axon-enterprise"
    assert "service_version" in body

    catalogs = body["catalogs"]
    # The four closed catalogues shipped in Fase 11.a / 11.c / 11.e.
    assert set(catalogs["trust_proofs"]) == {
        "hmac",
        "jwt_sig",
        "oauth_code_exchange",
        "ed25519",
    }
    assert set(catalogs["backpressure_policies"]) == {
        "drop_oldest",
        "degrade_quality",
        "pause_upstream",
        "fail",
    }
    # LegalBasis is 21 slugs — sanity check count + presence of a
    # few representative entries.
    assert len(catalogs["legal_bases"]) == 21
    for slug in [
        "GDPR.Art6.Consent",
        "HIPAA.164_502",
        "SOX.404",
        "PCI_DSS.v4_Req3",
    ]:
        assert slug in catalogs["legal_bases"]
    assert set(catalogs["ots_backends"]) == {"native", "ffmpeg"}


@pytest.mark.asyncio
async def test_primitives_endpoint_lists_seeded_buffer_kinds(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/api/v1/primitives/")
    assert resp.status_code == 200
    body = resp.json()
    kinds = set(body["registries"]["buffer_kinds_seeded"])
    # Must include the full 11.b seeded catalogue.
    for slug in [
        "raw",
        "pcm16",
        "mulaw8",
        "wav",
        "mp3",
        "opus",
        "jpeg",
        "png",
        "webp",
        "mp4",
        "webm",
        "pdf",
        "json",
        "csv",
    ]:
        assert slug in kinds


@pytest.mark.asyncio
async def test_primitives_response_is_cacheable(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/api/v1/primitives/")
    # Aggressive cache — content is stable per deploy; version is
    # the revalidation key encoded in the body.
    assert "public" in resp.headers.get("cache-control", "")
    assert "max-age" in resp.headers.get("cache-control", "")


@pytest.mark.asyncio
async def test_primitives_meta_documents_catalog_policies(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/api/v1/primitives/")
    body = resp.json()
    policies = body["meta"]["catalog_policies"]
    # Closed catalogues must be flagged "closed"; buffer kinds are
    # the one open registry.
    assert "closed" in policies["trust_proofs"]
    assert "closed" in policies["backpressure_policies"]
    assert "closed" in policies["legal_bases"]
    assert "closed" in policies["ots_backends"]
    assert "open" in policies["buffer_kinds"]
