"""
AXON Runtime — Tool Chain (v0.11.0)
=====================================
Sequential composition of tools with typed data flow piping.

A ``ToolChain`` declares an ordered list of tool invocations
where each step's output feeds into the next step's input.
Addresses weakness **W4** (no tool composition) from the
fortification analysis.

Example::

    chain = ToolChain(
        steps=[
            ToolChainStep("WebSearch", param_map={"query": "input"}),
            ToolChainStep("PDFExtractor", param_map={"query": "data[0].url"}),
        ]
    )
    result = await chain.execute(dispatcher, initial_input="AXON paper")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from axon.runtime.tools.base_tool import ToolResult

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  ToolChainStep — single step in a chain
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ToolChainStep:
    """One step in a tool chain.

    Attributes:
        tool_name: Name of the tool to invoke (must be in registry).
        param_map: Maps step parameter names to the data path from
                   the previous step's output.  The special key
                   ``"input"`` refers to the chain's initial input.
        extra_kwargs: Additional keyword arguments to pass to the tool.
    """

    tool_name: str
    param_map: dict[str, str] = field(default_factory=dict)
    extra_kwargs: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"ToolChainStep({self.tool_name})"


# ═══════════════════════════════════════════════════════════════════
#  ToolChain — sequential composition
# ═══════════════════════════════════════════════════════════════════


@dataclass
class ToolChain:
    """Sequential composition of tools with typed data flow.

    Each step receives the previous step's ``ToolResult.data``
    (or the initial input for the first step) and pipes it
    through a ``param_map`` to construct the tool's arguments.

    Fail-fast behaviour: if any step returns ``success=False``,
    the chain halts and returns that failure.

    Attributes:
        steps:       Ordered list of ``ToolChainStep`` objects.
        name:        Optional label for the chain.
        description: Optional documentation.
    """

    steps: list[ToolChainStep]
    name: str = ""
    description: str = ""

    async def execute(
        self,
        dispatcher: Any,
        initial_input: str = "",
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Execute the chain sequentially.

        Args:
            dispatcher:    A ``ToolDispatcher`` instance.
            initial_input: Input string for the first step.
            context:       Shared context dict available to all steps.

        Returns:
            The ``ToolResult`` of the last step, or the first failing step.
        """
        if not self.steps:
            return ToolResult(
                success=True,
                data=None,
                metadata={"chain": self.name, "steps": 0},
            )

        ctx = context or {}
        previous_data: Any = initial_input
        previous_result: ToolResult | None = None

        for i, step in enumerate(self.steps):
            logger.debug(
                "Chain '%s' step %d/%d: %s",
                self.name, i + 1, len(self.steps), step.tool_name,
            )

            # Build the query and kwargs from param_map
            query = self._resolve_query(step, previous_data, initial_input)
            kwargs = dict(step.extra_kwargs)
            kwargs.update(
                self._resolve_extra(step.param_map, previous_data, ctx)
            )

            # Use the dispatcher's dispatch method
            from axon.compiler.ir_nodes import IRUseTool

            ir_node = IRUseTool(tool_name=step.tool_name, argument=query)
            result = await dispatcher.dispatch(ir_node)

            if not result.success:
                logger.warning(
                    "Chain '%s' failed at step %d (%s): %s",
                    self.name, i + 1, step.tool_name, result.error,
                )
                result.metadata["chain"] = self.name
                result.metadata["failed_step"] = i + 1
                result.metadata["failed_tool"] = step.tool_name
                return result

            previous_data = result.data
            previous_result = result

        # Enrich final result with chain metadata
        assert previous_result is not None
        previous_result.metadata["chain"] = self.name
        previous_result.metadata["total_steps"] = len(self.steps)
        return previous_result

    # ── helpers ───────────────────────────────────────────────

    @staticmethod
    def _resolve_query(
        step: ToolChainStep,
        previous_data: Any,
        initial_input: str,
    ) -> str:
        """Determine the ``query`` argument for a step.

        If ``param_map`` has ``"query"`` → ``"input"``, uses the
        chain's initial input.  If ``"query"`` → ``"data"``, uses
        the previous step's raw data (stringified).
        """
        target = step.param_map.get("query", "data")

        if target == "input":
            return initial_input
        if target == "data":
            if isinstance(previous_data, str):
                return previous_data
            return str(previous_data)

        # Support simple dotted access: "data[0].url" etc.
        return str(previous_data)

    @staticmethod
    def _resolve_extra(
        param_map: dict[str, str],
        previous_data: Any,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve extra parameters from param_map (excluding 'query')."""
        extra: dict[str, Any] = {}
        for param_name, source in param_map.items():
            if param_name == "query":
                continue
            if source.startswith("ctx."):
                key = source[4:]
                extra[param_name] = context.get(key)
            elif source == "data":
                extra[param_name] = previous_data
        return extra

    def __repr__(self) -> str:
        steps_str = " → ".join(s.tool_name for s in self.steps)
        return f"ToolChain({self.name or 'unnamed'}: {steps_str})"
