"""
AXON Runtime — Data Science Dispatcher
========================================
Routes Data Science IR nodes directly to the in-memory associative
engine, bypassing the LLM model call pipeline.

This follows the same dispatch pattern as ``ToolDispatcher``: the
executor checks step metadata for a ``"data_science"`` flag and
delegates to this dispatcher instead of making a model call.

Usage::

    from axon.runtime.data_dispatcher import DataScienceDispatcher

    dispatcher = DataScienceDispatcher()
    result = await dispatcher.dispatch(ir_node, context={})

    if result.success:
        print(result.data)
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from axon.compiler.ir_nodes import (
    IRAggregate,
    IRAssociate,
    IRDataSpace,
    IRExplore,
    IRFocus,
    IRIngest,
    IRNode,
)
from axon.engine.dataspace import DataSpace


# ═══════════════════════════════════════════════════════════════════
#  RESULT CONTAINER
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class DataScienceResult:
    """Result of executing a Data Science IR node.

    Attributes:
        success:   Whether the operation completed without error.
        operation: The IR operation name (e.g., ``"ingest"``, ``"focus"``).
        data:      The output data (varies by operation).
        error:     Error message if the operation failed.
        metadata:  Additional information about the execution.
    """

    success: bool = True
    operation: str = ""
    data: Any = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        result: dict[str, Any] = {
            "success": self.success,
            "operation": self.operation,
        }
        if self.data is not None:
            result["data"] = self.data
        if self.error:
            result["error"] = self.error
        if self.metadata:
            result["metadata"] = self.metadata
        return result


# ═══════════════════════════════════════════════════════════════════
#  DISPATCHER
# ═══════════════════════════════════════════════════════════════════


class DataScienceDispatcher:
    """Dispatches Data Science IR nodes to the in-memory engine.

    Maintains a registry of active ``DataSpace`` instances (one per
    ``dataspace`` declaration). Each IR node type maps to the
    corresponding engine operation:

    ==============================  ====================================
    IR Node                         Engine Operation
    ==============================  ====================================
    ``IRDataSpace``                 Create a new ``DataSpace`` instance
    ``IRIngest``                    ``DataSpace.load_table()``
    ``IRFocus``                     ``DataSpace.select()``
    ``IRAssociate``                 ``DataSpace.association_index.add_link()``
    ``IRAggregate``                 ``DataSpace.aggregate()``
    ``IRExplore``                   ``DataSpace.explore()``
    ==============================  ====================================
    """

    def __init__(self) -> None:
        self._spaces: dict[str, DataSpace] = {}
        self._active_space: DataSpace | None = None
        self._active_space_name: str = ""

    # ── Public API ────────────────────────────────────────────────

    @property
    def spaces(self) -> dict[str, DataSpace]:
        """Registry of all active DataSpace instances."""
        return dict(self._spaces)

    @property
    def active_space(self) -> DataSpace | None:
        """The currently active DataSpace (last created or selected)."""
        return self._active_space

    async def dispatch(
        self,
        node: IRNode,
        context: dict[str, Any] | None = None,
    ) -> DataScienceResult:
        """Execute a Data Science IR node against the engine.

        Args:
            node:    The IR node to execute.
            context: Optional execution context (step name, etc.).

        Returns:
            A ``DataScienceResult`` with the operation outcome.
        """
        ctx = context or {}

        dispatch_map = {
            IRDataSpace: self._exec_dataspace,
            IRIngest: self._exec_ingest,
            IRFocus: self._exec_focus,
            IRAssociate: self._exec_associate,
            IRAggregate: self._exec_aggregate,
            IRExplore: self._exec_explore,
        }

        handler = dispatch_map.get(type(node))
        if handler is None:
            return DataScienceResult(
                success=False,
                operation="unknown",
                error=f"Unknown Data Science IR node: {type(node).__name__}",
            )

        try:
            return await handler(node, ctx)
        except Exception as exc:
            return DataScienceResult(
                success=False,
                operation=type(node).__name__,
                error=str(exc),
            )

    # ── Internal Dispatch Methods ─────────────────────────────────

    async def _exec_dataspace(
        self, node: IRDataSpace, ctx: dict[str, Any]
    ) -> DataScienceResult:
        """Create a new DataSpace and register it."""
        space = DataSpace(name=node.name)
        self._spaces[node.name] = space
        self._active_space = space
        self._active_space_name = node.name

        # Execute body statements (ingest, associate, etc.)
        body_results: list[dict[str, Any]] = []
        for child in node.body:
            child_result = await self.dispatch(child, ctx)
            body_results.append(child_result.to_dict())
            if not child_result.success:
                return DataScienceResult(
                    success=False,
                    operation="dataspace",
                    error=f"Failed in dataspace '{node.name}': {child_result.error}",
                    metadata={"body_results": body_results},
                )

        return DataScienceResult(
            success=True,
            operation="dataspace",
            data={"name": node.name, "tables": list(space.tables.keys())},
            metadata={"body_results": body_results},
        )

    async def _exec_ingest(
        self, node: IRIngest, ctx: dict[str, Any]
    ) -> DataScienceResult:
        """Ingest data into the active DataSpace."""
        space = self._get_active_space()
        if space is None:
            return self._no_space_error("ingest")

        source = node.source
        target = node.target

        # Try to load from various sources
        data = self._resolve_source(source)
        if data is None:
            return DataScienceResult(
                success=False,
                operation="ingest",
                error=f"Cannot resolve data source: '{source}'",
            )

        # Load into the DataSpace
        space.load_table(target, data)

        return DataScienceResult(
            success=True,
            operation="ingest",
            data={
                "source": source,
                "target": target,
                "rows": len(data),
                "columns": list(data[0].keys()) if data else [],
            },
        )

    async def _exec_focus(
        self, node: IRFocus, ctx: dict[str, Any]
    ) -> DataScienceResult:
        """Apply a selection (focus) on the active DataSpace."""
        space = self._get_active_space()
        if space is None:
            return self._no_space_error("focus")

        # Parse the expression: "table.column = value"
        expr = node.expression
        table_name, field_name, value = self._parse_focus_expression(expr)

        if not table_name or not field_name:
            return DataScienceResult(
                success=False,
                operation="focus",
                error=f"Cannot parse focus expression: '{expr}'",
            )

        state = space.select(table_name, field_name, value)

        return DataScienceResult(
            success=True,
            operation="focus",
            data={
                "expression": expr,
                "state": state,
            },
        )

    async def _exec_associate(
        self, node: IRAssociate, ctx: dict[str, Any]
    ) -> DataScienceResult:
        """Create a manual association between tables."""
        space = self._get_active_space()
        if space is None:
            return self._no_space_error("associate")

        left = node.left
        right = node.right
        field = node.using_field

        if not field:
            return DataScienceResult(
                success=False,
                operation="associate",
                error=(
                    f"Manual association between '{left}' and '{right}' "
                    "requires a 'using' field"
                ),
            )

        space.association_index.add_link(left, right, field)

        return DataScienceResult(
            success=True,
            operation="associate",
            data={
                "left": left,
                "right": right,
                "using_field": field,
            },
        )

    async def _exec_aggregate(
        self, node: IRAggregate, ctx: dict[str, Any]
    ) -> DataScienceResult:
        """Execute an aggregation on the active DataSpace."""
        space = self._get_active_space()
        if space is None:
            return self._no_space_error("aggregate")

        target = node.target
        group_by = list(node.group_by)

        result = space.aggregate(target, group_by)

        return DataScienceResult(
            success=True,
            operation="aggregate",
            data={
                "target": target,
                "group_by": group_by,
                "alias": node.alias,
                "result": result,
            },
        )

    async def _exec_explore(
        self, node: IRExplore, ctx: dict[str, Any]
    ) -> DataScienceResult:
        """Explore a table in the active DataSpace."""
        space = self._get_active_space()
        if space is None:
            return self._no_space_error("explore")

        target = node.target
        limit = node.limit

        snapshot = space.explore(target, limit=limit)

        return DataScienceResult(
            success=True,
            operation="explore",
            data={
                "target": target,
                "limit": limit,
                "snapshot": snapshot,
            },
        )

    # ── Helpers ───────────────────────────────────────────────────

    def _get_active_space(self) -> DataSpace | None:
        """Get the currently active DataSpace."""
        return self._active_space

    def _no_space_error(self, operation: str) -> DataScienceResult:
        """Return an error for operations without an active DataSpace."""
        return DataScienceResult(
            success=False,
            operation=operation,
            error=(
                f"No active DataSpace for '{operation}'. "
                "Create one with 'dataspace MySpace {{ ... }}' first."
            ),
        )

    @staticmethod
    def _resolve_source(source: str) -> list[dict[str, Any]] | None:
        """Resolve a data source string to a list of row dicts.

        Supports:
        - File paths (CSV, JSON)
        - Inline JSON strings

        Args:
            source: The source identifier (path or inline data).

        Returns:
            A list of row dictionaries, or None if unresolvable.
        """
        # Try as JSON string first
        if source.strip().startswith("["):
            try:
                data = json.loads(source)
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        # Try as file path
        path = Path(source)
        if path.exists():
            if path.suffix.lower() == ".csv":
                return DataScienceDispatcher._load_csv(path)
            if path.suffix.lower() == ".json":
                return DataScienceDispatcher._load_json(path)

        return None

    @staticmethod
    def _load_csv(path: Path) -> list[dict[str, Any]]:
        """Load a CSV file into row dictionaries."""
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]

    @staticmethod
    def _load_json(path: Path) -> list[dict[str, Any]]:
        """Load a JSON file (must be an array of objects)."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return [data]

    @staticmethod
    def _parse_focus_expression(
        expr: str,
    ) -> tuple[str, str, str]:
        """Parse a focus expression like 'Sales.Region = "North"'.

        Returns:
            A tuple of (table_name, field_name, value).
            Returns empty strings if parsing fails.
        """
        # Split on '='
        if "=" not in expr:
            return ("", "", "")

        left, _, right = expr.partition("=")
        left = left.strip()
        right = right.strip().strip("'\"")

        # Split left on '.'
        if "." in left:
            table, _, column = left.partition(".")
            return (table.strip(), column.strip(), right)

        return ("", left, right)
