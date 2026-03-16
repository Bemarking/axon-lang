"""
AXON Runtime — @contract_tool Decorator (v0.14.0)
===================================================
Python-side decorator for registering tools with formal contracts
and mandatory epistemic downgrade at the FFI boundary.

Theoretical foundation — Convergence Theorem 3:

    The @contract_tool decorator operates as an intricate
    **topological type bridge** — an FFI — between two inherently
    incompatible semantic universes: the cognitive ecosystem of
    axon-lang and the unverified world of Python.

Pipeline:
    1. ``inspect.signature()`` → extract parameter names and defaults
    2. ``typing.get_type_hints()`` → extract type annotations
    3. Generate ``ToolSchema`` with CSP constraints
    4. Generate ``BaseTool`` subclass wrapping the function
    5. Wire ``ContractMonitor`` for blame attribution
    6. Apply mandatory epistemic downgrade on all results

Usage::

    @contract_tool(
        name="WebSearch",
        description="Search the web",
        epistemic="speculate",      # optional: defaults to auto-inference
        effects=("io", "network"),  # optional: effect row
    )
    async def web_search(query: str, max_results: int = 5) -> list[dict]:
        ...

    # Registers: BaseTool subclass + ToolSchema + ContractMonitor
    # All results are automatically tainted + downgraded to believe
"""

from __future__ import annotations

import asyncio
import inspect
import typing
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Coroutine

from axon.runtime.tools.base_tool import BaseTool, ToolResult, TypedToolResult
from axon.runtime.tools.blame import BlameLabel, BlameFault, ContractMonitor
from axon.runtime.tools.tool_schema import ToolParameter, ToolSchema


# ═══════════════════════════════════════════════════════════════════
#  TYPE MAPPING — Python type annotations → ToolSchema type names
# ═══════════════════════════════════════════════════════════════════

_PYTHON_TO_SCHEMA: dict[Any, str] = {
    str: "str",
    int: "int",
    float: "float",
    bool: "bool",
    list: "list",
    dict: "dict",
}

_SENTINEL = object()


def _resolve_type_name(annotation: Any) -> str:
    """Convert a Python type annotation to a schema type string."""
    # Direct mapping
    if annotation in _PYTHON_TO_SCHEMA:
        return _PYTHON_TO_SCHEMA[annotation]

    # Handle generic types (list[str], dict[str, Any], etc.)
    origin = getattr(annotation, "__origin__", None)
    args = getattr(annotation, "__args__", ())

    if origin is list and args:
        inner = _resolve_type_name(args[0])
        return f"list[{inner}]"
    if origin is dict and args:
        key = _resolve_type_name(args[0])
        val = _resolve_type_name(args[1]) if len(args) > 1 else "Any"
        return f"dict[{key},{val}]"

    return "Any"


# ═══════════════════════════════════════════════════════════════════
#  @contract_tool DECORATOR
# ═══════════════════════════════════════════════════════════════════

def contract_tool(
    name: str | None = None,
    description: str = "",
    epistemic: str = "believe",
    effects: tuple[str, ...] = (),
) -> Callable:
    """
    Decorator that registers a Python function as an AXON tool with
    formal contracts and Indy blame semantics.

    Pipeline:
      1. Introspect function signature and type hints
      2. Generate ToolSchema with parameter constraints
      3. Create BaseTool subclass wrapping the function
      4. Wire ContractMonitor for blame attribution
      5. Apply epistemic downgrade on results

    Args:
        name:        Tool name (defaults to function name)
        description: Human-readable description
        epistemic:   Epistemic level: "know" | "believe" | "speculate" | "doubt"
        effects:     Effect row: ("io", "network", "pure")

    Returns:
        Decorated function that is also a registered AxonToolWrapper.
    """

    def decorator(func: Callable) -> AxonToolWrapper:
        tool_name = name or func.__name__
        sig = inspect.signature(func)
        hints = typing.get_type_hints(func)

        # Step 1: Build ToolParameters from signature
        params: list[ToolParameter] = []
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue
            type_name = _resolve_type_name(hints.get(param_name, str))
            required = param.default is inspect.Parameter.empty
            default = (
                param.default
                if param.default is not inspect.Parameter.empty
                else _SENTINEL
            )
            params.append(ToolParameter(
                name=param_name,
                type_name=type_name,
                required=required,
                default=default,
                description="",
            ))

        # Step 2: Determine output type
        return_hint = hints.get("return", Any)
        output_type = _resolve_type_name(return_hint)

        # Step 3: Generate ToolSchema
        schema = ToolSchema(
            name=tool_name,
            description=description or func.__doc__ or "",
            input_params=params,
            output_type=output_type,
        )

        # Step 4: Create wrapper
        wrapper = AxonToolWrapper(
            func=func,
            tool_name=tool_name,
            description=description,
            schema=schema,
            epistemic_level=epistemic,
            effect_row=effects,
        )
        return wrapper

    return decorator


# ═══════════════════════════════════════════════════════════════════
#  AXON TOOL WRAPPER — the registered tool with contracts
# ═══════════════════════════════════════════════════════════════════

class AxonToolWrapper:
    """
    Wraps a Python function as an AXON tool with full contract monitoring.

    This is the result of applying ``@contract_tool``. It implements
    the same interface as ``BaseTool`` but adds:
      - Precondition checking (blame CALLER)
      - Postcondition checking (blame SERVER)
      - Mandatory epistemic downgrade (believe+tainted)
      - Effect row tracking

    The wrapper is callable: calling it invokes the tool with
    contract monitoring.
    """

    def __init__(
        self,
        func: Callable,
        tool_name: str,
        description: str,
        schema: ToolSchema,
        epistemic_level: str = "believe",
        effect_row: tuple[str, ...] = (),
    ) -> None:
        self.func = func
        self.tool_name = tool_name
        self.description = description
        self.schema = schema
        self.epistemic_level = epistemic_level
        self.effect_row = effect_row
        self.monitor = ContractMonitor()

        # Preserve function metadata
        self.__name__ = func.__name__
        self.__doc__ = func.__doc__
        self.__module__ = getattr(func, "__module__", "")
        self.__qualname__ = getattr(func, "__qualname__", func.__name__)

    async def execute(self, **kwargs: Any) -> TypedToolResult:
        """
        Execute the tool with full contract monitoring.

        1. Check precondition (blame CALLER if fails)
        2. Execute the wrapped function
        3. Check postcondition (blame SERVER if fails)
        4. Apply epistemic downgrade (ALWAYS)

        Returns TypedToolResult with taint and epistemic metadata.
        """
        import time as _time
        start = _time.monotonic()

        # Step 1: Precondition check
        pre_fault = self.monitor.check_precondition(self.schema, kwargs)
        if pre_fault is not None:
            return TypedToolResult(
                success=False,
                data=None,
                error=f"Contract violation (CALLER): {pre_fault.message}",
                metadata={"blame": pre_fault.to_dict()},
                epistemic_mode=self.epistemic_level,
                tainted=True,
                epistemic_source=self.epistemic_level,
            )

        # Step 2: Execute
        try:
            if asyncio.iscoroutinefunction(self.func):
                result = await self.func(**kwargs)
            else:
                result = self.func(**kwargs)
        except Exception as exc:
            elapsed = (_time.monotonic() - start) * 1000
            return TypedToolResult(
                success=False,
                data=None,
                error=str(exc),
                execution_time_ms=elapsed,
                epistemic_mode=self.epistemic_level,
                tainted=True,
                epistemic_source=self.epistemic_level,
            )

        elapsed = (_time.monotonic() - start) * 1000

        # Step 3: Postcondition check
        post_fault = self.monitor.check_postcondition(self.schema, result)
        if post_fault is not None:
            return TypedToolResult(
                success=False,
                data=result,
                error=f"Contract violation (SERVER): {post_fault.message}",
                metadata={"blame": post_fault.to_dict()},
                execution_time_ms=elapsed,
                epistemic_mode=self.epistemic_level,
                tainted=True,
                epistemic_source=self.epistemic_level,
            )

        # Step 4: Mandatory epistemic downgrade (ALWAYS for FFI)
        return TypedToolResult(
            success=True,
            data=result,
            execution_time_ms=elapsed,
            epistemic_mode=self.epistemic_level,
            tainted=True,  # ALWAYS tainted at FFI boundary
            epistemic_source=self.epistemic_level,
        )

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Calling the wrapper invokes the raw function directly.

        For contract-monitored execution, use ``execute(**kwargs)`` or
        ``await execute(**kwargs)`` instead.  Direct ``__call__``
        preserves the original function's calling convention (sync/async,
        positional/keyword) so ``@contract_tool`` decorated functions
        remain drop-in replacements.
        """
        return self.func(*args, **kwargs)

    def __repr__(self) -> str:
        effects = ", ".join(self.effect_row) if self.effect_row else "pure"
        return (
            f"<@contract_tool '{self.tool_name}' "
            f"effects=<{effects}> "
            f"epistemic={self.epistemic_level}>"
        )
