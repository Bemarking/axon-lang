"""§Fase 34.b (v1.29.0) — Cross-stack drift gate for the Tool trait
+ ToolChunk closed-catalog surface.

Mirror of ``axon-rs/src/tool_trait.rs`` lib unit tests, plus a
**closed-catalog snapshot pin** asserting the Python side matches
the Rust side byte-identically for the surfaces D10 specifies as
cross-stack-contract:

1. ``ToolFinishReason`` closed catalog: exactly 3 variants
   ``{stop, error, cancelled}``.
2. ``ToolChunk`` field shape: ``{delta, finish_reason?, timestamp_ms}``.
3. ``ToolChunk`` serde elides ``finish_reason`` when None
   (D4 byte-compat).
4. ``Tool`` ABC method signatures: ``execute / stream / is_streaming``.
5. Default ``stream()`` wraps ``execute()`` as a single-chunk
   stream (D9 backwards-compat).
6. Default ``is_streaming()`` returns ``False``.

Drift detection: if either stack adds a new finish-reason variant,
renames a ToolChunk field, or changes the Tool method signatures,
this test fires loudly.

Drift gate is the Python-side counterpart of any future
``axon-rs/tests/fase34_b_tool_trait_rust_lib_pin.rs`` (the lib
unit tests are already inside ``tool_trait.rs``; the cross-stack
mirror lives here).
"""

from __future__ import annotations

import asyncio
import json
import pytest

from axon.runtime.tools.streaming import (
    TOOL_FINISH_REASON_VARIANTS,
    Tool,
    ToolChunk,
    ToolContext,
    ToolFinishCancelled,
    ToolFinishError,
    ToolFinishStop,
    parse_finish_reason,
)


# ─── Hardcoded cross-stack snapshot (mirror of axon-rs constant) ────
#
# This snapshot must equal the Rust side's
# ``ToolFinishReason::all_variants()`` return value. If either stack
# drifts, the test fires loudly. Adding a 4th variant requires
# updating the snapshot in BOTH stacks + cross-stack drift gate
# alignment.
RUST_TOOL_FINISH_REASON_VARIANTS_SNAPSHOT: tuple[str, ...] = (
    "stop",
    "error",
    "cancelled",
)


# ════════════════════════════════════════════════════════════════════
#  §1 — Closed-catalog ToolFinishReason cardinality + membership
# ════════════════════════════════════════════════════════════════════


def test_s1_toolfinishreason_cardinality_is_exactly_three():
    assert len(TOOL_FINISH_REASON_VARIANTS) == 3, (
        "34.b D10 cross-stack: ToolFinishReason has EXACTLY 3 variants "
        "{stop, error, cancelled}. Adding a 4th requires a deliberate "
        "sub-fase + Rust-side enum update + cross-stack drift gate "
        "alignment + adopter docs update."
    )


def test_s1_toolfinishreason_membership_matches_rust_snapshot():
    assert TOOL_FINISH_REASON_VARIANTS == RUST_TOOL_FINISH_REASON_VARIANTS_SNAPSHOT, (
        f"34.b D10 cross-stack: Python TOOL_FINISH_REASON_VARIANTS drifted "
        f"from the Rust snapshot. Got Python: {TOOL_FINISH_REASON_VARIANTS!r}, "
        f"Rust snapshot: {RUST_TOOL_FINISH_REASON_VARIANTS_SNAPSHOT!r}"
    )


def test_s1_toolfinishreason_all_variants_constructible():
    """Every snapshot variant MUST be constructible at the type level."""
    stop = ToolFinishStop()
    error = ToolFinishError(message="boom")
    cancelled = ToolFinishCancelled()
    assert stop.kind == "stop"
    assert error.kind == "error"
    assert error.message == "boom"
    assert cancelled.kind == "cancelled"


def test_s1_toolfinishreason_parser_rejects_unknown():
    """parse_finish_reason raises on unknown kind (closed-catalog
    enforcement at the deserialization boundary)."""
    with pytest.raises(ValueError, match="closed-catalog"):
        parse_finish_reason({"kind": "unknown_reason"})


# ════════════════════════════════════════════════════════════════════
#  §2 — ToolChunk field shape + serde round-trip
# ════════════════════════════════════════════════════════════════════


def test_s2_toolchunk_intermediate_serde_round_trip():
    chunk = ToolChunk.intermediate("Hola")
    d = chunk.to_dict()
    # D4 byte-compat: finish_reason MUST be elided when None.
    assert "finish_reason" not in d, (
        "34.b D4 cross-stack: None finish_reason MUST be elided from "
        f"the dict. Got: {d}"
    )
    back = ToolChunk.from_dict(d)
    assert back.delta == "Hola"
    assert back.finish_reason is None
    assert back.timestamp_ms == chunk.timestamp_ms


def test_s2_toolchunk_terminator_stop_serde_round_trip():
    chunk = ToolChunk.terminator("", ToolFinishStop())
    d = chunk.to_dict()
    assert d["finish_reason"]["kind"] == "stop"
    back = ToolChunk.from_dict(d)
    assert isinstance(back.finish_reason, ToolFinishStop)


def test_s2_toolchunk_terminator_error_serde_round_trip():
    chunk = ToolChunk.terminator(
        "",
        ToolFinishError(message="upstream timeout"),
    )
    d = chunk.to_dict()
    assert d["finish_reason"]["kind"] == "error"
    assert d["finish_reason"]["message"] == "upstream timeout"
    back = ToolChunk.from_dict(d)
    assert isinstance(back.finish_reason, ToolFinishError)
    assert back.finish_reason.message == "upstream timeout"


def test_s2_toolchunk_terminator_cancelled_serde_round_trip():
    chunk = ToolChunk.terminator("", ToolFinishCancelled())
    d = chunk.to_dict()
    assert d["finish_reason"]["kind"] == "cancelled"
    back = ToolChunk.from_dict(d)
    assert isinstance(back.finish_reason, ToolFinishCancelled)


def test_s2_toolchunk_json_shape_matches_rust():
    """Cross-stack byte equivalence: the JSON-serialized shape MUST
    match the Rust serde output verbatim (modulo key order)."""
    chunk = ToolChunk(delta="x", timestamp_ms=42, finish_reason=None)
    d = chunk.to_dict()
    # Adopter parsers ignoring unknown fields see no observable change
    # when a future axon-lang minor adds new optional fields.
    expected = {"delta": "x", "timestamp_ms": 42}
    assert d == expected, (
        f"34.b D4 cross-stack: ToolChunk JSON shape drift detected. "
        f"Got Python: {d}, expected (matches Rust): {expected}"
    )


def test_s2_toolchunk_is_terminator_helper():
    intermediate = ToolChunk.intermediate("x")
    terminator = ToolChunk.terminator("y", ToolFinishStop())
    assert not intermediate.is_terminator()
    assert terminator.is_terminator()


# ════════════════════════════════════════════════════════════════════
#  §3 — Tool ABC method signatures + default impls
# ════════════════════════════════════════════════════════════════════


class _MockResult:
    """Duck-typed mock for the existing axon.runtime.tools.base_tool.ToolResult."""

    def __init__(self, success: bool, data: str, error: str | None = None):
        self.success = success
        self.data = data
        self.error = error


class SyncTool(Tool):
    """Non-streaming tool — uses default stream() + is_streaming()."""

    async def execute(self, args: str, ctx: ToolContext) -> _MockResult:
        return _MockResult(success=True, data=f"sync({args})")


class StreamingToolImpl(Tool):
    """Streaming tool — overrides stream() + is_streaming()."""

    async def execute(self, args: str, ctx: ToolContext) -> _MockResult:
        return _MockResult(success=True, data="materialized fallback")

    async def stream(self, args: str, ctx: ToolContext):
        for chunk_text in ["alpha ", "beta ", "gamma"]:
            yield ToolChunk.intermediate(chunk_text)
        yield ToolChunk.terminator("", ToolFinishStop())

    def is_streaming(self) -> bool:
        return True


def test_s3_tool_abc_has_execute_stream_is_streaming_methods():
    """Method-signature pin — the Tool ABC MUST have these 3 methods.
    Drift detection: renaming or removing any of them fires this pin."""
    assert hasattr(Tool, "execute"), "Tool ABC MUST define execute()"
    assert hasattr(Tool, "stream"), "Tool ABC MUST define stream()"
    assert hasattr(Tool, "is_streaming"), "Tool ABC MUST define is_streaming()"


def test_s3_tool_default_is_streaming_is_false():
    tool = SyncTool()
    assert tool.is_streaming() is False, (
        "34.b D1+D9: default is_streaming() returns False. Backwards-compat: "
        "every non-streaming tool stays out of the streaming dispatch path."
    )


@pytest.mark.asyncio
async def test_s3_tool_default_stream_wraps_execute_one_chunk():
    """D9 backwards-compat: default stream() emits EXACTLY 1 chunk."""
    tool = SyncTool()
    ctx = ToolContext(cancel=asyncio.Event(), trace_id=0xDEAD_BEEF)
    chunks = [c async for c in tool.stream("hello", ctx)]
    assert len(chunks) == 1, (
        f"34.b D9: default stream() emits EXACTLY 1 chunk. Got {len(chunks)}."
    )
    assert chunks[0].delta == "sync(hello)"
    assert isinstance(chunks[0].finish_reason, ToolFinishStop)
    assert chunks[0].is_terminator()


@pytest.mark.asyncio
async def test_s3_tool_override_stream_emits_multiple_chunks():
    tool = StreamingToolImpl()
    ctx = ToolContext(cancel=asyncio.Event(), trace_id=0x42)
    chunks = [c async for c in tool.stream("", ctx)]
    assert len(chunks) == 4
    assert chunks[0].delta == "alpha "
    assert chunks[1].delta == "beta "
    assert chunks[2].delta == "gamma"
    assert chunks[3].is_terminator()
    assert isinstance(chunks[3].finish_reason, ToolFinishStop)


def test_s3_tool_override_is_streaming_returns_true():
    tool = StreamingToolImpl()
    assert tool.is_streaming() is True


# ════════════════════════════════════════════════════════════════════
#  §4 — ToolChunk.from_result conversion (D9 backwards-compat path)
# ════════════════════════════════════════════════════════════════════


def test_s4_toolchunk_from_result_success_maps_to_stop():
    result = _MockResult(success=True, data="42")
    chunk = ToolChunk.from_result(result)
    assert chunk.delta == "42"
    assert isinstance(chunk.finish_reason, ToolFinishStop)
    assert chunk.is_terminator()


def test_s4_toolchunk_from_result_failure_maps_to_error():
    result = _MockResult(
        success=False,
        data="division by zero",
        error="ZeroDivisionError",
    )
    chunk = ToolChunk.from_result(result)
    assert chunk.delta == "division by zero"
    assert isinstance(chunk.finish_reason, ToolFinishError)
    assert "ZeroDivisionError" in chunk.finish_reason.message


# ════════════════════════════════════════════════════════════════════
#  §5 — ToolContext field surface + cancel propagation
# ════════════════════════════════════════════════════════════════════


def test_s5_toolcontext_constructor_and_field_access():
    cancel = asyncio.Event()
    ctx = ToolContext(cancel=cancel, trace_id=0xCAFE_BABE)
    assert ctx.trace_id == 0xCAFE_BABE
    assert ctx.is_cancelled() is False
    cancel.set()
    assert ctx.is_cancelled() is True


# ════════════════════════════════════════════════════════════════════
#  §6 — Cross-stack snapshot self-consistency pin
# ════════════════════════════════════════════════════════════════════


def test_s6_python_and_rust_snapshots_equal():
    """The Python ``TOOL_FINISH_REASON_VARIANTS`` const and the
    hardcoded Rust snapshot in this test file MUST be equal. Both
    sides represent the same closed catalog; keeping them as
    separate constants makes the cross-stack invariant explicit at
    the test site."""
    assert TOOL_FINISH_REASON_VARIANTS == RUST_TOOL_FINISH_REASON_VARIANTS_SNAPSHOT, (
        "34.b D10: cross-stack closed-catalog drift detected between "
        "Python TOOL_FINISH_REASON_VARIANTS and the hardcoded Rust "
        "snapshot in this test file. Both should equal "
        "('stop', 'error', 'cancelled')."
    )
