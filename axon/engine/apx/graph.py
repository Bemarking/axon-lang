"""
AXON APX - Epistemic Dependency Graph

Core domain model for APX package resolution:
  C = (D, R, tau, sigma, omega)

This module enforces Phase 1 invariants:
- DAG validity
- G5 anti-monotonicity for dependency-like edges
- MEC (minimum epistemic contract) presence on all nodes
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from axon.engine.apx.lattice import EpistemicLattice, EpistemicLevel


class EdgeKind(str, Enum):
    DEPENDS_ON = "depends_on"
    DELEGATES_TO = "delegates_to"
    AUDITS = "audits"
    EXTENDS = "extends"


G5_ENFORCED_EDGES = {
    EdgeKind.DEPENDS_ON,
    EdgeKind.DELEGATES_TO,
    EdgeKind.AUDITS,
    EdgeKind.EXTENDS,
}


@dataclass(frozen=True)
class EpistemicContract:
    """Minimal contract required for package admission (MEC)."""

    ecid: str
    certificate_hash: str
    witness_count: int = 1

    def is_valid(self) -> bool:
        return bool(self.ecid and self.certificate_hash and self.witness_count > 0)


@dataclass
class EpistemicNode:
    """Package/module node in the APX graph."""

    package_id: str
    level: EpistemicLevel
    contract: EpistemicContract
    metadata: dict[str, str] = field(default_factory=dict)
    server_blame_count: int = 0

    def __post_init__(self) -> None:
        if not self.package_id:
            raise ValueError("package_id cannot be empty")
        if self.server_blame_count < 0:
            raise ValueError("server_blame_count cannot be negative")


@dataclass(frozen=True)
class EpistemicEdge:
    """Typed relation between packages."""

    source_id: str
    target_id: str
    kind: EdgeKind
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.source_id or not self.target_id:
            raise ValueError("edge endpoints cannot be empty")
        if not (0.0 < self.weight <= 1.0):
            raise ValueError("weight must be in (0, 1]")


class EpistemicGraph:
    """Mutable graph with structural and epistemic validators."""

    def __init__(self, name: str) -> None:
        if not name:
            raise ValueError("graph name cannot be empty")
        self.name = name
        self._nodes: dict[str, EpistemicNode] = {}
        self._edges: list[EpistemicEdge] = []

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    def node_ids(self) -> list[str]:
        return list(self._nodes.keys())

    def edges(self) -> tuple[EpistemicEdge, ...]:
        return tuple(self._edges)

    def get_node(self, package_id: str) -> EpistemicNode | None:
        return self._nodes.get(package_id)

    def add_node(self, node: EpistemicNode) -> None:
        if node.package_id in self._nodes:
            raise ValueError(f"duplicate node '{node.package_id}'")
        self._nodes[node.package_id] = node

    def add_edge(self, edge: EpistemicEdge) -> None:
        if edge.source_id not in self._nodes or edge.target_id not in self._nodes:
            raise ValueError("edge endpoints must already exist")
        if edge.source_id == edge.target_id:
            raise ValueError("self-loops are not allowed in APX dependency graph")
        self._edges.append(edge)

    def validate_acyclic(self) -> list[str]:
        """Return cycle violations; empty list means acyclic graph."""
        adjacency: dict[str, list[str]] = {node_id: [] for node_id in self._nodes}
        for edge in self._edges:
            adjacency[edge.source_id].append(edge.target_id)

        visited: set[str] = set()
        visiting: set[str] = set()
        errors: list[str] = []

        def dfs(node_id: str, path: list[str]) -> None:
            if node_id in visiting:
                cycle = " -> ".join(path + [node_id])
                errors.append(f"cycle detected: {cycle}")
                return
            if node_id in visited:
                return

            visiting.add(node_id)
            for nxt in adjacency[node_id]:
                dfs(nxt, path + [node_id])
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in self._nodes:
            if node_id not in visited:
                dfs(node_id, [])

        return errors

    def validate_mec(self) -> list[str]:
        """Every package must provide a valid minimum epistemic contract."""
        errors: list[str] = []
        for node in self._nodes.values():
            if not node.contract.is_valid():
                errors.append(f"MEC violation in '{node.package_id}': invalid contract")
        return errors

    def validate_g5(self) -> list[str]:
        """G5 anti-monotonicity: base dependencies must not be weaker than derivations.

        For an edge derived -> base, enforce sigma(base) >= sigma(derived).
        """
        errors: list[str] = []
        for edge in self._edges:
            if edge.kind not in G5_ENFORCED_EDGES:
                continue

            derived = self._nodes[edge.source_id]
            base = self._nodes[edge.target_id]

            if not EpistemicLattice.leq(derived.level, base.level):
                errors.append(
                    "G5 violation: "
                    f"{derived.package_id}({derived.level.name}) -> "
                    f"{base.package_id}({base.level.name})"
                )
        return errors

    def validate_all(self) -> list[str]:
        """Run all Phase 1 graph-level checks."""
        return [*self.validate_mec(), *self.validate_acyclic(), *self.validate_g5()]
