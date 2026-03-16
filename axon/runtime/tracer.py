"""
AXON Runtime — Execution Tracer
=================================
Semantic log of every decision the runtime makes.

The Tracer produces a structured, human-readable trace that answers
not just *what* the AI did, but *why* — which anchor activated, which
reasoning path was taken, which retry was triggered, and what the
validator decided.

Architecture:
    TraceEvent        — A single atomic event (timestamp, type, data)
    TraceSpan         — A named scope containing child events and sub-spans
    ExecutionTrace    — The root container for a full program execution
    Tracer            — The recorder: start_span(), emit(), end_span()

Event Types (18):
    step_start, step_end, model_call, model_response,
    anchor_check, anchor_pass, anchor_breach,
    validation_pass, validation_fail,
    retry_attempt, refine_start,
    memory_read, memory_write,
    confidence_check,
    agent_cycle_start, agent_cycle_end, agent_goal_check, agent_stuck
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ═══════════════════════════════════════════════════════════════════
#  EVENT TYPES — the vocabulary of the trace
# ═══════════════════════════════════════════════════════════════════


class TraceEventType(str, Enum):
    """Enumeration of all semantic events the runtime can emit.

    Each event type corresponds to a distinct runtime decision
    point, enabling post-hoc analysis of execution behavior.
    """

    # — Step lifecycle —
    STEP_START = "step_start"
    STEP_END = "step_end"

    # — Model interaction —
    MODEL_CALL = "model_call"
    MODEL_RESPONSE = "model_response"

    # — Anchor enforcement —
    ANCHOR_CHECK = "anchor_check"
    ANCHOR_PASS = "anchor_pass"
    ANCHOR_BREACH = "anchor_breach"

    # — Semantic validation —
    VALIDATION_PASS = "validation_pass"
    VALIDATION_FAIL = "validation_fail"

    # — Retry / refine —
    RETRY_ATTEMPT = "retry_attempt"
    REFINE_START = "refine_start"

    # — Memory operations —
    MEMORY_READ = "memory_read"
    MEMORY_WRITE = "memory_write"

    # — Confidence —
    CONFIDENCE_CHECK = "confidence_check"

    # — Agent BDI lifecycle —
    AGENT_CYCLE_START = "agent_cycle_start"
    AGENT_CYCLE_END = "agent_cycle_end"
    AGENT_GOAL_CHECK = "agent_goal_check"
    AGENT_STUCK = "agent_stuck"


# ═══════════════════════════════════════════════════════════════════
#  TRACE EVENT — a single atomic observation
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TraceEvent:
    """A single atomic event in the execution trace.

    Attributes:
        event_type:   The semantic category of this event.
        timestamp:    Unix timestamp (seconds) when the event occurred.
        step_name:    The step that produced this event (empty for
                      program-level events).
        data:         Arbitrary structured payload — contents vary
                      by event type.
        duration_ms:  Duration in milliseconds (only meaningful for
                      events that span time, e.g. model_call).
    """

    event_type: TraceEventType
    timestamp: float
    step_name: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        result: dict[str, Any] = {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
        }
        if self.step_name:
            result["step_name"] = self.step_name
        if self.data:
            result["data"] = self.data
        if self.duration_ms > 0:
            result["duration_ms"] = round(self.duration_ms, 2)
        return result


# ═══════════════════════════════════════════════════════════════════
#  TRACE SPAN — a named scope grouping related events
# ═══════════════════════════════════════════════════════════════════


@dataclass
class TraceSpan:
    """A named scope containing child events and nested sub-spans.

    Spans represent hierarchical execution structure:
    a flow span contains step spans, and each step span
    contains model_call, validation, anchor_check events.

    Attributes:
        name:         Human-readable span name (e.g. step or flow name).
        start_time:   Unix timestamp when the span opened.
        end_time:     Unix timestamp when the span closed (0.0 if still open).
        events:       Ordered list of events emitted within this span.
        children:     Ordered list of nested sub-spans.
        metadata:     Arbitrary key-value pairs for span-level annotations.
    """

    name: str
    start_time: float = 0.0
    end_time: float = 0.0
    events: list[TraceEvent] = field(default_factory=list)
    children: list[TraceSpan] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        """Total span duration in milliseconds."""
        if self.end_time <= 0:
            return 0.0
        return round((self.end_time - self.start_time) * 1000, 2)

    @property
    def is_open(self) -> bool:
        """Whether this span is still active (not yet closed)."""
        return self.end_time <= 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        result: dict[str, Any] = {
            "name": self.name,
            "start_time": self.start_time,
            "duration_ms": self.duration_ms,
            "events": [e.to_dict() for e in self.events],
        }
        if self.children:
            result["children"] = [c.to_dict() for c in self.children]
        if self.metadata:
            result["metadata"] = self.metadata
        if self.end_time > 0:
            result["end_time"] = self.end_time
        return result


# ═══════════════════════════════════════════════════════════════════
#  EXECUTION TRACE — the root container
# ═══════════════════════════════════════════════════════════════════


@dataclass
class ExecutionTrace:
    """Root container for a complete program execution trace.

    Holds all top-level spans (one per execution unit / run statement),
    plus program-level metadata such as backend name and timing.

    Attributes:
        program_name:  Name of the AXON program that was executed.
        backend_name:  Which backend processed the compilation.
        start_time:    Unix timestamp when execution began.
        end_time:      Unix timestamp when execution completed.
        spans:         Top-level spans (one per execution unit).
        metadata:      Program-level annotations.
    """

    program_name: str = ""
    backend_name: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    spans: list[TraceSpan] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        """Total execution duration in milliseconds."""
        if self.end_time <= 0:
            return 0.0
        return round((self.end_time - self.start_time) * 1000, 2)

    @property
    def total_events(self) -> int:
        """Count all events across all spans (recursive)."""
        return self._count_events(self.spans)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full trace to a JSON-compatible dictionary."""
        result: dict[str, Any] = {
            "program_name": self.program_name,
            "backend_name": self.backend_name,
            "start_time": self.start_time,
            "duration_ms": self.duration_ms,
            "total_events": self.total_events,
            "spans": [s.to_dict() for s in self.spans],
        }
        if self.end_time > 0:
            result["end_time"] = self.end_time
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @staticmethod
    def _count_events(spans: list[TraceSpan]) -> int:
        """Recursively count events across a list of spans."""
        count = 0
        for span in spans:
            count += len(span.events)
            count += ExecutionTrace._count_events(span.children)
        return count


# ═══════════════════════════════════════════════════════════════════
#  TRACER — the recorder
# ═══════════════════════════════════════════════════════════════════


class Tracer:
    """Records semantic execution events into a structured trace.

    The Tracer maintains a stack of open spans. Events emitted
    via ``emit()`` are appended to the innermost open span.
    ``start_span()`` pushes a new child span onto the stack,
    and ``end_span()`` pops it.

    Usage::

        tracer = Tracer(program_name="contract_analysis")
        tracer.start_span("analyze_clauses")
        tracer.emit(TraceEventType.MODEL_CALL, step_name="extract",
                    data={"prompt_tokens": 1200})
        tracer.emit(TraceEventType.MODEL_RESPONSE, step_name="extract",
                    data={"output_tokens": 350}, duration_ms=1200.5)
        tracer.end_span()
        trace = tracer.finalize()
    """

    def __init__(
        self,
        program_name: str = "",
        backend_name: str = "",
    ) -> None:
        self._trace = ExecutionTrace(
            program_name=program_name,
            backend_name=backend_name,
            start_time=time.time(),
        )
        self._span_stack: list[TraceSpan] = []

    # — Span management —

    def start_span(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> TraceSpan:
        """Open a new span as a child of the current innermost span.

        If no span is open, the new span becomes a top-level span
        on the ExecutionTrace.

        Args:
            name:      Human-readable name for the span.
            metadata:  Optional key-value annotations.

        Returns:
            The newly created (and now active) TraceSpan.
        """
        span = TraceSpan(
            name=name,
            start_time=time.time(),
            metadata=metadata or {},
        )

        if self._span_stack:
            self._span_stack[-1].children.append(span)
        else:
            self._trace.spans.append(span)

        self._span_stack.append(span)
        return span

    def end_span(self, metadata: dict[str, Any] | None = None) -> TraceSpan | None:
        """Close the current innermost span.

        Args:
            metadata:  Optional key-value pairs to merge into
                       the span's metadata on close.

        Returns:
            The closed TraceSpan, or None if no span was open.
        """
        if not self._span_stack:
            return None

        span = self._span_stack.pop()
        span.end_time = time.time()

        if metadata:
            span.metadata.update(metadata)

        return span

    @property
    def current_span(self) -> TraceSpan | None:
        """The innermost currently-open span, or None."""
        return self._span_stack[-1] if self._span_stack else None

    @property
    def depth(self) -> int:
        """Current span nesting depth (0 = no open spans)."""
        return len(self._span_stack)

    # — Event emission —

    def emit(
        self,
        event_type: TraceEventType,
        step_name: str = "",
        data: dict[str, Any] | None = None,
        duration_ms: float = 0.0,
    ) -> TraceEvent:
        """Record a semantic event in the current span.

        If no span is open, the event is silently dropped (the Tracer
        never raises — it is an observer, not a participant).

        Args:
            event_type:   The semantic category of this event.
            step_name:    The step that produced this event.
            data:         Arbitrary structured payload.
            duration_ms:  Duration for timed events.

        Returns:
            The created TraceEvent.
        """
        event = TraceEvent(
            event_type=event_type,
            timestamp=time.time(),
            step_name=step_name,
            data=data or {},
            duration_ms=duration_ms,
        )

        if self._span_stack:
            self._span_stack[-1].events.append(event)

        return event

    # — Finalization —

    def finalize(self) -> ExecutionTrace:
        """Close all remaining spans and return the complete trace.

        Any spans still open are forcibly closed with the current
        timestamp. This ensures the trace is always Complete.

        Returns:
            The finalized ExecutionTrace with all spans closed
            and timing information resolved.
        """
        while self._span_stack:
            self.end_span()

        self._trace.end_time = time.time()
        return self._trace

    @property
    def trace(self) -> ExecutionTrace:
        """Access the trace in progress (may have open spans)."""
        return self._trace

    # — Convenience emitters for common patterns —

    def emit_step_start(
        self,
        step_name: str,
        data: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Convenience: emit a STEP_START event."""
        return self.emit(TraceEventType.STEP_START, step_name=step_name, data=data)

    def emit_step_end(
        self,
        step_name: str,
        data: dict[str, Any] | None = None,
        duration_ms: float = 0.0,
    ) -> TraceEvent:
        """Convenience: emit a STEP_END event."""
        return self.emit(
            TraceEventType.STEP_END,
            step_name=step_name,
            data=data,
            duration_ms=duration_ms,
        )

    def emit_model_call(
        self,
        step_name: str,
        prompt_tokens: int = 0,
        data: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Convenience: emit a MODEL_CALL event."""
        payload = data or {}
        if prompt_tokens > 0:
            payload["prompt_tokens"] = prompt_tokens
        return self.emit(TraceEventType.MODEL_CALL, step_name=step_name, data=payload)

    def emit_model_response(
        self,
        step_name: str,
        output_tokens: int = 0,
        duration_ms: float = 0.0,
        data: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Convenience: emit a MODEL_RESPONSE event."""
        payload = data or {}
        if output_tokens > 0:
            payload["output_tokens"] = output_tokens
        return self.emit(
            TraceEventType.MODEL_RESPONSE,
            step_name=step_name,
            data=payload,
            duration_ms=duration_ms,
        )

    def emit_anchor_check(
        self,
        anchor_name: str,
        step_name: str = "",
        passed: bool = True,
        data: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Convenience: emit ANCHOR_CHECK + ANCHOR_PASS or ANCHOR_BREACH."""
        payload = data or {}
        payload["anchor_name"] = anchor_name

        self.emit(TraceEventType.ANCHOR_CHECK, step_name=step_name, data=payload)

        result_type = TraceEventType.ANCHOR_PASS if passed else TraceEventType.ANCHOR_BREACH
        return self.emit(result_type, step_name=step_name, data=payload)

    def emit_validation_result(
        self,
        step_name: str,
        passed: bool,
        expected_type: str = "",
        violations: list[str] | None = None,
        data: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Convenience: emit VALIDATION_PASS or VALIDATION_FAIL."""
        payload = data or {}
        if expected_type:
            payload["expected_type"] = expected_type
        if violations:
            payload["violations"] = violations

        event_type = (
            TraceEventType.VALIDATION_PASS if passed else TraceEventType.VALIDATION_FAIL
        )
        return self.emit(event_type, step_name=step_name, data=payload)

    def emit_retry_attempt(
        self,
        step_name: str,
        attempt: int,
        reason: str = "",
        data: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Convenience: emit a RETRY_ATTEMPT event."""
        payload = data or {}
        payload["attempt"] = attempt
        if reason:
            payload["reason"] = reason
        return self.emit(
            TraceEventType.RETRY_ATTEMPT, step_name=step_name, data=payload
        )

    def emit_confidence_check(
        self,
        step_name: str,
        score: float,
        floor: float,
        passed: bool,
        data: dict[str, Any] | None = None,
    ) -> TraceEvent:
        """Convenience: emit a CONFIDENCE_CHECK event."""
        payload = data or {}
        payload["score"] = score
        payload["floor"] = floor
        payload["passed"] = passed
        return self.emit(
            TraceEventType.CONFIDENCE_CHECK, step_name=step_name, data=payload
        )
