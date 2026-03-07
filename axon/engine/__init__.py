"""
AXON Engine — In-Memory Associative Data Engine
=================================================
A custom QIX-inspired engine for AXON's Data Science primitives.

Architecture:
  SymbolTable     → Dictionary-encoded column compression
  DataColumn      → Bit-stuffed pointer storage with inverted index
  AssociationIndex → Cross-table association graph (auto-link detection)
  SelectionEngine  → Selection state propagation (Selected/Associated/Excluded)
  DataSpace        → Top-level container orchestrating all components

The engine loads data in-memory using columnar storage with dictionary
compression, auto-detects associations between tables by shared column
names, and propagates selections across the association graph instantly.

AXON Selection Palette:
  Selected   → #b8a40f (Golden Amber)
  Associated → #FEF3C7 (Warm Cream)
  Excluded   → #A8A29E (Warm Gray)
"""

from axon.engine.symbol_table import SymbolTable
from axon.engine.data_column import DataColumn
from axon.engine.association_index import AssociationIndex, AssociationLink
from axon.engine.selection_state import SelectionState, SelectionEngine
from axon.engine.dataspace import DataSpace

__all__ = [
    "SymbolTable",
    "DataColumn",
    "AssociationIndex",
    "AssociationLink",
    "SelectionState",
    "SelectionEngine",
    "DataSpace",
]
