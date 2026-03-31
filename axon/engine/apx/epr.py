"""
AXON APX - Epistemic PageRank with Blame Penalty

Phase 1 scoring model over APX dependency graphs.

The score blends:
- graph propagation over weighted edges
- prior trust from epistemic levels
- penalty from SERVER blame history
"""

from __future__ import annotations

from math import exp

from axon.engine.apx.graph import EpistemicGraph
from axon.engine.apx.lattice import EpistemicLevel


LEVEL_PRIOR: dict[EpistemicLevel, float] = {
    EpistemicLevel.UNCERTAINTY: 0.10,
    EpistemicLevel.SPECULATION: 0.20,
    EpistemicLevel.OPINION: 0.35,
    EpistemicLevel.FACTUAL_CLAIM: 0.55,
    EpistemicLevel.CITED_FACT: 0.75,
    EpistemicLevel.CORROBORATED_FACT: 1.00,
}


class EpistemicPageRank:
    """Deterministic EPR implementation for APX package ranking."""

    def __init__(
        self,
        damping: float = 0.85,
        iterations: int = 40,
        blame_alpha: float = 0.2,
    ) -> None:
        if not (0.0 < damping < 1.0):
            raise ValueError("damping must be in (0,1)")
        if iterations < 1:
            raise ValueError("iterations must be >= 1")
        if blame_alpha < 0.0:
            raise ValueError("blame_alpha must be >= 0")

        self.damping = damping
        self.iterations = iterations
        self.blame_alpha = blame_alpha

    def compute(self, graph: EpistemicGraph) -> dict[str, float]:
        """Compute normalized EPR scores in [0,1]."""
        node_ids = graph.node_ids()
        if not node_ids:
            return {}

        incoming: dict[str, list[tuple[str, float]]] = {nid: [] for nid in node_ids}
        out_weight: dict[str, float] = {nid: 0.0 for nid in node_ids}

        for edge in graph.edges():
            incoming[edge.target_id].append((edge.source_id, edge.weight))
            out_weight[edge.source_id] += edge.weight

        priors: dict[str, float] = {}
        for node_id in node_ids:
            node = graph.get_node(node_id)
            assert node is not None
            priors[node_id] = LEVEL_PRIOR[node.level]

        scores = {nid: 1.0 / len(node_ids) for nid in node_ids}

        for _ in range(self.iterations):
            next_scores: dict[str, float] = {}
            for node_id in node_ids:
                propagated = 0.0
                for src, weight in incoming[node_id]:
                    denom = out_weight[src] if out_weight[src] > 0 else 1.0
                    propagated += scores[src] * (weight / denom)

                next_scores[node_id] = (
                    (1.0 - self.damping) * priors[node_id]
                    + self.damping * propagated
                )

            scores = next_scores

        for node_id in node_ids:
            node = graph.get_node(node_id)
            assert node is not None
            penalty = exp(-self.blame_alpha * node.server_blame_count)
            scores[node_id] *= penalty

        return self._normalize(scores)

    @staticmethod
    def quarantine_candidates(scores: dict[str, float], threshold: float = 0.2) -> list[str]:
        """Low-ranked packages should be quarantined by policy."""
        if not (0.0 <= threshold <= 1.0):
            raise ValueError("threshold must be in [0,1]")
        return sorted([pkg for pkg, score in scores.items() if score <= threshold])

    @staticmethod
    def _normalize(scores: dict[str, float]) -> dict[str, float]:
        if not scores:
            return {}

        values = list(scores.values())
        mn = min(values)
        mx = max(values)

        if mx == mn:
            return {k: 0.5 for k in scores}

        span = mx - mn
        return {k: (v - mn) / span for k, v in scores.items()}
