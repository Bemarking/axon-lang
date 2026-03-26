"""
AXON Engine — PIX Visual Tree
=================================
Visual data structures for Epistemic Vision — an extension of PIX
from document navigation to perceptual navigation.

DESIGN DECISION (for devs):
    PIX's core abstraction is "progressive navigation over structured data".
    A document is one case of structured data; an image is another.
    This module defines the VISUAL equivalent of document_tree.py:

        DocumentTree  →  VisualTree
        PixNode       →  VisualNode
        PixLocation   →  VisualLocation
        (new)         →  TopologicalSignature

    The key invariant shared by both: hierarchical decomposition of
    data into navigable regions with bounded search and auditable trails.

Field isomorphism (PixNode → VisualNode):
    node_id    →  node_id           (str, unique ID)
    title      →  label             (str, e.g. "Region NW quadrant")
    summary    →  betti_summary     (str, e.g. "β0=3, β1=1")
    content    →  signature         (TopologicalSignature, leaf data)
    location   →  bbox              (VisualLocation, spatial coords)
    children   →  children          (list[VisualNode])
    depth      →  depth             (int)

New fields without document analogue:
    phase_energy     — mean Gabor filter energy in the region
    curvature_stats  — Gaussian curvature statistics (min, max, mean)
    area_fraction    — fraction of total image area

Properties guaranteed (same as DocumentTree):
    (T1) Unique root
    (T2) Unique parent per non-root node
    (T3) Acyclicity → termination of traversal
    (T4) Exhaustive coverage → no pixel unaccounted
    (T5) Controlled disjunction → minimal overlap between sibling regions

Mathematical basis:
    - TopologicalSignature stores persistence diagrams: {(b_i, d_i)}
    - Stability: d_B(Dgm(I), Dgm(I+η)) ≤ ||η||_∞  (Bottleneck Theorem)
    - Betti numbers: β_n = rank(H_n) — connected components (0), loops (1)
"""

from __future__ import annotations

import json
import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Iterator


# ═══════════════════════════════════════════════════════════════════
#  VISUAL LOCATION — spatial analogue of PixLocation
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class VisualLocation:
    """Bounding box of a visual region in image coordinates.

    Analogue of PixLocation (page/offset) but for 2D spatial regions.

    FOR DEVS: PixLocation uses (page_start, page_end, offset_start, offset_end)
    because documents are 1D streams with page breaks. VisualLocation uses
    (x, y, w, h) because images are 2D grids. Both serve the same purpose:
    enabling direct extraction of content from the source.

    Attributes:
        x: Left edge in pixels (0 = leftmost column).
        y: Top edge in pixels (0 = topmost row).
        w: Width in pixels.
        h: Height in pixels.
    """

    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0

    @property
    def area(self) -> int:
        """Area in square pixels."""
        return self.w * self.h

    @property
    def center(self) -> tuple[float, float]:
        """Center point (cx, cy)."""
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    def contains(self, other: VisualLocation) -> bool:
        """Check if this bbox fully contains another."""
        return (
            self.x <= other.x
            and self.y <= other.y
            and self.x + self.w >= other.x + other.w
            and self.y + self.h >= other.y + other.h
        )

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> VisualLocation:
        return cls(
            x=data.get("x", 0),
            y=data.get("y", 0),
            w=data.get("w", 0),
            h=data.get("h", 0),
        )


# ═══════════════════════════════════════════════════════════════════
#  TOPOLOGICAL SIGNATURE — persistence diagram with stability
# ═══════════════════════════════════════════════════════════════════


@dataclass
class TopologicalSignature:
    """Persistence diagram of a visual region — the core visual "content".

    FOR DEVS: In document PIX, the "content" of a leaf node is a string
    of text. In visual PIX, the "content" is a TopologicalSignature:
    a set of (birth, death) pairs from persistent homology.

    Each pair (b_i, d_i) represents a topological feature:
        - b_i: the filtration value at which the feature appears
        - d_i: the filtration value at which it disappears
        - d_i - b_i = persistence (lifetime) of the feature

    Features with persistence > threshold τ are "real" structure;
    those below τ are topological noise.

    Mathematical guarantee (Bottleneck Stability Theorem):
        If ||I - I'||_∞ ≤ δ, then d_B(Dgm(I), Dgm(I')) ≤ δ
        This means small pixel perturbations cause small signature changes.

    Attributes:
        pairs_h0: Birth-death pairs for H_0 (connected components).
        pairs_h1: Birth-death pairs for H_1 (loops/holes).
        threshold: Persistence threshold τ for noise filtering.
    """

    pairs_h0: list[tuple[float, float]] = field(default_factory=list)
    pairs_h1: list[tuple[float, float]] = field(default_factory=list)
    threshold: float = 0.05

    @property
    def betti_0(self) -> int:
        """β₀ — number of significant connected components."""
        return len([p for p in self.pairs_h0 if p[1] - p[0] > self.threshold])

    @property
    def betti_1(self) -> int:
        """β₁ — number of significant loops/holes."""
        return len([p for p in self.pairs_h1 if p[1] - p[0] > self.threshold])

    @property
    def total_persistence(self) -> float:
        """Sum of all significant persistence values.

        Higher values → more topological complexity in the region.
        """
        return sum(
            d - b
            for pairs in (self.pairs_h0, self.pairs_h1)
            for b, d in pairs
            if d - b > self.threshold
        )

    @property
    def max_persistence(self) -> float:
        """Maximum single-feature persistence value."""
        all_p = [
            d - b
            for pairs in (self.pairs_h0, self.pairs_h1)
            for b, d in pairs
            if d - b > self.threshold
        ]
        return max(all_p) if all_p else 0.0

    def significant_pairs(self, dimension: int = 0) -> list[tuple[float, float]]:
        """Return only pairs with persistence above threshold.

        Args:
            dimension: 0 for connected components, 1 for loops.
        """
        source = self.pairs_h0 if dimension == 0 else self.pairs_h1
        return [(b, d) for b, d in source if d - b > self.threshold]

    def bottleneck_distance(self, other: TopologicalSignature) -> float:
        """Approximate bottleneck distance to another signature.

        FOR DEVS: This is a simplified O(n²) approximation. For production,
        use the exact algorithm from GUDHI or Hera (O(n^1.5 log n)).

        The Bottleneck Stability Theorem guarantees:
            d_B(Sig(I), Sig(I')) ≤ ||I - I'||_∞
        """
        return max(
            self._bottleneck_1d(self.significant_pairs(0), other.significant_pairs(0)),
            self._bottleneck_1d(self.significant_pairs(1), other.significant_pairs(1)),
        )

    def wasserstein_distance(self, other: TopologicalSignature, p: int = 2) -> float:
        """Approximate Wasserstein-p distance to another signature.

        More sensitive than bottleneck: penalizes all mismatches, not just worst.
        """
        return max(
            self._wasserstein_1d(self.significant_pairs(0), other.significant_pairs(0), p),
            self._wasserstein_1d(self.significant_pairs(1), other.significant_pairs(1), p),
        )

    @staticmethod
    def _bottleneck_1d(
        pairs_a: list[tuple[float, float]],
        pairs_b: list[tuple[float, float]],
    ) -> float:
        """1D bottleneck distance approximation via greedy matching."""
        if not pairs_a and not pairs_b:
            return 0.0

        # Cost of matching a point to the diagonal = persistence / 2
        costs_a = [(b + d) / 2.0 for b, d in pairs_a]  # diagonal projections
        costs_b = [(b + d) / 2.0 for b, d in pairs_b]

        # Greedy: match by nearest midpoint, unmatched go to diagonal
        used_b = set()
        max_cost = 0.0

        for i, (ba, da) in enumerate(pairs_a):
            best_cost = (da - ba) / 2.0  # cost to diagonal
            best_j = -1
            for j, (bb, db) in enumerate(pairs_b):
                if j in used_b:
                    continue
                cost = max(abs(ba - bb), abs(da - db))
                if cost < best_cost:
                    best_cost = cost
                    best_j = j
            if best_j >= 0:
                used_b.add(best_j)
            max_cost = max(max_cost, best_cost)

        # Unmatched points in B go to diagonal
        for j, (bb, db) in enumerate(pairs_b):
            if j not in used_b:
                max_cost = max(max_cost, (db - bb) / 2.0)

        return max_cost

    @staticmethod
    def _wasserstein_1d(
        pairs_a: list[tuple[float, float]],
        pairs_b: list[tuple[float, float]],
        p: int = 2,
    ) -> float:
        """1D Wasserstein-p distance approximation."""
        if not pairs_a and not pairs_b:
            return 0.0

        used_b = set()
        total = 0.0

        for ba, da in pairs_a:
            best_cost = ((da - ba) / 2.0) ** p  # diagonal
            best_j = -1
            for j, (bb, db) in enumerate(pairs_b):
                if j in used_b:
                    continue
                cost = max(abs(ba - bb), abs(da - db)) ** p
                if cost < best_cost:
                    best_cost = cost
                    best_j = j
            if best_j >= 0:
                used_b.add(best_j)
            total += best_cost

        for j, (bb, db) in enumerate(pairs_b):
            if j not in used_b:
                total += ((db - bb) / 2.0) ** p

        return total ** (1.0 / p) if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pairs_h0": self.pairs_h0,
            "pairs_h1": self.pairs_h1,
            "threshold": self.threshold,
            "betti_0": self.betti_0,
            "betti_1": self.betti_1,
            "total_persistence": round(self.total_persistence, 6),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TopologicalSignature:
        return cls(
            pairs_h0=[tuple(p) for p in data.get("pairs_h0", [])],
            pairs_h1=[tuple(p) for p in data.get("pairs_h1", [])],
            threshold=data.get("threshold", 0.05),
        )

    def __repr__(self) -> str:
        return (
            f"TopologicalSignature(β0={self.betti_0}, β1={self.betti_1}, "
            f"persistence={self.total_persistence:.4f})"
        )


# ═══════════════════════════════════════════════════════════════════
#  VISUAL NODE — analogue of PixNode
# ═══════════════════════════════════════════════════════════════════


@dataclass
class VisualNode:
    """A node in the PIX visual tree.

    FOR DEVS — Field Mapping from PixNode:
    ═══════════════════════════════════════
        PixNode.node_id    →  VisualNode.node_id      (same: unique ID)
        PixNode.title      →  VisualNode.label         (region label)
        PixNode.summary    →  VisualNode.betti_summary (topological summary)
        PixNode.content    →  VisualNode.signature     (TopologicalSignature)
        PixNode.location   →  VisualNode.bbox          (VisualLocation)
        PixNode.children   →  VisualNode.children      (list[VisualNode])
        PixNode.depth      →  VisualNode.depth         (same: tree depth)

    Additional fields (no document analogue):
        phase_energy     — mean energy from Gabor filter bank in [0, 1]
        curvature_stats  — Gaussian curvature: {"min", "max", "mean"}
        area_fraction    — this region's area / total image area

    Attributes:
        node_id:         Unique identifier within the visual tree.
        label:           Human-readable region label (~3-10 words).
        betti_summary:   Compressed topological summary string.
        signature:       Full TopologicalSignature (only for leaf nodes).
        bbox:            Bounding box in image coordinates.
        phase_energy:    Mean Gabor filter response energy [0, 1].
        curvature_stats: Gaussian curvature statistics for the region.
        area_fraction:   Fraction of total image area [0, 1].
        children:        Sub-regions (empty if leaf).
        depth:           Depth in tree (root = 0).
    """

    node_id: str
    label: str
    betti_summary: str = ""
    signature: TopologicalSignature | None = None
    bbox: VisualLocation = field(default_factory=VisualLocation)
    phase_energy: float = 0.0
    curvature_stats: dict[str, float] = field(default_factory=dict)
    area_fraction: float = 0.0
    children: list[VisualNode] = field(default_factory=list)
    depth: int = 0

    @property
    def is_leaf(self) -> bool:
        """A leaf node has no children (same as PixNode.is_leaf)."""
        return len(self.children) == 0

    @property
    def child_count(self) -> int:
        return len(self.children)

    def add_child(self, child: VisualNode) -> None:
        """Add a child node, setting its depth automatically.

        Same contract as PixNode.add_child().
        """
        child.depth = self.depth + 1
        self.children.append(child)

    def get_child_by_id(self, child_id: str) -> VisualNode | None:
        """Find a direct child by its node_id."""
        for child in self.children:
            if child.node_id == child_id:
                return child
        return None

    def find_node(self, target_id: str) -> VisualNode | None:
        """Recursively find a node by id in this subtree.

        Same contract as PixNode.find_node().
        """
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
            "label": self.label,
            "betti_summary": self.betti_summary,
            "signature": self.signature.to_dict() if self.signature else None,
            "bbox": self.bbox.to_dict(),
            "phase_energy": round(self.phase_energy, 6),
            "curvature_stats": self.curvature_stats,
            "area_fraction": round(self.area_fraction, 6),
            "depth": self.depth,
            "children": [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VisualNode:
        """Deserialize from dictionary."""
        children_data = data.get("children", [])
        sig_data = data.get("signature")
        node = cls(
            node_id=data["node_id"],
            label=data.get("label", ""),
            betti_summary=data.get("betti_summary", ""),
            signature=TopologicalSignature.from_dict(sig_data) if sig_data else None,
            bbox=VisualLocation.from_dict(data.get("bbox", {})),
            phase_energy=data.get("phase_energy", 0.0),
            curvature_stats=data.get("curvature_stats", {}),
            area_fraction=data.get("area_fraction", 0.0),
            depth=data.get("depth", 0),
        )
        for child_data in children_data:
            child = VisualNode.from_dict(child_data)
            node.children.append(child)
        return node

    def __repr__(self) -> str:
        tag = " [leaf]" if self.is_leaf else f" [{self.child_count} children]"
        sig_tag = f" β0={self.signature.betti_0},β1={self.signature.betti_1}" if self.signature else ""
        return f"VisualNode('{self.node_id}', '{self.label}'{sig_tag}{tag})"


# ═══════════════════════════════════════════════════════════════════
#  VISUAL TREE — analogue of DocumentTree
# ═══════════════════════════════════════════════════════════════════


class VisualTree:
    """PIX Visual Tree — V = (N, E, ρ_v, κ).

    FOR DEVS — Relation to DocumentTree:
    ═════════════════════════════════════
    This is the VISUAL equivalent of DocumentTree. It has the SAME API:
        - height(), node_count(), leaf_count()
        - bfs(), dfs(), leaves(), path_to(), find_node()
        - to_dict(), from_dict(), to_json(), from_json()
        - pretty_print(), __repr__()

    The only structural difference is that nodes are VisualNode instead
    of PixNode, and the tree represents spatial regions of an image
    instead of sections of a document.

    Guarantees: acyclicity, exhaustive spatial coverage, unique root.

    Example:
        tree = VisualTree("scene_001", root=VisualNode("root", "Full Image"))
        tree.root.add_child(VisualNode("nw", "Northwest Quadrant"))
        tree.root.add_child(VisualNode("ne", "Northeast Quadrant"))

        for node in tree.bfs():
            print(node.label, node.betti_summary)
    """

    __slots__ = ("_name", "_root", "_source", "_checksum", "_version",
                 "_image_width", "_image_height")

    def __init__(
        self,
        name: str,
        root: VisualNode,
        source: str = "",
        version: str = "1.0",
        image_width: int = 0,
        image_height: int = 0,
    ) -> None:
        self._name = name
        self._root = root
        self._source = source
        self._version = version
        self._checksum = ""
        self._image_width = image_width
        self._image_height = image_height

    @property
    def name(self) -> str:
        return self._name

    @property
    def root(self) -> VisualNode:
        return self._root

    @property
    def source(self) -> str:
        return self._source

    @property
    def version(self) -> str:
        return self._version

    @property
    def image_width(self) -> int:
        return self._image_width

    @property
    def image_height(self) -> int:
        return self._image_height

    @property
    def checksum(self) -> str:
        """Content hash for cache invalidation (same as DocumentTree)."""
        if not self._checksum:
            raw = json.dumps(self._root.to_dict(), sort_keys=True)
            self._checksum = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return self._checksum

    # ── Tree metrics (same API as DocumentTree) ──────────────────

    def height(self) -> int:
        """Maximum depth of the tree (root depth = 0)."""
        return self._compute_height(self._root)

    def _compute_height(self, node: VisualNode) -> int:
        if node.is_leaf:
            return 0
        return 1 + max(self._compute_height(c) for c in node.children)

    def node_count(self) -> int:
        """Total number of nodes in the tree."""
        return self._count_nodes(self._root)

    def _count_nodes(self, node: VisualNode) -> int:
        return 1 + sum(self._count_nodes(c) for c in node.children)

    def leaf_count(self) -> int:
        """Number of leaf nodes (regions with full signatures)."""
        return self._count_leaves(self._root)

    def _count_leaves(self, node: VisualNode) -> int:
        if node.is_leaf:
            return 1
        return sum(self._count_leaves(c) for c in node.children)

    # ── Traversal (same API as DocumentTree) ─────────────────────

    def bfs(self) -> Iterator[VisualNode]:
        """Breadth-first traversal of all nodes."""
        queue: list[VisualNode] = [self._root]
        while queue:
            node = queue.pop(0)
            yield node
            queue.extend(node.children)

    def dfs(self, node: VisualNode | None = None) -> Iterator[VisualNode]:
        """Depth-first (pre-order) traversal."""
        if node is None:
            node = self._root
        yield node
        for child in node.children:
            yield from self.dfs(child)

    def leaves(self) -> Iterator[VisualNode]:
        """Iterate over all leaf nodes."""
        for node in self.dfs():
            if node.is_leaf:
                yield node

    def path_to(self, target_id: str) -> list[VisualNode] | None:
        """Find the path from root to a node by id.

        Returns None if the node is not found.
        """
        return self._find_path(self._root, target_id, [])

    def _find_path(
        self, node: VisualNode, target_id: str, current_path: list[VisualNode]
    ) -> list[VisualNode] | None:
        current_path = [*current_path, node]
        if node.node_id == target_id:
            return current_path
        for child in node.children:
            result = self._find_path(child, target_id, current_path)
            if result is not None:
                return result
        return None

    def find_node(self, node_id: str) -> VisualNode | None:
        """Find a node anywhere in the tree by id."""
        return self._root.find_node(node_id)

    # ── Serialization (same API as DocumentTree) ─────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize the entire tree to a JSON-compatible dict."""
        return {
            "name": self._name,
            "source": self._source,
            "version": self._version,
            "checksum": self.checksum,
            "image_width": self._image_width,
            "image_height": self._image_height,
            "stats": {
                "node_count": self.node_count(),
                "leaf_count": self.leaf_count(),
                "height": self.height(),
            },
            "tree": self._root.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VisualTree:
        """Deserialize from dictionary."""
        root = VisualNode.from_dict(data["tree"])
        return cls(
            name=data["name"],
            root=root,
            source=data.get("source", ""),
            version=data.get("version", "1.0"),
            image_width=data.get("image_width", 0),
            image_height=data.get("image_height", 0),
        )

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> VisualTree:
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))

    # ── Display ──────────────────────────────────────────────────

    def pretty_print(self, node: VisualNode | None = None, prefix: str = "") -> str:
        """Return a human-readable tree visualization."""
        if node is None:
            node = self._root
        sig_info = f" [{node.betti_summary}]" if node.betti_summary else ""
        lines = [f"{prefix}{'└── ' if prefix else ''}{node.label}{sig_info} ({node.node_id})"]
        for i, child in enumerate(node.children):
            is_last = i == len(node.children) - 1
            child_prefix = prefix + ("    " if is_last else "│   ")
            connector = "└── " if is_last else "├── "
            child_sig = f" [{child.betti_summary}]" if child.betti_summary else ""
            lines.append(f"{prefix}{connector}{child.label}{child_sig} ({child.node_id})")
            if not child.is_leaf:
                for grandchild_line in self.pretty_print(child, child_prefix).split("\n")[1:]:
                    if grandchild_line.strip():
                        lines.append(grandchild_line)
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"VisualTree('{self._name}', "
            f"nodes={self.node_count()}, "
            f"leaves={self.leaf_count()}, "
            f"height={self.height()}, "
            f"image={self._image_width}×{self._image_height})"
        )
