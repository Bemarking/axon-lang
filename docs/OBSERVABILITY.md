# Observability — Operator Guide

Prometheus metrics + OpenTelemetry tracing + structured JSON logs,
all three wired via a single ASGI middleware. Replaces the v1.0.0
`MetricsCollector` scaffolding (in-memory dicts with
`# TODO: send to backend`) with a production-grade pipeline.

## Architecture

```
Request ──► ObservabilityMiddleware
               │  request_id := inbound X-Request-ID  OR  uuid4()
               │  structlog ContextVar: tenant_id, user_id, request_id
               │  OTel baggage: axon.tenant_id, axon.user_id,
               │                axon.request_id
               │  OTel span: "<METHOD> <route-template>"
               │  prometheus counters + histograms recorded on exit
               ▼
           Handler
               │
               ▼
           Service code (uses get_logger, @instrument)
               │
               ▼
   Exporters
     - /metrics    (Prometheus scrape target)
     - OTLP→gRPC   (otel-collector sidecar, fans out to vendor)
     - stdout      (fluentd/vector collects, ships to SIEM)
```

## Cardinality contract

| Metric | `tenant_id` label? | Rationale |
|---|---|---|
| `axon_http_requests_total` | ✅ | Counters scale per-series cheaply |
| `axon_http_request_duration_seconds` | ❌ | Histogram × tenants × buckets explodes memory |
| `axon_flow_executions_total` | ✅ | Counter; operator needs tenant breakdown |
| `axon_llm_tokens_total` | ✅ | Counter with `provider` + `direction` |
| `axon_quota_denials_total` | ✅ | Counter with `metric` + `reason` |
| `axon_rate_limits_total` | ✅ | Counter with `metric` |
| `axon_audit_events_total` | ✅ | Counter with `event_type` + `status` |
| `axon_db_queries_total` | ❌ | Infra signal, not tenant-facing |
| `axon_db_query_duration_seconds` | ❌ | Histogram — same rule as HTTP |

Per-tenant latency SLIs come from OTel exemplars + tail-sampled
traces, not from labels. This keeps Prometheus memory bounded even
at 10k+ tenants.

## Metric prefix

Every metric starts with `axon_` — matches what the Rust runtime
emits. One Prometheus rule file covers both planes.

## Middleware wiring

```python
from starlette.applications import Starlette
from starlette.routing import Mount, Route

from axon_enterprise.observability import (
    ObservabilityMiddleware,
    build_healthz_asgi_app,
    build_metrics_asgi_app,
    build_readyz_asgi_app,
    configure_logging,
    configure_tracing,
)

configure_logging()
configure_tracing()

app = Starlette(
    routes=[
        Route("/flows/{flow_id}", handler),
        Mount("/healthz", build_healthz_asgi_app()),
        Mount("/readyz",  build_readyz_asgi_app()),
        Mount("/metrics", build_metrics_asgi_app()),
    ],
)
app.add_middleware(ObservabilityMiddleware)
```

Order matters: `ObservabilityMiddleware` must be outermost so
metrics + tracing span the full request lifetime including error
handlers. ``TenantExtractor`` (10.a) and auth middleware (10.e)
install BELOW it so their ContextVars are visible to the log +
baggage push on exit.

## Structured logs

```python
from axon_enterprise.observability import get_logger, set_log_context

log = get_logger(__name__)
set_log_context(tenant_id=ctx.tenant_id, user_id=principal.user_id)

log.info("flow_executed", flow_id=str(flow.flow_id), duration_ms=42)
```

Output (JSON format):

```json
{
  "event": "flow_executed",
  "level": "info",
  "timestamp": "2026-04-21T12:34:56.789Z",
  "tenant_id": "acme",
  "user_id": "00000000-0000-0000-0000-000000000042",
  "request_id": "req-abc-123",
  "flow_id": "...",
  "duration_ms": 42
}
```

Correlation keys (`tenant_id`, `user_id`, `request_id`) are bound
once by the middleware; every downstream log line inherits them
without explicit `.bind(...)` calls. The log context is cleared on
exit so subsequent requests on the same worker start clean.

## Tracing

`configure_tracing()` installs the OTel SDK when
`AXON_OBS_TRACING_ENABLED=true`. OTLP gRPC export goes to whatever
`AXON_OBS_OTLP_ENDPOINT` points at — typically the OTel Collector
sidecar on port 4317. When the variable is unset spans are still
generated in-process (useful for structured error capture) but not
exported.

Sampling: `trace_sampling_ratio` applies to successful requests.
Errors recorded on the span via `span.record_exception` flip the
status to `ERROR` which the Collector's tail-sampler can keep at
100%.

Baggage keys (`axon.tenant_id`, `axon.user_id`, `axon.request_id`)
propagate to spans created in downstream services and to outgoing
HTTP calls instrumented via `opentelemetry-instrumentation-httpx`.

## Healthz + readyz

| Endpoint | Behaviour | K8s use |
|---|---|---|
| `/healthz` | Always 200 when the process is up | `livenessProbe` — restart pod on crash |
| `/readyz` | 200 when DB / deps are reachable, 503 otherwise | `readinessProbe` — pull from service rotation on dependency outage |

Liveness never checks DB connectivity — that would create a
restart-loop on Postgres hiccups. Readiness is the correct signal
for "pull me out of the load balancer until my deps come back".

Extend `check_readiness()` in `observability/healthz.py` as new
critical dependencies are wired (Redis for the rate limiter, KMS
for the signer, etc.). Each probe is wrapped in its own try so
one failure does not short-circuit the rest.

## Required environment

### Dev / test
```
AXON_OBS_LOG_LEVEL=DEBUG
AXON_OBS_LOG_FORMAT=console
AXON_OBS_TRACING_ENABLED=false
AXON_OBS_METRICS_ENABLED=true
```

### Production
```
AXON_OBS_LOG_LEVEL=INFO
AXON_OBS_LOG_FORMAT=json
AXON_OBS_METRICS_ENABLED=true
AXON_OBS_METRICS_PATH=/metrics
AXON_OBS_TRACING_ENABLED=true
AXON_OBS_OTLP_ENDPOINT=http://otel-collector:4317
AXON_OBS_TRACE_SAMPLING_RATIO=0.1
AXON_OBS_REQUEST_ID_HEADER=X-Request-ID
```

## Prometheus scrape config

```yaml
scrape_configs:
  - job_name: axon-enterprise
    metrics_path: /metrics
    static_configs:
      - targets: ["axon-enterprise:8000"]
    scrape_interval: 15s
```

## K8s probe YAML

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 10
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /readyz
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 5
  failureThreshold: 2
```

## What comes next

- 10.j (Admin API) mounts the middleware + exporter at the HTTP
  layer and wires the full route set.
- 10.l (Compliance) adds retention rules for the log stream so
  audit events survive fluentd rotation.
