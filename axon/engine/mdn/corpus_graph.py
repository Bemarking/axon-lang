"""
AXON Engine — MDN Corpus Graph
=================================
Core data structures implementing the formal model:

    C = (D, R, τ, ω, σ)     — Definition 1, §2.1

where:
    D   = finite set of documents
    R   ⊆ D × D × L         — labeled directed edges
    τ   : R → RelationType   — edge type function
    ω   : R → ℝ⁺             — edge weight function (0 < ω ≤ 1)
    σ   : D → EpistemicLevel  — document epistemic status

Invariants enforced (§5.1):
    (G1) |D| < ∞
    (G2) ∀ (Dᵢ, Dⱼ, l) ∈ R : Dᵢ, Dⱼ ∈ D
    (G3) τ is total on R
    (G4) 0 < ω(r) ≤ 1 ∀r ∈ R
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator


# ═══════════════════════════════════════════════════════════════════
#  RELATION TYPES — Definition 2 (Edge Semantics), §2.1
# ═══════════════════════════════════════════════════════════════════

# Standard relation types from the formal specification
STANDARD_RELATION_TYPES = {
    "cite",         # Dᵢ cites Dⱼ as evidence
    "depend",       # Dᵢ requires Dⱼ for comprehension
    "contradict",   # Dᵢ disputes claims in Dⱼ
    "elaborate",    # Dᵢ expands on Dⱼ
    "supersede",    # Dᵢ replaces Dⱼ (versioning)
    "implement",    # Dᵢ implements specification Dⱼ
    "exemplify",    # Dᵢ is an example of concept in Dⱼ
    "corroborate",  # Dᵢ independently supports Dⱼ
}

# Positive edges propagate epistemic trust (§2.3, Definition 4)
POSITIVE_RELATIONS = {"cite", "elaborate", "corroborate", "implement", "exemplify"}

# Negative edges propagate epistemic distrust (§2.3, Definition 4)
NEGATIVE_RELATIONS = {"contradict", "supersede"}


@dataclass(frozen=True)
class RelationType:
    """Typed edge label with semantic properties.

    From Definition 2 (Edge Semantics), §2.1:
        RelationType ::= cite | depend | contradict | elaborate | ...

    The `properties` field encodes the frame conditions from §3.1
    (reflexive, transitive, etc.) that determine modal logic axioms.

    The `domain_constraint` field, when set, restricts which
    document type pairs can be connected by this relation (§4.3).
    """

    name: str
    properties: frozenset[str] = frozenset()
    domain_constraint: tuple[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("RelationType name cannot be empty")

    @property
    def is_positive(self) -> bool:
        """Whether this relation propagates epistemic trust (§2.3)."""
        return self.name in POSITIVE_RELATIONS

    @property
    def is_negative(self) -> bool:
        """Whether this relation propagates epistemic distrust (§2.3)."""
        return self.name in NEGATIVE_RELATIONS

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, RelationType):
            return self.name == other.name
        return NotImplemented


# ═══════════════════════════════════════════════════════════════════
#  EDGE — R ⊆ D × D × L with weight ω
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Edge:
    """A typed, weighted directed edge in the corpus graph.

    Formal: (Dᵢ, Dⱼ, l) ∈ R with ω((Dᵢ, Dⱼ, l)) ∈ (0, 1]

    From Definition 1 and 3, §2.1:
        - source_id, target_id identify documents in D
        - relation is the edge type τ(r)
        - weight is ω(r), encoding relationship strength

    Invariant (G4): 0 < weight ≤ 1
    """

    source_id: str
    target_id: str
    relation: RelationType
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not (0.0 < self.weight <= 1.0):
            raise ValueError(
                f"Edge weight must be in (0, 1], got {self.weight} "
                f"(invariant G4, §2.1)"
            )
        if not self.source_id:
            raise ValueError("Edge source_id cannot be empty")
        if not self.target_id:
            raise ValueError("Edge target_id cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation": self.relation.name,
            "weight": round(self.weight, 4),
        }


# ═══════════════════════════════════════════════════════════════════
#  DOCUMENT — D ∈ D
# ═══════════════════════════════════════════════════════════════════


@dataclass
class Document:
    """A document node in the corpus graph.

    Each document has:
        - A unique identifier within the corpus
        - A semantic type from the extensible type system (§4.3)
        - Optional metadata and PIX tree for intra-document navigation
        - An epistemic level σ(D) from the epistemic lattice (§7.1)
    """

    doc_id: str
    title: str
    doc_type: str = "generic"
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    epistemic_level: str = "FactualClaim"  # from §7.1 lattice

    def __post_init__(self) -> None:
        if not self.doc_id:
            raise ValueError("Document doc_id cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "doc_type": self.doc_type,
            "summary": self.summary,
            "epistemic_level": self.epistemic_level,
        }

    def __hash__(self) -> int:
        return hash(self.doc_id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Document):
            return self.doc_id == other.doc_id
        return NotImplemented


# ═══════════════════════════════════════════════════════════════════
#  BUDGET — B = (max_depth, max_nodes, edge_filter), §2.2
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Budget:
    """Navigation budget controlling traversal bounds.

    From §2.2 Problem Statement:
        B = (max_depth, max_nodes, edge_filter)

    Guarantees:
        - Termination (T1): max_depth bounds path length
        - Bounded cost (T3): max_nodes bounds total documents visited
        - Type filtering: edge_filter restricts which relations to follow
    """

    max_depth: int = 5
    max_nodes: int = 50
    edge_filter: frozenset[str] | None = None  # None = all relations allowed

    def __post_init__(self) -> None:
        if self.max_depth < 1:
            raise ValueError(f"Budget max_depth must be ≥ 1, got {self.max_depth}")
        if self.max_nodes < 1:
            raise ValueError(f"Budget max_nodes must be ≥ 1, got {self.max_nodes}")

    def allows_relation(self, relation_name: str) -> bool:
        """Check if edge_filter allows this relation type."""
        if self.edge_filter is None:
            return True
        return relation_name in self.edge_filter


# ═══════════════════════════════════════════════════════════════════
#  PROVENANCE PATH — φ@π from §3.2 (P-CITE, P-EXTEND)
# ═══════════════════════════════════════════════════════════════════


@dataclass
class ProvenancePath:
    """A claim annotated with its provenance chain.

    Formal: φ@π where
        - φ is the claim (proposition)
        - π is the path through the corpus graph witnessing the claim

    From §5.1 (Path type):
        edges: List<Edge<D>>
        provenance: ProvenanceAnnotation

    Invariants:
        (1) Path coherence: ∀ i : edges[i].target = edges[i+1].source
        (2) No immediate revisit: ∀ i : edges[i].target ≠ edges[i].source
    """

    edges: list[Edge]
    claim: str = ""
    epistemic_type: str = "FactualClaim"
    confidence: float = 0.0

    def __post_init__(self) -> None:
        self._validate_coherence()

    def _validate_coherence(self) -> None:
        """Enforce path coherence invariant (§5.1, property 2).

        ∀ i : edges[i].target = edges[i+1].source
        """
        for i in range(len(self.edges) - 1):
            if self.edges[i].target_id != self.edges[i + 1].source_id:
                raise ValueError(
                    f"Path coherence violation at edge {i}: "
                    f"edges[{i}].target ({self.edges[i].target_id}) "
                    f"≠ edges[{i+1}].source ({self.edges[i+1].source_id}). "
                    f"Invariant: §5.1, property 2"
                )

    @property
    def nodes(self) -> list[str]:
        """Derived property: nodes = [edges[0].source] ++ edges.map(e => e.target).

        From §5.1: nodes are derived automatically from edges.
        """
        if not self.edges:
            return []
        result = [self.edges[0].source_id]
        result.extend(e.target_id for e in self.edges)
        return result

    @property
    def depth(self) -> int:
        """Path depth (number of hops)."""
        return len(self.edges)

    @property
    def total_weight(self) -> float:
        """Product of edge weights along the path."""
        if not self.edges:
            return 0.0
        result = 1.0
        for e in self.edges:
            result *= e.weight
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": self.nodes,
            "edges": [e.to_dict() for e in self.edges],
            "claim": self.claim,
            "epistemic_type": self.epistemic_type,
            "confidence": round(self.confidence, 4),
            "depth": self.depth,
        }


# ═══════════════════════════════════════════════════════════════════
#  NAVIGATION RESULT — §5.1
# ═══════════════════════════════════════════════════════════════════


@dataclass
class NavigationResult:
    """Output of multi-document navigation.

    From §5.1:
        type NavigationResult<D: Document> {
            paths:          Set<Path<D>>
            confidence:     ConfidenceScore
            contradictions: Set<(D, D, Proposition)>
        }

    The contradictions field records (Dᵢ, Dⱼ, φ) triples where
    Dᵢ ⊨ φ and Dⱼ ⊨ ¬φ (§3.3 modal contradiction).
    """

    paths: list[ProvenancePath] = field(default_factory=list)
    contradictions: list[tuple[str, str, str]] = field(default_factory=list)
    visited: set[str] = field(default_factory=set)
    confidence: float = 0.0

    @property
    def total_paths(self) -> int:
        """Number of provenance-annotated paths found."""
        return len(self.paths)

    @property
    def total_documents_visited(self) -> int:
        """Total unique documents explored."""
        return len(self.visited)

    @property
    def has_contradictions(self) -> bool:
        """Whether contradictions were detected (§3.3)."""
        return len(self.contradictions) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "paths": [p.to_dict() for p in self.paths],
            "contradictions": [
                {"doc_a": a, "doc_b": b, "proposition": phi}
                for a, b, phi in self.contradictions
            ],
            "visited": sorted(self.visited),
            "confidence": round(self.confidence, 4),
            "total_paths": self.total_paths,
            "total_documents_visited": self.total_documents_visited,
        }


# ═══════════════════════════════════════════════════════════════════
#  CORPUS GRAPH — C = (D, R, τ, ω, σ), Definition 1
# ═══════════════════════════════════════════════════════════════════


class CorpusGraph:
    """Document corpus as a labeled directed graph.

    Implements Definition 1 (§2.1):
        C = (D, R, τ, ω, σ) where
            D = finite set of documents
            R ⊆ D × D × L — labeled directed edges
            τ : R → RelationType — edge type function (implicit via Edge.relation)
            ω : R → ℝ⁺ — edge weight function (implicit via Edge.weight)
            σ : D → EpistemicLevel — encoded in Document.epistemic_level

    Invariants enforced:
        (G1) |D| < ∞ — guaranteed by Python dict
        (G2) ∀ (Dᵢ, Dⱼ, l) ∈ R : Dᵢ, Dⱼ ∈ D — checked in add_edge()
        (G3) τ is total on R — guaranteed by Edge dataclass
        (G4) 0 < ω(r) ≤ 1 — checked in Edge.__post_init__()
    """

    def __init__(self, name: str = "") -> None:
        self.name = name
        self._documents: dict[str, Document] = {}
        self._edges: list[Edge] = []
        # Adjacency index: source_id → list of (Edge, target Document)
        self._adj: dict[str, list[tuple[Edge, Document]]] = {}
        # EPR scores (§2.3) — computed lazily or via EpistemicPageRank
        self._epr_scores: dict[str, float] = {}
        self._epr_dirty: bool = True

    # ── Document operations ──────────────────────────────────────

    @property
    def documents(self) -> dict[str, Document]:
        """Dictionary of doc_id → Document."""
        return dict(self._documents)

    @property
    def document_count(self) -> int:
        """Number of documents in D."""
        return len(self._documents)

    @property
    def edge_count(self) -> int:
        """Number of edges in R."""
        return len(self._edges)

    def add_document(self, doc: Document) -> None:
        """Add a document to the corpus.

        Raises ValueError if doc_id already exists.
        """
        if doc.doc_id in self._documents:
            raise ValueError(f"Document '{doc.doc_id}' already exists in corpus")
        self._documents[doc.doc_id] = doc
        self._adj[doc.doc_id] = []
        self._epr_dirty = True

    def get_document(self, doc_id: str) -> Document | None:
        """Retrieve a document by ID."""
        return self._documents.get(doc_id)

    def has_document(self, doc_id: str) -> bool:
        """Check if document exists in corpus."""
        return doc_id in self._documents

    # ── Edge operations ──────────────────────────────────────────

    @property
    def edges(self) -> list[Edge]:
        """All edges in R."""
        return list(self._edges)

    def add_edge(self, edge: Edge) -> None:
        """Add an edge to the corpus graph.

        Enforces invariant (G2): both endpoints must be in D.
        Optionally validates ontological constraints (§4.3).
        """
        if edge.source_id not in self._documents:
            raise ValueError(
                f"Edge source '{edge.source_id}' not in corpus "
                f"(invariant G2, §2.1)"
            )
        if edge.target_id not in self._documents:
            raise ValueError(
                f"Edge target '{edge.target_id}' not in corpus "
                f"(invariant G2, §2.1)"
            )
        # Ontological validation (§4.3): check domain constraints
        if edge.relation.domain_constraint is not None:
            src_type = self._documents[edge.source_id].doc_type
            tgt_type = self._documents[edge.target_id].doc_type
            req_src, req_tgt = edge.relation.domain_constraint
            if src_type != req_src or tgt_type != req_tgt:
                raise ValueError(
                    f"Ontological constraint violation (§4.3): "
                    f"relation '{edge.relation.name}' requires "
                    f"({req_src}, {req_tgt}), got ({src_type}, {tgt_type})"
                )

        self._edges.append(edge)
        target_doc = self._documents[edge.target_id]
        self._adj[edge.source_id].append((edge, target_doc))
        self._epr_dirty = True

    def remove_document(self, doc_id: str) -> None:
        """Remove a document and all its incident edges.

        §5.5: Supports incremental graph mutation.
        Cascades by removing edges where doc_id is source or target.
        """
        if doc_id not in self._documents:
            raise ValueError(f"Document '{doc_id}' not in corpus")

        # Remove incident edges (both directions)
        self._edges = [
            e for e in self._edges
            if e.source_id != doc_id and e.target_id != doc_id
        ]

        # Remove from adjacency index
        del self._adj[doc_id]
        # Remove edges pointing TO this doc from other adjacency lists
        for src_id in list(self._adj.keys()):
            self._adj[src_id] = [
                (edge, target) for edge, target in self._adj[src_id]
                if target.doc_id != doc_id
            ]

        # Remove the document itself
        del self._documents[doc_id]
        self._epr_dirty = True

    def remove_edge(self, edge: Edge) -> None:
        """Remove a specific edge from the corpus.

        §5.5: Supports incremental graph mutation.
        Removes by identity (source, target, relation match).
        """
        matching = [
            e for e in self._edges
            if (e.source_id == edge.source_id
                and e.target_id == edge.target_id
                and e.relation.name == edge.relation.name)
        ]
        if not matching:
            raise ValueError(
                f"Edge ({edge.source_id} → {edge.target_id}, "
                f"{edge.relation.name}) not in corpus"
            )

        # Remove from edge list
        for m in matching:
            self._edges.remove(m)

        # Remove from adjacency index
        if edge.source_id in self._adj:
            self._adj[edge.source_id] = [
                (e, t) for e, t in self._adj[edge.source_id]
                if not (e.target_id == edge.target_id
                        and e.relation.name == edge.relation.name)
            ]

        self._epr_dirty = True

    def copy(self) -> "CorpusGraph":
        """Create a deep copy of this corpus graph.

        §5.5 functional semantics: C' = copy(C).
        The copy is independent — mutations to C' do not affect C.
        """
        new_corpus = CorpusGraph(name=self.name)
        # Copy documents (all fields)
        for doc in self._documents.values():
            new_corpus.add_document(
                Document(
                    doc_id=doc.doc_id,
                    title=doc.title,
                    doc_type=doc.doc_type,
                    summary=doc.summary,
                    metadata=dict(doc.metadata),
                    epistemic_level=doc.epistemic_level,
                )
            )
        # Copy edges
        for edge in self._edges:
            new_corpus.add_edge(
                Edge(edge.source_id, edge.target_id,
                     edge.relation, weight=edge.weight)
            )
        # Copy EPR scores
        if self._epr_scores:
            new_corpus.set_epr_scores(dict(self._epr_scores))
        return new_corpus

    def validate_edge(self, edge: Edge) -> bool:
        """Check if an edge would be valid without adding it."""
        if edge.source_id not in self._documents:
            return False
        if edge.target_id not in self._documents:
            return False
        if edge.relation.domain_constraint is not None:
            src_type = self._documents[edge.source_id].doc_type
            tgt_type = self._documents[edge.target_id].doc_type
            req_src, req_tgt = edge.relation.domain_constraint
            if src_type != req_src or tgt_type != req_tgt:
                return False
        return True

    # ── Graph queries ────────────────────────────────────────────

    def neighbors(
        self,
        doc_id: str,
        edge_filter: frozenset[str] | None = None,
    ) -> list[tuple[Document, Edge]]:
        """Get neighboring documents with their connecting edges.

        Implements the neighbor expansion step from §5.4:
            neighbors ← {(D', l) : (D, D', l) ∈ R ∧ l ∈ B.edge_filter}

        Args:
            doc_id: Source document identifier.
            edge_filter: If provided, only return neighbors connected
                         via edges with relation names in this set.

        Returns:
            List of (target_document, connecting_edge) tuples.
        """
        if doc_id not in self._adj:
            return []
        result = []
        for edge, target in self._adj[doc_id]:
            if edge_filter is not None and edge.relation.name not in edge_filter:
                continue
            result.append((target, edge))
        return result

    def out_degree(self, doc_id: str) -> int:
        """Out-degree of a document: Δ(C) from §5.4.

        The max out-degree across the corpus is the branching factor
        used in complexity analysis: O(Δ(C)^d · C_eval).
        """
        if doc_id not in self._adj:
            return 0
        return len(self._adj[doc_id])

    def max_out_degree(self) -> int:
        """Maximum out-degree Δ(C) across the corpus."""
        if not self._adj:
            return 0
        return max(len(neighbors) for neighbors in self._adj.values())

    # ── EPR scores ───────────────────────────────────────────────

    @property
    def epr_scores(self) -> dict[str, float]:
        """Epistemic PageRank scores (§2.3).

        These are computed by EpistemicPageRank and set via set_epr_scores().
        """
        return dict(self._epr_scores)

    def set_epr_scores(self, scores: dict[str, float]) -> None:
        """Set pre-computed EPR scores."""
        self._epr_scores = dict(scores)
        self._epr_dirty = False

    @property
    def epr_dirty(self) -> bool:
        """Whether EPR scores need recomputation."""
        return self._epr_dirty

    def get_epr(self, doc_id: str) -> float:
        """Get EPR score for a document. Returns 0.0 if not computed."""
        return self._epr_scores.get(doc_id, 0.0)

    # ── Iteration ────────────────────────────────────────────────

    def iter_documents(self) -> Iterator[Document]:
        """Iterate over all documents in the corpus."""
        yield from self._documents.values()

    def iter_edges(self) -> Iterator[Edge]:
        """Iterate over all edges in the corpus."""
        yield from self._edges

    def document_ids(self) -> set[str]:
        """Set of all document IDs."""
        return set(self._documents.keys())

    # ── Serialization ────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "documents": {
                doc_id: doc.to_dict()
                for doc_id, doc in self._documents.items()
            },
            "edges": [e.to_dict() for e in self._edges],
            "epr_scores": {
                doc_id: round(score, 6)
                for doc_id, score in self._epr_scores.items()
            },
            "document_count": self.document_count,
            "edge_count": self.edge_count,
        }

    def __repr__(self) -> str:
        return (
            f"CorpusGraph(name={self.name!r}, "
            f"docs={self.document_count}, edges={self.edge_count})"
        )
