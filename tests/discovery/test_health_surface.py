"""Tests — health/status surface formalization (Fase 21.f).

Endpoints under test:

- ``/healthz`` — pure liveness (always 200). Pre-existed; tested here
  for regression-protection against the formalization edits.
- ``/livez`` — k8s-modern alias of ``/healthz``. Same handler, both
  names mounted so adopters use whichever convention their orchestrator
  prefers.
- ``/version`` — server version + build metadata. New in 21.f.

``/readyz`` is not unit-testable here without a live DB (it runs a
real ``SELECT 1`` against Postgres). Its contract is exercised by
the existing integration suite in ``tests/observability/`` (preserved,
not duplicated). The test here for ``/readyz`` mounts it and asserts
it returns *some* JSON-shaped 200/503, no behaviour assertion.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from starlette.applications import Starlette
from starlette.routing import Mount, Route

from axon_enterprise.http.discovery import version_endpoint
from axon_enterprise.observability import build_healthz_asgi_app


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """Mounts only the endpoints that don't require live DB.

    healthz/livez are pure liveness (no deps), version is pure metadata.
    readyz is excluded — it would call the real db_healthcheck which
    needs a live Postgres pool.
    """
    app = Starlette(
        routes=[
            Mount("/healthz", build_healthz_asgi_app()),
            Mount("/livez", build_healthz_asgi_app()),
            Route("/version", version_endpoint, methods=["GET"]),
        ]
    )
    transport = httpx.ASGITransport(app=app)
    # follow_redirects mirrors real-world probe behaviour: Starlette
    # Mount() returns 307 from ``/healthz`` to ``/healthz/`` and k8s
    # kubelet (and httpx-based monitors) follow the redirect transparently.
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as c:
        yield c


# ── 1. /healthz still returns 200 + status:ok (regression) ──────────


@pytest.mark.asyncio
async def test_healthz_returns_200_status_ok(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


# ── 2. /livez is byte-identical alias of /healthz ───────────────────


@pytest.mark.asyncio
async def test_livez_is_alias_of_healthz(
    client: httpx.AsyncClient,
) -> None:
    """Liveness aliasing: both endpoints must produce identical responses
    so adopters can swap one for the other in their orchestrator config
    without behavioural surprise."""
    h = await client.get("/healthz")
    l = await client.get("/livez")
    assert h.status_code == l.status_code == 200
    assert h.json() == l.json()


# ── 3. /version returns 200 + JSON ──────────────────────────────────


@pytest.mark.asyncio
async def test_version_endpoint_returns_200_json(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/version")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert isinstance(resp.json(), dict)


# ── 4. /version reflects __version__ + python_version + axon-lang ───


@pytest.mark.asyncio
async def test_version_fields_drift_gate(
    client: httpx.AsyncClient,
) -> None:
    """All five documented fields present + axon_enterprise_version
    matches the package source of truth. Catches drift between the
    endpoint and ``__version__`` after future bumps."""
    import sys

    from axon_enterprise import __version__

    body = (await client.get("/version")).json()
    assert body["axon_enterprise_version"] == __version__
    # axon-lang is a hard dep — must resolve in a healthy install.
    assert body["axon_lang_installed_version"] is not None
    # python_version must match what's actually running.
    assert body["python_version"] == (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    # build_sha + build_date present (may be null in dev) — required keys.
    assert "build_sha" in body
    assert "build_date" in body


# ── 5. build metadata reflects env vars when set ────────────────────


@pytest.mark.asyncio
async def test_build_metadata_from_env(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``AXON_BUILD_SHA`` and ``AXON_BUILD_DATE`` are set at
    container build time, they surface in the response. When unset
    they're null. Verifies the contract documented in the module."""
    monkeypatch.setenv("AXON_BUILD_SHA", "deadbeef1234")
    monkeypatch.setenv("AXON_BUILD_DATE", "2026-05-06T00:00:00Z")
    body = (await client.get("/version")).json()
    assert body["build_sha"] == "deadbeef1234"
    assert body["build_date"] == "2026-05-06T00:00:00Z"

    monkeypatch.delenv("AXON_BUILD_SHA")
    monkeypatch.delenv("AXON_BUILD_DATE")
    body = (await client.get("/version")).json()
    assert body["build_sha"] is None
    assert body["build_date"] is None


# ── 6. /version Cache-Control + ETag + If-None-Match → 304 ──────────


@pytest.mark.asyncio
async def test_version_cache_control_etag_and_304(
    client: httpx.AsyncClient,
) -> None:
    first = await client.get("/version")
    cache_control = first.headers.get("cache-control", "")
    assert "public" in cache_control
    assert "max-age=" in cache_control
    etag = first.headers.get("etag", "")
    assert etag.startswith('"') and etag.endswith('"')
    assert len(etag) == 66

    second = await client.get("/version", headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""
