"""
AXON Engine — MDN Memory Module
====================================
Memory-Augmented Multi-Document Navigation:
Structural Learning via Epistemic Graph Transformation.

Extends the MDN corpus C = (D, R, τ, ω, σ) to:

    C* = (D, R, τ, ω, σ, H, μ)

where:
    H   = (Q, Π, O)              — history structure (Definition 2)
    μ   : (C, H) → C'            — memory update operator (Definition 3)

Memory is NOT storage — it is a continuous deformation of the
epistemic landscape. The operator μ transforms corpus geometry
(weights, epistemic levels) while preserving topology (nodes,
edges, types).

Types of memory (orthogonal, exhaustive):
    Episodic   — Π ⊆ Paths(C)           — traversal trajectories
    Semantic   — ω'(r) = ω(r) + Δ(r|H)  — edge weight adaptation
    Procedural — Bias(D) ∈ ℝ^|D|         — navigation policy learning

Formal properties:
    - Locality:      Δω(r) ≠ 0 ⟹ r ∈ Edges(Π)           (Definition 4)
    - Monotonicity:  σ(Dᵢ) ≤ σ(Dⱼ) ⟹ σ'(Dᵢ) ≤ σ'(Dⱼ)   (Theorem 1)
    - Convergence:   C^(t) → C* under bounded updates      (Theorem 2)
    - Generalization: ∃ C,H : Nav(μ(C,H)) ≠ Nav(C)        (Theorem 3)
    - Identity:      μ(C, ∅) = C                           (Proposition 2)

Mathematical references:
    See docs/memory_augmented_mdn.md for the full formal treatment.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterator


from axon.engine.mdn.corpus_graph import (
    CorpusGraph,
    Document,
    Edge,
    NavigationResult,
    ProvenancePath,
    RelationType,
)
from axon.engine.mdn.epistemic_types import (
    EpistemicLevel,
    promote,
    demote,
)


# ═══════════════════════════════════════════════════════════════════
#  INTERACTION RECORD — Element of O in H = (Q, Π, O)
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class InteractionRecord:
    """A single interaction outcome oᵢ = (qᵢ, πᵢ, sᵢ, tᵢ).

    Records one complete navigation interaction consisting of:
        - The query that initiated it
        - The provenance path traversed
        - The outcome quality score
        - A monotonic timestamp for ordering

    From Definition 2 (History Structure) in the Memory-Augmented MDN paper.
    """

    query: str
    path: ProvenancePath
    outcome_score: float
    timestamp: int

    def __post_init__(self) -> None:
        if not self.query:
            raise ValueError("InteractionRecord query cannot be empty")
        if not (0.0 <= self.outcome_score <= 1.0):
            raise ValueError(
                f"Outcome score must be in [0, 1], got {self.outcome_score}"
            )
        if self.timestamp < 0:
            raise ValueError(
                f"Timestamp must be non-negative, got {self.timestamp}"
            )

    @property
    def traversed_edges(self) -> list[Edge]:
        """Extract traversed edges from the path."""
        return list(self.path.edges)

    @property
    def traversed_doc_ids(self) -> set[str]:
        """Extract set of document IDs visited in this interaction."""
        return set(self.path.nodes) if self.path.nodes else set()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "query": self.query,
            "path": self.path.to_dict(),
            "outcome_score": round(self.outcome_score, 6),
            "timestamp": self.timestamp,
        }


# ═══════════════════════════════════════════════════════════════════
#  HISTORY STRUCTURE — H = (Q, Π, O)
# ═══════════════════════════════════════════════════════════════════


class History:
    """History structure H = (Q, Π, O) with bounded growth.

    From Definition 2:
        Q = {q₁, q₂, ..., qₘ}   — set of past queries
        Π ⊆ Paths(C)             — set of traversed paths
        O = {o₁, o₂, ..., oₘ}   — interaction outcomes

    The history is append-only (write-once for each interaction)
    and supports bounded growth via a configurable maximum size.
    When the maximum is exceeded, the oldest interactions (by
    timestamp) are evicted — a simple LRU policy.

    Args:
        max_size: Maximum number of interaction records to retain.
                  Default: 1000. When exceeded, oldest are evicted.
    """

    def __init__(self, max_size: int = 1000) -> None:
        if max_size < 1:
            raise ValueError(f"max_size must be ≥ 1, got {max_size}")
        self._max_size = max_size
        self._records: list[InteractionRecord] = []
        self._timestamp_counter: int = 0

    # ── Properties ────────────────────────────────────────────────

    @property
    def max_size(self) -> int:
        """Maximum number of records before eviction."""
        return self._max_size

    @property
    def size(self) -> int:
        """Current number of interaction records."""
        return len(self._records)

    @property
    def is_empty(self) -> bool:
        """Whether history contains no interactions."""
        return len(self._records) == 0

    @property
    def queries(self) -> list[str]:
        """Q — set of past queries (ordered by timestamp)."""
        return [r.query for r in self._records]

    @property
    def paths(self) -> list[ProvenancePath]:
        """Π — set of traversed paths."""
        return [r.path for r in self._records]

    @property
    def records(self) -> list[InteractionRecord]:
        """O — interaction outcomes (read-only copy)."""
        return list(self._records)

    @property
    def mean_outcome_score(self) -> float:
        """Running mean of outcome scores s̄ (baseline for learning signal)."""
        if not self._records:
            return 0.5  # Bayesian prior: assume neutral before evidence
        return sum(r.outcome_score for r in self._records) / len(self._records)

    # ── Mutation ──────────────────────────────────────────────────

    def record(
        self,
        query: str,
        path: ProvenancePath,
        outcome_score: float,
    ) -> InteractionRecord:
        """Record a new interaction and return the created record.

        Appends to history. If max_size is exceeded, evicts the oldest
        record (lowest timestamp).

        Args:
            query:         The navigation query.
            path:          The provenance path traversed.
            outcome_score: Quality score ∈ [0, 1] of the navigation outcome.

        Returns:
            The created InteractionRecord with auto-assigned timestamp.
        """
        record = InteractionRecord(
            query=query,
            path=path,
            outcome_score=outcome_score,
            timestamp=self._timestamp_counter,
        )
        self._timestamp_counter += 1
        self._records.append(record)

        # Bounded growth: evict oldest if necessary
        if len(self._records) > self._max_size:
            self._records.pop(0)

        return record

    # ── Queries ───────────────────────────────────────────────────

    def edges_in_history(self) -> set[tuple[str, str, str]]:
        """Edges(Π) — set of all edges traversed in any recorded path.

        Returns edge identifiers as (source_id, target_id, relation_name)
        tuples for use in the locality constraint (Definition 4).
        """
        edge_set: set[tuple[str, str, str]] = set()
        for record in self._records:
            for edge in record.traversed_edges:
                edge_set.add((edge.source_id, edge.target_id, edge.relation.name))
        return edge_set

    def docs_in_history(self) -> set[str]:
        """All document IDs that appear in any recorded path."""
        doc_ids: set[str] = set()
        for record in self._records:
            doc_ids |= record.traversed_doc_ids
        return doc_ids

    def iter_records(self) -> Iterator[InteractionRecord]:
        """Iterate over all records in timestamp order."""
        yield from self._records

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "max_size": self._max_size,
            "size": self.size,
            "mean_outcome_score": round(self.mean_outcome_score, 6),
            "records": [r.to_dict() for r in self._records],
        }


# ═══════════════════════════════════════════════════════════════════
#  EPISODIC MEMORY — M_episodic = Π ⊆ Paths(C)
# ═══════════════════════════════════════════════════════════════════


class EpisodicMemory:
    """Episodic memory: stores concrete traversal trajectories.

    From Definition 5:
        M_episodic = Π ⊆ Paths(C)

    Episodic memory is write-once, read-many. Trajectories are
    appended but never modified. Recall uses structural similarity
    (Jaccard index on node sets) rather than embeddings.
    """

    def __init__(self) -> None:
        self._trajectories: list[tuple[str, ProvenancePath]] = []

    @property
    def size(self) -> int:
        """Number of stored trajectories."""
        return len(self._trajectories)

    def record(self, query: str, path: ProvenancePath) -> None:
        """Record a traversal trajectory (append-only).

        Args:
            query: The query that produced this trajectory.
            path:  The provenance path traversed.
        """
        self._trajectories.append((query, path))

    def recall(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[ProvenancePath]:
        """Recall paths relevant to a query.

        Uses Jaccard similarity on node sets between the query's
        keyword tokens and stored path nodes. This is purely structural —
        no embeddings required.

        similarity(q, π) = |tokens(q) ∩ tokens(stored_q)| / |tokens(q) ∪ tokens(stored_q)|

        Args:
            query: The current query.
            top_k: Maximum number of paths to return.

        Returns:
            List of the top-k most similar stored paths.
        """
        if not self._trajectories:
            return []

        query_tokens = set(query.lower().split())
        scored: list[tuple[float, ProvenancePath]] = []

        for stored_query, path in self._trajectories:
            stored_tokens = set(stored_query.lower().split())
            union = query_tokens | stored_tokens
            if not union:
                continue
            similarity = len(query_tokens & stored_tokens) / len(union)
            scored.append((similarity, path))

        # Sort by similarity descending
        scored.sort(key=lambda x: x[0], reverse=True)
        return [path for _, path in scored[:top_k]]

    def recall_doc_ids(self, query: str, top_k: int = 5) -> set[str]:
        """Recall document IDs from paths relevant to query.

        Convenience method returning the union of all doc_ids from
        the top-k recalled paths.
        """
        paths = self.recall(query, top_k=top_k)
        doc_ids: set[str] = set()
        for path in paths:
            doc_ids.update(path.nodes)
        return doc_ids


# ═══════════════════════════════════════════════════════════════════
#  SEMANTIC MEMORY — ω'(r) = ω(r) + Δ(r | H)
# ═══════════════════════════════════════════════════════════════════


class SemanticMemory:
    """Semantic memory: updates edge weights from interaction outcomes.

    From Definition 6:
        ω'(r) = ω(r) + Δ(r | H)

    where the learning signal is:
        Δ(r | H) = η · Σ_{o ∈ O : r ∈ Edges(πₒ)} (sₒ - s̄) · decay(tₒ)

    With:
        η ∈ (0, 1)                  — learning rate
        γ ∈ (0, 1)                  — temporal decay factor
        ε > 0                       — minimum weight (prevents collapse)

    Formal constraints enforced:
        - Locality (Def 4): only edges in Edges(Π) are modified
        - Bounds (G4):      ω'(r) ∈ [ε, 1.0]

    Args:
        learning_rate: η — controls update magnitude. Default: 0.1
        decay_factor:  γ — temporal decay. Default: 0.95
        min_weight:    ε — minimum edge weight. Default: 0.001
    """

    def __init__(
        self,
        learning_rate: float = 0.1,
        decay_factor: float = 0.95,
        min_weight: float = 0.001,
    ) -> None:
        if not (0.0 < learning_rate <= 1.0):
            raise ValueError(
                f"Learning rate η must be in (0, 1], got {learning_rate}"
            )
        if not (0.0 < decay_factor < 1.0):
            raise ValueError(
                f"Decay factor γ must be in (0, 1), got {decay_factor}"
            )
        if not (0.0 < min_weight < 1.0):
            raise ValueError(
                f"Min weight ε must be in (0, 1), got {min_weight}"
            )
        self.learning_rate = learning_rate
        self.decay_factor = decay_factor
        self.min_weight = min_weight

    def compute_weight_deltas(
        self,
        history: History,
        current_time: int | None = None,
    ) -> dict[tuple[str, str, str], float]:
        """Compute Δ(r | H) for all edges in Edges(Π).

        Implements the learning signal from Definition 6:
            Δ(r | H) = η · Σ_{o ∈ O : r ∈ Edges(πₒ)} (sₒ - s̄) · decay(tₒ)

        Returns:
            Dict mapping edge_id → Δ(r | H).
            Edge identifiers are (source_id, target_id, relation_name) tuples.

        Enforces:
            - Locality: only edges that were traversed appear in output
        """
        if history.is_empty:
            return {}

        baseline = history.mean_outcome_score
        t_now = current_time if current_time is not None else history.size

        deltas: dict[tuple[str, str, str], float] = {}

        for record in history.iter_records():
            deviation = record.outcome_score - baseline
            decay = self.decay_factor ** (t_now - record.timestamp)
            signal = self.learning_rate * deviation * decay

            for edge in record.traversed_edges:
                edge_key = (edge.source_id, edge.target_id, edge.relation.name)
                deltas[edge_key] = deltas.get(edge_key, 0.0) + signal

        return deltas

    def apply_to_corpus(
        self,
        corpus: CorpusGraph,
        history: History,
        current_time: int | None = None,
    ) -> CorpusGraph:
        """Apply semantic memory: transform ω → ω' on a corpus copy.

        This operation:
        1. Computes Δ(r | H) for all edges in Edges(Π)
        2. Creates a new corpus with updated weights
        3. Clamps all weights to [ε, 1.0] (invariant G4)

        Args:
            corpus:       The original corpus C.
            history:      The interaction history H.
            current_time: Override for current timestamp (for testing).

        Returns:
            A new CorpusGraph C' with ω' = ω + Δ applied.
            The original corpus is NOT modified.
        """
        deltas = self.compute_weight_deltas(history, current_time)
        if not deltas:
            return corpus.copy()

        # Build the new corpus with updated weights
        new_corpus = CorpusGraph(name=corpus.name)

        # Copy all documents (unchanged under μ)
        for doc in corpus.iter_documents():
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

        # Copy edges with updated weights
        for edge in corpus.iter_edges():
            edge_key = (edge.source_id, edge.target_id, edge.relation.name)
            delta = deltas.get(edge_key, 0.0)
            new_weight = self._clamp_weight(edge.weight + delta)
            new_corpus.add_edge(
                Edge(
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    relation=edge.relation,
                    weight=new_weight,
                )
            )

        # Preserve EPR scores if available (will be recomputed by caller)
        if corpus.epr_scores:
            new_corpus.set_epr_scores(corpus.epr_scores)

        return new_corpus

    def _clamp_weight(self, w: float) -> float:
        """Clamp weight to [ε, 1.0] (invariant G4 preservation).

        ω'(r) = clamp(ω(r) + Δ(r | H), ε, 1.0)
        """
        return max(self.min_weight, min(1.0, w))


# ═══════════════════════════════════════════════════════════════════
#  PROCEDURAL MEMORY — π_nav : (Q, C, H) → Bias ∈ ℝ^|D|
# ═══════════════════════════════════════════════════════════════════


class ProceduralMemory:
    """Procedural memory: learned navigation bias.

    From Definition 7:
        Bias(D') = Σ_{o ∈ O : D' ∈ Nodes(πₒ)} sₒ · decay(tₒ) / Z

    Documents frequently visited in high-scoring interactions
    accumulate higher bias. The bias vector is integrated into
    the navigator's scoring function as a prior over candidate
    documents for expansion.

    Unlike semantic memory (which modifies the graph), procedural
    memory modifies the *navigator's behavior* without altering
    the corpus itself.

    Args:
        decay_factor: γ — temporal decay for bias computation.
                      Default: 0.95
    """

    def __init__(self, decay_factor: float = 0.95) -> None:
        if not (0.0 < decay_factor < 1.0):
            raise ValueError(
                f"Decay factor must be in (0, 1), got {decay_factor}"
            )
        self.decay_factor = decay_factor

    def compute_bias(
        self,
        history: History,
        doc_ids: set[str],
        current_time: int | None = None,
    ) -> dict[str, float]:
        """Compute Bias(D) for all documents in the corpus.

        Bias(D') = Σ_{o ∈ O : D' ∈ Nodes(πₒ)} sₒ · decay(tₒ) / Z

        Args:
            history:      The interaction history H.
            doc_ids:      Set of all document IDs in the corpus.
            current_time: Override for current timestamp.

        Returns:
            Dict mapping doc_id → normalized bias ∈ [0, 1].
            Documents with no history get bias = 0.
        """
        if history.is_empty:
            return dict.fromkeys(doc_ids, 0.0)

        t_now = current_time if current_time is not None else history.size

        raw_bias: dict[str, float] = dict.fromkeys(doc_ids, 0.0)

        for record in history.iter_records():
            decay = self.decay_factor ** (t_now - record.timestamp)
            weighted_score = record.outcome_score * decay

            for doc_id in record.traversed_doc_ids:
                if doc_id in raw_bias:
                    raw_bias[doc_id] += weighted_score

        # Normalize: Z = Σ raw_bias(D'')
        z = sum(raw_bias.values())
        if z > 0:
            return {d: v / z for d, v in raw_bias.items()}
        return dict.fromkeys(doc_ids, 0.0)


# ═══════════════════════════════════════════════════════════════════
#  MEMORY OPERATOR — μ : (C, H) → C'
# ═══════════════════════════════════════════════════════════════════


class MemoryOperator:
    """Memory update operator μ : (C, H) → C' — functorial endomorphism on Corp.

    From Definition 3 (Memory Update Operator):
        μ transforms corpus geometry (ω, σ) while preserving topology (D, R, τ).

    The operator applies three transformations in sequence:
        1. Semantic:   ω'(r) = ω(r) + Δ(r | H)     — weight adaptation
        2. Epistemic:  σ' via promote/demote         — level adjustment
        3. (Structural shortcuts are deferred to μ⁺, see §7.2 of the paper)

    Formal properties:
        - Locality (Def 4):     only traversed edges are modified
        - Monotonicity (Thm 1): epistemic ordering preserved
        - Convergence (Thm 2):  bounded updates → fixed-point
        - Identity (Prop 2):    μ(C, ∅) = C

    Args:
        semantic_memory:   The semantic memory engine.
        procedural_memory: The procedural memory engine.
        epistemic_update:  Whether to apply epistemic level updates.
                           Default: True.
    """

    def __init__(
        self,
        semantic_memory: SemanticMemory | None = None,
        procedural_memory: ProceduralMemory | None = None,
        epistemic_update: bool = True,
    ) -> None:
        self.semantic = semantic_memory or SemanticMemory()
        self.procedural = procedural_memory or ProceduralMemory()
        self.epistemic_update = epistemic_update

    def update(
        self,
        corpus: CorpusGraph,
        history: History,
    ) -> CorpusGraph:
        """Apply the memory transformation μ(C, H) → C'.

        Implements the full memory update pipeline:
            1. Semantic: adjust edge weights ω' = ω + Δ(r | H)
            2. Epistemic: update σ' via promotion from high-scoring paths

        Args:
            corpus:  The current corpus C.
            history: The interaction history H.

        Returns:
            Transformed corpus C' = μ(C, H).
            The original corpus C is NOT modified.

        Identity property (Proposition 2): μ(C, ∅) = C
        """
        if history.is_empty:
            return corpus.copy()

        # Step 1: Semantic memory — ω'(r) = ω(r) + Δ(r | H)
        transformed = self.semantic.apply_to_corpus(corpus, history)

        # Step 2: Epistemic memory — σ' via promote/demote
        if self.epistemic_update:
            self._apply_epistemic_updates(transformed, history)

        return transformed

    def compute_bias(
        self,
        history: History,
        doc_ids: set[str],
    ) -> dict[str, float]:
        """Compute procedural memory bias for navigation.

        Returns:
            Dict mapping doc_id → bias ∈ [0, 1].
        """
        return self.procedural.compute_bias(history, doc_ids)

    def _apply_epistemic_updates(
        self,
        corpus: CorpusGraph,
        history: History,
    ) -> None:
        """Update epistemic levels σ' based on interaction outcomes.

        For documents in high-scoring paths (sₒ > s̄), edges with positive
        relations trigger promotion. For low-scoring paths, contradiction
        edges trigger demotion.

        Monotonicity (Theorem 1):
            σ(Dᵢ) ≤ σ(Dⱼ) ⟹ σ'(Dᵢ) ≤ σ'(Dⱼ)

        Modifies corpus in place (called after copy in update()).
        """
        baseline = history.mean_outcome_score
        evidence = self._count_evidence(history, baseline)
        self._apply_evidence_to_corpus(corpus, evidence)

    @staticmethod
    def _count_evidence(
        history: History,
        baseline: float,
    ) -> dict[str, tuple[int, int]]:
        """Count promotion/demotion evidence per document.

        Returns:
            Dict mapping doc_id → (promotion_count, demotion_count).
        """
        promotion: dict[str, int] = {}
        demotion: dict[str, int] = {}

        for record in history.iter_records():
            MemoryOperator._accumulate_edge_evidence(
                record, baseline, promotion, demotion,
            )

        all_docs = set(promotion) | set(demotion)
        return {d: (promotion.get(d, 0), demotion.get(d, 0)) for d in all_docs}

    @staticmethod
    def _accumulate_edge_evidence(
        record: InteractionRecord,
        baseline: float,
        promotion: dict[str, int],
        demotion: dict[str, int],
    ) -> None:
        """Accumulate edge evidence from a single interaction record."""
        if record.outcome_score > baseline:
            for edge in record.traversed_edges:
                if edge.relation.is_positive:
                    promotion[edge.target_id] = promotion.get(edge.target_id, 0) + 1
        elif record.outcome_score < baseline:
            for edge in record.traversed_edges:
                if edge.relation.is_negative:
                    demotion[edge.target_id] = demotion.get(edge.target_id, 0) + 1

    @staticmethod
    def _apply_evidence_to_corpus(
        corpus: CorpusGraph,
        evidence: dict[str, tuple[int, int]],
    ) -> None:
        """Apply promotion/demotion evidence to document epistemic levels.

        Note: Document.epistemic_level is stored as a string label
        (e.g., "FactualClaim"). We convert to EpistemicLevel enum for
        arithmetic, then store back as a string label.
        """
        for doc in corpus.iter_documents():
            counts = evidence.get(doc.doc_id)
            if counts is None:
                continue

            p_count, d_count = counts
            # Convert string label → EpistemicLevel enum
            current_level = EpistemicLevel.from_label(
                doc.epistemic_level or "Uncertainty"
            )
            new_level = current_level

            for _ in range(p_count):
                new_level = promote(new_level, "citation")

            for _ in range(d_count):
                new_level = demote(new_level, "contradiction")

            if new_level != current_level:
                # Store back as string label
                object.__setattr__(doc, 'epistemic_level', new_level.to_label())


# ═══════════════════════════════════════════════════════════════════
#  MEMORY-AUGMENTED CORPUS — C* = (D, R, τ, ω, σ, H, μ)
# ═══════════════════════════════════════════════════════════════════


class MemoryAugmentedCorpus:
    """Memory-augmented corpus C* = (D, R, τ, ω, σ, H, μ).

    From Definition 1 (Memory-Augmented Corpus):
        Extends the MDN corpus with a history structure H and
        a memory update operator μ.

    This is the primary API for memory-augmented navigation. It wraps
    a CorpusGraph with memory capabilities, providing:
        - Interaction recording (episodic memory)
        - Graph transformation (semantic memory via μ)
        - Navigation bias (procedural memory)
        - Recall of relevant past paths

    The lifecycle is:
        1. Create with a base corpus
        2. Navigate and record interactions
        3. Apply memory → get transformed corpus
        4. Navigate on transformed corpus (better results)
        5. Repeat (convergence guaranteed by Theorem 2)

    Args:
        corpus:          The base corpus C = (D, R, τ, ω, σ).
        history:         Optional pre-existing history H. Default: empty.
        operator:        Optional memory operator μ. Default: standard.
        max_history:     Maximum history size. Default: 1000.

    Example:
        >>> corpus = CorpusBuilder("Legal").add_document(...).build()
        >>> mac = MemoryAugmentedCorpus(corpus)
        >>> # After navigation:
        >>> mac.record_interaction("liability query", result.paths[0], 0.9)
        >>> # Apply memory:
        >>> transformed = mac.apply_memory()
        >>> # Navigate on transformed corpus for better results
    """

    def __init__(
        self,
        corpus: CorpusGraph,
        history: History | None = None,
        operator: MemoryOperator | None = None,
        max_history: int = 1000,
    ) -> None:
        self._base_corpus = corpus
        self._current_corpus = corpus.copy()
        self._history = history or History(max_size=max_history)
        self._operator = operator or MemoryOperator()
        self._episodic = EpisodicMemory()
        self._memory_applied = False

    # ── Properties ────────────────────────────────────────────────

    @property
    def corpus(self) -> CorpusGraph:
        """The current (possibly memory-transformed) corpus."""
        return self._current_corpus

    @property
    def base_corpus(self) -> CorpusGraph:
        """The original, untransformed corpus."""
        return self._base_corpus

    @property
    def history(self) -> History:
        """The interaction history H."""
        return self._history

    @property
    def episodic_memory(self) -> EpisodicMemory:
        """Episodic memory M_episodic."""
        return self._episodic

    @property
    def interaction_count(self) -> int:
        """Number of recorded interactions."""
        return self._history.size

    @property
    def is_memory_applied(self) -> bool:
        """Whether memory transformation has been applied."""
        return self._memory_applied

    # ── Core Operations ───────────────────────────────────────────

    def record_interaction(
        self,
        query: str,
        path: ProvenancePath,
        outcome_score: float,
    ) -> InteractionRecord:
        """Record a navigation interaction.

        This appends to both the history H and episodic memory.
        Memory transformation is NOT automatically applied — call
        apply_memory() explicitly to trigger μ(C, H) → C'.

        Args:
            query:         The navigation query.
            path:          The traversed provenance path.
            outcome_score: Quality of the result ∈ [0, 1].

        Returns:
            The created InteractionRecord.
        """
        record = self._history.record(query, path, outcome_score)
        self._episodic.record(query, path)
        self._memory_applied = False  # Mark as stale
        return record

    def apply_memory(self) -> CorpusGraph:
        """Apply the memory transformation μ(C, H) → C'.

        Transforms the base corpus using the accumulated history,
        producing a new corpus with updated weights and epistemic
        levels. The transformation is applied to the BASE corpus
        (not the previously transformed one) to ensure convergence
        properties from Theorem 2.

        Returns:
            The transformed corpus C'.
        """
        self._current_corpus = self._operator.update(
            self._base_corpus, self._history,
        )
        self._memory_applied = True
        return self._current_corpus

    def recall(self, query: str, top_k: int = 5) -> set[str]:
        """Recall relevant document IDs from episodic memory.

        Uses structural similarity (Jaccard index on query tokens)
        to find past paths relevant to the current query.

        Args:
            query: The current navigation query.
            top_k: Maximum number of past paths to consider.

        Returns:
            Set of doc_ids from recalled paths.
        """
        return self._episodic.recall_doc_ids(query, top_k=top_k)

    def compute_navigation_bias(self) -> dict[str, float]:
        """Compute procedural memory bias for navigation.

        Returns:
            Dict mapping doc_id → bias ∈ [0, 1].
        """
        doc_ids = self._current_corpus.document_ids()
        return self._operator.compute_bias(self._history, doc_ids)

    # ── Serialization ─────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "base_corpus": self._base_corpus.to_dict(),
            "current_corpus": self._current_corpus.to_dict(),
            "history": self._history.to_dict(),
            "episodic_memory_size": self._episodic.size,
            "memory_applied": self._memory_applied,
            "interaction_count": self.interaction_count,
        }

    def __repr__(self) -> str:
        return (
            f"MemoryAugmentedCorpus("
            f"corpus={self._current_corpus!r}, "
            f"interactions={self.interaction_count}, "
            f"memory_applied={self._memory_applied})"
        )
