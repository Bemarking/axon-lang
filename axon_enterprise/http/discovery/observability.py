"""Discovery + integration-context observability (Fase 21.h).

Wraps Fase 21 endpoints with structured-log + Prometheus instrumentation
so SRE can detect adopter integration patterns + misconfigurations
without doxxing individual consumers.

Privacy discipline (D7):

- ``user-agent`` is *never* logged in full. We classify into a small
  set of labels (``browser`` / ``sdk`` / ``cli`` / ``unknown``) so we
  can see "lots of CLI hits to capabilities" without keeping verbose
  fingerprints.
- ``remote-addr`` is *never* logged in full. We anonymize to a /24
  (IPv4) or /48 (IPv6) so we can detect a misconfigured adopter coming
  from one subnet without identifying individual users in that subnet.
- Tokens / ``Authorization`` header / response body are never logged.

Prometheus metrics live in the shared ``default_registry`` so the
existing ``/metrics`` endpoint serves them too. Label cardinality
contract follows the ``observability/metrics.py`` convention:
counters carry tenant_slug labels (sparse, per-tenant series); histograms do not.
"""

from __future__ import annotations

import functools
import ipaddress
import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from prometheus_client import Counter, Histogram
from starlette.requests import Request
from starlette.responses import Response

from axon_enterprise.identity.principal import current_principal_or_none
from axon_enterprise.observability.metrics import default_registry

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.http.discovery"
)


# ── Prometheus metrics ──────────────────────────────────────────────

DISCOVERY_REQUESTS_TOTAL: Counter = Counter(
    "axon_discovery_requests_total",
    "Discovery doc fetches by doc name and HTTP status.",
    labelnames=("doc", "status"),
    registry=default_registry,
)

# No tenant label on the histogram — same cardinality discipline as
# HTTP_REQUEST_DURATION_SECONDS in observability/metrics.py.
DISCOVERY_REQUEST_DURATION_SECONDS: Histogram = Histogram(
    "axon_discovery_request_duration_seconds",
    "Discovery doc fetch latency by doc name.",
    labelnames=("doc",),
    registry=default_registry,
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

TENANT_INTEGRATION_CONTEXT_REQUESTS_TOTAL: Counter = Counter(
    "axon_tenant_integration_context_requests_total",
    "Integration-context fetches by tenant slug and HTTP status.",
    labelnames=("tenant_slug", "status"),
    registry=default_registry,
)


# ── Privacy helpers ─────────────────────────────────────────────────

_BROWSER_MARKERS = ("mozilla", "chrome", "safari", "firefox", "edge", "webkit")
_CLI_MARKERS = ("curl", "wget", "httpie", "axon-cli")
_SDK_MARKERS = (
    "python-requests",
    "python/",
    "httpx",
    "axios",
    "go-http-client",
    "okhttp",
    "java/",
    "node-fetch",
    "ruby",
)


def classify_user_agent(ua: str | None) -> str:
    """Classify a User-Agent into a small fixed-cardinality label.

    The order matters: CLI tools and SDK clients sometimes embed
    "mozilla" tokens, so we check for unambiguous CLI / SDK markers
    first and fall back to browser / unknown last.
    """
    if not ua:
        return "unknown"
    ua_l = ua.lower()
    if any(marker in ua_l for marker in _CLI_MARKERS):
        return "cli"
    if any(marker in ua_l for marker in _SDK_MARKERS):
        return "sdk"
    if any(marker in ua_l for marker in _BROWSER_MARKERS):
        return "browser"
    return "unknown"


def anonymize_ip(ip: str | None) -> str | None:
    """Truncate an IP to a /24 (IPv4) or /48 (IPv6) network for logging.

    /24 keeps about 256 hosts indistinguishable from each other —
    enough granularity to detect a misconfigured corporate egress
    without identifying individual users behind it.
    """
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    prefix = 24 if isinstance(addr, ipaddress.IPv4Address) else 48
    return str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))


# ── Wrappers ────────────────────────────────────────────────────────

_HandlerT = Callable[[Request], Awaitable[Response]]


def with_discovery_observability(doc_name: str, handler: _HandlerT) -> _HandlerT:
    """Wrap a discovery endpoint handler so each invocation emits a
    ``discovery.fetched`` structured event + bumps Prometheus counters.
    """

    @functools.wraps(handler)
    async def wrapped(request: Request) -> Response:
        start = time.monotonic()
        ua_class = classify_user_agent(request.headers.get("user-agent"))
        ip_anon = anonymize_ip(request.client.host if request.client else None)
        status = 500
        try:
            response = await handler(request)
            status = response.status_code
            return response
        finally:
            elapsed_s = time.monotonic() - start
            DISCOVERY_REQUESTS_TOTAL.labels(doc=doc_name, status=str(status)).inc()
            DISCOVERY_REQUEST_DURATION_SECONDS.labels(doc=doc_name).observe(elapsed_s)
            _logger.info(
                "discovery.fetched",
                doc=doc_name,
                ua_class=ua_class,
                remote_ip_anon=ip_anon,
                status=status,
                ms=round(elapsed_s * 1000, 2),
            )

    return wrapped


def with_integration_context_observability(handler: _HandlerT) -> _HandlerT:
    """Wrap the integration-context handler with tenant-scoped telemetry.

    The principal is set by ``AuthMiddleware`` *before* the handler runs.
    On a 401 (no principal installed) we record ``tenant_slug='unknown'``
    so the metric still increments — the spike pattern is still visible.
    """

    @functools.wraps(handler)
    async def wrapped(request: Request) -> Response:
        start = time.monotonic()
        ua_class = classify_user_agent(request.headers.get("user-agent"))
        ip_anon = anonymize_ip(request.client.host if request.client else None)
        status = 500
        tenant_slug = "unknown"
        try:
            response = await handler(request)
            status = response.status_code
            principal = current_principal_or_none()
            if principal is not None:
                tenant_slug = principal.tenant_id
            return response
        except Exception:
            principal = current_principal_or_none()
            if principal is not None:
                tenant_slug = principal.tenant_id
            raise
        finally:
            TENANT_INTEGRATION_CONTEXT_REQUESTS_TOTAL.labels(
                tenant_slug=tenant_slug, status=str(status)
            ).inc()
            _logger.info(
                "tenant.integration_context.fetched",
                tenant_slug=tenant_slug,
                ua_class=ua_class,
                remote_ip_anon=ip_anon,
                status=status,
                ms=round((time.monotonic() - start) * 1000, 2),
            )

    return wrapped


# ── Test helpers ────────────────────────────────────────────────────


def reset_metrics_for_test() -> None:
    """Zero out the counters/histograms — pytest fixture support.

    Prometheus client doesn't expose a public reset API; we walk the
    private ``_metrics`` dict to clear per-label series. Safe in tests
    because the registry is module-global and we want test isolation.
    """
    for metric in (
        DISCOVERY_REQUESTS_TOTAL,
        DISCOVERY_REQUEST_DURATION_SECONDS,
        TENANT_INTEGRATION_CONTEXT_REQUESTS_TOTAL,
    ):
        metric._metrics.clear()  # type: ignore[attr-defined]


def metric_value(counter: Counter, **labels: Any) -> float:
    """Read the current value of a labelled counter for assertions."""
    return counter.labels(**labels)._value.get()  # type: ignore[attr-defined]
