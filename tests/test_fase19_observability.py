"""
Fase 19.i — observability layer tests.

Covers the three signal families exposed by
``axon/runtime/observability.py``:

  * Prometheus metrics — counters + histogram increment when
    dispatchers run, even when prometheus_client is uninstalled
    (no-op path).
  * OpenTelemetry spans — context manager works whether or not
    opentelemetry is installed.
  * Structured audit events — dispatchers (remember / hibernate /
    drill) emit events that show up in the in-memory sink with
    flow_name + primitive + action + subject populated.

Soft-dependency contract: nothing in this layer requires the optional
libs at import time. The test asserts that when prometheus_client IS
installed, the metrics are populated; when an adopter swaps in their
own audit sink, custom events flow through correctly.
"""

from __future__ import annotations

import asyncio
import secrets

import pytest

from axon.runtime import observability
from axon.runtime.executor import Executor
from axon.runtime.observability import (
    AuditEvent,
    emit_audit,
    get_audit_sink,
    iter_audit_events,
    metrics_text,
    record_dispatcher,
    reset_metrics_for_test,
    set_audit_sink,
    span,
)
from axon.runtime.pem import (
    ContinuityTokenSigner,
    InMemoryHibernationStore,
)

from tests.test_executor import MockModelClient, make_program, make_unit


# ═══════════════════════════════════════════════════════════════════
#  PROMETHEUS METRICS
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _reset_metrics_between_tests():
    reset_metrics_for_test()
    yield
    reset_metrics_for_test()


def test_record_dispatcher_increments_counter_and_histogram():
    """When prometheus_client is installed, recording a dispatcher
    invocation populates both the call counter and the duration
    histogram."""
    if not observability._HAS_PROMETHEUS:
        pytest.skip("prometheus_client not installed")
    record_dispatcher("test_primitive", duration_seconds=0.01)
    record_dispatcher("test_primitive", duration_seconds=0.02)
    text = metrics_text()
    assert 'axon_dispatcher_calls_total{primitive="test_primitive"} 2.0' in text
    # Histogram emits multiple lines per labelled series; just check
    # the metric name + label appear.
    assert "axon_dispatcher_duration_seconds" in text
    assert 'primitive="test_primitive"' in text


def test_record_dispatcher_error_class_increments_error_counter():
    if not observability._HAS_PROMETHEUS:
        pytest.skip("prometheus_client not installed")
    record_dispatcher(
        "boom", duration_seconds=0.001, error_class="AxonRuntimeError",
    )
    text = metrics_text()
    assert (
        'axon_dispatcher_errors_total{error_class="AxonRuntimeError",'
        'primitive="boom"} 1.0'
    ) in text


def test_metrics_text_empty_when_no_recordings_made():
    """No recordings → metrics_text returns the registry exposition
    (which may be empty if no metrics have been touched)."""
    text = metrics_text()
    # Either the libs are uninstalled (empty string) or the registry
    # exists but has no labelled series → text contains only the
    # # HELP / # TYPE lines but no actual data lines.
    assert "axon_dispatcher_calls_total{" not in text


def test_record_dispatcher_safe_when_libs_missing(monkeypatch):
    """Pretend prometheus_client is not installed; recording must
    not raise."""
    monkeypatch.setattr(observability, "_HAS_PROMETHEUS", False)
    record_dispatcher("any", duration_seconds=0.01)
    assert metrics_text() == ""


# ═══════════════════════════════════════════════════════════════════
#  OPENTELEMETRY SPANS
# ═══════════════════════════════════════════════════════════════════


def test_span_works_when_otel_installed():
    """Span context manager always returns a usable object."""
    with span("test.span") as s:
        assert s is not None
        # set_attribute should not raise — works on real OTel spans
        # AND the no-op fallback.
        s.set_attribute("kind", "test")


def test_span_safe_when_otel_missing(monkeypatch):
    monkeypatch.setattr(observability, "_HAS_OTEL", False)
    with span("test.span") as s:
        s.set_attribute("kind", "test")  # no-op, must not raise


# ═══════════════════════════════════════════════════════════════════
#  STRUCTURED AUDIT EVENTS
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _reset_audit_sink_between_tests():
    # Reset to a fresh in-memory sink before/after every test so
    # cases see a clean event log.
    set_audit_sink(observability._InMemoryAuditSink())
    yield
    set_audit_sink(observability._InMemoryAuditSink())


def test_emit_audit_writes_to_in_memory_sink():
    emit_audit(
        flow_name="flow", primitive="test", action="store",
        subject="key", detail={"size": 42},
    )
    events = list(iter_audit_events())
    assert len(events) == 1
    assert events[0].flow_name == "flow"
    assert events[0].primitive == "test"
    assert events[0].action == "store"
    assert events[0].subject == "key"
    assert events[0].detail == {"size": 42}


def test_audit_event_to_json_round_trip():
    import json
    event = AuditEvent(
        timestamp=1234.5,
        flow_name="flow",
        primitive="hibernate",
        action="checkpoint",
        subject="flow:cid",
        detail={"event_name": "wakeup"},
    )
    decoded = json.loads(event.to_json())
    assert decoded["primitive"] == "hibernate"
    assert decoded["subject"] == "flow:cid"
    assert decoded["detail"]["event_name"] == "wakeup"


def test_custom_audit_sink_replaces_default():
    captured: list[AuditEvent] = []

    class CapturingSink:
        def emit(self, event):
            captured.append(event)

    set_audit_sink(CapturingSink())
    emit_audit(
        flow_name="flow", primitive="test",
        action="action", subject="subj",
    )
    assert len(captured) == 1
    assert captured[0].subject == "subj"


# ═══════════════════════════════════════════════════════════════════
#  EXECUTOR INTEGRATION
# ═══════════════════════════════════════════════════════════════════


def _hibernate_step(continuation_id: str = "cid"):
    from axon.backends.base_backend import CompiledStep
    return CompiledStep(
        step_name="hibernate",
        user_prompt="",
        metadata={"hibernate": {
            "event_name": "wakeup",
            "timeout": "1h",
            "continuation_id": continuation_id,
        }},
    )


@pytest.mark.asyncio
async def test_hibernate_dispatcher_records_metric_and_audit():
    """End-to-end: running a hibernate step through the Executor
    records the prometheus metric AND emits an audit event with
    primitive=hibernate, action=checkpoint."""
    executor = Executor(
        client=MockModelClient(),
        continuity_signer=ContinuityTokenSigner(secrets.token_bytes(32)),
        hibernation_store=InMemoryHibernationStore(),
    )
    program = make_program([make_unit("flow", [_hibernate_step("cid")])])
    await executor.execute(program)

    if observability._HAS_PROMETHEUS:
        text = metrics_text()
        assert 'axon_dispatcher_calls_total{primitive="hibernate"} 1.0' in text

    events = list(iter_audit_events())
    hibernates = [e for e in events if e.primitive == "hibernate"]
    assert len(hibernates) == 1
    assert hibernates[0].flow_name == "flow"
    assert hibernates[0].action == "checkpoint"
    assert hibernates[0].subject == "flow:cid"
    assert "expires_at" in hibernates[0].detail


@pytest.mark.asyncio
async def test_remember_dispatcher_records_metric_and_audit():
    from axon.backends.base_backend import CompiledStep
    step = CompiledStep(
        step_name="remember:Memo",
        user_prompt="",
        metadata={"remember": {
            "expression": "findings", "memory_target": "Memo",
        }},
    )
    executor = Executor(client=MockModelClient())
    program = make_program([make_unit("flow", [step])])
    await executor.execute(program)

    events = list(iter_audit_events())
    remembers = [e for e in events if e.primitive == "remember"]
    assert len(remembers) == 1
    assert remembers[0].action == "store"
    assert remembers[0].subject == "Memo"

    if observability._HAS_PROMETHEUS:
        text = metrics_text()
        assert 'axon_dispatcher_calls_total{primitive="remember"} 1.0' in text
