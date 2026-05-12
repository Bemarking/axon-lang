"""§Fase 33.b — Flow execution event stream (Python mirror).

Byte-identical sibling of `axon-rs/src/flow_execution_event.rs`. The
closed catalog of 6 variants {FlowStart, StepStart, StepToken,
StepComplete, FlowComplete, FlowError} maps to the same JSON shape
on both stacks.

Consumed by:

  * Cross-stack drift gate `tests/test_fase33_flow_execution_event.py`
    parametrizing over `tests/fixtures/fase33_flow_execution_event/
    corpus.json`. Each corpus entry is a (variant, JSON) pair; both
    stacks serialize the variant + deserialize the JSON + verify
    byte-identical round-trip.

  * Future Python AxonServer integration (FastAPI EventSourceResponse
    wiring) when the Python runtime catches up on the per-event
    streaming surface Rust ships in 33.c onwards.

Pillar trace per D2:

  - MATHEMATICS — the catalog is a closed sum type; the helpers
    `is_terminator()` / `is_step_scoped()` / `kind()` are total over
    every variant.
  - LOGIC — receiver invariant: exactly one FlowStart, followed by
    per-step (StepStart → 0..N StepToken → StepComplete), followed
    by exactly one FlowComplete OR FlowError.
  - PHILOSOPHY — the source declaration IS the runtime contract.
  - COMPUTING — JSON serialization shape is locked by the
    `tests/fixtures/fase33_flow_execution_event/corpus.json` drift
    gate; cross-stack parity holds byte-for-byte.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any


def now_ms() -> int:
    """Unix milliseconds. Helper used by producers emitting events.
    Mirror of Rust `flow_execution_event::now_ms`."""
    return int(time.time() * 1000)


# ── The 6 variants ──────────────────────────────────────────────────


@dataclass
class FlowStart:
    """Emitted exactly once at the very start of execution."""
    flow_name: str
    backend: str
    timestamp_ms: int


@dataclass
class StepStart:
    """Emitted exactly once per step at its start boundary."""
    step_name: str
    step_index: int
    step_type: str
    timestamp_ms: int


@dataclass
class StepToken:
    """Emitted per chunk produced by the step's backend.

    For streaming backends (Anthropic SSE, OpenAI streaming, …) this
    fires per chunk as bytes arrive from the upstream. For non-
    streaming backends, fires once with the full step output.

    `token_index` is a per-flow monotonic counter starting at 1 on
    each new FlowStart. W3C SSE `Last-Event-ID` resumes correlate
    against this field.
    """
    step_name: str
    content: str
    token_index: int
    timestamp_ms: int


@dataclass
class StepComplete:
    """Emitted exactly once per step at its end boundary."""
    step_name: str
    step_index: int
    success: bool
    full_output: str
    tokens_input: int
    tokens_output: int
    timestamp_ms: int


@dataclass
class FlowComplete:
    """Terminator — success path. Receiver MUST close the stream."""
    flow_name: str
    backend: str
    success: bool
    steps_executed: int
    tokens_input: int
    tokens_output: int
    latency_ms: int
    timestamp_ms: int


@dataclass
class FlowError:
    """Terminator — failure path. Receiver MUST close the stream."""
    flow_name: str
    error: str
    timestamp_ms: int


# The closed union — kept as a tuple so adopters can match against
# isinstance() exhaustively.
FlowExecutionEvent = (
    FlowStart
    | StepStart
    | StepToken
    | StepComplete
    | FlowComplete
    | FlowError
)


# ── Helpers (mirror of Rust impls) ──────────────────────────────────


_TERMINATORS = (FlowComplete, FlowError)
_STEP_SCOPED = (StepStart, StepToken, StepComplete)


def is_terminator(event: FlowExecutionEvent) -> bool:
    """Closed predicate: is this the terminator of the stream?
    Mirror of Rust `FlowExecutionEvent::is_terminator`."""
    return isinstance(event, _TERMINATORS)


def is_step_scoped(event: FlowExecutionEvent) -> bool:
    """Closed predicate: does this event carry a `step_name`?
    Mirror of Rust `FlowExecutionEvent::is_step_scoped`."""
    return isinstance(event, _STEP_SCOPED)


def kind(event: FlowExecutionEvent) -> str:
    """String discriminator matching the JSON `kind` field (snake_case
    per the Rust serde rename). Mirror of Rust `kind()`."""
    if isinstance(event, FlowStart):
        return "flow_start"
    if isinstance(event, StepStart):
        return "step_start"
    if isinstance(event, StepToken):
        return "step_token"
    if isinstance(event, StepComplete):
        return "step_complete"
    if isinstance(event, FlowComplete):
        return "flow_complete"
    if isinstance(event, FlowError):
        return "flow_error"
    raise TypeError(f"Not a FlowExecutionEvent variant: {type(event).__name__}")


# ── JSON serialization (Rust-parity tag = "kind") ──────────────────


def to_json(event: FlowExecutionEvent) -> dict[str, Any]:
    """Project a variant into a dict matching the Rust JSON shape.
    `kind` discriminator first, then variant fields in declared
    order. Cross-stack drift gate asserts byte-identical output.
    """
    if isinstance(event, FlowStart):
        return {
            "kind": "flow_start",
            "flow_name": event.flow_name,
            "backend": event.backend,
            "timestamp_ms": event.timestamp_ms,
        }
    if isinstance(event, StepStart):
        return {
            "kind": "step_start",
            "step_name": event.step_name,
            "step_index": event.step_index,
            "step_type": event.step_type,
            "timestamp_ms": event.timestamp_ms,
        }
    if isinstance(event, StepToken):
        return {
            "kind": "step_token",
            "step_name": event.step_name,
            "content": event.content,
            "token_index": event.token_index,
            "timestamp_ms": event.timestamp_ms,
        }
    if isinstance(event, StepComplete):
        return {
            "kind": "step_complete",
            "step_name": event.step_name,
            "step_index": event.step_index,
            "success": event.success,
            "full_output": event.full_output,
            "tokens_input": event.tokens_input,
            "tokens_output": event.tokens_output,
            "timestamp_ms": event.timestamp_ms,
        }
    if isinstance(event, FlowComplete):
        return {
            "kind": "flow_complete",
            "flow_name": event.flow_name,
            "backend": event.backend,
            "success": event.success,
            "steps_executed": event.steps_executed,
            "tokens_input": event.tokens_input,
            "tokens_output": event.tokens_output,
            "latency_ms": event.latency_ms,
            "timestamp_ms": event.timestamp_ms,
        }
    if isinstance(event, FlowError):
        return {
            "kind": "flow_error",
            "flow_name": event.flow_name,
            "error": event.error,
            "timestamp_ms": event.timestamp_ms,
        }
    raise TypeError(f"Not a FlowExecutionEvent variant: {type(event).__name__}")


def from_json(d: dict[str, Any]) -> FlowExecutionEvent:
    """Reverse of `to_json`. Reads the `kind` discriminator and
    constructs the matching variant. Raises `ValueError` on unknown
    `kind`, mirroring Rust serde's unknown-variant rejection."""
    k = d.get("kind")
    if k == "flow_start":
        return FlowStart(
            flow_name=d["flow_name"],
            backend=d["backend"],
            timestamp_ms=d["timestamp_ms"],
        )
    if k == "step_start":
        return StepStart(
            step_name=d["step_name"],
            step_index=d["step_index"],
            step_type=d["step_type"],
            timestamp_ms=d["timestamp_ms"],
        )
    if k == "step_token":
        return StepToken(
            step_name=d["step_name"],
            content=d["content"],
            token_index=d["token_index"],
            timestamp_ms=d["timestamp_ms"],
        )
    if k == "step_complete":
        return StepComplete(
            step_name=d["step_name"],
            step_index=d["step_index"],
            success=d["success"],
            full_output=d["full_output"],
            tokens_input=d["tokens_input"],
            tokens_output=d["tokens_output"],
            timestamp_ms=d["timestamp_ms"],
        )
    if k == "flow_complete":
        return FlowComplete(
            flow_name=d["flow_name"],
            backend=d["backend"],
            success=d["success"],
            steps_executed=d["steps_executed"],
            tokens_input=d["tokens_input"],
            tokens_output=d["tokens_output"],
            latency_ms=d["latency_ms"],
            timestamp_ms=d["timestamp_ms"],
        )
    if k == "flow_error":
        return FlowError(
            flow_name=d["flow_name"],
            error=d["error"],
            timestamp_ms=d["timestamp_ms"],
        )
    raise ValueError(f"Unknown FlowExecutionEvent kind: {k!r}")


__all__ = [
    "FlowExecutionEvent",
    "FlowStart",
    "StepStart",
    "StepToken",
    "StepComplete",
    "FlowComplete",
    "FlowError",
    "to_json",
    "from_json",
    "is_terminator",
    "is_step_scoped",
    "kind",
    "now_ms",
]
