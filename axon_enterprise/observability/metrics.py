"""Typed Prometheus metric registries.

Replaces the v1.0.0 ``MetricsCollector`` in-memory scaffolding
with a real ``prometheus_client.CollectorRegistry``. Every metric
is declared at module import time so the Prometheus dashboards that
scrape us never see a "metric not yet registered" gap after boot.

Naming convention
-----------------
``axon_*`` prefix shared with the Rust runtime (§axon-rs emits the
same prefix) so one Prometheus rule file covers both planes.

Label cardinality contract
--------------------------
- ``tenant_id`` label on **counters only**. Counters are sparse and
  Prometheus handles per-label series cheaply.
- ``tenant_id`` is NOT a label on histograms. A histogram of
  ``request duration`` × ``tenant_id`` × ``10 buckets`` explodes
  memory at ~1k tenants. Per-tenant latency comes from OTel
  exemplars + trace sampling, not from label cardinality.
- ``path`` on HTTP metrics is the route template (``/tenants/{id}``),
  not the raw URL. The middleware guards against cardinality
  explosion from unrouted 404s.

Available registries
--------------------
All metrics live in a single ``default_registry`` so ``/metrics``
serves the whole suite in one scrape. Subsystems may create private
registries for test isolation via ``CollectorRegistry()``.
"""

from __future__ import annotations

from typing import Any

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    make_asgi_app,
)

# ── Registry ──────────────────────────────────────────────────────────

default_registry: CollectorRegistry = CollectorRegistry(auto_describe=True)


# ── HTTP surface ─────────────────────────────────────────────────────

HTTP_REQUESTS_TOTAL: Counter = Counter(
    "axon_http_requests_total",
    "HTTP requests processed by the service.",
    labelnames=("tenant_id", "method", "path", "status"),
    registry=default_registry,
)

# No tenant_id label on the latency histogram — see docstring.
HTTP_REQUEST_DURATION_SECONDS: Histogram = Histogram(
    "axon_http_request_duration_seconds",
    "HTTP request latency.",
    labelnames=("method", "path"),
    registry=default_registry,
    buckets=(
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
    ),
)


# ── DB ───────────────────────────────────────────────────────────────

DB_QUERIES_TOTAL: Counter = Counter(
    "axon_db_queries_total",
    "Database queries issued by the service.",
    labelnames=("operation", "outcome"),  # tenant omitted — infra signal
    registry=default_registry,
)

DB_QUERY_DURATION_SECONDS: Histogram = Histogram(
    "axon_db_query_duration_seconds",
    "Database query latency.",
    labelnames=("operation",),
    registry=default_registry,
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
)


# ── Flows + LLM ──────────────────────────────────────────────────────

FLOW_EXECUTIONS_TOTAL: Counter = Counter(
    "axon_flow_executions_total",
    "Flow executions broken down by outcome.",
    labelnames=("tenant_id", "status"),
    registry=default_registry,
)

LLM_TOKENS_TOTAL: Counter = Counter(
    "axon_llm_tokens_total",
    "LLM tokens consumed.",
    labelnames=("tenant_id", "provider", "direction"),
    registry=default_registry,
)


# ── Quota + rate limits ─────────────────────────────────────────────

QUOTA_DENIALS_TOTAL: Counter = Counter(
    "axon_quota_denials_total",
    "Quota-enforcement denials (hard_cap plans hitting their ceiling).",
    labelnames=("tenant_id", "metric", "reason"),
    registry=default_registry,
)

RATE_LIMITS_TOTAL: Counter = Counter(
    "axon_rate_limits_total",
    "Per-minute rate limiter denials.",
    labelnames=("tenant_id", "metric"),
    registry=default_registry,
)


# ── Audit + SSO ──────────────────────────────────────────────────────

AUDIT_EVENTS_TOTAL: Counter = Counter(
    "axon_audit_events_total",
    "Audit events written to the hash-chained log.",
    labelnames=("tenant_id", "event_type", "status"),
    registry=default_registry,
)

SSO_LOGINS_TOTAL: Counter = Counter(
    "axon_sso_logins_total",
    "SSO logins grouped by provider + outcome.",
    labelnames=("tenant_id", "provider", "outcome"),
    registry=default_registry,
)


# ── §Fase 29.c — Parser-error telemetry counter ──────────────────────

PARSER_ERRORS_TOTAL: Counter = Counter(
    "axon_parser_errors_total",
    "Parser errors emitted by the OSS axon-lang parser, grouped by "
    "tenant + vertical + error code. NEVER carries source text in any "
    "label — privacy boundary documented in plan vivo D4.",
    labelnames=("tenant_id", "vertical", "code"),
    registry=default_registry,
)


# ── Infra gauges ─────────────────────────────────────────────────────

DB_POOL_CHECKED_OUT: Gauge = Gauge(
    "axon_db_pool_checked_out",
    "Connections currently checked out from the DB pool.",
    registry=default_registry,
)

BUILD_INFO: Gauge = Gauge(
    "axon_build_info",
    "Static build metadata — always 1, carries version/commit labels.",
    labelnames=("service", "version", "commit"),
    registry=default_registry,
)


# ── ASGI exporter ────────────────────────────────────────────────────


def build_metrics_asgi_app(registry: CollectorRegistry | None = None) -> Any:
    """Return an ASGI app that serves the Prometheus text exposition.

    Mount under the configured ``observability.metrics_path`` (default
    ``/metrics``). Uses the prometheus_client sample-returning ASGI
    wrapper which supports OpenMetrics negotiation via the
    ``Accept`` header.
    """
    return make_asgi_app(registry=registry or default_registry)
