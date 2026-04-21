"""Middleware + healthz tests — pure ASGI, no Starlette app needed."""

from __future__ import annotations

import json

import pytest

from axon_enterprise.config import ObservabilitySettings
from axon_enterprise.observability import (
    ObservabilityMiddleware,
    build_healthz_asgi_app,
    current_request_id,
)
from axon_enterprise.observability.middleware import _CURRENT_REQUEST_ID


# ── ASGI helpers ────────────────────────────────────────────────────


def _make_scope(
    path: str = "/", method: str = "GET", headers: list[tuple[bytes, bytes]] | None = None
) -> dict:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
        "query_string": b"",
        "route": None,
    }


async def _receive() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}


# ── ObservabilityMiddleware ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_generates_request_id_when_missing() -> None:
    captured: dict[str, str] = {}

    async def app(scope, receive, send) -> None:
        captured["rid"] = current_request_id() or ""
        await send(
            {"type": "http.response.start", "status": 200, "headers": []}
        )
        await send({"type": "http.response.body", "body": b""})

    mw = ObservabilityMiddleware(app, settings=ObservabilitySettings())
    messages: list[dict] = []

    async def send(message) -> None:  # noqa: ANN001
        messages.append(message)

    await mw(_make_scope("/healthz"), _receive, send)
    assert len(captured["rid"]) > 0
    # Must appear in response headers too
    start = messages[0]
    header_names = [h[0] for h in start["headers"]]
    assert b"x-request-id" in header_names


@pytest.mark.asyncio
async def test_preserves_inbound_request_id() -> None:
    captured: dict[str, str] = {}

    async def app(scope, receive, send) -> None:
        captured["rid"] = current_request_id() or ""
        await send(
            {"type": "http.response.start", "status": 200, "headers": []}
        )
        await send({"type": "http.response.body", "body": b""})

    mw = ObservabilityMiddleware(app, settings=ObservabilitySettings())

    async def send(message) -> None:  # noqa: ANN001
        pass

    scope = _make_scope(
        "/x", headers=[(b"x-request-id", b"upstream-req-1")]
    )
    await mw(scope, _receive, send)
    assert captured["rid"] == "upstream-req-1"


@pytest.mark.asyncio
async def test_request_id_cleared_after_response() -> None:
    async def app(scope, receive, send) -> None:
        await send(
            {"type": "http.response.start", "status": 200, "headers": []}
        )
        await send({"type": "http.response.body", "body": b""})

    mw = ObservabilityMiddleware(app, settings=ObservabilitySettings())

    async def send(message) -> None:  # noqa: ANN001
        pass

    await mw(_make_scope("/"), _receive, send)
    assert _CURRENT_REQUEST_ID.get() is None


@pytest.mark.asyncio
async def test_metrics_incremented_on_response() -> None:
    from axon_enterprise.observability.metrics import HTTP_REQUESTS_TOTAL

    before = HTTP_REQUESTS_TOTAL.labels(
        tenant_id="unknown", method="GET", path="/probe", status="200"
    )._value.get()  # type: ignore[attr-defined]

    async def app(scope, receive, send) -> None:
        await send(
            {"type": "http.response.start", "status": 200, "headers": []}
        )
        await send({"type": "http.response.body", "body": b""})

    mw = ObservabilityMiddleware(app, settings=ObservabilitySettings())

    async def send(message) -> None:  # noqa: ANN001
        pass

    await mw(_make_scope("/probe"), _receive, send)
    after = HTTP_REQUESTS_TOTAL.labels(
        tenant_id="unknown", method="GET", path="/probe", status="200"
    )._value.get()  # type: ignore[attr-defined]
    assert after == before + 1


@pytest.mark.asyncio
async def test_non_http_scope_passes_through() -> None:
    calls: list[str] = []

    async def app(scope, receive, send) -> None:
        calls.append(scope["type"])

    mw = ObservabilityMiddleware(app, settings=ObservabilitySettings())

    async def send(_m) -> None:  # noqa: ANN001
        pass

    await mw({"type": "lifespan"}, _receive, send)
    assert calls == ["lifespan"]


@pytest.mark.asyncio
async def test_exception_still_cleans_context() -> None:
    async def app(scope, receive, send) -> None:
        raise RuntimeError("boom")

    mw = ObservabilityMiddleware(app, settings=ObservabilitySettings())

    async def send(_m) -> None:  # noqa: ANN001
        pass

    with pytest.raises(RuntimeError):
        await mw(_make_scope("/"), _receive, send)
    assert _CURRENT_REQUEST_ID.get() is None


# ── Healthz ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_healthz_always_returns_200() -> None:
    app = build_healthz_asgi_app()
    messages: list[dict] = []

    async def send(m) -> None:  # noqa: ANN001
        messages.append(m)

    await app(_make_scope("/healthz"), _receive, send)
    assert messages[0]["status"] == 200
    body = b"".join(m.get("body", b"") for m in messages if "body" in m)
    parsed = json.loads(body)
    assert parsed["status"] == "ok"
