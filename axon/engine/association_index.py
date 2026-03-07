"""
AXON Engine — Association Index (Cross-Table Link Graph)
==========================================================
Manages the association graph between tables in a DataSpace.

QIX's core insight: tables are linked by *shared field names*.
If Table_A has column "Country" and Table_B has column "Country",
they are automatically associated. No explicit JOINs needed.

The AssociationIndex maintains a graph of these links and can
find shortest association paths between any two tables (BFS).

Example:
    idx = AssociationIndex()
    idx.register_table("Sales", ["ProductID", "Region", "Revenue"])
    idx.register_table("Products", ["ProductID", "Category", "Price"])
    idx.register_table("Regions", ["Region", "Country", "Manager"])

    idx.find_links("Sales")
    # → [Link(Sales↔Products via ProductID), Link(Sales↔Regions via Region)]

    idx.get_association_path("Products", "Regions")
    # → ["Products", "Sales", "Regions"]  (through Sales)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AssociationLink:
    """A link between two tables through a shared field name."""
    table_a: str
    table_b: str
    field_name: str

    def involves(self, table_name: str) -> bool:
        """Check if this link involves the given table."""
        return self.table_a == table_name or self.table_b == table_name

    def other_table(self, table_name: str) -> str:
        """Get the other table in this link."""
        if self.table_a == table_name:
            return self.table_b
        if self.table_b == table_name:
            return self.table_a
        raise ValueError(f"Table '{table_name}' is not part of this link")

    def __repr__(self) -> str:
        return f"Link({self.table_a}↔{self.table_b} via '{self.field_name}')"


class AssociationIndex:
    """Manages the association graph between tables.

    Auto-detects links: when two tables share a column name,
    an AssociationLink is created automatically. Multiple shared
    columns between two tables create multiple links.

    The graph supports:
      - Link discovery: find all links for a table
      - Path finding: BFS shortest path between any two tables
      - Neighbor lookup: which tables directly connect?
    """

    __slots__ = ("_tables", "_links", "_adjacency")

    def __init__(self) -> None:
        # table_name → set of column names
        self._tables: dict[str, set[str]] = {}
        # All discovered links
        self._links: list[AssociationLink] = []
        # Adjacency list: table → {neighbor_table: [field_names]}
        self._adjacency: dict[str, dict[str, list[str]]] = {}

    def register_table(self, table_name: str, columns: list[str]) -> list[AssociationLink]:
        """Register a table and its columns. Discovers links to existing tables.

        Returns the list of newly discovered links.
        """
        column_set = set(columns)
        new_links: list[AssociationLink] = []

        # Check for shared columns with all previously registered tables
        for existing_name, existing_columns in self._tables.items():
            shared = column_set & existing_columns
            for field_name in sorted(shared):  # sorted for determinism
                link = AssociationLink(
                    table_a=existing_name,
                    table_b=table_name,
                    field_name=field_name,
                )
                self._links.append(link)
                new_links.append(link)

                # Update adjacency
                self._adjacency.setdefault(existing_name, {}).setdefault(table_name, []).append(field_name)
                self._adjacency.setdefault(table_name, {}).setdefault(existing_name, []).append(field_name)

        self._tables[table_name] = column_set
        return new_links

    def find_links(self, table_name: str) -> list[AssociationLink]:
        """Find all links involving the given table."""
        return [link for link in self._links if link.involves(table_name)]

    def get_associated_tables(self, table_name: str) -> set[str]:
        """Get all tables directly linked to the given table."""
        return set(self._adjacency.get(table_name, {}).keys())

    def get_linking_fields(self, table_a: str, table_b: str) -> list[str]:
        """Get the field names that link two tables directly."""
        return list(self._adjacency.get(table_a, {}).get(table_b, []))

    def get_association_path(self, from_table: str, to_table: str) -> list[str] | None:
        """Find the shortest path between two tables (BFS).

        Returns a list of table names forming the path, or None if
        the tables are not connected.
        """
        if from_table == to_table:
            return [from_table]

        if from_table not in self._tables or to_table not in self._tables:
            return None

        # BFS
        visited: set[str] = {from_table}
        queue: deque[list[str]] = deque([[from_table]])

        while queue:
            path = queue.popleft()
            current = path[-1]

            for neighbor in self._adjacency.get(current, {}):
                if neighbor == to_table:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])

        return None  # No path found

    def all_links(self) -> list[AssociationLink]:
        """Return all discovered links."""
        return list(self._links)

    @property
    def table_names(self) -> list[str]:
        """Names of all registered tables."""
        return sorted(self._tables.keys())

    @property
    def table_count(self) -> int:
        return len(self._tables)

    @property
    def link_count(self) -> int:
        return len(self._links)

    def __repr__(self) -> str:
        return (
            f"AssociationIndex("
            f"tables={self.table_count}, "
            f"links={self.link_count})"
        )
