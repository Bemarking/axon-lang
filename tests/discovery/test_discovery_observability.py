"""Tests — discovery + integration-context observability (Fase 21.h).

Verifies that the wrapped endpoints emit the structured log events
described in D7 and increment the Prometheus counters described in
§3.6, with the privacy discipline strictly enforced (no full UA, no
full IP, no tokens).

Tests run against the bare endpoint + its wrapper applied directly
(no full app build, no DB) so they stay fast and unit-level.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
import structlog
from starlette.applications import Starlette
from starlette.routing import Route

from axon_enterprise.http.api.integration_context import (
    integration_context_endpoint,
)
from axon_enterprise.http.discovery import (
    DISCOVERY_REQUESTS_TOTAL,
    TENANT_INTEGRATION_CONTEXT_REQUESTS_TOTAL,
    anonymize_ip,
    capabilities_endpoint,
    classify_user_agent,
    with_discovery_observability,
    with_integration_context_observability,
)
from axon_enterprise.http.discovery.observability import (
    metric_value,
    reset_metrics_for_test,
)
from axon_enterprise.identity.principal import (
    CURRENT_PRINCIPAL,
    PrincipalContext,
    set_current_principal,
)


@pytest.fixture(autouse=True)
def _reset_metrics() -> None:
    """Each test sees fresh counters — registries are module-global."""
    reset_metrics_for_test()


@pytest_asyncio.fixture
async def discovery_client() -> AsyncIterator[httpx.AsyncClient]:
    app = Starlette(
        routes=[
            Route(
                "/.well-known/axon-capabilities.json",
                with_discovery_observability("axon-capabilities", capabilities_endpoint),
                methods=["GET"],
            )
        ]
    )
    transport = httpx.ASGITransport(app=app, client=("203.0.113.45", 12345))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


# ── 1. Discovery hit emits structured event with privacy discipline ──


@pytest.mark.asyncio
async def test_discovery_emits_structured_event_with_privacy(
    discovery_client: httpx.AsyncClient,
) -> None:
    """A successful discovery fetch emits exactly one ``discovery.fetched``
    event whose payload contains the documented fields and NEVER contains
    the raw User-Agent, full client IP, or any header that could carry a
    token."""
    real_ua = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 SuspiciousFingerprintXYZ"
    with structlog.testing.capture_logs() as captured:
        await discovery_client.get(
            "/.well-known/axon-capabilities.json",
            headers={
                "User-Agent": real_ua,
                "Authorization": "Bearer secret-token-must-not-leak",
            },
        )

    fetched = [e for e in captured if e.get("event") == "discovery.fetched"]
    assert len(fetched) == 1, "expected exactly one discovery.fetched event"
    event = fetched[0]
    # Required fields per the schema in D7 / §3.6.
    assert event["doc"] == "axon-capabilities"
    assert event["ua_class"] == "browser"
    assert event["remote_ip_anon"] == "203.0.113.0/24"
    assert event["status"] == 200
    assert isinstance(event["ms"], float)
    assert event["ms"] >= 0

    # Privacy discipline: serialize the entire event and verify no
    # leaks of raw UA, full IP, or bearer tokens.
    blob = repr(event)
    assert "SuspiciousFingerprintXYZ" not in blob, "raw UA leaked into log"
    assert "203.0.113.45" not in blob, "full IP leaked into log"
    assert "secret-token-must-not-leak" not in blob, "bearer token leaked into log"


# ── 2. Discovery hit increments per-doc Prometheus counter ───────────


@pytest.mark.asyncio
async def test_discovery_increments_prometheus_counter(
    discovery_client: httpx.AsyncClient,
) -> None:
    before = metric_value(
        DISCOVERY_REQUESTS_TOTAL, doc="axon-capabilities", status="200"
    )
    await discovery_client.get("/.well-known/axon-capabilities.json")
    await discovery_client.get("/.well-known/axon-capabilities.json")
    after = metric_value(
        DISCOVERY_REQUESTS_TOTAL, doc="axon-capabilities", status="200"
    )
    assert after - before == pytest.approx(2.0)


# ── 3. UA classifier covers browser / sdk / cli / unknown ────────────


def test_ua_classifier_buckets() -> None:
    """The classifier is the source of truth for the ``ua_class`` label;
    drift in this function would silently change observability semantics."""
    cases = [
        # browsers
        ("Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/127.0", "browser"),
        ("Mozilla/5.0 (Windows NT 10.0) Firefox/128.0", "browser"),
        # SDKs
        ("python-requests/2.31.0", "sdk"),
        ("httpx/0.27.2", "sdk"),
        ("axios/1.7.0", "sdk"),
        ("Go-http-client/2.0", "sdk"),
        # CLIs
        ("curl/8.5.0", "cli"),
        ("Wget/1.21.4", "cli"),
        ("HTTPie/3.2.2", "cli"),
        # Unknown / empty
        ("", "unknown"),
        (None, "unknown"),
        ("MysteryProbe/1.0", "unknown"),
    ]
    for ua, expected in cases:
        got = classify_user_agent(ua)
        assert got == expected, f"classify_user_agent({ua!r}): want {expected!r} got {got!r}"


# ── 4. IP anonymizer truncates to /24 (v4) and /48 (v6) ──────────────


def test_ip_anonymizer_truncates_to_safe_prefix() -> None:
    """IPv4 → /24, IPv6 → /48. None / malformed → None. Privacy invariant
    a future contributor could easily break by widening the prefix; the
    test pins the safe defaults."""
    assert anonymize_ip("203.0.113.45") == "203.0.113.0/24"
    assert anonymize_ip("198.51.100.7") == "198.51.100.0/24"
    assert anonymize_ip("2001:db8:1234:5678::1") == "2001:db8:1234::/48"
    assert anonymize_ip(None) is None
    assert anonymize_ip("") is None
    assert anonymize_ip("not-an-ip") is None


# ── 5. integration-context emits tenant-scoped event + counter ───────


@pytest.mark.asyncio
async def test_integration_context_observability() -> None:
    """The wrapped integration-context handler emits a
    ``tenant.integration_context.fetched`` event including the
    tenant_slug and bumps the per-tenant counter."""

    # Stub middleware that installs the principal so the handler returns 200.
    class _StubAuth:
        def __init__(self, app, principal: PrincipalContext) -> None:
            self.app = app
            self.principal = principal

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return
            from axon_enterprise.tenant import (
                CURRENT_TENANT,
                TenantContext,
                TenantPlan,
                set_current_tenant,
            )

            ptoken = set_current_principal(self.principal)
            ttoken = set_current_tenant(
                TenantContext(tenant_id=self.principal.tenant_id, plan=TenantPlan.ENTERPRISE)
            )
            try:
                await self.app(scope, receive, send)
            finally:
                CURRENT_PRINCIPAL.reset(ptoken)
                CURRENT_TENANT.reset(ttoken)

    principal = PrincipalContext(
        user_id=uuid4(),
        email="admin@acme.example",
        tenant_id="acme",
        role_names=frozenset({"owner"}),
    )

    app = Starlette(
        routes=[
            Route(
                "/api/v1/tenant/me/integration-context/",
                with_integration_context_observability(integration_context_endpoint),
                methods=["GET"],
            )
        ]
    )
    app.add_middleware(_StubAuth, principal=principal)
    transport = httpx.ASGITransport(app=app, client=("198.51.100.7", 9999))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        with structlog.testing.capture_logs() as captured:
            resp = await c.get("/api/v1/tenant/me/integration-context/")

    assert resp.status_code == 200
    events = [e for e in captured if e.get("event") == "tenant.integration_context.fetched"]
    assert len(events) == 1
    event = events[0]
    assert event["tenant_slug"] == "acme"
    assert event["status"] == 200
    assert event["remote_ip_anon"] == "198.51.100.0/24"

    counter_val = metric_value(
        TENANT_INTEGRATION_CONTEXT_REQUESTS_TOTAL,
        tenant_slug="acme",
        status="200",
    )
    assert counter_val == pytest.approx(1.0)


# ── 6. Wrapper records status of error responses too ────────────────


@pytest.mark.asyncio
async def test_discovery_wrapper_records_non_200_status(
    discovery_client: httpx.AsyncClient,
) -> None:
    """When the inner handler returns 304 (cache hit), the wrapper still
    increments the ``status='304'`` series + emits the event with status
    304. The metric must distinguish cache hits from real fetches."""
    first = await discovery_client.get("/.well-known/axon-capabilities.json")
    etag = first.headers["etag"]

    with structlog.testing.capture_logs() as captured:
        second = await discovery_client.get(
            "/.well-known/axon-capabilities.json",
            headers={"If-None-Match": etag},
        )

    assert second.status_code == 304
    events = [e for e in captured if e.get("event") == "discovery.fetched"]
    assert len(events) == 1
    assert events[0]["status"] == 304

    val = metric_value(
        DISCOVERY_REQUESTS_TOTAL, doc="axon-capabilities", status="304"
    )
    assert val == pytest.approx(1.0)
