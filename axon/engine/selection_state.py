"""
AXON Engine — Selection State & Propagation Engine
=====================================================
Implements the associative selection model with AXON's custom palette.

When a user selects values in one column, the selection propagates
across all associated tables instantly:

  Selected   (#b8a40f Golden Amber)  → The values the user chose
  Associated (#FEF3C7 Warm Cream)    → Related/possible values
  Excluded   (#A8A29E Warm Gray)     → No association to selection

This is the heart of the associative model: instead of rigid JOINs
that hide data, ALL data remains visible with its relationship state
clearly indicated by color.

Algorithm:
  1. User selects values in a column → those values become SELECTED
  2. Find all rows matching the selection in that column
  3. For all OTHER columns in the same table:
     - Values present in matching rows → ASSOCIATED
     - Values NOT present → EXCLUDED
  4. For LINKED tables (via AssociationIndex):
     - Find the linking field values in matching rows
     - In the linked table, find rows matching those linking values
     - Repeat step 3 for the linked table
  5. Cascade across the entire association graph (BFS)
"""

from __future__ import annotations

from collections import deque
from enum import Enum
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from axon.engine.association_index import AssociationIndex
    from axon.engine.data_column import DataColumn


class SelectionState(Enum):
    """AXON selection states with custom palette colors."""
    SELECTED   = "#b8a40f"   # Golden Amber — dato elegido
    ASSOCIATED = "#FEF3C7"   # Warm Cream  — dato asociado
    EXCLUDED   = "#A8A29E"   # Warm Gray   — dato no asociado


class SelectionEngine:
    """Propagates selections across the association graph.

    Maintains the current selection state for every value in every
    column across all tables in the DataSpace.
    """

    __slots__ = ("_tables", "_association_index", "_selected_rows", "_state_cache")

    def __init__(
        self,
        tables: dict[str, dict[str, DataColumn]],
        association_index: AssociationIndex,
    ) -> None:
        # table_name → {column_name: DataColumn}
        self._tables = tables
        self._association_index = association_index
        # table_name → set of selected row indices
        self._selected_rows: dict[str, set[int]] = {}
        # Cache: (table, column) → {value: SelectionState}
        self._state_cache: dict[tuple[str, str], dict[Any, SelectionState]] = {}

    def select(
        self,
        table_name: str,
        column_name: str,
        values: list[Any],
    ) -> None:
        """Apply a selection and propagate across the association graph.

        Args:
            table_name: The table containing the selection column.
            column_name: The column being filtered.
            values: The values to select (these become SELECTED).
        """
        self.clear()

        if table_name not in self._tables:
            raise KeyError(f"Table '{table_name}' not found in DataSpace")
        table_columns = self._tables[table_name]
        if column_name not in table_columns:
            raise KeyError(
                f"Column '{column_name}' not found in table '{table_name}'"
            )

        source_column = table_columns[column_name]

        # Step 1: Find rows matching the selected values
        matching_rows: set[int] = set()
        for value in values:
            matching_rows |= source_column.rows_matching_value(value)

        self._selected_rows[table_name] = matching_rows

        # Step 2: Compute states for the source table
        self._compute_table_states(table_name, matching_rows, column_name, values)

        # Step 3: Propagate across linked tables (BFS)
        self._propagate(table_name, matching_rows)

    def _compute_table_states(
        self,
        table_name: str,
        active_rows: set[int],
        selection_column: str | None = None,
        selected_values: list[Any] | None = None,
    ) -> None:
        """Compute selection states for all columns in a table."""
        table_columns = self._tables[table_name]

        for col_name, column in table_columns.items():
            state: dict[Any, SelectionState] = {}
            all_values = column.distinct_values()

            if col_name == selection_column and selected_values is not None:
                # This is the selection column
                selected_set = set(selected_values)
                associated_values = column.values_at_rows(active_rows)
                for value in all_values:
                    if value in selected_set:
                        state[value] = SelectionState.SELECTED
                    elif value in associated_values:
                        state[value] = SelectionState.ASSOCIATED
                    else:
                        state[value] = SelectionState.EXCLUDED
            else:
                # Non-selection column: values in active rows are ASSOCIATED
                associated_values = column.values_at_rows(active_rows)
                for value in all_values:
                    if value in associated_values:
                        state[value] = SelectionState.ASSOCIATED
                    else:
                        state[value] = SelectionState.EXCLUDED

            self._state_cache[(table_name, col_name)] = state

    def _propagate(self, source_table: str, source_rows: set[int]) -> None:
        """BFS propagation across linked tables."""
        visited: set[str] = {source_table}
        # Queue: (table_name, active_rows_in_this_table)
        queue: deque[tuple[str, set[int]]] = deque([(source_table, source_rows)])

        while queue:
            current_table, current_rows = queue.popleft()

            # Find all linked tables
            neighbors = self._association_index.get_associated_tables(current_table)

            for neighbor_table in neighbors:
                if neighbor_table in visited:
                    continue
                if neighbor_table not in self._tables:
                    continue

                visited.add(neighbor_table)

                # Find linking fields
                linking_fields = self._association_index.get_linking_fields(
                    current_table, neighbor_table
                )

                # Determine active rows in the neighbor table
                neighbor_active_rows: set[int] = set()
                current_columns = self._tables[current_table]
                neighbor_columns = self._tables[neighbor_table]

                for link_field in linking_fields:
                    if link_field in current_columns and link_field in neighbor_columns:
                        # Get the linking values from current table's active rows
                        linking_values = current_columns[link_field].values_at_rows(current_rows)

                        # Find matching rows in neighbor table
                        for value in linking_values:
                            neighbor_active_rows |= neighbor_columns[link_field].rows_matching_value(value)

                self._selected_rows[neighbor_table] = neighbor_active_rows

                # Compute states for neighbor table
                self._compute_table_states(neighbor_table, neighbor_active_rows)

                # Continue BFS
                queue.append((neighbor_table, neighbor_active_rows))

    def clear(self) -> None:
        """Clear all selections and reset states."""
        self._selected_rows.clear()
        self._state_cache.clear()

    def get_state(
        self,
        table_name: str,
        column_name: str,
    ) -> dict[Any, SelectionState]:
        """Get the selection state for every value in a column.

        Returns {value: SelectionState} mapping.
        If no selection is active, returns empty dict.
        """
        return dict(self._state_cache.get((table_name, column_name), {}))

    def get_possible_values(self, table_name: str, column_name: str) -> set[Any]:
        """Get values that are SELECTED or ASSOCIATED (not excluded)."""
        states = self._state_cache.get((table_name, column_name), {})
        return {
            value for value, state in states.items()
            if state in (SelectionState.SELECTED, SelectionState.ASSOCIATED)
        }

    def get_excluded_values(self, table_name: str, column_name: str) -> set[Any]:
        """Get values that are EXCLUDED (no association)."""
        states = self._state_cache.get((table_name, column_name), {})
        return {
            value for value, state in states.items()
            if state == SelectionState.EXCLUDED
        }

    def get_selected_values(self, table_name: str, column_name: str) -> set[Any]:
        """Get values that are directly SELECTED."""
        states = self._state_cache.get((table_name, column_name), {})
        return {
            value for value, state in states.items()
            if state == SelectionState.SELECTED
        }

    def get_active_rows(self, table_name: str) -> set[int]:
        """Get the set of active (non-excluded) row indices for a table."""
        return set(self._selected_rows.get(table_name, set()))

    @property
    def has_selection(self) -> bool:
        """Whether any selection is currently active."""
        return len(self._selected_rows) > 0

    def __repr__(self) -> str:
        tables_with_selection = [
            f"{t}({len(rows)} rows)"
            for t, rows in self._selected_rows.items()
        ]
        return f"SelectionEngine(active={', '.join(tables_with_selection) or 'none'})"
