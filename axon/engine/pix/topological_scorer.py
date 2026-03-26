"""
AXON Engine — PIX Topological Scorer
=========================================
Visual scoring functions for PIX navigation — determines which
image regions are worth exploring based on topological complexity
and epistemic information gain.

DESIGN DECISION (for devs):
    This module is the VISUAL analogue of the scoring system in navigator.py:
        ThresholdScorer   →  BettiScorer  (testing scorer)
        (LLM Scorer)      →  TopologicalScorer  (production scorer)

    Both implement the ScoringFunction protocol from navigator.py:
        def score(query, title, summary) → tuple[float, str]

    The key difference:
        - Document PIX: LLM evaluates "how relevant is this section?"
        - Visual PIX: Math evaluates "how much information would this region add?"

    Because visual scoring is deterministic (no LLM needed), this is
    one of the key advantages of the visual extension: pure math scoring.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# ═══════════════════════════════════════════════════════════════════
#  BETTI SCORER — testing scorer (analogue of ThresholdScorer)
# ═══════════════════════════════════════════════════════════════════


class BettiScorer:
    """Simple Betti-number-based scorer for testing.

    FOR DEVS: This is the visual analogue of ThresholdScorer.

    ThresholdScorer scores by keyword overlap:
        score = |query_terms ∩ text_terms| / |query_terms|

    BettiScorer scores by topological complexity:
        score = (β0 + β1) / max_complexity, normalized to [0, 1]

    The betti_summary string is expected in format:
        "β0=3, β1=1, P=0.45, E=0.72"

    Both return tuple[float, str] to satisfy ScoringFunction protocol.
    Not intended for production — use TopologicalScorer instead.

    Example:
        scorer = BettiScorer(max_complexity=10)
        score, reason = scorer.score("", "Region NW L2", "β0=3, β1=1, P=0.45")
        # → (0.4, "Topological complexity: β0=3, β1=1 → 4/10")
    """

    def __init__(self, max_complexity: int = 10) -> None:
        self._max_complexity = max(max_complexity, 1)

    def score(
        self, query: str, title: str, summary: str,
    ) -> tuple[float, str]:
        """Score a visual node by its topological complexity.

        Args:
            query:   Ignored in BettiScorer (purely structural scoring).
            title:   Node label (e.g. "Region NW L2").
            summary: Betti summary string (e.g. "β0=3, β1=1, P=0.45").

        Returns:
            Tuple of (score ∈ [0,1], reasoning_text).
        """
        beta_0, beta_1 = self._parse_betti(summary)
        complexity = beta_0 + beta_1
        score = min(complexity / self._max_complexity, 1.0)

        reasoning = (
            f"Topological complexity: β0={beta_0}, β1={beta_1} "
            f"→ {complexity}/{self._max_complexity}"
        )
        return score, reasoning

    @staticmethod
    def _parse_betti(summary: str) -> tuple[int, int]:
        """Parse Betti numbers from summary string.

        Expected format: "β0=3, β1=1, ..."
        Gracefully handles malformed input.
        """
        beta_0, beta_1 = 0, 0
        for part in summary.split(","):
            part = part.strip()
            if part.startswith("β0=") or part.startswith("β0="):
                try:
                    beta_0 = int(part.split("=")[1])
                except (ValueError, IndexError):
                    pass
            elif part.startswith("β1=") or part.startswith("β1="):
                try:
                    beta_1 = int(part.split("=")[1])
                except (ValueError, IndexError):
                    pass
        return beta_0, beta_1


# ═══════════════════════════════════════════════════════════════════
#  TOPOLOGICAL SCORER — production scorer
# ═══════════════════════════════════════════════════════════════════


class TopologicalScorer:
    """Production scorer based on Epistemic Information Gain.

    FOR DEVS: This scorer implements the ScoringFunction protocol
    from navigator.py but uses MATHEMATICAL COMPUTATION instead of
    LLM inference. This is a fundamental advantage of visual PIX:
    scoring is deterministic, repeatable, and free.

    FROM PAPER §2.5.3:
        G(ω) = H[Q(s)] - E[H[Q(s|o_ω)]]
        (Information Gain = Current Entropy - Expected Posterior Entropy)

    In practice, we approximate this using the topological summary:
        1. Parse β0, β1, P (persistence), E (energy) from summary
        2. Estimate information content from topological complexity
        3. Weight by unexploredness (via query context)

    The scoring formula:
        score = w_topo · f(β0, β1) + w_persist · g(P) + w_energy · h(E)

    where f, g, h are sigmoid-normalized functions and w_* are weights.

    Attributes:
        weight_topology:   Weight for β0 + β1 complexity [0, 1].
        weight_persistence: Weight for total persistence [0, 1].
        weight_energy:     Weight for Gabor phase energy [0, 1].
        max_betti:         Normalization constant for Betti numbers.
        max_persistence:   Normalization constant for persistence.
    """

    def __init__(
        self,
        weight_topology: float = 0.4,
        weight_persistence: float = 0.4,
        weight_energy: float = 0.2,
        max_betti: int = 20,
        max_persistence: float = 5.0,
    ) -> None:
        # Normalize weights
        total = weight_topology + weight_persistence + weight_energy
        self._w_topo = weight_topology / total
        self._w_persist = weight_persistence / total
        self._w_energy = weight_energy / total
        self._max_betti = max(max_betti, 1)
        self._max_persist = max(max_persistence, 0.01)

    def score(
        self, query: str, title: str, summary: str,
    ) -> tuple[float, str]:
        """Score a visual node by estimated information gain.

        Args:
            query:   Semantic query (optional, for future sheaf integration).
            title:   Node label.
            summary: Betti summary string "β0=N, β1=M, P=X.XX, E=Y.YY".

        Returns:
            Tuple of (score ∈ [0,1], reasoning_text).
        """
        beta_0, beta_1, persistence, energy = self._parse_summary(summary)

        # Component scores (sigmoid-normalized)
        topo_raw = (beta_0 + beta_1) / self._max_betti
        topo_score = self._sigmoid(topo_raw)

        persist_raw = persistence / self._max_persist
        persist_score = self._sigmoid(persist_raw)

        energy_score = min(energy, 1.0)  # already in [0, 1]

        # Weighted combination
        final = (
            self._w_topo * topo_score
            + self._w_persist * persist_score
            + self._w_energy * energy_score
        )

        reasoning = (
            f"InfoGain: topo={topo_score:.2f}(β0={beta_0},β1={beta_1}) "
            f"persist={persist_score:.2f}(P={persistence:.2f}) "
            f"energy={energy_score:.2f} → {final:.3f}"
        )
        return min(final, 1.0), reasoning

    @staticmethod
    def _sigmoid(x: float, k: float = 5.0) -> float:
        """Sigmoid normalization: maps [0, ∞) → [0, 1).

        k controls steepness. Higher k → sharper transition.
        sigmoid(0) = 0.5, so we shift: 2·sigmoid(x) - 1 for [0,1] range.
        """
        return 2.0 / (1.0 + math.exp(-k * x)) - 1.0

    @staticmethod
    def _parse_summary(summary: str) -> tuple[int, int, float, float]:
        """Parse all fields from betti_summary string.

        Expected format: "β0=3, β1=1, P=0.45, E=0.72"
        Returns: (beta_0, beta_1, persistence, energy)
        """
        beta_0, beta_1 = 0, 0
        persistence, energy = 0.0, 0.0

        for part in summary.split(","):
            part = part.strip()
            try:
                if part.startswith("β0=") or part.startswith("β0="):
                    beta_0 = int(part.split("=")[1])
                elif part.startswith("β1=") or part.startswith("β1="):
                    beta_1 = int(part.split("=")[1])
                elif part.startswith("P="):
                    persistence = float(part.split("=")[1])
                elif part.startswith("E="):
                    energy = float(part.split("=")[1])
            except (ValueError, IndexError):
                continue

        return beta_0, beta_1, persistence, energy
