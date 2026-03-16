"""
AXON Runtime — Tools Package (v0.14.0)
========================================
Public API for the AXON tool system.

This package provides:

**Core Types (v0.10):**
- ``BaseTool``               — Abstract base class for all tools.
- ``ToolResult``             — Standardised execution result.
- ``RuntimeToolRegistry``    — Tool registration and lookup.
- ``ToolDispatcher``         — Bridge between IR and runtime tools.

**v0.11.0 Additions:**
- ``TypedToolResult``        — Extended result with epistemic metadata (W5).
- ``ToolSchema``             — Formal tool contracts (W1, W2).
- ``ToolParameter``          — Schema parameter specification (W2).
- ``ToolChain``              — Sequential tool composition (W4).
- ``ToolChainStep``          — Individual step in a chain (W4).
- ``ToolMetrics``            — Per-execution observation (W3).
- ``ToolMetricsCollector``   — Aggregation & feedback loop (W3, W7).

**v0.14.0 Additions (Convergence Theorems 1-4):**
- ``contract_tool``          — FFI decorator with blame semantics (CT-3).
- ``csp_tool``               — Auto-inferring CSP decorator (CT-4).
- ``BlameLabel``             — Blame attribution enum (CT-3).
- ``ContractMonitor``        — Pre/postcondition enforcement (CT-3).

Factory:
- ``create_default_registry(mode)`` — Quick setup with stubs, backends,
  or hybrid registration.
"""

from __future__ import annotations

from typing import Any

from axon.runtime.tools.base_tool import BaseTool, ToolResult, TypedToolResult
from axon.runtime.tools.dispatcher import ToolDispatcher
from axon.runtime.tools.registry import RuntimeToolRegistry
from axon.runtime.tools.tool_chain import ToolChain, ToolChainStep
from axon.runtime.tools.tool_metrics import ToolMetrics, ToolMetricsCollector
from axon.runtime.tools.tool_schema import ToolParameter, ToolSchema

# v0.14.0 — Convergence Theorems 3 & 4
from axon.runtime.tools.blame import BlameLabel, ContractMonitor
from axon.runtime.tools.contract_tool import contract_tool
from axon.runtime.tools.csp_tool import csp_tool


def create_default_registry(
    *,
    mode: str = "hybrid",
    config: dict[str, Any] | None = None,
) -> RuntimeToolRegistry:
    """Create a ``RuntimeToolRegistry`` with sensible defaults.

    Args:
        mode: One of ``"stub"``, ``"real"``, or ``"hybrid"``.

            * ``stub``   — all stubs, no real backends.
            * ``real``   — stubs first, then overwrite with real backends.
            * ``hybrid`` — stubs first, then only backends whose deps
                           are satisfied.

        config: Optional config dict passed to ``register_all_backends()``.

    Returns:
        A populated ``RuntimeToolRegistry``.
    """
    from axon.runtime.tools.stubs import register_all_stubs

    registry = RuntimeToolRegistry()

    if mode == "stub":
        register_all_stubs(registry)
    elif mode in ("real", "hybrid"):
        register_all_stubs(registry)
        from axon.runtime.tools.backends import register_all_backends
        register_all_backends(registry, config=config)
    else:
        raise ValueError(
            f"Unknown mode: {mode!r}. Use 'stub', 'real', or 'hybrid'."
        )

    return registry


__all__ = [
    # Core (v0.10)
    "BaseTool",
    "ToolResult",
    "RuntimeToolRegistry",
    "ToolDispatcher",
    "create_default_registry",
    # v0.11.0 additions
    "TypedToolResult",
    "ToolSchema",
    "ToolParameter",
    "ToolChain",
    "ToolChainStep",
    "ToolMetrics",
    "ToolMetricsCollector",
    # v0.14.0 additions (Convergence Theorems 1-4)
    "BlameLabel",
    "ContractMonitor",
    "contract_tool",
    "csp_tool",
]
