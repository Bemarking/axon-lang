"""
AXON Engine — Data Column (Bit-Stuffed Pointer Storage)
=========================================================
Columnar storage using dictionary-encoded symbol IDs with
an inverted index for instant row lookups.

Each DataColumn wraps a SymbolTable and stores row data as
compact integer pointers. The inverted index maps each symbol ID
to the set of row indices where it appears, enabling O(1) lookups.

Example:
    st = SymbolTable("Region")
    col = DataColumn("Region", st)
    col.load(["LATAM", "EMEA", "LATAM", "APAC", "LATAM"])
    col.rows_matching_value("LATAM")  # → {0, 2, 4}
    col.get(3)                         # → "APAC"
"""

from __future__ import annotations

import sys
from array import array
from typing import Any

from axon.engine.symbol_table import SymbolTable


class DataColumn:
    """A single column of data stored as dictionary-encoded pointers.

    Maintains:
      - A pointer array (encoded symbol IDs, one per row)
      - An inverted index (symbol_id → set of row indices)
    """

    __slots__ = ("_name", "_symbol_table", "_pointers", "_inverted_index", "_row_count")

    def __init__(self, name: str, symbol_table: SymbolTable | None = None) -> None:
        self._name = name
        self._symbol_table = symbol_table or SymbolTable(name)
        self._pointers: array = array("I")  # unsigned int array
        self._inverted_index: dict[int, set[int]] = {}
        self._row_count: int = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def symbol_table(self) -> SymbolTable:
        return self._symbol_table

    @property
    def row_count(self) -> int:
        return self._row_count

    @property
    def cardinality(self) -> int:
        """Number of distinct values in this column."""
        return self._symbol_table.cardinality

    def load(self, values: list[Any]) -> None:
        """Bulk-load an entire column of values.

        Replaces any existing data.
        """
        self._pointers = array("I")
        self._inverted_index = {}
        self._row_count = 0

        for value in values:
            self.append(value)

    def append(self, value: Any) -> None:
        """Append a single value to the column."""
        symbol_id = self._symbol_table.encode(value)
        row_idx = self._row_count

        self._pointers.append(symbol_id)

        if symbol_id not in self._inverted_index:
            self._inverted_index[symbol_id] = set()
        self._inverted_index[symbol_id].add(row_idx)

        self._row_count += 1

    def get(self, row_idx: int) -> Any:
        """Get the decoded value at the given row index."""
        if row_idx < 0 or row_idx >= self._row_count:
            raise IndexError(
                f"Row index {row_idx} out of range for column '{self._name}' "
                f"with {self._row_count} rows"
            )
        symbol_id = self._pointers[row_idx]
        return self._symbol_table.decode(symbol_id)

    def get_encoded(self, row_idx: int) -> int:
        """Get the raw symbol ID at the given row index."""
        if row_idx < 0 or row_idx >= self._row_count:
            raise IndexError(
                f"Row index {row_idx} out of range for column '{self._name}' "
                f"with {self._row_count} rows"
            )
        return self._pointers[row_idx]

    def rows_matching(self, symbol_id: int) -> set[int]:
        """Get all row indices where this symbol ID appears."""
        return set(self._inverted_index.get(symbol_id, set()))

    def rows_matching_value(self, value: Any) -> set[int]:
        """Get all row indices where this value appears."""
        symbol_id = self._symbol_table.lookup_id(value)
        if symbol_id is None:
            return set()
        return self.rows_matching(symbol_id)

    def distinct_values(self) -> set[Any]:
        """Return all distinct values present in this column."""
        return self._symbol_table.values

    def values_at_rows(self, row_indices: set[int]) -> set[Any]:
        """Get the set of distinct values at the given row indices."""
        result = set()
        for idx in row_indices:
            if 0 <= idx < self._row_count:
                result.add(self._symbol_table.decode(self._pointers[idx]))
        return result

    def all_values(self) -> list[Any]:
        """Return all values in row order (decoded)."""
        return [self._symbol_table.decode(sid) for sid in self._pointers]

    @property
    def compression_ratio(self) -> float:
        """Estimated compression ratio vs. naive storage.

        Compares the memory used by the pointer array + symbol table
        against storing raw Python objects per row.
        """
        if self._row_count == 0:
            return 1.0

        # Estimate raw size: ~50 bytes per Python object (conservative)
        raw_size = self._row_count * 50

        # Compressed: pointer array + symbol table entries
        pointer_bytes = self._pointers.itemsize * self._row_count
        symbol_bytes = self.cardinality * 50  # symbol table entries
        compressed_size = pointer_bytes + symbol_bytes

        if compressed_size == 0:
            return 1.0
        return raw_size / compressed_size

    @property
    def memory_bytes(self) -> int:
        """Approximate memory usage in bytes."""
        return (
            sys.getsizeof(self._pointers)
            + sys.getsizeof(self._inverted_index)
            + sum(sys.getsizeof(s) for s in self._inverted_index.values())
        )

    def __len__(self) -> int:
        return self._row_count

    def __repr__(self) -> str:
        return (
            f"DataColumn('{self._name}', "
            f"rows={self._row_count}, "
            f"cardinality={self.cardinality}, "
            f"compression={self.compression_ratio:.1f}x)"
        )
