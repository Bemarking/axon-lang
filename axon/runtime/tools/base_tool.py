"""
AXON Runtime — Base Tool Interface (v0.11.0)
==============================================
Abstract base class and result types for all runtime tools.

Every tool in the AXON runtime implements ``BaseTool``, whether
it's a Phase 4 stub or a Phase 5/6 real backend. The interface
is async from the ground up so real backends can make I/O calls
without blocking the event loop.

v0.11.0 additions:
- ``TypedToolResult`` — extends ``ToolResult`` with epistemic type
  information (confidence, semantic type, provenance).
- ``BaseTool.SCHEMA`` — optional ``ToolSchema`` for formal contracts.

Architecture::

    COMPILE TIME (StdlibTool / IRToolSpec)
        → defines the SPEC: parameter schemas, types, metadata
    RUNTIME (BaseTool)
        → defines the EXECUTION: stub or real backend
    BRIDGE (ToolDispatcher)
        → reads IRToolSpec, calls the registered BaseTool
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar


# ═══════════════════════════════════════════════════════════════════
#  TOOL RESULT — standardised output of any tool execution
# ═══════════════════════════════════════════════════════════════════


@dataclass
class ToolResult:
    """Standardised result returned by every tool execution.

    Attributes:
        success:   ``True`` if the tool completed without error.
        data:      The payload — its shape depends on the tool.
        error:     Human-readable error message on failure.
        metadata:  Extra info (provider, timings, warnings, etc.).
    """

    success: bool
    data: Any
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        result: dict[str, Any] = {
            "success": self.success,
            "data": self.data,
        }
        if self.error is not None:
            result["error"] = self.error
        if self.metadata:
            result["metadata"] = self.metadata
        return result


# ═══════════════════════════════════════════════════════════════════
#  TYPED TOOL RESULT — extended result with epistemic metadata
# ═══════════════════════════════════════════════════════════════════


@dataclass
class TypedToolResult(ToolResult):
    """Extended tool result with epistemic type information.

    Maps directly to the epistemic lattice from §5 (Lattice Theory)
    of the mathematical prompt optimization research.  The
    ``to_epistemic_type()`` method converts confidence + mode into
    one of the lattice nodes for taint propagation.

    Attributes:
        semantic_type:    Logical type of the data (e.g. ``"list[dict]"``).
        confidence:       0.0–1.0 confidence score of the result.
        epistemic_mode:   ``"know"``, ``"believe"``, or ``"speculate"``.
        provenance:       Source attribution (e.g. ``"serper.dev"``).
        execution_time_ms: Wall-clock execution time in milliseconds.
    """

    semantic_type: str = "Any"
    confidence: float = 1.0
    epistemic_mode: str = "know"  # know | believe | speculate
    provenance: str = ""
    execution_time_ms: float = 0.0
    # v0.14.0 — Convergence Theorems 2 & 3: effect tracking
    tainted: bool = False              # True if data crossed FFI boundary
    epistemic_source: str = ""         # effect row epistemic level of source tool

    def to_epistemic_type(self) -> str:
        """Map to epistemic lattice node.

        Returns one of:
        - ``"CitedFact"``    — high confidence, know-mode
        - ``"Uncertainty"``  — low confidence (any mode)
        - ``"Speculation"``  — mid confidence, non-know mode
        - ``"Belief"``       — mid confidence, believe mode
        """
        if self.confidence >= 0.8 and self.epistemic_mode == "know":
            return "CitedFact"
        if self.confidence < 0.4:
            return "Uncertainty"
        if self.epistemic_mode == "speculate":
            return "Speculation"
        if self.epistemic_mode == "believe":
            return "Belief"
        return "CitedFact"  # default for know-mode + mid confidence

    def to_dict(self) -> dict[str, Any]:
        """Serialize including epistemic fields."""
        result = super().to_dict()
        result["semantic_type"] = self.semantic_type
        result["confidence"] = self.confidence
        result["epistemic_mode"] = self.epistemic_mode
        if self.provenance:
            result["provenance"] = self.provenance
        if self.execution_time_ms > 0:
            result["execution_time_ms"] = self.execution_time_ms
        return result


# ═══════════════════════════════════════════════════════════════════
#  BASE TOOL — abstract contract for all runtime tools
# ═══════════════════════════════════════════════════════════════════


class BaseTool(ABC):
    """Abstract base class that every AXON runtime tool must implement.

    Subclasses MUST set the two class-level constants:

    * ``TOOL_NAME``  — unique identifier matching the ``IRToolSpec.name``.
    * ``IS_STUB``    — ``True`` for Phase 4 stubs, ``False`` for real
                       backends.

    And implement two methods:

    * ``validate_config()`` — verify the config dict at construction.
    * ``execute()``         — the async execution entry point.

    Example::

        class WebSearchBrave(BaseTool):
            TOOL_NAME = "WebSearch"
            IS_STUB = False
            DEFAULT_TIMEOUT = 10.0

            def validate_config(self) -> None:
                if "api_key" not in self.config:
                    raise ValueError("Missing api_key")

            async def execute(self, query: str, **kwargs) -> ToolResult:
                ...
    """

    # ── Class-level constants (override in subclass) ─────────────
    TOOL_NAME: ClassVar[str] = ""
    IS_STUB: ClassVar[bool] = False
    DEFAULT_TIMEOUT: ClassVar[float] = 30.0
    SCHEMA: ClassVar[Any] = None  # Optional ToolSchema (v0.11.0)
    # v0.14.0 — Convergence Theorem 2: algebraic effect row
    # Declares the side-effects and epistemic level of this tool.
    # Example: ("io", "network"), epistemic="speculate"
    EFFECT_ROW: ClassVar[tuple[str, ...]] = ()       # ("io", "network", "pure")
    EPISTEMIC_LEVEL: ClassVar[str] = "believe"        # default: FFI = believe

    # ── Instance lifecycle ───────────────────────────────────────

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config: dict[str, Any] = config or {}
        self.validate_config()

    @abstractmethod
    def validate_config(self) -> None:
        """Validate that ``self.config`` has the required keys.

        Stubs may accept any config; real backends should raise
        ``ValueError`` for missing keys (e.g. ``api_key``).
        """

    # ── Execution ────────────────────────────────────────────────

    @abstractmethod
    async def execute(self, query: str, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given query.

        This is the **only** execution interface.  All tools must
        implement this as ``async def``.

        Args:
            query:    The primary input (e.g. search query, code, path).
            **kwargs: Tool-specific parameters (e.g. ``max_results``).

        Returns:
            A ``ToolResult`` with ``success``/``data``/``error``.
        """

    # ── Convenience properties ───────────────────────────────────

    @property
    def get_tool_name(self) -> str:
        """Tool name (forwards to ``TOOL_NAME``)."""
        return self.TOOL_NAME

    @property
    def get_is_stub(self) -> bool:
        """Whether this implementation is a stub."""
        return self.IS_STUB

    def __repr__(self) -> str:
        stub_tag = " [STUB]" if self.IS_STUB else ""
        return f"<{self.__class__.__name__} '{self.TOOL_NAME}'{stub_tag}>"
