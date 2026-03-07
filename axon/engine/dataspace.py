"""
AXON Engine — DataSpace (Top-Level Container)
================================================
The main entry point for AXON's in-memory associative data engine.

A DataSpace is a container for one or more tables that can be
associated, filtered, and aggregated — all in-memory, no OLAP
cubes, no rigid hierarchies.

Example:
    ds = DataSpace("SalesAnalysis")
    ds.load_table("Sales", [
        {"ProductID": "A1", "Region": "LATAM", "Revenue": 1500},
        {"ProductID": "B2", "Region": "EMEA",  "Revenue": 3200},
        {"ProductID": "A1", "Region": "APAC",  "Revenue": 900},
    ])
    ds.load_table("Products", [
        {"ProductID": "A1", "Category": "Software", "Price": 99},
        {"ProductID": "B2", "Category": "Hardware", "Price": 299},
    ])
    # Tables auto-linked via "ProductID"

    ds.select("Sales", "Region", ["LATAM"])
    # Propagates: Software is ASSOCIATED, Hardware is EXCLUDED

    ds.aggregate("Sales", "Revenue", "sum")
    # → 1500  (only LATAM rows are active)
"""

from __future__ import annotations

import statistics
from typing import Any

from axon.engine.data_column import DataColumn
from axon.engine.association_index import AssociationIndex
from axon.engine.selection_state import SelectionEngine, SelectionState


class DataSpace:
    """In-memory container for associated tables.

    Orchestrates all engine components:
      - DataColumn instances for columnar storage
      - AssociationIndex for auto-link detection
      - SelectionEngine for state propagation
    """

    __slots__ = (
        "_name",
        "_compression",
        "_tables",          # table_name → {col_name: DataColumn}
        "_row_counts",      # table_name → int
        "_association_index",
        "_selection_engine",
    )

    def __init__(self, name: str, compression: str = "auto") -> None:
        self._name = name
        self._compression = compression
        self._tables: dict[str, dict[str, DataColumn]] = {}
        self._row_counts: dict[str, int] = {}
        self._association_index = AssociationIndex()
        self._selection_engine: SelectionEngine | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def associations(self) -> AssociationIndex:
        return self._association_index

    @property
    def table_names(self) -> list[str]:
        return sorted(self._tables.keys())

    def load_table(self, name: str, data: list[dict[str, Any]]) -> None:
        """Load a table from a list of row dictionaries.

        Automatically:
          - Creates DataColumn instances with dictionary encoding
          - Registers the table in the AssociationIndex
          - Rebuilds the SelectionEngine
        """
        if not data:
            self._tables[name] = {}
            self._row_counts[name] = 0
            self._association_index.register_table(name, [])
            self._rebuild_selection_engine()
            return

        # Determine columns from the first row
        column_names = list(data[0].keys())

        # Create columns and load data
        columns: dict[str, DataColumn] = {}
        for col_name in column_names:
            col = DataColumn(col_name)
            col.load([row.get(col_name) for row in data])
            columns[col_name] = col

        self._tables[name] = columns
        self._row_counts[name] = len(data)

        # Register with association index (auto-detects links)
        self._association_index.register_table(name, column_names)

        # Rebuild selection engine with updated tables
        self._rebuild_selection_engine()

    def _rebuild_selection_engine(self) -> None:
        """Rebuild the SelectionEngine after table changes."""
        self._selection_engine = SelectionEngine(
            self._tables, self._association_index
        )

    def get_column(self, table_name: str, column_name: str) -> DataColumn:
        """Get a specific DataColumn."""
        if table_name not in self._tables:
            raise KeyError(f"Table '{table_name}' not found")
        if column_name not in self._tables[table_name]:
            raise KeyError(f"Column '{column_name}' not found in '{table_name}'")
        return self._tables[table_name][column_name]

    def get_columns(self, table_name: str) -> list[str]:
        """Get column names for a table."""
        if table_name not in self._tables:
            raise KeyError(f"Table '{table_name}' not found")
        return list(self._tables[table_name].keys())

    def row_count(self, table_name: str) -> int:
        """Get row count for a table."""
        return self._row_counts.get(table_name, 0)

    # ── Selection API ──────────────────────────────────────────────

    def select(self, table_name: str, column_name: str, values: list[Any]) -> None:
        """Apply a focus selection and propagate across associations.

        Corresponds to AXON's `focus on` primitive.
        """
        if self._selection_engine is None:
            raise RuntimeError("No tables loaded in DataSpace")
        self._selection_engine.select(table_name, column_name, values)

    def clear_selections(self) -> None:
        """Clear all active selections."""
        if self._selection_engine:
            self._selection_engine.clear()

    def get_selection_state(
        self, table_name: str, column_name: str
    ) -> dict[Any, SelectionState]:
        """Get the selection state map for a column."""
        if self._selection_engine is None:
            return {}
        return self._selection_engine.get_state(table_name, column_name)

    def get_possible(self, table_name: str, column_name: str) -> set[Any]:
        """Get SELECTED + ASSOCIATED values (not excluded)."""
        if self._selection_engine is None:
            return set()
        return self._selection_engine.get_possible_values(table_name, column_name)

    def get_excluded(self, table_name: str, column_name: str) -> set[Any]:
        """Get EXCLUDED values (no association)."""
        if self._selection_engine is None:
            return set()
        return self._selection_engine.get_excluded_values(table_name, column_name)

    # ── Aggregation API ────────────────────────────────────────────

    _AGGREGATE_FUNCS = {
        "sum": sum,
        "count": len,
        "avg": lambda vals: statistics.mean(vals) if vals else 0,
        "min": lambda vals: min(vals) if vals else None,
        "max": lambda vals: max(vals) if vals else None,
        "median": lambda vals: statistics.median(vals) if vals else None,
        "stdev": lambda vals: statistics.stdev(vals) if len(vals) > 1 else 0.0,
    }

    def aggregate(
        self,
        table_name: str,
        column_name: str,
        func: str,
        group_by: list[str] | None = None,
    ) -> Any:
        """Aggregate a column, respecting active selections.

        Corresponds to AXON's `aggregate X by Y` primitive.

        Args:
            table_name: Table to aggregate.
            column_name: Column to apply the aggregate function to.
            func: One of "sum", "count", "avg", "min", "max", "median", "stdev".
            group_by: Optional list of columns to group by.

        Returns:
            If group_by is None: a single scalar result.
            If group_by is provided: a dict mapping group keys → results.
        """
        if func not in self._AGGREGATE_FUNCS:
            raise ValueError(
                f"Unknown aggregate function '{func}'. "
                f"Valid: {', '.join(self._AGGREGATE_FUNCS.keys())}"
            )

        if table_name not in self._tables:
            raise KeyError(f"Table '{table_name}' not found")

        agg_func = self._AGGREGATE_FUNCS[func]

        # Determine active rows (all rows if no selection)
        if self._selection_engine and self._selection_engine.has_selection:
            active_rows = self._selection_engine.get_active_rows(table_name)
            if not active_rows:
                # Table has no active rows → return identity
                return 0 if func in ("sum", "count") else None
        else:
            active_rows = set(range(self._row_counts.get(table_name, 0)))

        target_column = self.get_column(table_name, column_name)

        if group_by is None:
            # Simple aggregation
            values = [
                target_column.get(i)
                for i in sorted(active_rows)
                if target_column.get(i) is not None
            ]
            return agg_func(values)

        # Grouped aggregation
        group_columns = [self.get_column(table_name, g) for g in group_by]
        groups: dict[tuple, list] = {}

        for row_idx in sorted(active_rows):
            group_key = tuple(gc.get(row_idx) for gc in group_columns)
            value = target_column.get(row_idx)
            if value is not None:
                groups.setdefault(group_key, []).append(value)

        return {key: agg_func(vals) for key, vals in groups.items()}

    # ── Exploration API ────────────────────────────────────────────

    def explore(
        self, table_name: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Return rows from a table, respecting active selections.

        Corresponds to AXON's `explore X [limit N]` primitive.
        """
        if table_name not in self._tables:
            raise KeyError(f"Table '{table_name}' not found")

        columns = self._tables[table_name]
        col_names = list(columns.keys())

        # Determine active rows
        if self._selection_engine and self._selection_engine.has_selection:
            active_rows = sorted(self._selection_engine.get_active_rows(table_name))
        else:
            active_rows = list(range(self._row_counts.get(table_name, 0)))

        if limit is not None:
            active_rows = active_rows[:limit]

        result: list[dict[str, Any]] = []
        for row_idx in active_rows:
            row = {name: columns[name].get(row_idx) for name in col_names}
            result.append(row)

        return result

    # ── Statistics ─────────────────────────────────────────────────

    @property
    def stats(self) -> dict[str, Any]:
        """Engine statistics: tables, rows, compression, associations."""
        table_stats = {}
        for tname, columns in self._tables.items():
            col_stats = {}
            for cname, col in columns.items():
                col_stats[cname] = {
                    "rows": col.row_count,
                    "cardinality": col.cardinality,
                    "compression_ratio": round(col.compression_ratio, 2),
                    "bits_per_pointer": col.symbol_table.bits_per_pointer(),
                }
            table_stats[tname] = {
                "columns": col_stats,
                "row_count": self._row_counts.get(tname, 0),
            }

        return {
            "name": self._name,
            "tables": table_stats,
            "total_tables": len(self._tables),
            "total_associations": self._association_index.link_count,
            "associations": [
                repr(link) for link in self._association_index.all_links()
            ],
        }

    def __repr__(self) -> str:
        return (
            f"DataSpace('{self._name}', "
            f"tables={len(self._tables)}, "
            f"links={self._association_index.link_count})"
        )
