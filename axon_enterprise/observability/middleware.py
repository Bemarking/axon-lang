"""ASGI middleware that wires metrics + logging + tracing per request.

Responsibilities per request
----------------------------
1. Resolve / generate the ``X-Request-ID`` header. Clients that
   supply one (typically a gateway) have their value propagated
   through; otherwise we mint a UUID so correlation keys are
   always present.
2. Push correlation keys into the log ContextVars (``request_id``,
   plus ``tenant_id`` / ``user_id`` when the upstream extractors
   have run).
3. Start an OTel span scoped to the HTTP request + attach the
   baggage keys so every downstream span inherits them.
4. Increment the HTTP counters on completion + observe the
   duration histogram.
5. Clear the log + tracing context on exit so the next request on
   the same worker starts clean.

The middleware is defensive: failures in the observability layer
never fail the request. A broken metric push produces a warning
log but the handler's response is unaffected.
"""

from __future__ import annotations

import contextvars
import time
import uuid
from typing import Any, Awaitable, Callable

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from axon_enterprise.config import ObservabilitySettings, get_settings
from axon_enterprise.observability.logging import (
    _LOG_CONTEXT,
    set_log_context,
)
from axon_enterprise.observability.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
)
from axon_enterprise.observability.tracing import (
    get_tracer,
    set_tenant_baggage,
)

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.observability.middleware"
)


# Public contextvar so handlers can read the current request id
# without going through the headers.
_CURRENT_REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "axon.current_request_id", default=None
)


def current_request_id() -> str | None:
    return _CURRENT_REQUEST_ID.get()


class ObservabilityMiddleware:
    """Pure ASGI middleware — no Starlette ``BaseHTTPMiddleware``.

    ``BaseHTTPMiddleware`` buffers the response body and has documented
    quirks with streaming responses + background tasks. Pure ASGI is
    leaner and plays well with SSE / WebSockets that our flow
    execution endpoints use.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: ObservabilitySettings | None = None,
    ) -> None:
        self.app = app
        self.settings = settings or get_settings().observability

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method: str = scope["method"]
        path: str = _safe_path(scope)
        request_id = _extract_request_id(scope, self.settings.request_id_header)

        log_token = set_log_context(
            request_id=request_id,
            method=method,
            path=path,
        )
        req_id_token = _CURRENT_REQUEST_ID.set(request_id)
        baggage_token = set_tenant_baggage(
            tenant_id=None,  # TenantExtractor sets real tenant downstream
            user_id=None,
            request_id=request_id,
        )

        tracer = get_tracer("axon_enterprise.http")
        span_cm = tracer.start_as_current_span(f"{method} {path}")
        status_code_holder: list[int] = [500]

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_code_holder[0] = int(message["status"])
                headers = list(message.get("headers") or [])
                headers.append(
                    (
                        self.settings.request_id_header.lower().encode("ascii"),
                        request_id.encode("ascii"),
                    )
                )
                message = {**message, "headers": headers}
            await send(message)

        started = time.perf_counter()
        try:
            with span_cm as span:
                span.set_attribute("http.method", method)
                span.set_attribute("http.route", path)
                span.set_attribute("axon.request_id", request_id)
                try:
                    await self.app(scope, receive, _send)
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(_status_error(str(exc)))
                    status_code_holder[0] = 500
                    raise
        finally:
            duration = time.perf_counter() - started
            self._record(
                method=method,
                path=path,
                status=status_code_holder[0],
                duration=duration,
            )
            if baggage_token is not None:
                try:
                    from opentelemetry import context as otel_context

                    otel_context.detach(baggage_token)
                except Exception:  # noqa: BLE001
                    pass
            _LOG_CONTEXT.reset(log_token)
            _CURRENT_REQUEST_ID.reset(req_id_token)

    # ── Internals ─────────────────────────────────────────────────────

    def _record(
        self, *, method: str, path: str, status: int, duration: float
    ) -> None:
        try:
            from axon_enterprise.tenant import current_tenant_or_none

            tenant_ctx = current_tenant_or_none()
            tenant_label = tenant_ctx.tenant_id if tenant_ctx else "unknown"
            HTTP_REQUESTS_TOTAL.labels(
                tenant_id=tenant_label,
                method=method,
                path=path,
                status=str(status),
            ).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(
                method=method, path=path
            ).observe(duration)
        except Exception as exc:  # noqa: BLE001
            # Observability must never fail a request. Log + move on.
            _logger.warning("observability_record_failed", error=str(exc))


# ── Helpers ───────────────────────────────────────────────────────────


def _extract_request_id(scope: Scope, header_name: str) -> str:
    """Return the inbound request id header or mint a fresh uuid4."""
    needle = header_name.lower().encode("ascii")
    for name, value in scope.get("headers") or []:
        if name == needle:
            try:
                return value.decode("ascii")
            except UnicodeDecodeError:
                break
    return str(uuid.uuid4())


def _safe_path(scope: Scope) -> str:
    """Prefer the Starlette route path template when available.

    Starlette populates ``scope["route"]`` with the ``APIRoute`` /
    ``Route`` for matched paths. Using the template keeps
    ``axon_http_requests_total{path="/tenants/{id}"}`` cardinality
    bounded. Fall back to the raw path for 404s.
    """
    route = scope.get("route")
    if route is not None:
        template = getattr(route, "path", None)
        if template:
            return template
    return str(scope.get("path") or "/unknown")


def _status_error(description: str) -> Any:
    try:
        from opentelemetry.trace import Status, StatusCode

        return Status(StatusCode.ERROR, description)
    except ImportError:  # pragma: no cover
        return None
