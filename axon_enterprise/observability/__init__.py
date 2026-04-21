"""Observability wiring — Fase 10.i.

Replaces the v1.0.0 ``MetricsCollector`` scaffolding (in-memory
dicts, ``# TODO: Send to metrics backend``) with real Prometheus
metrics, OTel tracing with tenant baggage, and structlog-driven
JSON logging with ContextVar-aware correlation keys.

Cardinality contract
--------------------
``tenant_id`` is a label on **counters** (usage events, quota
denials, rate limits, audit writes, HTTP requests) but NEVER on
**histograms** (request duration, DB query duration). A histogram
with high-cardinality labels explodes Prometheus memory — the
combination of metric name × bucket × label cardinality is the
classic ops-lesson. Per-tenant latency SLIs come from exemplars or
tail-sampled traces, not from labels.
"""

from axon_enterprise.observability.decorators import instrument
from axon_enterprise.observability.healthz import (
    HealthStatus,
    build_healthz_asgi_app,
    build_readyz_asgi_app,
    check_readiness,
)
from axon_enterprise.observability.logging import (
    clear_log_context,
    configure_logging,
    get_logger,
    set_log_context,
)
from axon_enterprise.observability.metrics import (
    AUDIT_EVENTS_TOTAL,
    DB_QUERIES_TOTAL,
    FLOW_EXECUTIONS_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
    LLM_TOKENS_TOTAL,
    QUOTA_DENIALS_TOTAL,
    RATE_LIMITS_TOTAL,
    build_metrics_asgi_app,
    default_registry,
)
from axon_enterprise.observability.middleware import (
    ObservabilityMiddleware,
    current_request_id,
)
from axon_enterprise.observability.tracing import (
    configure_tracing,
    get_tracer,
    set_tenant_baggage,
    shutdown_tracing,
)

__all__ = [
    "AUDIT_EVENTS_TOTAL",
    "DB_QUERIES_TOTAL",
    "FLOW_EXECUTIONS_TOTAL",
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION_SECONDS",
    "HealthStatus",
    "LLM_TOKENS_TOTAL",
    "ObservabilityMiddleware",
    "QUOTA_DENIALS_TOTAL",
    "RATE_LIMITS_TOTAL",
    "build_healthz_asgi_app",
    "build_metrics_asgi_app",
    "build_readyz_asgi_app",
    "check_readiness",
    "clear_log_context",
    "configure_logging",
    "configure_tracing",
    "current_request_id",
    "default_registry",
    "get_logger",
    "get_tracer",
    "instrument",
    "set_log_context",
    "set_tenant_baggage",
    "shutdown_tracing",
]
