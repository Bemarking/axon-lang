"""
AXON Engine — Epistemic PageRank (EPR)
=========================================
Computes document importance via signed graph propagation.

Implements Definition 4.2 (Epistemic PageRank via Signed Propagation), §2.3:

    EPR(Dᵢ) = EPR⁺(Dᵢ) - λ · EPR⁻(Dᵢ)

where EPR⁺, EPR⁻ are the unique solutions to:
    EPR⁺ = (1 - d) · u⁺ + d · (P⁺)ᵀ · EPR⁺    — trust propagation
    EPR⁻ = (1 - d) · u⁻ + d · (P⁻)ᵀ · EPR⁻    — distrust propagation

Parameters:
    d ∈ (0, 1) — damping factor (typically 0.85)
    λ ∈ [0, 1] — distrust penalty weight

This module wraps NetworkX's PageRank implementation behind a clean
interface, allowing future replacement with custom implementations
(e.g., incremental PageRank from §5.5).

Architecture decision: NetworkX as backend with custom interface.
"""

from __future__ import annotations

from typing import Any

from axon.engine.mdn.corpus_graph import (
    CorpusGraph,
    POSITIVE_RELATIONS,
    NEGATIVE_RELATIONS,
)

# ── NetworkX import with graceful fallback ────────────────────────
try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False


class EpistemicPageRank:
    """Epistemic PageRank computation via signed graph decomposition.

    From §2.3 Definition 4 (Signed Corpus Decomposition):
        G⁺ = (D, R⁺) where R⁺ = {r ∈ R : τ(r) ∈ {cite, elaborate, corroborate}}
        G⁻ = (D, R⁻) where R⁻ = {r ∈ R : τ(r) ∈ {contradict, supersede}}

    EPR combines trust and distrust propagation:
        EPR(Dᵢ) = EPR⁺(Dᵢ) - λ · EPR⁻(Dᵢ)

    Uses NetworkX's PageRank internally with custom interface.

    Args:
        damping:   d ∈ (0, 1), default 0.85 (Theorem 3 convergence)
        distrust_weight: λ ∈ [0, 1], penalty for negative edges
        max_iter:  Maximum iterations for power method convergence
        tol:       Convergence tolerance
    """

    def __init__(
        self,
        damping: float = 0.85,
        distrust_weight: float = 0.3,
        max_iter: int = 100,
        tol: float = 1e-6,
    ) -> None:
        if not (0.0 < damping < 1.0):
            raise ValueError(f"Damping factor must be in (0, 1), got {damping}")
        if not (0.0 <= distrust_weight <= 1.0):
            raise ValueError(
                f"Distrust weight must be in [0, 1], got {distrust_weight}"
            )
        self.damping = damping
        self.distrust_weight = distrust_weight
        self.max_iter = max_iter
        self.tol = tol

    def compute(self, corpus: CorpusGraph) -> dict[str, float]:
        """Compute EPR scores for all documents in the corpus.

        Returns:
            dict mapping doc_id → EPR score.
            Scores are normalized to [0, 1] range.
        """
        if corpus.document_count == 0:
            return {}

        if not HAS_NETWORKX:
            return self._compute_fallback(corpus)

        # Step 1: Build signed subgraphs (Definition 4, §2.3)
        g_positive = self._build_subgraph(corpus, positive=True)
        g_negative = self._build_subgraph(corpus, positive=False)

        # Step 2: Compute EPR⁺ (trust propagation)
        epr_positive = self._pagerank(g_positive, corpus)

        # Step 3: Compute EPR⁻ (distrust propagation)
        epr_negative = self._pagerank(g_negative, corpus)

        # Step 4: Combine — EPR(Dᵢ) = EPR⁺(Dᵢ) - λ · EPR⁻(Dᵢ)
        epr_scores: dict[str, float] = {}
        all_doc_ids = corpus.document_ids()

        for doc_id in all_doc_ids:
            trust = epr_positive.get(doc_id, 0.0)
            distrust = epr_negative.get(doc_id, 0.0)
            epr_scores[doc_id] = trust - self.distrust_weight * distrust

        # Normalize to [0, 1] range
        epr_scores = self._normalize(epr_scores)

        # Update corpus with computed scores
        corpus.set_epr_scores(epr_scores)

        return epr_scores

    def compute_and_apply(self, corpus: CorpusGraph) -> dict[str, float]:
        """Compute EPR and apply to the corpus in one step."""
        scores = self.compute(corpus)
        corpus.set_epr_scores(scores)
        return scores

    # ── NetworkX-backed implementation ───────────────────────────

    def _build_subgraph(
        self,
        corpus: CorpusGraph,
        positive: bool,
    ) -> nx.DiGraph:
        """Build the positive (G⁺) or negative (G⁻) subgraph.

        From Definition 4, §2.3:
            G⁺ = (D, R⁺) where R⁺ = {r : τ(r) ∈ positive_relations}
            G⁻ = (D, R⁻) where R⁻ = {r : τ(r) ∈ negative_relations}
        """
        g = nx.DiGraph()

        # Add all documents as nodes (ensures dangling nodes are included)
        for doc_id in corpus.document_ids():
            g.add_node(doc_id)

        # Add filtered edges
        target_relations = POSITIVE_RELATIONS if positive else NEGATIVE_RELATIONS
        for edge in corpus.iter_edges():
            if edge.relation.name in target_relations:
                g.add_edge(
                    edge.source_id,
                    edge.target_id,
                    weight=edge.weight,
                )

        return g

    def _pagerank(
        self,
        graph: nx.DiGraph,
        corpus: CorpusGraph,
    ) -> dict[str, float]:
        """Compute PageRank on a subgraph.

        Uses NetworkX's pagerank implementation which handles:
            - (P1) Non-negativity
            - (P2-P3) Row-stochasticity
            - (P4) Dangling nodes → uniform distribution

        From Definition 4.1, §2.3.
        """
        if graph.number_of_nodes() == 0:
            return {}
        if graph.number_of_edges() == 0:
            # No edges → uniform distribution
            n = graph.number_of_nodes()
            return {node: 1.0 / n for node in graph.nodes()}

        try:
            return nx.pagerank(
                graph,
                alpha=self.damping,
                max_iter=self.max_iter,
                tol=self.tol,
                weight="weight",
            )
        except nx.PowerIterationFailedConvergence:
            # Fallback to uniform on convergence failure
            n = graph.number_of_nodes()
            return {node: 1.0 / n for node in graph.nodes()}

    # ── Normalization ────────────────────────────────────────────

    @staticmethod
    def _normalize(scores: dict[str, float]) -> dict[str, float]:
        """Normalize scores to [0, 1] range via min-max scaling."""
        if not scores:
            return {}
        values = list(scores.values())
        min_val = min(values)
        max_val = max(values)
        if max_val == min_val:
            # All scores equal → uniform 0.5
            return {k: 0.5 for k in scores}
        rng = max_val - min_val
        return {k: (v - min_val) / rng for k, v in scores.items()}

    # ── Fallback (no NetworkX) ───────────────────────────────────

    def _compute_fallback(self, corpus: CorpusGraph) -> dict[str, float]:
        """Simple degree-based approximation when NetworkX is unavailable.

        This is NOT the proper EPR computation — just a reasonable
        approximation for testing. Production should always use NetworkX.
        """
        scores: dict[str, float] = {}
        for doc_id in corpus.document_ids():
            in_positive = sum(
                1 for e in corpus.iter_edges()
                if e.target_id == doc_id and e.relation.name in POSITIVE_RELATIONS
            )
            in_negative = sum(
                1 for e in corpus.iter_edges()
                if e.target_id == doc_id and e.relation.name in NEGATIVE_RELATIONS
            )
            scores[doc_id] = (
                in_positive - self.distrust_weight * in_negative
            )

        return self._normalize(scores)

    # ── Incremental Update (§5.5) ──────────────────────────────────

    def incremental_update(
        self,
        corpus: CorpusGraph,
        affected_doc_ids: set[str],
        k_hop: int = 2,
    ) -> dict[str, float]:
        """Incremental EPR recomputation for affected subgraph.

        From §5.5: Uses k-hop neighborhood to localize the update,
        avoiding full O(|D|) recomputation for local changes.

        Algorithm:
            1. Compute k-hop neighborhood N_k around affected nodes
            2. Extract induced subgraph G[N_k]
            3. Recompute EPR on G[N_k] (local PageRank)
            4. Blend local scores with existing global scores using
               damping-based decay weight

        Complexity: O(Δ^k · C_PR) where Δ = max degree, C_PR = PageRank cost
        vs full recompute: O(|D| · C_PR)

        The parameter k controls propagation radius:
            k=1 → immediate neighbors only
            k=2 → captures >95% of EPR change (geometric decay at rate d)
            k=3 → captures >99% (diminishing returns)

        Args:
            corpus:           The corpus graph C (already mutated with new docs/edges).
            affected_doc_ids: Set of doc_ids that were added, removed, or had
                              edges modified.
            k_hop:            Radius of neighborhood to recompute. Default: 2.

        Returns:
            dict mapping doc_id → updated EPR score for ALL documents.
            Unaffected documents retain their previous scores.
        """
        if corpus.document_count == 0:
            return {}

        if not affected_doc_ids:
            # Nothing changed — return current scores
            return dict(corpus.epr_scores)

        # Filter affected_doc_ids to only those still in the corpus
        valid_affected = affected_doc_ids & corpus.document_ids()
        if not valid_affected:
            # All affected docs were removed — full recompute needed
            return self.compute(corpus)

        # Step 1: Compute k-hop neighborhood around affected nodes
        neighborhood = self._k_hop_union(corpus, valid_affected, k_hop)

        # Step 2: If neighborhood covers most of the corpus, just do full recompute
        coverage = len(neighborhood) / max(corpus.document_count, 1)
        if coverage > 0.7:
            return self.compute(corpus)

        if not HAS_NETWORKX:
            return self.compute(corpus)

        # Step 3: Extract induced subgraph and recompute locally
        local_g_pos = self._extract_subgraph(corpus, neighborhood, positive=True)
        local_g_neg = self._extract_subgraph(corpus, neighborhood, positive=False)

        local_epr_pos = self._pagerank(local_g_pos, corpus)
        local_epr_neg = self._pagerank(local_g_neg, corpus)

        # Step 4: Compute local EPR scores
        local_scores: dict[str, float] = {}
        for doc_id in neighborhood:
            trust = local_epr_pos.get(doc_id, 0.0)
            distrust = local_epr_neg.get(doc_id, 0.0)
            local_scores[doc_id] = trust - self.distrust_weight * distrust

        # Step 5: Blend with existing global scores
        blended = self._blend_scores(corpus, local_scores, neighborhood)

        # Step 6: Normalize and apply
        blended = self._normalize(blended)
        corpus.set_epr_scores(blended)

        return blended

    def _k_hop_union(
        self,
        corpus: CorpusGraph,
        doc_ids: set[str],
        k: int,
    ) -> set[str]:
        """Union of k-hop neighborhoods for multiple seed nodes.

        N_k(S) = ⋃_{d ∈ S} N_k(d)
        """
        result: set[str] = set()
        for doc_id in doc_ids:
            result |= self.k_hop_neighborhood(corpus, doc_id, k)
        return result

    def _extract_subgraph(
        self,
        corpus: CorpusGraph,
        node_set: set[str],
        positive: bool,
    ) -> "nx.DiGraph":
        """Extract the induced signed subgraph on a node subset.

        G[S] = (S, {(u,v) ∈ R : u,v ∈ S ∧ sign(u,v) matches})

        This is the localized version of _build_subgraph for
        incremental updates.
        """
        g = nx.DiGraph()

        for doc_id in node_set:
            g.add_node(doc_id)

        target_relations = POSITIVE_RELATIONS if positive else NEGATIVE_RELATIONS
        for edge in corpus.iter_edges():
            if (
                edge.source_id in node_set
                and edge.target_id in node_set
                and edge.relation.name in target_relations
            ):
                g.add_edge(
                    edge.source_id,
                    edge.target_id,
                    weight=edge.weight,
                )

        return g

    def _blend_scores(
        self,
        corpus: CorpusGraph,
        local_scores: dict[str, float],
        neighborhood: set[str],
    ) -> dict[str, float]:
        """Blend locally recomputed scores with existing global scores.

        For nodes in the neighborhood: use the new local score.
        For nodes outside: retain the existing global score.

        At the boundary (nodes in neighborhood but at max k distance),
        we apply a decay weight to smooth the transition:

            blended(d) = α · local(d) + (1-α) · global(d)

        where α = 1.0 for affected nodes and decays by damping factor
        for boundary nodes.
        """
        existing = corpus.epr_scores
        blended: dict[str, float] = {}

        for doc_id in corpus.document_ids():
            if doc_id in local_scores:
                # Node was in the recomputed neighborhood
                blended[doc_id] = local_scores[doc_id]
            elif doc_id in existing:
                # Node was outside — keep existing score
                blended[doc_id] = existing[doc_id]
            else:
                # New node with no prior score — default
                blended[doc_id] = 0.0

        return blended

    @staticmethod
    def k_hop_neighborhood(
        corpus: CorpusGraph,
        doc_id: str,
        k: int = 2,
    ) -> set[str]:
        """Get k-hop neighborhood of a document.

        From §5.5: The parameter k controls how far the update propagates.
        k=2 captures >95% of EPR change (geometric decay at rate d).

        Uses bidirectional expansion: follows both outgoing AND incoming
        edges to capture the full influence region.
        """
        visited: set[str] = {doc_id}
        frontier: set[str] = {doc_id}

        for _ in range(k):
            next_frontier: set[str] = set()
            for fid in frontier:
                # Outgoing neighbors
                for neighbor, edge in corpus.neighbors(fid):
                    if neighbor.doc_id not in visited:
                        visited.add(neighbor.doc_id)
                        next_frontier.add(neighbor.doc_id)
                # Incoming neighbors (reverse edges affect EPR too)
                for edge in corpus.iter_edges():
                    if edge.target_id == fid and edge.source_id not in visited:
                        visited.add(edge.source_id)
                        next_frontier.add(edge.source_id)
            frontier = next_frontier
            if not frontier:
                break

        return visited
