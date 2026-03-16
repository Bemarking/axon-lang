"""
AXON Runtime — @csp_tool Decorator (v0.14.0)
===============================================
Auto-generates constraint satisfaction (CSP) specifications from
Python function signatures, including epistemic inference.

Theoretical foundation — Convergence Theorem 4:

    @csp_tool : (Python function) → ∀(constraints, epistemic_level, effect_row)

    The decorator performs FULL automatic inference:
      1. Signature → ToolSchema (parameter constraints)
      2. Signature → Epistemic level (heuristic inference)
      3. Signature → Effect row (side-effect analysis)

    This is the "zero-friction" API for tool authors who don't
    want to manually annotate constraints. The decorator does
    the right thing by default, with conservative assumptions.

Comparison with @contract_tool:
    @contract_tool — explicit: YOU declare epistemic + effects
    @csp_tool      — automatic: WE infer epistemic + effects

Usage::

    @csp_tool
    async def web_search(query: str, max_results: int = 5) -> list[dict]:
        '''Search the web for results.'''
        ...

    # Automatically inferred:
    # - epistemic_level: "speculate" (has no clear pure markers)
    # - effect_row: ("io",) (async function)
    # - schema: ToolSchema(query=str required, max_results=int optional)

    @csp_tool(description="Custom description")
    async def custom_tool(data: dict) -> str:
        ...
"""

from __future__ import annotations

from typing import Any, Callable

from axon.runtime.tools.contract_tool import contract_tool, AxonToolWrapper
from axon.runtime.tools.epistemic_inference import (
    infer_effect_row,
    infer_epistemic_level,
)


# ═══════════════════════════════════════════════════════════════════
#  @csp_tool DECORATOR — auto-inference version of @contract_tool
# ═══════════════════════════════════════════════════════════════════

def csp_tool(
    func: Callable | None = None,
    *,
    name: str | None = None,
    description: str = "",
) -> AxonToolWrapper | Callable:
    """
    Auto-inferring tool decorator with CSP constraint generation.

    Unlike ``@contract_tool`` which requires explicit annotations,
    ``@csp_tool`` infers everything from the Python signature:

      - **Epistemic level**: inferred from function name, params,
        and async/sync nature using heuristic rules.
      - **Effect row**: inferred from parameter names and I/O markers.
      - **Schema**: generated from type hints and defaults.

    Can be used with or without arguments::

        @csp_tool                              # bare decorator
        async def my_tool(...)                 # auto-infer everything

        @csp_tool(name="CustomName")           # with optional args
        async def my_tool(...)                 # auto-infer epistemic/effects

    Args:
        func:        When used as bare decorator, the function itself.
        name:        Optional tool name (defaults to function name).
        description: Optional description (defaults to docstring).

    Returns:
        An AxonToolWrapper with fully inferred contracts.
    """

    def _decorate(fn: Callable) -> AxonToolWrapper:
        # Auto-infer epistemic level and effects
        epistemic = infer_epistemic_level(fn)
        effects = infer_effect_row(fn)

        # Delegate to @contract_tool with inferred values
        return contract_tool(
            name=name or fn.__name__,
            description=description or fn.__doc__ or "",
            epistemic=epistemic,
            effects=effects,
        )(fn)

    # Support both @csp_tool and @csp_tool(...)
    if func is not None:
        return _decorate(func)
    return _decorate
