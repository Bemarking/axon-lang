"""
Observability layer for the AXON runtime (Fase 19.i).

Three signal families, all with **soft** dependencies — neither
``prometheus_client`` nor ``opentelemetry`` is required to run AXON.
When either library is missing, the corresponding helpers degrade to
typed no-ops; existing dispatcher code that calls into this module
keeps working unchanged.

  * **Prometheus metrics** — per-primitive counters and a histogram
    of dispatcher duration. Fed by the dispatchers' STEP_END trace
    events. Use :func:`metrics_text` to scrape.
  * **OpenTelemetry spans** — per-step spans that nest under the
    unit span. Adopters configure the OTel SDK / exporter
    out-of-band; we only emit spans against the global tracer.
  * **Structured audit events** — JSON-line records appended to an
    in-process buffer (and optionally flushed to an
    ``AuditSink`` adopter implementation). Used for memory writes
    (Remember), CPS checkpoints (Hibernate), and PIX queries
    (Drill / Trail) — operations adopters typically need a tamper-
    evident trail of for compliance review.

Adopters opt in by:

  * Installing ``prometheus_client`` (>=0.16) and / or
    ``opentelemetry-api`` (>=1.20) + the SDK they want.
  * Optionally registering an :class:`AuditSink` via
    :func:`set_audit_sink` to forward events to durable storage.

Without those steps the layer is a no-op — zero overhead in the hot
path beyond a couple of attribute lookups.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Protocol


# ═══════════════════════════════════════════════════════════════════
#  SOFT IMPORTS
# ═══════════════════════════════════════════════════════════════════
#
# We catch ImportError so adopters running without the libraries
# installed see a no-op layer rather than a startup failure. The
# `_HAS_*` flags discriminate at call time.

try:
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Histogram,
        generate_latest,
    )
    _HAS_PROMETHEUS = True
except ImportError:  # pragma: no cover — exercised in adopter envs without the dep
    _HAS_PROMETHEUS = False
    CollectorRegistry = None  # type: ignore[assignment]
    Counter = None  # type: ignore[assignment]
    Histogram = None  # type: ignore[assignment]

    def generate_latest(_registry: Any = None) -> bytes:  # type: ignore[no-redef]
        return b""

try:
    from opentelemetry import trace as _otel_trace
    _HAS_OTEL = True
except ImportError:  # pragma: no cover
    _HAS_OTEL = False
    _otel_trace = None  # type: ignore[assignment]


# ═══════════════════════════════════════════════════════════════════
#  PROMETHEUS METRICS
# ═══════════════════════════════════════════════════════════════════


_REGISTRY: Any = None
_DISPATCHER_CALLS: Any = None
_DISPATCHER_DURATION: Any = None
_DISPATCHER_ERRORS: Any = None
_lock = threading.Lock()


def _ensure_metrics() -> None:
    """Lazily build the metric objects on first use. Keeps the
    no-op path zero-cost for adopters who never call into this
    module."""
    global _REGISTRY, _DISPATCHER_CALLS, _DISPATCHER_DURATION, _DISPATCHER_ERRORS
    if not _HAS_PROMETHEUS:
        return
    if _REGISTRY is not None:
        return
    with _lock:
        if _REGISTRY is not None:
            return
        # Use a private registry rather than the prometheus default —
        # multi-tenant adopters can mint per-tenant metric stacks
        # without colliding.
        _REGISTRY = CollectorRegistry()
        _DISPATCHER_CALLS = Counter(
            "axon_dispatcher_calls_total",
            "Total dispatcher invocations by primitive (Fase 19.i).",
            ["primitive"],
            registry=_REGISTRY,
        )
        _DISPATCHER_DURATION = Histogram(
            "axon_dispatcher_duration_seconds",
            "Dispatcher wall-clock duration (Fase 19.i).",
            ["primitive"],
            buckets=(
                0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0,
            ),
            registry=_REGISTRY,
        )
        _DISPATCHER_ERRORS = Counter(
            "axon_dispatcher_errors_total",
            "Dispatcher invocations that raised AxonRuntimeError "
            "(Fase 19.i).",
            ["primitive", "error_class"],
            registry=_REGISTRY,
        )


def record_dispatcher(
    primitive: str, *, duration_seconds: float, error_class: str | None = None,
) -> None:
    """Record one dispatcher invocation.

    No-op if ``prometheus_client`` is not installed. ``error_class``
    is the exception class name (e.g. ``"AxonRuntimeError"``) when
    the dispatcher raised; ``None`` on success.
    """
    if not _HAS_PROMETHEUS:
        return
    _ensure_metrics()
    _DISPATCHER_CALLS.labels(primitive=primitive).inc()
    _DISPATCHER_DURATION.labels(primitive=primitive).observe(duration_seconds)
    if error_class is not None:
        _DISPATCHER_ERRORS.labels(
            primitive=primitive, error_class=error_class,
        ).inc()


def metrics_text() -> str:
    """Return the Prometheus exposition text. Empty string when
    ``prometheus_client`` is not installed."""
    if not _HAS_PROMETHEUS or _REGISTRY is None:
        return ""
    return generate_latest(_REGISTRY).decode("utf-8")


def reset_metrics_for_test() -> None:
    """Clear the registry — used by tests to assert isolation
    between cases. Adopters generally never call this."""
    global _REGISTRY, _DISPATCHER_CALLS, _DISPATCHER_DURATION, _DISPATCHER_ERRORS
    with _lock:
        _REGISTRY = None
        _DISPATCHER_CALLS = None
        _DISPATCHER_DURATION = None
        _DISPATCHER_ERRORS = None


# ═══════════════════════════════════════════════════════════════════
#  OPENTELEMETRY SPANS
# ═══════════════════════════════════════════════════════════════════


class _NoopSpanCtx:
    """Context-manager + attribute setter that does nothing — used
    when ``opentelemetry`` is not installed so dispatcher code can
    use ``with span(...) as s:`` unconditionally."""

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def set_attribute(self, _key: str, _value: Any) -> None:
        return None

    def record_exception(self, _exc: BaseException) -> None:
        return None


def span(name: str, *, attributes: dict[str, Any] | None = None) -> Any:
    """Open an OpenTelemetry span around a code region.

    Returns a context manager that yields a span with
    ``set_attribute`` / ``record_exception``. When ``opentelemetry``
    is not installed, returns a typed no-op so dispatcher code does
    not need conditional imports.
    """
    if not _HAS_OTEL:
        return _NoopSpanCtx()
    tracer = _otel_trace.get_tracer("axon.runtime")
    cm = tracer.start_as_current_span(name)
    if attributes:
        # Defer attribute setting until the span is active — OTel
        # requires this. We hand the cm back; the dispatcher calls
        # set_attribute on the yielded span as needed.
        class _Wrapped:
            def __enter__(self):
                self._span = cm.__enter__()
                for k, v in attributes.items():
                    self._span.set_attribute(k, v)
                return self._span

            def __exit__(self, *exc):
                return cm.__exit__(*exc)

        return _Wrapped()
    return cm


# ═══════════════════════════════════════════════════════════════════
#  STRUCTURED AUDIT EVENTS
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One audit-log entry. Append-only — the structured trail
    adopters review for compliance.

    Fields are deliberately minimal so the event can be serialized
    as a single JSON line. Adopters extend by attaching their own
    sink and enriching events at write time.
    """

    timestamp: float
    flow_name: str
    primitive: str       # remember / hibernate / drill / trail / ...
    action: str          # e.g. "store" / "checkpoint" / "query"
    subject: str         # the affected memory key / session_id / pix_ref
    detail: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "timestamp": self.timestamp,
            "flow_name": self.flow_name,
            "primitive": self.primitive,
            "action": self.action,
            "subject": self.subject,
            "detail": self.detail,
        }, default=str, sort_keys=True)


class AuditSink(Protocol):
    """Adopter-supplied durable sink for audit events. Implementations
    might forward to a SIEM, append to a write-ahead log, or stream
    to Kafka. The default sink is in-memory only and lost on process
    exit."""

    def emit(self, event: AuditEvent) -> None:
        """Persist one event. Called synchronously from the
        dispatcher hot path — adopters writing to slow I/O should
        buffer or offload to a thread."""
        ...


class _InMemoryAuditSink:
    """Default sink — keeps the last N events in a deque for
    introspection. Production adopters override via
    :func:`set_audit_sink`."""

    __slots__ = ("_events", "_lock", "_capacity")

    def __init__(self, capacity: int = 1024) -> None:
        from collections import deque
        self._events: Any = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._capacity = capacity

    def emit(self, event: AuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> list[AuditEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


_AUDIT_SINK: AuditSink = _InMemoryAuditSink()


def set_audit_sink(sink: AuditSink) -> None:
    """Replace the active audit sink. Pass an instance of
    :class:`_InMemoryAuditSink` to reset to the default."""
    global _AUDIT_SINK
    _AUDIT_SINK = sink


def get_audit_sink() -> AuditSink:
    """Return the active audit sink — used by tests + adopter code
    that introspects emitted events."""
    return _AUDIT_SINK


def emit_audit(
    *,
    flow_name: str,
    primitive: str,
    action: str,
    subject: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append one audit event to the active sink. Safe to call from
    any dispatcher; the in-memory default sink is lock-protected."""
    event = AuditEvent(
        timestamp=time.time(),
        flow_name=flow_name,
        primitive=primitive,
        action=action,
        subject=subject,
        detail=detail or {},
    )
    _AUDIT_SINK.emit(event)


def iter_audit_events() -> Iterator[AuditEvent]:
    """Iterate the in-memory audit buffer. Convenience for tests +
    adopter code that wants to read recent events. Adopters with a
    custom :class:`AuditSink` should query their own sink instead."""
    sink = _AUDIT_SINK
    if isinstance(sink, _InMemoryAuditSink):
        yield from sink.snapshot()


# ═══════════════════════════════════════════════════════════════════
#  TIMING DECORATOR
# ═══════════════════════════════════════════════════════════════════


def time_dispatcher(primitive: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: wrap an async dispatcher to record Prometheus
    metrics + open an OTel span. Use sparingly — most dispatchers
    integrate the metrics manually because they need the duration
    for their own STEP_END trace event.

    Adopters who want per-method observability without manual
    integration can apply this decorator to custom dispatchers.
    """
    def _decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        async def _wrapped(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            error_class: str | None = None
            with span(f"axon.dispatch.{primitive}"):
                try:
                    return await fn(*args, **kwargs)
                except Exception as exc:
                    error_class = type(exc).__name__
                    raise
                finally:
                    record_dispatcher(
                        primitive,
                        duration_seconds=time.perf_counter() - start,
                        error_class=error_class,
                    )
        _wrapped.__name__ = fn.__name__
        _wrapped.__qualname__ = fn.__qualname__
        return _wrapped
    return _decorate


__all__ = [
    "AuditEvent",
    "AuditSink",
    "emit_audit",
    "get_audit_sink",
    "iter_audit_events",
    "metrics_text",
    "record_dispatcher",
    "reset_metrics_for_test",
    "set_audit_sink",
    "span",
    "time_dispatcher",
]
