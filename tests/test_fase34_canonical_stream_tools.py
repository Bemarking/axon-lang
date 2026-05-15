"""§Fase 34.k — Canonical streaming-tool patterns (Python mirror).

Cross-stack mirror of ``axon-rs/tests/fase34_canonical_stream_tools.rs``.

Ships the SAME 8 adopter-agnostic canonical ``Tool`` patterns as
Python ``Tool`` ABC subclasses, and asserts they produce the SAME
canonical delta sequences via the shared ``CANONICAL_CORPUS``. Drift
in either stack (Rust or Python) fails BOTH gates.

## OSS / ENTERPRISE split

Verticals (banking / medicine / legal / government) are exclusive to
axon-enterprise — the OSS ``axon`` package stays 100% adopter-
agnostic. These 8 patterns are domain-neutral; the vertical-grounded
instances ship in axon-enterprise's vertical R&D track (Fase 34.m
v1.20.0 catch-up).

## The 8 canonical patterns

1. ``ChunkedListProcessor`` — per-input-item streaming.
2. ``ProgressiveRefinement`` — draft → refined → final.
3. ``PaginatedSource`` — one chunk per page.
4. ``MultiStagePipeline`` — parse → transform → validate → emit.
5. ``ProgressReporter`` — progress markers + final result.
6. ``EarlyErrorTool`` — partial chunks then Error terminator.
7. ``CancelAwareCounter`` — cooperative cancel-into-tool-body (D5).
8. ``BurstProducer`` — fast burst producer.

The Python mirror tests the ``Tool.stream()`` async-generator output
directly (Python has no Rust-side ``unified_stream_handler`` — the
dispatcher is Rust-only). The cross-stack contract is the **delta
sequence + terminator kind** parity, pinned by ``CANONICAL_CORPUS``.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import pytest

from axon.runtime.tools.streaming import (
    Tool,
    ToolChunk,
    ToolContext,
    ToolFinishCancelled,
    ToolFinishError,
    ToolFinishStop,
)

# ═══════════════════════════════════════════════════════════════════
#  Pattern 1 — ChunkedListProcessor
# ═══════════════════════════════════════════════════════════════════


def _list_items(args: str) -> list[str]:
    return [
        f"item:{s.strip()}"
        for s in args.split(",")
        if s.strip()
    ]


class ChunkedListProcessor(Tool):
    """Streams one ``item:<x>`` chunk per non-empty element of a
    comma-separated ``args`` list."""

    async def execute(self, args: str, ctx: ToolContext) -> Any:
        return "|".join(_list_items(args))

    async def stream(
        self, args: str, ctx: ToolContext
    ) -> AsyncIterator[ToolChunk]:
        for item in _list_items(args):
            yield ToolChunk.intermediate(item)
        yield ToolChunk.terminator("", ToolFinishStop())

    def is_streaming(self) -> bool:
        return True


# ═══════════════════════════════════════════════════════════════════
#  Pattern 2 — ProgressiveRefinement
# ═══════════════════════════════════════════════════════════════════


def _refinement_stages(args: str) -> list[str]:
    return [f"draft:{args}", f"refined:{args}", f"final:{args}"]


class ProgressiveRefinement(Tool):
    """Streams a 3-stage refinement: draft → refined → final."""

    async def execute(self, args: str, ctx: ToolContext) -> Any:
        return "|".join(_refinement_stages(args))

    async def stream(
        self, args: str, ctx: ToolContext
    ) -> AsyncIterator[ToolChunk]:
        for stage in _refinement_stages(args):
            yield ToolChunk.intermediate(stage)
        yield ToolChunk.terminator("", ToolFinishStop())

    def is_streaming(self) -> bool:
        return True


# ═══════════════════════════════════════════════════════════════════
#  Pattern 3 — PaginatedSource
# ═══════════════════════════════════════════════════════════════════


def _pages(args: str) -> list[str]:
    try:
        n = int(args.strip())
    except ValueError:
        n = 0
    return [f"page-{i}" for i in range(max(n, 0))]


class PaginatedSource(Tool):
    """Streams one ``page-<i>`` chunk per page of an N-page set."""

    async def execute(self, args: str, ctx: ToolContext) -> Any:
        return "|".join(_pages(args))

    async def stream(
        self, args: str, ctx: ToolContext
    ) -> AsyncIterator[ToolChunk]:
        for page in _pages(args):
            yield ToolChunk.intermediate(page)
        yield ToolChunk.terminator("", ToolFinishStop())

    def is_streaming(self) -> bool:
        return True


# ═══════════════════════════════════════════════════════════════════
#  Pattern 4 — MultiStagePipeline
# ═══════════════════════════════════════════════════════════════════

_PIPELINE_STAGES = ("parse", "transform", "validate", "emit")


def _pipeline_chunks(args: str) -> list[str]:
    return [f"stage:{stage}:{args}" for stage in _PIPELINE_STAGES]


class MultiStagePipeline(Tool):
    """Streams one chunk per pipeline stage."""

    async def execute(self, args: str, ctx: ToolContext) -> Any:
        return "|".join(_pipeline_chunks(args))

    async def stream(
        self, args: str, ctx: ToolContext
    ) -> AsyncIterator[ToolChunk]:
        for chunk in _pipeline_chunks(args):
            yield ToolChunk.intermediate(chunk)
        yield ToolChunk.terminator("", ToolFinishStop())

    def is_streaming(self) -> bool:
        return True


# ═══════════════════════════════════════════════════════════════════
#  Pattern 5 — ProgressReporter
# ═══════════════════════════════════════════════════════════════════


def _progress_chunks(args: str) -> list[str]:
    return [
        "progress:25",
        "progress:50",
        "progress:75",
        "progress:100",
        f"result:{args}",
    ]


class ProgressReporter(Tool):
    """Streams progress markers then a final ``result:<args>`` chunk."""

    async def execute(self, args: str, ctx: ToolContext) -> Any:
        return "|".join(_progress_chunks(args))

    async def stream(
        self, args: str, ctx: ToolContext
    ) -> AsyncIterator[ToolChunk]:
        for chunk in _progress_chunks(args):
            yield ToolChunk.intermediate(chunk)
        yield ToolChunk.terminator("", ToolFinishStop())

    def is_streaming(self) -> bool:
        return True


# ═══════════════════════════════════════════════════════════════════
#  Pattern 6 — EarlyErrorTool
# ═══════════════════════════════════════════════════════════════════

EARLY_ERROR_MESSAGE = "early-error-tool: simulated mid-stream failure"


def _early_error_partials(args: str) -> list[str]:
    return [f"partial:{args}:1", f"partial:{args}:2"]


class EarlyErrorTool(Tool):
    """Streams 2 partial chunks then a mid-stream Error terminator."""

    async def execute(self, args: str, ctx: ToolContext) -> Any:
        return EARLY_ERROR_MESSAGE

    async def stream(
        self, args: str, ctx: ToolContext
    ) -> AsyncIterator[ToolChunk]:
        for chunk in _early_error_partials(args):
            yield ToolChunk.intermediate(chunk)
        yield ToolChunk.terminator(
            "", ToolFinishError(message=EARLY_ERROR_MESSAGE)
        )

    def is_streaming(self) -> bool:
        return True


# ═══════════════════════════════════════════════════════════════════
#  Pattern 7 — CancelAwareCounter
# ═══════════════════════════════════════════════════════════════════


class CancelAwareCounter(Tool):
    """Streams up to N ``tick-<i>`` chunks, polling ``ctx.cancel``
    between each. On mid-stream cancel emits a Cancelled terminator
    + ends — the canonical cooperative cancel-into-tool-body
    pattern (Fase 34.h D5 discipline at the adopter-tool layer)."""

    async def execute(self, args: str, ctx: ToolContext) -> Any:
        try:
            n = int(args.strip())
        except ValueError:
            n = 0
        return f"counted {n}"

    async def stream(
        self, args: str, ctx: ToolContext
    ) -> AsyncIterator[ToolChunk]:
        try:
            max_ticks = int(args.strip())
        except ValueError:
            max_ticks = 0
        for i in range(max(max_ticks, 0)):
            if ctx.is_cancelled():
                yield ToolChunk.terminator("", ToolFinishCancelled())
                return
            yield ToolChunk.intermediate(f"tick-{i}")
        yield ToolChunk.terminator("", ToolFinishStop())

    def is_streaming(self) -> bool:
        return True


# ═══════════════════════════════════════════════════════════════════
#  Pattern 8 — BurstProducer
# ═══════════════════════════════════════════════════════════════════


def _burst_chunks(args: str) -> list[str]:
    try:
        n = int(args.strip())
    except ValueError:
        n = 0
    return [f"burst-{i}" for i in range(max(n, 0))]


class BurstProducer(Tool):
    """Streams a burst of N ``burst-<i>`` chunks rapidly."""

    async def execute(self, args: str, ctx: ToolContext) -> Any:
        return f"burst of {len(_burst_chunks(args))}"

    async def stream(
        self, args: str, ctx: ToolContext
    ) -> AsyncIterator[ToolChunk]:
        for chunk in _burst_chunks(args):
            yield ToolChunk.intermediate(chunk)
        yield ToolChunk.terminator("", ToolFinishStop())

    def is_streaming(self) -> bool:
        return True


# ═══════════════════════════════════════════════════════════════════
#  Cross-stack canonical corpus
# ═══════════════════════════════════════════════════════════════════

# Mirror of the Rust ``CANONICAL_CORPUS``. Each entry:
#   (tool_name, input, expected_deltas, terminator_kind)
# Drift in EITHER stack fails BOTH gates.
CANONICAL_CORPUS: list[tuple[str, str, list[str], str]] = [
    (
        "ChunkedListProcessor",
        "alpha,beta,gamma",
        ["item:alpha", "item:beta", "item:gamma"],
        "stop",
    ),
    (
        "ProgressiveRefinement",
        "hello",
        ["draft:hello", "refined:hello", "final:hello"],
        "stop",
    ),
    (
        "PaginatedSource",
        "4",
        ["page-0", "page-1", "page-2", "page-3"],
        "stop",
    ),
    (
        "MultiStagePipeline",
        "data",
        [
            "stage:parse:data",
            "stage:transform:data",
            "stage:validate:data",
            "stage:emit:data",
        ],
        "stop",
    ),
    (
        "ProgressReporter",
        "output",
        [
            "progress:25",
            "progress:50",
            "progress:75",
            "progress:100",
            "result:output",
        ],
        "stop",
    ),
    (
        "EarlyErrorTool",
        "task",
        ["partial:task:1", "partial:task:2"],
        "error",
    ),
    (
        "CancelAwareCounter",
        "5",
        ["tick-0", "tick-1", "tick-2", "tick-3", "tick-4"],
        "stop",
    ),
    (
        "BurstProducer",
        "6",
        ["burst-0", "burst-1", "burst-2", "burst-3", "burst-4", "burst-5"],
        "stop",
    ),
]

_PATTERN_REGISTRY: dict[str, type[Tool]] = {
    "ChunkedListProcessor": ChunkedListProcessor,
    "ProgressiveRefinement": ProgressiveRefinement,
    "PaginatedSource": PaginatedSource,
    "MultiStagePipeline": MultiStagePipeline,
    "ProgressReporter": ProgressReporter,
    "EarlyErrorTool": EarlyErrorTool,
    "CancelAwareCounter": CancelAwareCounter,
    "BurstProducer": BurstProducer,
}


# ═══════════════════════════════════════════════════════════════════
#  Test scaffolding
# ═══════════════════════════════════════════════════════════════════


def _fresh_ctx() -> ToolContext:
    return ToolContext(cancel=asyncio.Event(), trace_id=0x34)


async def _drain_pattern(
    tool: Tool, args: str, ctx: ToolContext
) -> tuple[list[str], str]:
    """Drain a tool's ``stream()`` async generator into
    (intermediate deltas, terminator kind slug). The terminator's
    own delta is appended to the delta list IFF non-empty (mirrors
    the Rust ``drain_pattern`` helper)."""
    deltas: list[str] = []
    terminator = "none"
    async for chunk in tool.stream(args, ctx):
        if chunk.delta:
            deltas.append(chunk.delta)
        if chunk.finish_reason is not None:
            fr = chunk.finish_reason
            if isinstance(fr, ToolFinishStop):
                terminator = "stop"
            elif isinstance(fr, ToolFinishError):
                terminator = "error"
            elif isinstance(fr, ToolFinishCancelled):
                terminator = "cancelled"
            break
    return deltas, terminator


# ═══════════════════════════════════════════════════════════════════
#  §1 — Each pattern produces its canonical delta sequence × 8
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_chunked_list_processor_emits_per_item():
    deltas, term = await _drain_pattern(
        ChunkedListProcessor(), "alpha,beta,gamma", _fresh_ctx()
    )
    assert deltas == ["item:alpha", "item:beta", "item:gamma"]
    assert term == "stop"


@pytest.mark.asyncio
async def test_chunked_list_processor_empty_input_emits_only_terminator():
    deltas, term = await _drain_pattern(
        ChunkedListProcessor(), "", _fresh_ctx()
    )
    assert deltas == []
    assert term == "stop"


@pytest.mark.asyncio
async def test_progressive_refinement_emits_three_stages():
    deltas, term = await _drain_pattern(
        ProgressiveRefinement(), "hello", _fresh_ctx()
    )
    assert deltas == ["draft:hello", "refined:hello", "final:hello"]
    assert term == "stop"


@pytest.mark.asyncio
async def test_paginated_source_emits_n_pages():
    deltas, term = await _drain_pattern(PaginatedSource(), "4", _fresh_ctx())
    assert deltas == ["page-0", "page-1", "page-2", "page-3"]
    assert term == "stop"


@pytest.mark.asyncio
async def test_multi_stage_pipeline_emits_four_stages():
    deltas, term = await _drain_pattern(
        MultiStagePipeline(), "data", _fresh_ctx()
    )
    assert deltas == [
        "stage:parse:data",
        "stage:transform:data",
        "stage:validate:data",
        "stage:emit:data",
    ]
    assert term == "stop"


@pytest.mark.asyncio
async def test_progress_reporter_emits_progress_then_result():
    deltas, term = await _drain_pattern(
        ProgressReporter(), "output", _fresh_ctx()
    )
    assert deltas == [
        "progress:25",
        "progress:50",
        "progress:75",
        "progress:100",
        "result:output",
    ]
    assert term == "stop"


@pytest.mark.asyncio
async def test_early_error_tool_emits_partials_then_error_terminator():
    deltas, term = await _drain_pattern(EarlyErrorTool(), "task", _fresh_ctx())
    assert deltas == ["partial:task:1", "partial:task:2"]
    assert term == "error"


@pytest.mark.asyncio
async def test_burst_producer_emits_n_burst_chunks():
    deltas, term = await _drain_pattern(BurstProducer(), "6", _fresh_ctx())
    assert len(deltas) == 6
    assert deltas[0] == "burst-0"
    assert deltas[5] == "burst-5"
    assert term == "stop"


# ═══════════════════════════════════════════════════════════════════
#  §2 — Cancel discipline (D5 cancel-into-tool-body)
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cancel_aware_counter_runs_to_completion_without_cancel():
    deltas, term = await _drain_pattern(
        CancelAwareCounter(), "5", _fresh_ctx()
    )
    assert deltas == ["tick-0", "tick-1", "tick-2", "tick-3", "tick-4"]
    assert term == "stop"


@pytest.mark.asyncio
async def test_cancel_aware_counter_honors_mid_stream_cancel():
    # Drain manually, firing cancel after 2 ticks. The tool's
    # per-tick cancel poll observes the flag + emits a Cancelled
    # terminator instead of continuing to tick-49.
    cancel = asyncio.Event()
    ctx = ToolContext(cancel=cancel, trace_id=0)
    deltas: list[str] = []
    terminator = "none"
    pulled = 0
    async for chunk in CancelAwareCounter().stream("50", ctx):
        if chunk.delta:
            deltas.append(chunk.delta)
        pulled += 1
        if pulled == 2:
            cancel.set()  # fire after 2 ticks
        if chunk.finish_reason is not None:
            fr = chunk.finish_reason
            if isinstance(fr, ToolFinishCancelled):
                terminator = "cancelled"
            elif isinstance(fr, ToolFinishStop):
                terminator = "stop"
            elif isinstance(fr, ToolFinishError):
                terminator = "error"
            break
    assert terminator == "cancelled"
    assert len(deltas) < 50, "cancel short-circuited the count"
    assert all(d.startswith("tick-") for d in deltas)


# ═══════════════════════════════════════════════════════════════════
#  §3 — execute() synchronous path (D9 backwards-compat)
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_execute_paths_materialize_pattern_output():
    ctx = _fresh_ctx()
    assert (
        await ChunkedListProcessor().execute("a,b", ctx) == "item:a|item:b"
    )
    assert (
        await ProgressiveRefinement().execute("x", ctx)
        == "draft:x|refined:x|final:x"
    )
    assert await PaginatedSource().execute("2", ctx) == "page-0|page-1"
    assert await BurstProducer().execute("3", ctx) == "burst of 3"


@pytest.mark.asyncio
async def test_every_pattern_reports_is_streaming_true():
    for name, cls in _PATTERN_REGISTRY.items():
        assert cls().is_streaming() is True, f"{name} must be streaming"


# ═══════════════════════════════════════════════════════════════════
#  §4 — Cross-stack canonical corpus pin
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name,args,expected_deltas,terminator_kind",
    CANONICAL_CORPUS,
    ids=[c[0] for c in CANONICAL_CORPUS],
)
async def test_canonical_corpus_parity(
    tool_name: str,
    args: str,
    expected_deltas: list[str],
    terminator_kind: str,
):
    """The single source of cross-stack truth: every pattern, when
    streamed with its corpus input, MUST produce exactly the
    recorded delta sequence + terminator kind. The Rust mirror
    ``axon-rs/tests/fase34_canonical_stream_tools.rs`` asserts the
    SAME corpus — drift in either stack fails both gates."""
    tool = _PATTERN_REGISTRY[tool_name]()
    deltas, term = await _drain_pattern(tool, args, _fresh_ctx())
    assert deltas == expected_deltas, f"corpus drift on {tool_name}"
    assert term == terminator_kind, f"terminator drift on {tool_name}"


def test_corpus_covers_all_eight_patterns():
    assert len(CANONICAL_CORPUS) == 8
    names = {c[0] for c in CANONICAL_CORPUS}
    assert names == set(_PATTERN_REGISTRY.keys()), (
        "CANONICAL_CORPUS must cover exactly the 8 registered patterns"
    )
    kinds = {c[3] for c in CANONICAL_CORPUS}
    assert "stop" in kinds
    assert "error" in kinds
