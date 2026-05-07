"""Tests for v1.15.3 path-template matcher + dispatcher integration.

Two layers:

1. **Unit** — exercises ``axon.server.path_matcher`` directly:
   ``compile_template``, ``match_path``, ``canonical_template``,
   ``detect_template_collisions``. Pure functions, no I/O.

2. **Dispatcher integration** — builds a Starlette app via the real
   ``axon.server.http_app.create_app`` factory wired to a tiny stub
   ``AxonServer``-shaped object that exposes only the surface the
   dispatcher touches. Drives requests through ``httpx.ASGITransport``
   so the assertions cover the full request → ``_resolve_endpoint``
   → path-param injection → flow invocation pipeline.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import pytest_asyncio

from axon.server.http_app import create_app
from axon.server.path_matcher import (
    canonical_template,
    compile_template,
    detect_template_collisions,
    match_path,
)


# ═══════════════════════════════════════════════════════════════════
#  Layer 1 — path_matcher unit tests
# ═══════════════════════════════════════════════════════════════════


def test_compile_template_extracts_param_names_in_order() -> None:
    regex, names = compile_template("/api/orders/{order_id}/items/{item_id}")
    assert names == ["order_id", "item_id"]
    m = regex.match("/api/orders/abc/items/xyz")
    assert m is not None
    assert m.groupdict() == {"order_id": "abc", "item_id": "xyz"}


def test_compile_template_rejects_duplicate_param_names() -> None:
    """Two ``{id}`` in the same template makes the captured name
    ambiguous — Python regex would also raise. Surface a clear error
    at compile time."""
    with pytest.raises(ValueError, match="more than once"):
        compile_template("/api/{id}/sub/{id}")


def test_match_path_single_param_happy_path() -> None:
    assert match_path("/api/tenants/{tenant_id}", "/api/tenants/acme") == {
        "tenant_id": "acme"
    }


def test_match_path_multi_param_happy_path() -> None:
    got = match_path(
        "/api/orgs/{org}/projects/{project}", "/api/orgs/bemarking/projects/axon"
    )
    assert got == {"org": "bemarking", "project": "axon"}


def test_match_path_returns_none_for_no_match() -> None:
    assert match_path("/api/tenants/{tenant_id}", "/api/users/me") is None
    assert match_path("/api/tenants/{tenant_id}", "/api/tenants") is None


def test_match_path_rejects_empty_param_value() -> None:
    """``/api/tenants/{tenant_id}`` must NOT match
    ``/api/tenants/`` — the trailing-slash variant is structurally a
    different route. The regex requires at least one character per
    parameter ([^/]+)."""
    assert match_path("/api/tenants/{tenant_id}", "/api/tenants/") is None


def test_match_path_does_not_consume_slashes() -> None:
    """Path parameters must not greedily swallow path segments. ``{id}``
    does NOT match ``abc/def`` — that would route a 2-segment URL to
    a 3-segment template."""
    assert (
        match_path("/api/tenants/{tenant_id}", "/api/tenants/abc/def") is None
    )


def test_match_path_handles_url_encoded_values() -> None:
    """Starlette URL-decodes path before passing to handlers, so the
    matcher sees decoded values. Our regex accepts any non-slash
    character, including unicode."""
    assert match_path("/api/users/{name}", "/api/users/John%20Doe") == {
        "name": "John%20Doe"
    }
    assert match_path("/api/users/{name}", "/api/users/josé") == {
        "name": "josé"
    }


def test_match_path_literal_no_params_acts_as_equality() -> None:
    """A template with no ``{}`` placeholders behaves exactly like
    string equality — preserves pre-v1.15.3 behaviour for
    template-free endpoints."""
    assert match_path("/api/me", "/api/me") == {}
    assert match_path("/api/me", "/api/other") is None


def test_canonical_template_collapses_param_names() -> None:
    assert canonical_template("/api/users/{id}") == "/api/users/{*}"
    assert canonical_template("/api/users/{id}") == canonical_template(
        "/api/users/{user_id}"
    )
    # Multi-param shapes also collapse.
    assert canonical_template("/api/{a}/sub/{b}") == "/api/{*}/sub/{*}"
    # Literal templates are unchanged.
    assert canonical_template("/api/me") == "/api/me"


def test_detect_template_collisions_flags_duplicate_canonical_paths() -> None:
    """Two endpoints with structurally identical paths under the same
    method are reported. The dispatcher takes the first registered, so
    the second is silently dead — surface the bug at deploy time."""
    collisions = detect_template_collisions(
        [
            ("get_user_v1", "GET", "/api/users/{id}"),
            ("get_user_v2", "GET", "/api/users/{user_id}"),
            ("create_user", "POST", "/api/users/{id}"),  # different method, ok
            ("get_me", "GET", "/api/me"),
        ]
    )
    # One collision: GET on the canonical /api/users/{*}
    assert collisions == {("GET", "/api/users/{*}"): ["get_user_v1", "get_user_v2"]}


def test_detect_template_collisions_returns_empty_when_clean() -> None:
    assert (
        detect_template_collisions(
            [
                ("get_user", "GET", "/api/users/{id}"),
                ("create_user", "POST", "/api/users"),
                ("get_me", "GET", "/api/me"),
            ]
        )
        == {}
    )


# ═══════════════════════════════════════════════════════════════════
#  Layer 2 — dispatcher integration via create_app + stub server
# ═══════════════════════════════════════════════════════════════════


@dataclass
class _StubEndpoint:
    """Mirrors the surface ``EndpointInfo`` exposes to the dispatcher."""
    name: str
    method: str
    path: str
    execute_flow: str = "stub_flow"
    output_type: str = "object"


@dataclass
class _StubResult:
    """Mirrors the surface ``EndpointExecutionResult`` exposes."""
    success: bool = True
    status_code: int = 200
    response: Any = None
    error: str = ""
    duration_ms: float = 1.0


@dataclass
class _StubConfig:
    """Mirrors the surface ``AuthMiddleware`` reads at request time.
    Empty ``auth_token`` skips auth entirely — the dispatcher tests
    aren't about auth, they're about routing."""
    auth_token: str = ""


@dataclass
class _StubServer:
    """Tiny ``AxonServer``-shaped stub. Only the surface
    ``dispatch_endpoint`` + ``AuthMiddleware`` touch is implemented;
    everything else can raise ``AttributeError`` if accidentally hit."""
    endpoints: list[_StubEndpoint] = field(default_factory=list)
    is_running: bool = True
    last_payload: dict[str, Any] | None = None
    last_endpoint: _StubEndpoint | None = None
    recorded_events: list[dict[str, Any]] = field(default_factory=list)
    config: _StubConfig = field(default_factory=_StubConfig)

    async def start(self) -> None:
        self.is_running = True

    async def stop(self) -> None:
        self.is_running = False

    def list_endpoints(self) -> list[_StubEndpoint]:
        return list(self.endpoints)

    async def execute_endpoint_request(
        self,
        endpoint: _StubEndpoint,
        *,
        payload: dict[str, Any],
        trace_id: str,
    ) -> _StubResult:
        self.last_endpoint = endpoint
        self.last_payload = dict(payload)
        return _StubResult(
            success=True,
            status_code=200,
            response={"echoed": payload},
        )

    def record_endpoint_event(self, *args: Any, **kwargs: Any) -> None:
        self.recorded_events.append({"args": args, "kwargs": kwargs})


@pytest_asyncio.fixture
async def make_client():  # noqa: ANN201
    """Yield a factory that wires a fresh app + httpx client per test.

    Each call returns ``(client, stub_server)`` so tests can both
    drive requests and inspect what the dispatcher passed downstream.
    """
    clients: list[httpx.AsyncClient] = []

    async def _factory(
        endpoints: list[_StubEndpoint],
    ) -> tuple[httpx.AsyncClient, _StubServer]:
        server = _StubServer(endpoints=endpoints)
        app = create_app(server)
        transport = httpx.ASGITransport(app=app)
        client = httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        )
        clients.append(client)
        return client, server

    yield _factory

    for c in clients:
        await c.aclose()


# ── Dispatcher: single param GET → param injected into payload ──────


@pytest.mark.asyncio
async def test_dispatcher_extracts_single_path_param_into_payload(
    make_client,
) -> None:
    client, server = await make_client(
        [_StubEndpoint(name="get_tenant", method="GET", path="/api/tenants/{tenant_id}")]
    )
    resp = await client.get("/api/tenants/acme")
    assert resp.status_code == 200
    assert server.last_payload == {"tenant_id": "acme"}


# ── Dispatcher: multi-param POST → all injected ────────────────────


@pytest.mark.asyncio
async def test_dispatcher_extracts_multi_param_with_body(make_client) -> None:
    client, server = await make_client(
        [
            _StubEndpoint(
                name="add_item",
                method="POST",
                path="/api/orgs/{org}/projects/{project}/items",
            )
        ]
    )
    resp = await client.post(
        "/api/orgs/bemarking/projects/axon/items",
        json={"item_name": "shield", "qty": 3},
    )
    assert resp.status_code == 200
    assert server.last_payload == {
        "item_name": "shield",
        "qty": 3,
        "org": "bemarking",
        "project": "axon",
    }


# ── Dispatcher: exact match wins over template ─────────────────────


@pytest.mark.asyncio
async def test_dispatcher_exact_match_wins_over_template(make_client) -> None:
    """``/api/users/me`` and ``/api/users/{id}`` both could route
    ``/api/users/me``. Exact match must win — the explicit handler
    is the operator's intent."""
    client, server = await make_client(
        [
            # Order doesn't matter; exact match is preferred regardless.
            _StubEndpoint(name="get_user_by_id", method="GET", path="/api/users/{id}"),
            _StubEndpoint(name="get_self", method="GET", path="/api/users/me"),
        ]
    )
    resp = await client.get("/api/users/me")
    assert resp.status_code == 200
    assert server.last_endpoint is not None
    assert server.last_endpoint.name == "get_self"
    assert server.last_payload == {}  # no path params extracted


# ── Dispatcher: unknown path still 404 ─────────────────────────────


@pytest.mark.asyncio
async def test_dispatcher_unknown_path_returns_404(make_client) -> None:
    client, _ = await make_client(
        [_StubEndpoint(name="get_user", method="GET", path="/api/users/{id}")]
    )
    resp = await client.get("/api/orders/123")
    assert resp.status_code == 404


# ── Dispatcher: DELETE with empty body + path params works ─────────


@pytest.mark.asyncio
async def test_dispatcher_delete_with_empty_body_and_path_param(
    make_client,
) -> None:
    """Pre-v1.15.3 the dispatcher rejected non-GET requests without
    a JSON body, blocking the natural ``DELETE /api/users/{id}``
    pattern. v1.15.3 treats empty body as ``{}``; path params then
    flow through normally."""
    client, server = await make_client(
        [_StubEndpoint(name="delete_user", method="DELETE", path="/api/users/{id}")]
    )
    resp = await client.delete("/api/users/abc-123")
    assert resp.status_code == 200
    assert server.last_payload == {"id": "abc-123"}


# ── Dispatcher: shadow warning surfaces in logger ──────────────────


@pytest.mark.asyncio
async def test_dispatcher_warns_when_path_param_shadows_body_key(
    make_client, caplog
) -> None:
    """If both the path and the body declare ``user_id``, path wins
    silently (HTTP convention) BUT the dispatcher logs a warning so
    the adopter notices the override."""
    import logging

    client, server = await make_client(
        [_StubEndpoint(name="upsert_user", method="POST", path="/api/users/{user_id}")]
    )
    with caplog.at_level(logging.WARNING, logger="axon.server.http_app"):
        resp = await client.post(
            "/api/users/from-path",
            json={"user_id": "from-body", "name": "alice"},
        )
    assert resp.status_code == 200
    # Path value wins on the merged payload.
    assert server.last_payload == {"user_id": "from-path", "name": "alice"}
    # Warning was emitted naming the shadowed key.
    warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("user_id" in msg and "shadow" in msg for msg in warning_messages), (
        f"expected shadow warning for 'user_id'; got: {warning_messages!r}"
    )


# ── Dispatcher: literal endpoint with no params still works ────────


@pytest.mark.asyncio
async def test_dispatcher_literal_endpoint_without_params(make_client) -> None:
    """Pre-v1.15.3 behaviour preserved for endpoints declared with
    fully literal paths (the only kind that worked before)."""
    client, server = await make_client(
        [_StubEndpoint(name="health", method="GET", path="/api/health")]
    )
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert server.last_payload == {}
