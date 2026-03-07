"""
AXON Engine — Symbol Table (Dictionary Encoding)
==================================================
Maps distinct values → compact integer IDs for columnar compression.

Inspired by QlikView's QIX engine: each column maintains its own
symbol table. Repeated values are stored as small integer pointers
instead of full values, achieving typical compression ratios of 80-90%.

Example:
    st = SymbolTable("Country")
    encoded = st.encode_column(["USA", "Canada", "USA", "Mexico", "USA"])
    # encoded = [0, 1, 0, 2, 0]
    # st.symbols = {0: "USA", 1: "Canada", 2: "Mexico"}
    # st.cardinality = 3
"""

from __future__ import annotations

from typing import Any


class SymbolTable:
    """Dictionary-encoded value store for a single column.

    Maintains a bidirectional mapping between original values and
    compact integer symbol IDs. Shared symbol tables across columns
    enable automatic association detection.
    """

    __slots__ = ("_name", "_value_to_id", "_id_to_value", "_next_id")

    def __init__(self, name: str) -> None:
        self._name = name
        self._value_to_id: dict[Any, int] = {}
        self._id_to_value: dict[int, Any] = {}
        self._next_id: int = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def cardinality(self) -> int:
        """Number of distinct values encoded."""
        return len(self._value_to_id)

    @property
    def symbols(self) -> dict[int, Any]:
        """Read-only view: symbol_id → original value."""
        return dict(self._id_to_value)

    @property
    def values(self) -> set[Any]:
        """Set of all distinct original values."""
        return set(self._value_to_id.keys())

    def encode(self, value: Any) -> int:
        """Encode a single value → symbol ID.

        If the value has not been seen before, assigns a new ID.
        """
        if value in self._value_to_id:
            return self._value_to_id[value]

        symbol_id = self._next_id
        self._next_id += 1
        self._value_to_id[value] = symbol_id
        self._id_to_value[symbol_id] = value
        return symbol_id

    def decode(self, symbol_id: int) -> Any:
        """Decode a symbol ID → original value.

        Raises:
            KeyError: If symbol_id is not in the table.
        """
        if symbol_id not in self._id_to_value:
            raise KeyError(
                f"Symbol ID {symbol_id} not found in SymbolTable '{self._name}'. "
                f"Valid IDs: 0..{self._next_id - 1}"
            )
        return self._id_to_value[symbol_id]

    def encode_column(self, values: list[Any]) -> list[int]:
        """Encode an entire column of values → list of symbol IDs."""
        return [self.encode(v) for v in values]

    def lookup_id(self, value: Any) -> int | None:
        """Look up the symbol ID for a value without creating it.

        Returns None if the value has never been encoded.
        """
        return self._value_to_id.get(value)

    def bits_per_pointer(self) -> int:
        """Minimum bits needed to represent any symbol ID.

        Used for bit-stuffed pointer optimization.
        If cardinality=100, needs ceil(log2(100))=7 bits per pointer.
        """
        if self.cardinality <= 1:
            return 1
        n = self.cardinality
        bits = 0
        while (1 << bits) < n:
            bits += 1
        return bits

    def __len__(self) -> int:
        return self.cardinality

    def __repr__(self) -> str:
        return (
            f"SymbolTable('{self._name}', "
            f"cardinality={self.cardinality}, "
            f"bits_per_ptr={self.bits_per_pointer()})"
        )

    def __contains__(self, value: Any) -> bool:
        return value in self._value_to_id
