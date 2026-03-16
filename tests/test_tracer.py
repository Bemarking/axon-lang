"""
Tests for axon.runtime.tracer
"""

import pytest

from axon.runtime.tracer import (
    ExecutionTrace,
    TraceEvent,
    TraceEventType,
    TraceSpan,
    Tracer,
)


# ═══════════════════════════════════════════════════════════════════
#  TraceEvent
# ═══════════════════════════════════════════════════════════════════


class TestTraceEvent:
    def test_creation(self):
        event = TraceEvent(
            event_type=TraceEventType.STEP_START,
            timestamp=100.0,
            step_name="analyze",
        )
        assert event.event_type == TraceEventType.STEP_START
        assert event.step_name == "analyze"
        assert event.duration_ms == 0.0

    def test_to_dict(self):
        event = TraceEvent(
            event_type=TraceEventType.MODEL_CALL,
            timestamp=100.0,
            step_name="s1",
            data={"prompt": "hello"},
            duration_ms=42.5,
        )
        d = event.to_dict()
        assert d["event_type"] == "model_call"
        assert d["step_name"] == "s1"
        assert d["data"]["prompt"] == "hello"
        assert d["duration_ms"] == 42.5

    def test_all_event_types_exist(self):
        expected = {
            "step_start", "step_end", "model_call", "model_response",
            "anchor_check", "anchor_pass", "anchor_breach",
            "validation_pass", "validation_fail",
            "retry_attempt", "refine_start",
            "memory_read", "memory_write",
            "confidence_check",
            "agent_cycle_start", "agent_cycle_end",
            "agent_goal_check", "agent_stuck",
            # Shield security events
            "shield_scan_start", "shield_scan_pass", "shield_scan_breach",
            "shield_taint_check", "shield_capability_check",
        }
        actual = {e.value for e in TraceEventType}
        assert actual == expected


# ═══════════════════════════════════════════════════════════════════
#  TraceSpan
# ═══════════════════════════════════════════════════════════════════


class TestTraceSpan:
    def test_creation(self):
        span = TraceSpan(name="test_span", start_time=100.0)
        assert span.name == "test_span"
        assert span.is_open is True

    def test_duration(self):
        span = TraceSpan(name="s", start_time=100.0, end_time=100.5)
        assert span.duration_ms == pytest.approx(500.0, abs=0.1)

    def test_nested_children(self):
        parent = TraceSpan(name="parent")
        child = TraceSpan(name="child")
        parent.children.append(child)
        assert len(parent.children) == 1
        assert parent.children[0].name == "child"

    def test_to_dict(self):
        span = TraceSpan(
            name="s",
            start_time=1.0,
            end_time=2.0,
            metadata={"key": "val"},
        )
        d = span.to_dict()
        assert d["name"] == "s"
        assert "metadata" in d


# ═══════════════════════════════════════════════════════════════════
#  Tracer
# ═══════════════════════════════════════════════════════════════════


class TestTracer:
    def test_emit_event(self):
        tracer = Tracer(program_name="test")
        event = tracer.emit(TraceEventType.STEP_START, step_name="s1")
        assert event.event_type == TraceEventType.STEP_START
        assert event.step_name == "s1"

    def test_span_lifecycle(self):
        tracer = Tracer()
        tracer.start_span("outer")
        tracer.emit(TraceEventType.STEP_START, step_name="s1")
        tracer.start_span("inner")
        tracer.emit(TraceEventType.MODEL_CALL, step_name="s1")
        tracer.end_span()
        tracer.end_span()

        trace = tracer.finalize()
        assert len(trace.spans) == 1
        outer = trace.spans[0]
        assert outer.name == "outer"
        assert len(outer.events) == 1
        assert len(outer.children) == 1
        assert outer.children[0].name == "inner"

    def test_finalize_produces_trace(self):
        tracer = Tracer(program_name="my_prog", backend_name="anthropic")
        tracer.start_span("unit:flow1")
        tracer.emit(TraceEventType.STEP_START)
        tracer.end_span()

        trace = tracer.finalize()
        assert isinstance(trace, ExecutionTrace)
        assert trace.program_name == "my_prog"
        assert trace.backend_name == "anthropic"
        assert trace.end_time > 0

    def test_emit_model_call(self):
        tracer = Tracer()
        event = tracer.emit_model_call(
            step_name="s1",
            prompt_tokens=50,
        )
        assert event.event_type == TraceEventType.MODEL_CALL

    def test_emit_anchor_check(self):
        tracer = Tracer()
        event = tracer.emit_anchor_check(
            anchor_name="NoHallucination",
            step_name="s1",
        )
        assert event.event_type == TraceEventType.ANCHOR_PASS

    def test_emit_validation_result(self):
        tracer = Tracer()
        event = tracer.emit_validation_result(
            step_name="s1",
            passed=False,
            violations=["Type mismatch"],
        )
        assert event.event_type == TraceEventType.VALIDATION_FAIL

    def test_emit_step_start(self):
        tracer = Tracer()
        event = tracer.emit_step_start(step_name="s1")
        assert event.event_type == TraceEventType.STEP_START

    def test_trace_to_dict(self):
        tracer = Tracer(program_name="prog")
        tracer.start_span("span1")
        tracer.emit(TraceEventType.STEP_START, step_name="s1")
        tracer.end_span()
        trace = tracer.finalize()
        d = trace.to_dict()
        assert d["program_name"] == "prog"
        assert len(d["spans"]) == 1

    def test_total_events(self):
        tracer = Tracer()
        tracer.start_span("s")
        tracer.emit(TraceEventType.STEP_START)
        tracer.emit(TraceEventType.MODEL_CALL)
        tracer.emit(TraceEventType.STEP_END)
        tracer.end_span()
        trace = tracer.finalize()
        assert trace.total_events == 3
