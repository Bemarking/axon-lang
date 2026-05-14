"""
AXON Runtime — Tool streaming surface (Fase 34.b, v1.29.0+)
============================================================

Cross-stack Python mirror of ``axon-rs/src/tool_trait.rs``. Ships
the structural foundation for tools-as-stream-producers:

- :class:`ToolFinishStop` / :class:`ToolFinishError` /
  :class:`ToolFinishCancelled` — closed-catalog finish reasons
  (sealed dataclasses sum-typed as ``ToolFinishReason``).
- :class:`ToolChunk` — closed-catalog tool stream chunk.
- :class:`ToolContext` — per-invocation context carrying the
  cancellation event + request-scoped trace_id.
- :class:`Tool` — async ABC with ``execute()`` + default
  ``stream()`` + default ``is_streaming()``. Default
  ``stream()`` wraps ``execute()`` as a single-chunk stream
  (D9 backwards-compat).

The existing :class:`axon.runtime.tools.base_tool.BaseTool` ABC
stays as-is — every existing tool keeps working unchanged. This
module is the structural foundation for the dispatcher's
streaming path (Fase 34.d wires it in).

D-letter coverage:

- **D1** — `Tool` trait surface.
- **D6** — ``ToolChunk`` shape supports per-chunk audit
  (counts + concatenated-delta hash; populated in Fase 34.i).
- **D9** — default ``stream()`` wraps ``execute()`` as a single-
  chunk stream so adopters who don't migrate see no behavior
  change.
- **D10** — cross-stack contract with axon-rs. The drift gate
  ``tests/test_fase34_b_tool_trait_cross_stack.py`` enforces the
  1-to-1 surface contract (closed-catalog membership, field
  names, method signatures).
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, ClassVar, Optional, Union


# ═══════════════════════════════════════════════════════════════════
#  ToolFinishReason — closed-catalog finish reason
# ═══════════════════════════════════════════════════════════════════
#
# Closed catalog mirrored from axon-rs ToolFinishReason enum.
# Sealed via sum-typed dataclasses with a class-level ``kind``
# discriminator matching the Rust serde tag.


@dataclass(frozen=True)
class ToolFinishStop:
    """Stream completed without error."""

    kind: ClassVar[str] = "stop"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "stop"}


@dataclass(frozen=True)
class ToolFinishError:
    """Tool execution failed mid-stream."""

    message: str
    kind: ClassVar[str] = "error"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "error", "message": self.message}


@dataclass(frozen=True)
class ToolFinishCancelled:
    """Cancellation propagated into the tool body (D5)."""

    kind: ClassVar[str] = "cancelled"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "cancelled"}


# Sum type alias for the closed-catalog finish reason.
ToolFinishReason = Union[ToolFinishStop, ToolFinishError, ToolFinishCancelled]


def parse_finish_reason(payload: dict[str, Any]) -> ToolFinishReason:
    """Deserialize a finish_reason payload into the closed-catalog
    variant. Raises :class:`ValueError` on unknown ``kind``."""
    kind = payload.get("kind")
    if kind == "stop":
        return ToolFinishStop()
    if kind == "error":
        return ToolFinishError(message=payload.get("message", ""))
    if kind == "cancelled":
        return ToolFinishCancelled()
    raise ValueError(
        f"33.b D1 closed-catalog violation: unknown ToolFinishReason "
        f"kind: {kind!r}. Closed catalog = "
        f"{{'stop', 'error', 'cancelled'}}"
    )


# Closed-catalog enumeration for drift-gate pins.
TOOL_FINISH_REASON_VARIANTS: tuple[str, ...] = ("stop", "error", "cancelled")


# ═══════════════════════════════════════════════════════════════════
#  ToolChunk — closed-catalog tool stream chunk
# ═══════════════════════════════════════════════════════════════════


@dataclass
class ToolChunk:
    """Closed-catalog tool stream chunk. Cross-stack mirror of
    axon-rs ``tool_trait::ToolChunk``.

    Field shape (matches Rust struct byte-identically modulo
    Python's None ↔ Rust Option<...> serde encoding):

    - ``delta``: chunk content (str).
    - ``timestamp_ms``: Unix milliseconds when the chunk was
      emitted (int).
    - ``finish_reason``: populated ONLY on the terminator chunk;
      ``None`` on intermediate chunks. Serde-elided when None
      per D4 byte-compat.
    """

    delta: str
    timestamp_ms: int
    finish_reason: Optional[ToolFinishReason] = None

    @staticmethod
    def now_ms() -> int:
        """Current Unix milliseconds."""
        return int(time.time() * 1000)

    @classmethod
    def intermediate(cls, delta: str) -> "ToolChunk":
        """Construct an intermediate chunk (continuation, no
        terminator)."""
        return cls(delta=delta, timestamp_ms=cls.now_ms(), finish_reason=None)

    @classmethod
    def terminator(
        cls,
        delta: str,
        finish_reason: ToolFinishReason,
    ) -> "ToolChunk":
        """Construct a terminator chunk carrying the given finish
        reason."""
        return cls(
            delta=delta,
            timestamp_ms=cls.now_ms(),
            finish_reason=finish_reason,
        )

    @classmethod
    def from_result(cls, result: Any) -> "ToolChunk":
        """Convert a synchronous :class:`ToolResult`-like object
        (success: bool, data: Any) into a single-chunk stream's
        terminator chunk. Used by the default ``Tool.stream()`` impl
        to wrap ``execute()`` results as a one-element stream (D9
        backwards-compat).

        Duck-typed against the existing
        :class:`axon.runtime.tools.base_tool.ToolResult` — does NOT
        import it to avoid a circular dependency.
        """
        success = bool(getattr(result, "success", True))
        data = getattr(result, "data", "")
        # ``data`` may be a structured payload (dict / list); we
        # str-coerce for the wire delta. Adopters who need richer
        # serialization override ``stream()`` directly.
        delta = data if isinstance(data, str) else str(data) if data is not None else ""

        if success:
            finish_reason: ToolFinishReason = ToolFinishStop()
        else:
            error_msg = getattr(result, "error", None) or "tool execution failed"
            finish_reason = ToolFinishError(message=str(error_msg))

        return cls(
            delta=delta,
            timestamp_ms=cls.now_ms(),
            finish_reason=finish_reason,
        )

    def is_terminator(self) -> bool:
        """Whether this chunk carries a ``finish_reason``."""
        return self.finish_reason is not None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict. ``finish_reason``
        is elided when None (D4 byte-compat)."""
        d: dict[str, Any] = {
            "delta": self.delta,
            "timestamp_ms": self.timestamp_ms,
        }
        if self.finish_reason is not None:
            d["finish_reason"] = self.finish_reason.to_dict()
        return d

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ToolChunk":
        """Deserialize from a JSON-compatible dict."""
        finish_reason: Optional[ToolFinishReason] = None
        if "finish_reason" in payload and payload["finish_reason"] is not None:
            finish_reason = parse_finish_reason(payload["finish_reason"])
        return cls(
            delta=payload["delta"],
            timestamp_ms=payload["timestamp_ms"],
            finish_reason=finish_reason,
        )


# ═══════════════════════════════════════════════════════════════════
#  ToolContext — per-invocation context
# ═══════════════════════════════════════════════════════════════════


@dataclass
class ToolContext:
    """Per-tool-invocation context. Cross-stack mirror of
    axon-rs ``tool_trait::ToolContext``.

    Carries:

    - ``cancel``: :class:`asyncio.Event` — tool bodies poll this
      between chunks for D5 cancel-into-tool-body propagation.
      The dispatcher's request-scoped cancel signal is wired
      through this field by the streaming dispatcher path
      (Fase 34.d).
    - ``trace_id``: request-scoped int — used by tools for
      audit-correlation + distributed-trace propagation
      downstream of the HTTP request.
    """

    cancel: asyncio.Event
    trace_id: int

    def is_cancelled(self) -> bool:
        """Whether cancellation has been signalled. Tool bodies
        poll this between chunks for cooperative cancel."""
        return self.cancel.is_set()


# ═══════════════════════════════════════════════════════════════════
#  Tool — async ABC for tool implementations
# ═══════════════════════════════════════════════════════════════════


class Tool(ABC):
    """Async tool ABC. Cross-stack Python mirror of axon-rs
    ``tool_trait::Tool``.

    Implementations define :meth:`execute` for synchronous tool
    invocation AND optionally override :meth:`stream` for
    per-chunk streaming dispatch.

    Default ``stream()`` impl invokes ``execute()`` and wraps the
    result as a single-chunk stream via
    :meth:`ToolChunk.from_result`. This is the D9 backwards-compat
    guarantee — every existing non-streaming tool automatically
    becomes a single-chunk stream producer when the dispatcher
    invokes ``stream()`` on it.

    The :meth:`is_streaming` flag defaults to ``False``. Tool
    implementations registered via the registry get this
    automatically derived from ``effect_row`` — presence of
    ``stream:<policy>`` sets it to ``True``. Adopters writing
    direct ``Tool`` impls override this method.
    """

    @abstractmethod
    async def execute(self, args: str, ctx: ToolContext) -> Any:
        """Execute the tool synchronously. Returns an arbitrary
        result (Python is duck-typed; the existing
        :class:`axon.runtime.tools.base_tool.ToolResult` is the
        canonical shape for cross-stack parity)."""
        ...

    async def stream(
        self, args: str, ctx: ToolContext
    ) -> AsyncIterator[ToolChunk]:
        """Stream the tool's output as a sequence of
        :class:`ToolChunk` instances.

        Default impl: invokes :meth:`execute` and yields a single
        terminator chunk via :meth:`ToolChunk.from_result`. This
        is the D9 backwards-compat guarantee.

        Adopters override this method when their tool body
        genuinely produces a stream (HTTP tools talking to SSE
        upstreams; MCP tools with partial-response notifications;
        native tools computing a sequence over a long-running
        computation). Implementations that override should also
        override :meth:`is_streaming` to return ``True``.
        """
        result = await self.execute(args, ctx)
        yield ToolChunk.from_result(result)

    def is_streaming(self) -> bool:
        """Whether this tool is a stream producer. Default:
        ``False``.

        The dispatcher's streaming path (Fase 34.d) reads this
        flag to decide whether to route through ``stream()`` or
        ``execute()``. Tools that override ``stream()`` SHOULD
        override this to return ``True``.
        """
        return False
