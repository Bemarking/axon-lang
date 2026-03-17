"""
AXON Engine — MDN Corpus Navigator
=====================================
Bounded BFS with information-gain pruning on corpus graphs.

Implements Algorithm MDN-Navigate(Q, C, D₀, B) from §5.4:

    1. Initialize frontier with starting document
    2. For each depth level up to B.max_depth:
       a. Score each frontier document for relevance (§4.4)
       b. Expand neighbors with type filtering (§4.3)
       c. Information-gain scoring with greedy selection (Theorem 2, §2.2)
       d. Adaptive pruning via median threshold
       e. No-immediate-revisit check (§5.1, invariant 3)
    3. Return NavigationResult with provenance paths

Complexity (§5.4):
    - Worst case: O(Δ(C)^d · C_eval)
    - Expected:   O(b̄ · d · C_eval) where b̄ ≈ 2-3

Termination guarantees:
    - (T1) max_depth is finite
    - (T2) visited set is monotonically increasing
    - (T3) max_nodes is a hard bound
"""

from __future__ import annotations

import statistics
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from axon.engine.mdn.corpus_graph import (
    Budget,
    CorpusGraph,
    Document,
    Edge,
    NavigationResult,
    ProvenancePath,
)
from axon.engine.mdn.epistemic_types import classify_provenance


# ═══════════════════════════════════════════════════════════════════
#  SCORING PROTOCOL — Pluggable relevance/info-gain estimation
# ═══════════════════════════════════════════════════════════════════


@runtime_checkable
class RelevanceScorer(Protocol):
    """Protocol for relevance scoring.

    Approximates P(D relevant | Q, H) from §4.4.
    Implementations may use:
        - Embedding similarity (cosine(Q, D.summary))
        - Structural prior (EPR, edge weights)
        - LLM scoring (like PIX's ScoringFunction)
    """

    def score_relevance(
        self,
        query: str,
        document: Document,
        path_context: list[str],
    ) -> float:
        """Score document relevance ∈ [0, 1].

        Args:
            query:        The search query Q.
            document:     The candidate document D.
            path_context: List of doc_ids visited so far (D₀, ..., Dₜ₋₁).

        Returns:
            Relevance score in [0, 1].
        """
        ...


@runtime_checkable
class InfoGainEstimator(Protocol):
    """Protocol for information gain estimation.

    Approximates I(A; D' | Q, D₀, ..., Dₖ) from Theorem 2, §2.2.
    """

    def estimate_info_gain(
        self,
        query: str,
        candidate: Document,
        path_context: list[str],
        edge: Edge,
    ) -> float:
        """Estimate information gain ≥ 0.

        Uses:
            - Embedding similarity between Q and D'.summary
            - Edge-type informativeness ατ (§2.4)
            - Diminishing returns from visited documents (submodularity)

        Args:
            query:        The search query Q.
            candidate:    The candidate document D'.
            path_context: Current navigation history.
            edge:         The edge connecting current document to candidate.

        Returns:
            Estimated information gain ≥ 0.
        """
        ...


# ═══════════════════════════════════════════════════════════════════
#  DEFAULT SCORERS — Simple implementations for testing & MVP
# ═══════════════════════════════════════════════════════════════════


class EPRRelevanceScorer:
    """Default scorer combining EPR with edge weight.

    relevance(D, Q, path) = α · EPR(D) + β · ω(edge to D) + γ · keyword_overlap
    where α + β + γ = 1

    This is a simple baseline; production use should replace with
    LLM-based or embedding-based scoring.
    """

    def __init__(
        self,
        corpus: CorpusGraph,
        alpha: float = 0.3,
        beta: float = 0.4,
        gamma: float = 0.3,
    ) -> None:
        self.corpus = corpus
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma

    def score_relevance(
        self,
        query: str,
        document: Document,
        path_context: list[str],
    ) -> float:
        epr = self.corpus.get_epr(document.doc_id)

        # Simple keyword overlap as a baseline for γ component
        query_words = set(query.lower().split())
        doc_words = set(document.title.lower().split())
        if document.summary:
            doc_words |= set(document.summary.lower().split())
        overlap = len(query_words & doc_words) / max(len(query_words), 1)

        return self.alpha * epr + self.gamma * overlap


class DefaultInfoGainEstimator:
    """Default info-gain estimator using EPR + edge weight + diminishing returns.

    Approximates I(A; D' | Q, D₀, ..., Dₖ) via:
        gain ≈ relevance(D') · ω(edge) · decay(depth)

    The decay factor models the submodularity from Theorem 2.1:
    diminishing returns as more documents are visited.
    """

    def __init__(
        self,
        corpus: CorpusGraph,
        decay_rate: float = 0.8,
    ) -> None:
        self.corpus = corpus
        self.decay_rate = decay_rate

    def estimate_info_gain(
        self,
        query: str,
        candidate: Document,
        path_context: list[str],
        edge: Edge,
    ) -> float:
        # Base relevance from EPR and simple keyword match
        epr = self.corpus.get_epr(candidate.doc_id)
        query_words = set(query.lower().split())
        doc_words = set(candidate.title.lower().split())
        if candidate.summary:
            doc_words |= set(candidate.summary.lower().split())
        overlap = len(query_words & doc_words) / max(len(query_words), 1)

        base_relevance = 0.5 * epr + 0.5 * overlap

        # Edge weight contribution
        weight = edge.weight

        # Diminishing returns (submodularity approximation)
        depth = len(path_context)
        decay = self.decay_rate ** depth

        return base_relevance * weight * decay


# ═══════════════════════════════════════════════════════════════════
#  CORPUS NAVIGATOR — Algorithm MDN-Navigate, §5.4
# ═══════════════════════════════════════════════════════════════════


@dataclass
class NavigationStep:
    """Record of a single step in the multi-document navigation.

    Analogous to PIX's NavigationStep but at the corpus (inter-document) level.
    """

    doc_id: str
    doc_title: str
    relevance_score: float
    info_gain: float
    depth: int
    via_edge: Edge | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "doc_title": self.doc_title,
            "relevance_score": round(self.relevance_score, 4),
            "info_gain": round(self.info_gain, 4),
            "depth": self.depth,
            "via_relation": self.via_edge.relation.name if self.via_edge else None,
        }


class CorpusNavigator:
    """Bounded BFS with information-gain pruning on corpus graphs.

    Implements Algorithm MDN-Navigate(Q, C, D₀, B) from §5.4.

    The navigator follows an ε-informative policy (Definition 3, §2.2):
    at each step, it selects documents with information gain ≥ adaptive threshold θ.

    By Theorem 2.1 (Corollary, §2.2), the greedy selection achieves a
    (1 - 1/e) ≈ 0.632 approximation to the optimal information gain.

    Args:
        corpus:            The corpus graph C.
        relevance_scorer:  Scorer for P(D relevant | Q, H) (§4.4).
        info_gain_scorer:  Estimator for I(A; D' | Q, ...) (Theorem 2).
        relevance_threshold: τ_rel — minimum relevance to consider a document
                              relevant to the query. Default: 0.1
        quantile_p:        The quantile p for the adaptive threshold θ (line 28).
                           Lower p = more exploration, higher p = faster convergence.
                           Default: 0.5 (median).
    """

    def __init__(
        self,
        corpus: CorpusGraph,
        relevance_scorer: RelevanceScorer | None = None,
        info_gain_scorer: InfoGainEstimator | None = None,
        relevance_threshold: float = 0.1,
        quantile_p: float = 0.5,
    ) -> None:
        self.corpus = corpus
        self.relevance_scorer = relevance_scorer or EPRRelevanceScorer(corpus)
        self.info_gain_scorer = info_gain_scorer or DefaultInfoGainEstimator(corpus)
        self.relevance_threshold = relevance_threshold
        self.quantile_p = quantile_p

    def navigate(
        self,
        start_doc_id: str,
        query: str,
        budget: Budget,
    ) -> NavigationResult:
        """Execute multi-document navigation.

        Implements the pseudocode from §5.4 line-by-line.

        Args:
            start_doc_id: D₀ — the starting document.
            query:        Q — the navigation query.
            budget:       B — navigation budget constraints.

        Returns:
            NavigationResult with provenance-annotated paths.

        Raises:
            ValueError: If start_doc_id is not in the corpus.
        """
        if not self.corpus.has_document(start_doc_id):
            raise ValueError(f"Start document '{start_doc_id}' not in corpus")

        # Line 1-3: Initialize
        # frontier: list of (current_doc_id, path_edges_so_far)
        frontier: list[tuple[str, list[Edge]]] = [(start_doc_id, [])]
        visited: set[str] = set()
        collected_paths: list[ProvenancePath] = []
        steps: list[NavigationStep] = []

        # Line 5: For depth = 0 to B.max_depth (T1: finite bound)
        for depth in range(budget.max_depth + 1):
            next_frontier: list[tuple[str, list[Edge]]] = []

            # Line 7: For each (D, path) in frontier
            for doc_id, path_edges in frontier:

                # Line 8-9: Budget enforcement (T3)
                if len(visited) >= budget.max_nodes:
                    break

                # Line 10-11: No re-exploration (T2)
                if doc_id in visited:
                    continue
                # Line 12: Mark as visited
                visited.add(doc_id)

                doc = self.corpus.get_document(doc_id)
                if doc is None:
                    continue

                # Line 14-17: Relevance test and path collection
                path_context = self._path_nodes(path_edges, start_doc_id)
                relevance = self.relevance_scorer.score_relevance(
                    query, doc, path_context,
                )

                step = NavigationStep(
                    doc_id=doc_id,
                    doc_title=doc.title,
                    relevance_score=relevance,
                    info_gain=0.0,
                    depth=depth,
                    via_edge=path_edges[-1] if path_edges else None,
                )
                steps.append(step)

                if relevance >= self.relevance_threshold:
                    # Collect provenance path: φ@π (§3.2)
                    prov_path = ProvenancePath(
                        edges=list(path_edges),
                        claim="",  # to be populated by downstream processing
                        epistemic_type=classify_provenance(
                            path_length=len(path_edges),
                        ).to_label(),
                        confidence=relevance,
                    )
                    collected_paths.append(prov_path)

                # Line 20: Neighbor expansion with type filtering (§4.3)
                neighbors = self.corpus.neighbors(
                    doc_id,
                    edge_filter=budget.edge_filter,
                )

                if not neighbors:
                    continue

                # Line 24-25: Information-gain scoring (Theorem 2, §2.2)
                gains: dict[str, float] = {}
                neighbor_map: dict[str, tuple[Document, Edge]] = {}
                for neighbor_doc, edge in neighbors:
                    if neighbor_doc.doc_id in visited:
                        continue
                    gain = self.info_gain_scorer.estimate_info_gain(
                        query, neighbor_doc, path_context, edge,
                    )
                    gains[neighbor_doc.doc_id] = gain
                    neighbor_map[neighbor_doc.doc_id] = (neighbor_doc, edge)

                if not gains:
                    continue

                # Line 28: Adaptive pruning threshold
                theta = self._adaptive_threshold(list(gains.values()))

                # Line 29: Select above threshold
                selected = {
                    nid: g for nid, g in gains.items() if g >= theta
                }

                # Line 31-34: Expand frontier
                for nid, gain_value in selected.items():
                    neighbor_doc, edge = neighbor_map[nid]
                    new_path = list(path_edges) + [edge]

                    # Line 33: No-immediate-revisit check (§5.1, invariant 3)
                    if self._no_immediate_revisit(new_path):
                        next_frontier.append((nid, new_path))

            # Line 36: Update frontier
            frontier = next_frontier

            # Early exit if frontier is empty
            if not frontier:
                break

        # Line 38-42: Build result
        contradictions = self._detect_contradictions(collected_paths)
        confidence = self._aggregate_confidence(collected_paths)

        return NavigationResult(
            paths=collected_paths,
            contradictions=contradictions,
            visited=visited,
            confidence=confidence,
        )

    # ── Private helpers ──────────────────────────────────────────

    def _path_nodes(self, edges: list[Edge], start_id: str) -> list[str]:
        """Derive node list from edge list (§5.1 derived property)."""
        if not edges:
            return [start_id]
        result = [edges[0].source_id]
        result.extend(e.target_id for e in edges)
        return result

    def _adaptive_threshold(self, gains: list[float]) -> float:
        """Compute adaptive pruning threshold θ (line 28, §5.4).

        Uses quantile(gains, p) where p = self.quantile_p.
        Lower p = more exploration (higher b̄).
        Higher p = more exploitation (lower b̄, faster convergence).
        """
        if not gains:
            return 0.0
        if len(gains) == 1:
            return gains[0]

        sorted_gains = sorted(gains)
        idx = max(0, int(len(sorted_gains) * self.quantile_p) - 1)
        return sorted_gains[idx]

    @staticmethod
    def _no_immediate_revisit(path_edges: list[Edge]) -> bool:
        """Check §5.1 invariant 3: no immediate revisit.

        Returns True iff path[-1].target ≠ path[-2].target (when |path| ≥ 2).
        Also checks that no self-loops exist: edges[i].source ≠ edges[i].target.
        """
        if len(path_edges) < 2:
            return True
        # No self-loop on the new edge
        last = path_edges[-1]
        if last.source_id == last.target_id:
            return False
        # No immediate revisit
        return path_edges[-1].target_id != path_edges[-2].target_id

    @staticmethod
    def _detect_contradictions(
        paths: list[ProvenancePath],
    ) -> list[tuple[str, str, str]]:
        """Detect contradictions between paths (§3.3).

        Placeholder: in a full implementation, this would use modal logic
        to detect ⟨contradict⟩φ. Here we check for paths reaching the same
        document via contradicting edge types.
        """
        contradictions: list[tuple[str, str, str]] = []
        # Detect edges with "contradict" relation type
        for path in paths:
            for edge in path.edges:
                if edge.relation.name == "contradict":
                    contradictions.append(
                        (edge.source_id, edge.target_id, "contradiction_detected")
                    )
        return contradictions

    @staticmethod
    def _aggregate_confidence(paths: list[ProvenancePath]) -> float:
        """Aggregate confidence across paths (Proposition 6, §4.1).

        Uses the mean of individual path confidences as a simple baseline.
        Full implementation would use Bayesian posterior updating (§4.4).
        """
        if not paths:
            return 0.0
        return sum(p.confidence for p in paths) / len(paths)
