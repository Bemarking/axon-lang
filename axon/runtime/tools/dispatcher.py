"""
AXON Runtime — Tool Dispatcher (v0.11.0)
==========================================
Bridge between the compiler IR (``IRUseTool``) and the runtime
tool system (``BaseTool`` via ``RuntimeToolRegistry``).

The Executor calls ``ToolDispatcher.dispatch()`` whenever a compiled
step contains a tool invocation.  The dispatcher:

1. Resolves the tool name → ``BaseTool`` implementation via the registry.
2. Validates input against ``tool.SCHEMA`` if present (W2).
3. Applies the tool's configured timeout.
4. Returns a ``TypedToolResult`` with execution time (W3).

v0.11.0 additions:
- Schema validation before execution (W2).
- ``dispatch_with_retry()`` — PID-informed exponential backoff (W6).
- ``dispatch_parallel()`` — concurrent dispatch via asyncio.gather (W8).
- Timing instrumentation in all paths.

This is the *only* integration point between compile-time metadata
(``IRToolSpec``) and runtime execution (``BaseTool.execute``).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from axon.compiler.ir_nodes import IRUseTool
from axon.runtime.tools.base_tool import BaseTool, ToolResult, TypedToolResult
from axon.runtime.tools.registry import RuntimeToolRegistry

logger = logging.getLogger(__name__)


class ToolDispatcher:
    """Dispatches ``IRUseTool`` nodes to registered ``BaseTool`` instances.

    Usage::

        registry = RuntimeToolRegistry()
        register_all_stubs(registry)   # Phase 4
        dispatcher = ToolDispatcher(registry)

        result = await dispatcher.dispatch(ir_use_tool, context={})
    """

    def __init__(
        self,
        registry: RuntimeToolRegistry,
        *,
        default_config: dict[str, Any] | None = None,
    ) -> None:
        """
        Args:
            registry:       The tool registry to look up implementations.
            default_config: Fallback config dict passed to tools that
                            don't have step-level config overrides.
        """
        self._registry = registry
        self._default_config = default_config or {}

    # ── Main dispatch ────────────────────────────────────────────

    async def dispatch(
        self,
        ir_use_tool: IRUseTool,
        *,
        context: dict[str, Any] | None = None,
        config_override: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Dispatch an IR tool invocation to the registered backend.

        Args:
            ir_use_tool:     The ``IRUseTool`` node from a compiled step.
            context:         Execution context (prior step results, etc.).
            config_override: Step-level config that overrides defaults.

        Returns:
            A ``ToolResult`` (or ``TypedToolResult``) from the executed tool.
        """
        tool_name = ir_use_tool.tool_name
        query = ir_use_tool.argument
        config = {**self._default_config, **(config_override or {})}

        logger.debug("Dispatching tool '%s' with query: %s", tool_name, query)

        # Resolve tool from registry
        try:
            tool = self._registry.get(tool_name, config or None)
        except KeyError as exc:
            return ToolResult(
                success=False,
                data=None,
                error=f"Tool not found: {exc}",
                metadata={"tool_name": tool_name},
            )

        # ── Schema validation (v0.11.0 — W2) ────────────────
        if tool.SCHEMA is not None:
            ctx_args = context or {}
            valid, errors = tool.SCHEMA.validate_input(
                {"query": query, **ctx_args}
            )
            if not valid:
                return ToolResult(
                    success=False,
                    data=None,
                    error=(
                        f"Schema validation failed for '{tool_name}': "
                        + "; ".join(errors)
                    ),
                    metadata={
                        "tool_name": tool_name,
                        "validation_errors": errors,
                    },
                )

        # Warn if stub
        if tool.IS_STUB:
            logger.warning(
                "⚠️  Using STUB for '%s' — data is simulated", tool_name
            )

        # Execute with timeout and timing
        timeout = tool.DEFAULT_TIMEOUT
        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                tool.execute(query, **(context or {})),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            elapsed = (time.perf_counter() - t0) * 1000
            return TypedToolResult(
                success=False,
                data=None,
                error=(
                    f"Tool '{tool_name}' timed out "
                    f"after {timeout}s"
                ),
                metadata={
                    "tool_name": tool_name,
                    "timeout_seconds": timeout,
                },
                execution_time_ms=elapsed,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = (time.perf_counter() - t0) * 1000
            logger.exception("Tool '%s' raised an exception", tool_name)
            return TypedToolResult(
                success=False,
                data=None,
                error=f"Tool '{tool_name}' failed: {exc}",
                metadata={"tool_name": tool_name},
                execution_time_ms=elapsed,
            )

        elapsed = (time.perf_counter() - t0) * 1000

        # Wrap in TypedToolResult if not already
        if isinstance(result, TypedToolResult):
            result.execution_time_ms = elapsed
        else:
            result = TypedToolResult(
                success=result.success,
                data=result.data,
                error=result.error,
                metadata=result.metadata,
                execution_time_ms=elapsed,
                provenance=("stub" if tool.IS_STUB else "backend"),
            )

        # Inject standard metadata
        result.metadata.setdefault("tool_name", tool_name)
        result.metadata.setdefault("is_stub", tool.IS_STUB)

        return result

    # ── Retry dispatch (v0.11.0 — W6) ───────────────────────────

    async def dispatch_with_retry(
        self,
        ir_use_tool: IRUseTool,
        *,
        context: dict[str, Any] | None = None,
        config_override: dict[str, Any] | None = None,
        max_retries: int = 3,
        base_delay: float = 0.5,
    ) -> ToolResult:
        """Dispatch with PID-informed exponential backoff on failure.

        Implements self-healing from §6 (Control Theory).  On each
        failure, the delay doubles (exponential backoff) and the
        previous error context is injected for the next attempt.

        Args:
            ir_use_tool:     The tool invocation node.
            context:         Execution context.
            config_override: Config overrides.
            max_retries:     Maximum retry attempts (total = max_retries + 1).
            base_delay:      Initial delay in seconds before first retry.

        Returns:
            The successful ``ToolResult``, or the last failure after
            exhausting all retries.
        """
        last_result: ToolResult | None = None
        ctx = dict(context or {})

        for attempt in range(1, max_retries + 2):  # +1 for initial try
            result = await self.dispatch(
                ir_use_tool,
                context=ctx,
                config_override=config_override,
            )

            # Inject attempt metadata
            result.metadata["attempt"] = attempt
            result.metadata["max_retries"] = max_retries

            if result.success:
                result.metadata["total_attempts"] = attempt
                return result

            last_result = result
            logger.warning(
                "Tool '%s' failed (attempt %d/%d): %s",
                ir_use_tool.tool_name, attempt, max_retries + 1,
                result.error,
            )

            if attempt <= max_retries:
                # Inject failure context for next attempt (self-healing)
                ctx["_previous_error"] = result.error
                ctx["_retry_attempt"] = attempt

                # Exponential backoff
                delay = base_delay * (2 ** (attempt - 1))
                await asyncio.sleep(delay)

        assert last_result is not None
        last_result.metadata["total_attempts"] = max_retries + 1
        last_result.metadata["exhausted_retries"] = True
        return last_result

    # ── Parallel dispatch (v0.11.0 — W8) ────────────────────────

    async def dispatch_parallel(
        self,
        invocations: list[IRUseTool],
        *,
        context: dict[str, Any] | None = None,
        config_override: dict[str, Any] | None = None,
    ) -> list[ToolResult]:
        """Dispatch multiple independent tools concurrently.

        Uses ``asyncio.gather`` with ``return_exceptions=True``
        so one failure doesn't crash the others.

        Args:
            invocations:     List of ``IRUseTool`` nodes to dispatch.
            context:         Shared context (read-only assumed).
            config_override: Config overrides applied to all tools.

        Returns:
            List of ``ToolResult`` objects in the same order as
            *invocations*.
        """
        if not invocations:
            return []

        async def _safe_dispatch(ir: IRUseTool) -> ToolResult:
            try:
                return await self.dispatch(
                    ir, context=context, config_override=config_override,
                )
            except Exception as exc:  # noqa: BLE001
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"Parallel dispatch error: {exc}",
                    metadata={"tool_name": ir.tool_name},
                )

        results = await asyncio.gather(
            *(_safe_dispatch(ir) for ir in invocations),
        )
        return list(results)

    # ── Convenience ──────────────────────────────────────────────

    @property
    def registry(self) -> RuntimeToolRegistry:
        """The underlying tool registry."""
        return self._registry

    def __repr__(self) -> str:
        return f"<ToolDispatcher registry={self._registry!r}>"
