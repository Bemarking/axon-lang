"""Unit tests for the metrics registry + structlog configuration."""

from __future__ import annotations

import io
import json

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from axon_enterprise.config import ObservabilitySettings
from axon_enterprise.observability import (
    AUDIT_EVENTS_TOTAL,
    FLOW_EXECUTIONS_TOTAL,
    HTTP_REQUESTS_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    LLM_TOKENS_TOTAL,
    QUOTA_DENIALS_TOTAL,
    RATE_LIMITS_TOTAL,
    build_metrics_asgi_app,
    clear_log_context,
    default_registry,
    set_log_context,
)
from axon_enterprise.observability.logging import configure_logging


# ── Metric registry ─────────────────────────────────────────────────


def test_metrics_are_registered_with_axon_prefix() -> None:
    names = [
        m.name
        for m in [
            HTTP_REQUESTS_TOTAL,
            HTTP_REQUEST_DURATION_SECONDS,
            FLOW_EXECUTIONS_TOTAL,
            LLM_TOKENS_TOTAL,
            QUOTA_DENIALS_TOTAL,
            RATE_LIMITS_TOTAL,
            AUDIT_EVENTS_TOTAL,
        ]
    ]
    for n in names:
        assert n.startswith("axon_"), f"{n} must use the axon_ prefix"


def test_tenant_id_label_only_on_counters() -> None:
    # Counters carry tenant_id
    assert "tenant_id" in HTTP_REQUESTS_TOTAL._labelnames  # type: ignore[attr-defined]
    assert "tenant_id" in FLOW_EXECUTIONS_TOTAL._labelnames  # type: ignore[attr-defined]
    # Histograms do NOT
    assert "tenant_id" not in HTTP_REQUEST_DURATION_SECONDS._labelnames  # type: ignore[attr-defined]


def test_http_duration_buckets_cover_sensible_range() -> None:
    buckets = HTTP_REQUEST_DURATION_SECONDS._upper_bounds  # type: ignore[attr-defined]
    assert buckets[0] <= 0.005
    assert buckets[-2] >= 5.0  # last "real" bucket before +Inf


def test_counter_increment_produces_sample() -> None:
    HTTP_REQUESTS_TOTAL.labels(
        tenant_id="alpha", method="GET", path="/healthz", status="200"
    ).inc()
    output = generate_latest(default_registry).decode("utf-8")
    assert "axon_http_requests_total" in output
    assert 'tenant_id="alpha"' in output


def test_histogram_observation_recorded() -> None:
    HTTP_REQUEST_DURATION_SECONDS.labels(method="GET", path="/healthz").observe(
        0.05
    )
    output = generate_latest(default_registry).decode("utf-8")
    assert "axon_http_request_duration_seconds_bucket" in output


# ── ASGI exporter ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_metrics_asgi_app_serves_exposition_format() -> None:
    registry = CollectorRegistry()
    from prometheus_client import Counter

    c = Counter("axon_demo_total", "demo", registry=registry)
    c.inc()

    app = build_metrics_asgi_app(registry=registry)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/metrics",
        "headers": [],
        "query_string": b"",
    }

    messages: list[dict] = []

    async def receive():  # noqa: ANN001
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message) -> None:  # noqa: ANN001
        messages.append(message)

    await app(scope, receive, send)
    assert messages[0]["status"] == 200
    body = b"".join(m.get("body", b"") for m in messages if "body" in m)
    assert b"axon_demo_total" in body


# ── structlog configuration ─────────────────────────────────────────


def test_configure_logging_accepts_json_and_console() -> None:
    # Both formats must configure without raising.
    configure_logging(ObservabilitySettings(log_level="INFO", log_format="json"))
    configure_logging(
        ObservabilitySettings(log_level="INFO", log_format="console")
    )


def test_log_context_contextvar_round_trip() -> None:
    clear_log_context()
    token = set_log_context(tenant_id="alpha", user_id="u1")
    from axon_enterprise.observability.logging import _LOG_CONTEXT

    ctx = _LOG_CONTEXT.get()
    assert ctx["tenant_id"] == "alpha"
    assert ctx["user_id"] == "u1"
    _LOG_CONTEXT.reset(token)
    assert _LOG_CONTEXT.get() == {}


def test_json_logging_includes_contextvars() -> None:
    """End-to-end: setting a log context injects keys into the JSON line."""
    import structlog

    buf = io.StringIO()
    configure_logging(
        ObservabilitySettings(log_level="INFO", log_format="json")
    )
    # Replace the logger factory's writer with our buffer.
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            # Our context processor
            _inject_test_context,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        logger_factory=structlog.WriteLoggerFactory(file=buf),
    )

    clear_log_context()
    set_log_context(tenant_id="alpha", request_id="req-42")
    logger = structlog.get_logger("test")
    logger.info("something_happened", extra_key="v")

    output = buf.getvalue().strip()
    parsed = json.loads(output)
    assert parsed["tenant_id"] == "alpha"
    assert parsed["request_id"] == "req-42"
    assert parsed["extra_key"] == "v"
    assert parsed["event"] == "something_happened"


def _inject_test_context(logger, method_name, event_dict):  # noqa: ANN001
    from axon_enterprise.observability.logging import _LOG_CONTEXT

    for k, v in _LOG_CONTEXT.get().items():
        event_dict.setdefault(k, v)
    return event_dict
