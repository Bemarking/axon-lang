"""
Supervisor telemetry: OTel spans + Prometheus counters/gauges/histograms +
structlog JSON logs (Fase 16.e).

Cardinality contract follows the enterprise-wide convention (see
`axon_enterprise/observability/__init__.py`): `tenant_id` is allowed
on counters; histograms keep label cardinality low.

Metrics published:

  axon_supervisor_restarts_total{daemon, tenant, reason}        Counter
  axon_supervisor_active_daemons{tenant}                        Gauge
  axon_supervisor_restart_delay_seconds{tenant}                 Histogram
  axon_supervisor_state_snapshot_bytes{daemon}                  Histogram
  axon_supervisor_intensity_exceeded_total{daemon, tenant}      Counter

OTel spans wrap each lifecycle event with consistent attributes:
`daemon.name`, `daemon.tenant`, `daemon.attempt`, `daemon.outcome`,
`daemon.policy`, `daemon.exc_type`. Spans are short-lived (start/end
within the hook callback); long-lived span trees (e.g., the entire
daemon lifecycle) belong in calling code that may want to span the
restart cascade.
"""

from __future__ import annotations

from typing import Any

# Prometheus client is a hard dependency of axon-enterprise (see
# pyproject dependencies). Imports here are direct, not optional.
from prometheus_client import Counter, Gauge, Histogram

# OTel and structlog are also hard deps via observability/.
try:
    from opentelemetry import trace as _otel_trace
    _tracer = _otel_trace.get_tracer("axon_enterprise.supervisor")
except ImportError:  # pragma: no cover — defensive
    _tracer = None

try:
    import structlog
    _logger = structlog.get_logger("axon_enterprise.supervisor")
except ImportError:  # pragma: no cover — defensive
    import logging
    _logger = logging.getLogger("axon_enterprise.supervisor")


# ── Prometheus metrics (module-level, registered once) ──────────────

SUPERVISOR_RESTARTS_TOTAL: Counter = Counter(
    "axon_supervisor_restarts_total",
    "Total number of daemon restarts performed by the supervisor.",
    labelnames=("daemon", "tenant", "reason"),
)

SUPERVISOR_ACTIVE_DAEMONS: Gauge = Gauge(
    "axon_supervisor_active_daemons",
    "Number of daemons currently in the running state.",
    labelnames=("tenant",),
)

SUPERVISOR_RESTART_DELAY_SECONDS: Histogram = Histogram(
    "axon_supervisor_restart_delay_seconds",
    "Backoff delay applied before each restart, in seconds.",
    labelnames=("tenant",),
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

SUPERVISOR_STATE_SNAPSHOT_BYTES: Histogram = Histogram(
    "axon_supervisor_state_snapshot_bytes",
    "Serialized size of state snapshots taken across the crash boundary.",
    labelnames=("daemon",),
    buckets=(64, 256, 1024, 4096, 16384, 65536, 262144, 1048576),
)

SUPERVISOR_INTENSITY_EXCEEDED_TOTAL: Counter = Counter(
    "axon_supervisor_intensity_exceeded_total",
    "Number of times a daemon hit the restart-intensity cap and was given up.",
    labelnames=("daemon", "tenant"),
)


class SupervisorTelemetry:
    """Façade for emitting all three telemetry signals (metrics,
    traces, logs) from a single call site.

    Constructed once per `EnterpriseSupervisorHooks` instance and
    invoked from each lifecycle hook. The façade is purposely thin —
    no buffering, no batching — so failures surface immediately.
    """

    def __init__(
        self,
        *,
        tenant_resolver=None,
    ) -> None:
        # Optional callable: name → tenant_id. Defaults to '_global'.
        self._tenant_resolver = tenant_resolver or (lambda _: "_global")

    def _tenant_for(self, daemon_name: str) -> str:
        try:
            return str(self._tenant_resolver(daemon_name) or "_global")
        except Exception:
            return "_global"

    # ── Lifecycle emitters ─────────────────────────────────────────

    def emit_start(self, daemon_name: str, attempt: int) -> None:
        tenant = self._tenant_for(daemon_name)
        SUPERVISOR_ACTIVE_DAEMONS.labels(tenant=tenant).inc()
        self._log("daemon_start", daemon=daemon_name, tenant=tenant, attempt=attempt)
        self._span_event("supervisor.daemon.start", daemon=daemon_name, tenant=tenant, attempt=attempt)

    def emit_crash(
        self,
        daemon_name: str,
        exc: BaseException,
        attempt: int,
    ) -> None:
        tenant = self._tenant_for(daemon_name)
        reason = type(exc).__name__
        SUPERVISOR_RESTARTS_TOTAL.labels(
            daemon=daemon_name, tenant=tenant, reason=reason,
        ).inc()
        SUPERVISOR_ACTIVE_DAEMONS.labels(tenant=tenant).dec()
        self._log(
            "daemon_crash",
            daemon=daemon_name,
            tenant=tenant,
            attempt=attempt,
            exception_type=reason,
            exception_message=str(exc)[:512],
        )
        self._span_event(
            "supervisor.daemon.crash",
            daemon=daemon_name,
            tenant=tenant,
            attempt=attempt,
            exc_type=reason,
        )

    def emit_restart(
        self,
        daemon_name: str,
        attempt: int,
        delay_s: float,
    ) -> None:
        tenant = self._tenant_for(daemon_name)
        SUPERVISOR_RESTART_DELAY_SECONDS.labels(tenant=tenant).observe(delay_s)
        self._log(
            "daemon_restart",
            daemon=daemon_name,
            tenant=tenant,
            attempt=attempt,
            delay_seconds=delay_s,
        )
        self._span_event(
            "supervisor.daemon.restart",
            daemon=daemon_name, tenant=tenant, attempt=attempt, delay_s=delay_s,
        )

    def emit_intensity_exceeded(
        self,
        daemon_name: str,
        restart_count: int,
    ) -> None:
        tenant = self._tenant_for(daemon_name)
        SUPERVISOR_INTENSITY_EXCEEDED_TOTAL.labels(
            daemon=daemon_name, tenant=tenant,
        ).inc()
        self._log(
            "daemon_intensity_exceeded",
            daemon=daemon_name, tenant=tenant, restart_count=restart_count,
        )
        self._span_event(
            "supervisor.daemon.intensity_exceeded",
            daemon=daemon_name, tenant=tenant, restart_count=restart_count,
        )

    def emit_snapshot(
        self,
        daemon_name: str,
        size_bytes: int,
    ) -> None:
        if size_bytes < 0:
            return
        SUPERVISOR_STATE_SNAPSHOT_BYTES.labels(daemon=daemon_name).observe(size_bytes)
        self._log("daemon_state_snapshot", daemon=daemon_name, bytes=size_bytes)

    def emit_restore(
        self,
        daemon_name: str,
        size_bytes: int,
    ) -> None:
        self._log("daemon_state_restored", daemon=daemon_name, bytes=size_bytes)
        self._span_event(
            "supervisor.daemon.restore",
            daemon=daemon_name, bytes=size_bytes,
        )

    # ── Internal helpers ───────────────────────────────────────────

    def _log(self, event: str, **fields: Any) -> None:
        try:
            getattr(_logger, "info", _logger)(event, **fields)
        except Exception:
            pass

    def _span_event(self, name: str, **attrs: Any) -> None:
        if _tracer is None:
            return
        try:
            with _tracer.start_as_current_span(name) as span:
                for k, v in attrs.items():
                    try:
                        span.set_attribute(k, v)
                    except Exception:
                        pass
        except Exception:
            pass
