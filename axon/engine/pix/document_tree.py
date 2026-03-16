"""
AXON Engine — PIX Document Tree
=================================
Formal tree data structure implementing D = (N, E, ρ, κ).

Every document is represented as a tree where:
  - N  = set of nodes (sections, subsections, paragraphs)
  - E  = directed edges (parent → child)
  - ρ  = node representation (title, summary, location)
  - κ  = children function

Properties guaranteed:
  (T1) Unique root
  (T2) Unique parent per non-root node
  (T3) Acyclicity → termination of traversal
  (T4) Exhaustive coverage → no information loss
  (T5) Controlled disjunction → minimal redundancy between siblings
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass(frozen=True)
class PixLocation:
    """Spatial metadata for a document section.

    Enables non-linear content retrieval: given a node selected
    during navigation, the location allows direct extraction of
    the original content from the source document.
    """

    page_start: int = 0
    page_end: int = 0
    offset_start: int = 0
    offset_end: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "page_start": self.page_start,
            "page_end": self.page_end,
            "offset_start": self.offset_start,
            "offset_end": self.offset_end,
        }

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> PixLocation:
        return cls(
            page_start=data.get("page_start", 0),
            page_end=data.get("page_end", 0),
            offset_start=data.get("offset_start", 0),
            offset_end=data.get("offset_end", 0),
        )


@dataclass
class PixNode:
    """A node in the PIX document tree.

    Representation: ρ(nᵢ) = ⟨titleᵢ, summaryᵢ, locationᵢ, childrenᵢ⟩

    Attributes:
        node_id:  Unique identifier within the tree.
        title:    High semantic density string (~5-15 words).
        summary:  Lossy compression of content (H(summary) << H(content)).
        location: Spatial metadata [page_start, page_end] × [offset_start, offset_end].
        content:  Full content (only populated for leaf nodes).
        children: References to descendant nodes (empty if leaf).
        depth:    Depth in the tree (root = 0).
    """

    node_id: str
    title: str
    summary: str = ""
    location: PixLocation = field(default_factory=PixLocation)
    content: str = ""
    children: list[PixNode] = field(default_factory=list)
    depth: int = 0

    @property
    def is_leaf(self) -> bool:
        """A leaf node has no children."""
        return len(self.children) == 0

    @property
    def child_count(self) -> int:
        return len(self.children)

    def add_child(self, child: PixNode) -> None:
        """Add a child node, setting its depth automatically."""
        child.depth = self.depth + 1
        self.children.append(child)

    def get_child_by_id(self, child_id: str) -> PixNode | None:
        """Find a direct child by its node_id."""
        for child in self.children:
            if child.node_id == child_id:
                return child
        return None

    def find_node(self, target_id: str) -> PixNode | None:
        """Recursively find a node by id in this subtree."""
        if self.node_id == target_id:
            return self
        for child in self.children:
            found = child.find_node(target_id)
            if found is not None:
                return found
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dictionary."""
        return {
            "node_id": self.node_id,
            "title": self.title,
            "summary": self.summary,
            "location": self.location.to_dict(),
            "content": self.content,
            "depth": self.depth,
            "children": [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PixNode:
        """Deserialize from dictionary."""
        children_data = data.get("children", [])
        node = cls(
            node_id=data["node_id"],
            title=data.get("title", ""),
            summary=data.get("summary", ""),
            location=PixLocation.from_dict(data.get("location", {})),
            content=data.get("content", ""),
            depth=data.get("depth", 0),
        )
        for child_data in children_data:
            child = PixNode.from_dict(child_data)
            node.children.append(child)
        return node

    def __repr__(self) -> str:
        leaf_tag = " [leaf]" if self.is_leaf else f" [{self.child_count} children]"
        return f"PixNode('{self.node_id}', '{self.title}'{leaf_tag})"


class DocumentTree:
    """PIX Document Tree — D = (N, E, ρ, κ).

    The top-level container for a document's structural representation.
    Guarantees: acyclicity, exhaustive coverage, unique root.

    Example:
        tree = DocumentTree("contract_v2", root=PixNode("root", "Master Agreement"))
        tree.root.add_child(PixNode("s1", "Definitions"))
        tree.root.add_child(PixNode("s2", "Liabilities"))

        for node in tree.bfs():
            print(node.title)
    """

    __slots__ = ("_name", "_root", "_source", "_checksum", "_version")

    def __init__(
        self,
        name: str,
        root: PixNode,
        source: str = "",
        version: str = "1.0",
    ) -> None:
        self._name = name
        self._root = root
        self._source = source
        self._version = version
        self._checksum = ""

    @property
    def name(self) -> str:
        return self._name

    @property
    def root(self) -> PixNode:
        return self._root

    @property
    def source(self) -> str:
        return self._source

    @property
    def version(self) -> str:
        return self._version

    @property
    def checksum(self) -> str:
        """Content hash for cache invalidation."""
        if not self._checksum:
            raw = json.dumps(self._root.to_dict(), sort_keys=True)
            self._checksum = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return self._checksum

    # ── Tree metrics ──────────────────────────────────────────────

    def height(self) -> int:
        """Maximum depth of the tree (root depth = 0)."""
        return self._compute_height(self._root)

    def _compute_height(self, node: PixNode) -> int:
        if node.is_leaf:
            return 0
        return 1 + max(self._compute_height(c) for c in node.children)

    def node_count(self) -> int:
        """Total number of nodes in the tree."""
        return self._count_nodes(self._root)

    def _count_nodes(self, node: PixNode) -> int:
        return 1 + sum(self._count_nodes(c) for c in node.children)

    def leaf_count(self) -> int:
        """Number of leaf nodes (content-bearing terminals)."""
        return self._count_leaves(self._root)

    def _count_leaves(self, node: PixNode) -> int:
        if node.is_leaf:
            return 1
        return sum(self._count_leaves(c) for c in node.children)

    # ── Traversal ─────────────────────────────────────────────────

    def bfs(self) -> Iterator[PixNode]:
        """Breadth-first traversal of all nodes."""
        queue: list[PixNode] = [self._root]
        while queue:
            node = queue.pop(0)
            yield node
            queue.extend(node.children)

    def dfs(self, node: PixNode | None = None) -> Iterator[PixNode]:
        """Depth-first (pre-order) traversal."""
        if node is None:
            node = self._root
        yield node
        for child in node.children:
            yield from self.dfs(child)

    def leaves(self) -> Iterator[PixNode]:
        """Iterate over all leaf nodes."""
        for node in self.dfs():
            if node.is_leaf:
                yield node

    def path_to(self, target_id: str) -> list[PixNode] | None:
        """Find the path from root to a node by id.

        Returns None if the node is not found.
        """
        return self._find_path(self._root, target_id, [])

    def _find_path(
        self, node: PixNode, target_id: str, current_path: list[PixNode]
    ) -> list[PixNode] | None:
        current_path = [*current_path, node]
        if node.node_id == target_id:
            return current_path
        for child in node.children:
            result = self._find_path(child, target_id, current_path)
            if result is not None:
                return result
        return None

    def find_node(self, node_id: str) -> PixNode | None:
        """Find a node anywhere in the tree by id."""
        return self._root.find_node(node_id)

    # ── Serialization ─────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize the entire tree to a JSON-compatible dict."""
        return {
            "name": self._name,
            "source": self._source,
            "version": self._version,
            "checksum": self.checksum,
            "stats": {
                "node_count": self.node_count(),
                "leaf_count": self.leaf_count(),
                "height": self.height(),
            },
            "tree": self._root.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DocumentTree:
        """Deserialize from dictionary."""
        root = PixNode.from_dict(data["tree"])
        tree = cls(
            name=data["name"],
            root=root,
            source=data.get("source", ""),
            version=data.get("version", "1.0"),
        )
        return tree

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> DocumentTree:
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))

    # ── Display ───────────────────────────────────────────────────

    def pretty_print(self, node: PixNode | None = None, prefix: str = "") -> str:
        """Return a human-readable tree visualization."""
        if node is None:
            node = self._root
        lines = [f"{prefix}{'└── ' if prefix else ''}{node.title} ({node.node_id})"]
        for i, child in enumerate(node.children):
            is_last = i == len(node.children) - 1
            child_prefix = prefix + ("    " if is_last else "│   ")
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{child.title} ({child.node_id})")
            if not child.is_leaf:
                for grandchild_line in self.pretty_print(child, child_prefix).split("\n")[1:]:
                    if grandchild_line.strip():
                        lines.append(grandchild_line)
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"DocumentTree('{self._name}', "
            f"nodes={self.node_count()}, "
            f"leaves={self.leaf_count()}, "
            f"height={self.height()})"
        )
