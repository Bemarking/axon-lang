"""OpenTelemetry setup + tenant/user/request baggage.

OTLP gRPC export to a sidecar Collector (K8s idiomatic) so we
stay backend-agnostic — operators point the Collector at Datadog,
Grafana Cloud, Tempo, Jaeger, or nothing (dev) without any code
change here.

Baggage carries ``tenant_id``, ``user_id``, ``request_id`` across
service boundaries so every downstream span inherits the
correlation keys. The ASGI middleware extracts these from inbound
headers / ContextVars and sets the baggage once per request.

OTel is fully optional: when ``tracing_enabled=false`` or no OTLP
endpoint is configured, spans are still created (in-memory) but
nothing is exported — dev and tests run without a Collector.
"""

from __future__ import annotations

from typing import Any

from axon_enterprise.config import ObservabilitySettings, get_settings

_provider: Any | None = None  # set by configure_tracing


def configure_tracing(settings: ObservabilitySettings | None = None) -> None:
    """Install the OTel SDK with an OTLP exporter + baggage propagator."""
    s = settings or get_settings().observability
    if not s.tracing_enabled:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import (
            ParentBased,
            TraceIdRatioBased,
        )
    except ImportError:  # pragma: no cover
        # OTel is optional. Without the SDK installed we still let
        # the application start — tests + dev environments just
        # skip tracing entirely.
        return

    resource = Resource.create(
        {
            SERVICE_NAME: s.service_name,
            SERVICE_VERSION: s.service_version,
        }
    )
    sampler = ParentBased(
        root=TraceIdRatioBased(s.trace_sampling_ratio)
    )
    provider = TracerProvider(resource=resource, sampler=sampler)

    if s.otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=s.otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)

    global _provider
    _provider = provider


def shutdown_tracing() -> None:
    """Flush pending spans — call on graceful shutdown."""
    global _provider
    if _provider is None:
        return
    try:
        _provider.shutdown()
    finally:
        _provider = None


def get_tracer(name: str = "axon_enterprise") -> Any:
    """Return an OTel tracer. Falls back to a no-op when OTel absent."""
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except ImportError:  # pragma: no cover
        return _NoopTracer()


def set_tenant_baggage(
    *,
    tenant_id: str | None,
    user_id: str | None,
    request_id: str | None,
) -> Any:
    """Attach correlation keys to the current OTel context.

    Callers receive the context token so they can ``detach`` on exit.
    Baggage is propagated to every downstream span created inside
    the scope + to outgoing HTTP calls instrumented via
    ``opentelemetry-instrumentation-httpx``.
    """
    try:
        from opentelemetry import baggage, context
    except ImportError:  # pragma: no cover
        return None

    ctx = context.get_current()
    if tenant_id:
        ctx = baggage.set_baggage("axon.tenant_id", tenant_id, context=ctx)
    if user_id:
        ctx = baggage.set_baggage("axon.user_id", user_id, context=ctx)
    if request_id:
        ctx = baggage.set_baggage("axon.request_id", request_id, context=ctx)
    return context.attach(ctx)


class _NoopTracer:
    """Fallback when OTel SDK is not installed."""

    def start_as_current_span(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        import contextlib

        @contextlib.contextmanager
        def _no_op():
            yield _NoopSpan()

        return _no_op()


class _NoopSpan:
    def set_attribute(self, *args: Any, **kwargs: Any) -> None:
        pass

    def record_exception(self, *args: Any, **kwargs: Any) -> None:
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass
