"""
AXON Engine — PEM Active Inference Module
============================================
§3 — Navigation: From Passive Policy to Active Inference.

Transforms the MDN navigator from a passive scorer to a proactive
agent that minimizes Expected Free Energy (G), unifying epistemic
and psychological objectives.

Core equation (Eq. 3 from the PEM paper):

                    T
    π* = arg min   Σ   G(π, τ)
           π      τ=t

Decomposition:

    G(π, τ) = Epistemic_value(π, τ) + Pragmatic_value(π, τ)

    Epistemic:   expected information gain (reduce uncertainty)
    Pragmatic:   expected allostatic safety (maintain safe zone)

Based on Karl Friston's Free Energy Principle, adapted for
cognitive-epistemic navigation over document corpora.

Key properties:
    - Proactive: actively selects evidence presentation order
    - Unified: single objective combines truth-seeking and safety
    - Anticipatory: considers future psychological impact
    - Non-myopic: scores entire trajectories, not just next steps

Mathematical references:
    - Friston (2010), "The Free-Energy Principle: A Unified Brain Theory?"
    - See docs/psychological_epistemic_modeling.md §3

"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from axon.engine.pem.cognitive_state import (
    CognitiveState,
    CognitiveManifold,
    InteractionSignal,
)
from axon.engine.pem.density_matrix import (
    DensityMatrix,
    _mat_mul,
    _trace,
)


# ═══════════════════════════════════════════════════════════════════
#  ALLOSTATIC ZONE — Defines the "safe" cognitive region
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class AllostaticBound:
    """Defines the safe range for a cognitive dimension.

    Allostasis: the process of achieving stability through change.
    An allostatic zone defines the region of cognitive state space
    where the user can function effectively without distress.

    Outside the zone, the pragmatic cost increases quadratically,
    incentivizing the system to guide the user back.

    Args:
        dimension: Name of the cognitive dimension.
        lower:     Lower bound of the safe zone.
        upper:     Upper bound of the safe zone.
        weight:    Importance of this dimension in pragmatic cost.
    """

    dimension: str
    lower: float
    upper: float
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.lower >= self.upper:
            raise ValueError(
                f"AllostaticBound '{self.dimension}': "
                f"lower ({self.lower}) must be < upper ({self.upper})"
            )
        if self.weight <= 0:
            raise ValueError(
                f"AllostaticBound '{self.dimension}': "
                f"weight ({self.weight}) must be > 0"
            )

    def violation(self, value: float) -> float:
        """Compute how far `value` falls outside the safe zone.

        Returns:
            0.0 if within zone, positive distance² if outside.
        """
        if value < self.lower:
            return self.weight * (self.lower - value) ** 2
        if value > self.upper:
            return self.weight * (value - self.upper) ** 2
        return 0.0


class AllostaticZone:
    """Defines the complete safe region in cognitive state space.

    The allostatic zone is the Cartesian product of per-dimension
    safe ranges. When the cognitive state leaves this zone, the
    pragmatic cost component of free energy increases, incentivizing
    the system to choose evidence that guides the user back.

    Default safe zones (for k=5 standard dimensions):
        affect:         [-0.6, 0.8]  — avoid extreme negativity
        cognitive_load: [0.0, 0.7]   — avoid cognitive overload
        certainty:      [0.2, 1.0]   — avoid crippling doubt
        openness:       [0.3, 1.0]   — maintain some receptivity
        trust:          [0.2, 1.0]   — avoid complete mistrust

    Args:
        bounds: List of AllostaticBound specifications.
    """

    DEFAULT_BOUNDS = [
        AllostaticBound("affect", -0.6, 0.8, weight=1.5),
        AllostaticBound("cognitive_load", 0.0, 0.7, weight=2.0),
        AllostaticBound("certainty", 0.2, 1.0, weight=1.0),
        AllostaticBound("openness", 0.3, 1.0, weight=0.8),
        AllostaticBound("trust", 0.2, 1.0, weight=1.2),
    ]

    def __init__(
        self,
        bounds: list[AllostaticBound] | None = None,
    ) -> None:
        bounds_list = bounds or self.DEFAULT_BOUNDS
        self._bounds = {b.dimension: b for b in bounds_list}

    def total_violation(self, state: CognitiveState) -> float:
        """Compute total allostatic violation cost.

        V(ψ) = Σ_d weight(d) · max(0, dist_to_zone(ψ(d)))²

        Returns:
            0.0 if state is within the safe zone.
            Positive value proportional to the violation severity.
        """
        total = 0.0
        for dim_name, value in state.values.items():
            bound = self._bounds.get(dim_name)
            if bound:
                total += bound.violation(value)
        return total

    def is_safe(self, state: CognitiveState) -> bool:
        """Check if the state is within the allostatic zone."""
        return self.total_violation(state) < 1e-10

    def most_violated_dimension(
        self, state: CognitiveState,
    ) -> str | None:
        """Return the dimension with the largest violation."""
        max_violation = 0.0
        max_dim: str | None = None
        for dim_name, value in state.values.items():
            bound = self._bounds.get(dim_name)
            if bound:
                v = bound.violation(value)
                if v > max_violation:
                    max_violation = v
                    max_dim = dim_name
        return max_dim


# ═══════════════════════════════════════════════════════════════════
#  FREE ENERGY COMPONENTS — Epistemic and Pragmatic values
# ═══════════════════════════════════════════════════════════════════


class EpistemicValue:
    """Computes the epistemic component of free energy.

    The epistemic value measures expected information gain from
    traversing a particular evidence path. Higher information gain
    means greater reduction in uncertainty.

    Computed as the expected decrease in Von Neumann entropy:

        E_π = S(ρ) - E[S(ρ' | π)]

    where S is Von Neumann entropy and ρ' is the projected state
    after assimilating evidence along path π.

    High epistemic value → path is informative
    Low epistemic value  → path is redundant
    """

    def compute(
        self,
        density: DensityMatrix,
        projector: list[list[float]],
    ) -> float:
        """Compute epistemic value of one evidence projection.

        E = S(ρ) - S(Π·ρ·Π / Tr(Π·ρ·Π))

        Args:
            density:   Current density matrix ρ.
            projector: Evidence projector Π.

        Returns:
            Expected entropy reduction (positive = informative).
        """
        current_entropy = density.von_neumann_entropy()

        # Compute projected state
        born_prob = density.born_probability(projector)
        if born_prob < 1e-12:
            return 0.0  # Impossible evidence contributes nothing

        try:
            projected = density.project(projector)
            projected_entropy = projected.von_neumann_entropy()
        except ValueError:
            return 0.0

        # Information gain = entropy reduction, weighted by probability
        return born_prob * (current_entropy - projected_entropy)

    def compute_trajectory(
        self,
        density: DensityMatrix,
        projectors: list[list[list[float]]],
    ) -> float:
        """Compute total epistemic value over a trajectory.

        E_total = Σ_τ E(ρ_τ, Π_τ)

        The density matrix is updated after each projection,
        capturing the sequential nature of evidence presentation.
        """
        total = 0.0
        current = density

        for proj in projectors:
            value = self.compute(current, proj)
            total += value

            # Update density for next step
            born_prob = current.born_probability(proj)
            if born_prob > 1e-12:
                try:
                    current = current.project(proj)
                except ValueError:
                    break

        return total


class PragmaticValue:
    """Computes the pragmatic component of free energy.

    The pragmatic value measures the expected psychological safety
    of traversing a particular path. It penalizes evidence that
    would push the cognitive state outside the allostatic zone.

    Computed as the negative expected allostatic violation:

        P_π = -E[V(ψ' | π)]

    where V is the allostatic violation cost and ψ' is the
    anticipated cognitive state after the interaction.

    High pragmatic value → path maintains psychological safety
    Low pragmatic value  → path may cause cognitive distress
    """

    def __init__(
        self,
        allostatic_zone: AllostaticZone | None = None,
        manifold: CognitiveManifold | None = None,
    ) -> None:
        self.zone = allostatic_zone or AllostaticZone()
        self.manifold = manifold or CognitiveManifold()

    def compute(
        self,
        state: CognitiveState,
        anticipated_signal: InteractionSignal,
    ) -> float:
        """Compute pragmatic value of one interaction step.

        P = -V(ψ') where ψ' = evolve(ψ, signal)

        We simulate one step of manifold evolution to anticipate
        the resulting cognitive state, then compute its violation cost.

        Args:
            state:              Current cognitive state ψ.
            anticipated_signal: Expected signal from this evidence.

        Returns:
            Negative violation cost (higher = safer, max = 0).
        """
        # Simulate: ψ' = evolve(ψ_copy, signal)
        anticipated_state = state.copy()
        self.manifold.evolve(anticipated_state, anticipated_signal)

        # Pragmatic value = -(violation cost)
        violation = self.zone.total_violation(anticipated_state)
        return -violation

    def compute_trajectory(
        self,
        state: CognitiveState,
        signals: list[InteractionSignal],
    ) -> float:
        """Compute total pragmatic value over a trajectory.

        P_total = -Σ_τ V(ψ_τ)
        """
        total = 0.0
        sim_state = state.copy()

        for signal in signals:
            self.manifold.evolve(sim_state, signal)
            total -= self.zone.total_violation(sim_state)

        return total


# ═══════════════════════════════════════════════════════════════════
#  FREE ENERGY MINIMIZER — The Active Inference Agent
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TrajectoryScore:
    """Score for a candidate navigation trajectory.

    Fields:
        trajectory_id:   Identifier for the candidate path.
        free_energy:     G = -(epistemic + pragmatic). Lower is better.
        epistemic_value: Information gain component.
        pragmatic_value: Psychological safety component.
        composite_score: Negative free energy (higher = better).
    """

    trajectory_id: str
    epistemic_value: float
    pragmatic_value: float

    @property
    def free_energy(self) -> float:
        """G = -(E + P). The quantity to minimize."""
        return -(self.epistemic_value + self.pragmatic_value)

    @property
    def composite_score(self) -> float:
        """Score = -G = E + P. The quantity to maximize."""
        return self.epistemic_value + self.pragmatic_value

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "trajectory_id": self.trajectory_id,
            "epistemic_value": round(self.epistemic_value, 6),
            "pragmatic_value": round(self.pragmatic_value, 6),
            "free_energy": round(self.free_energy, 6),
            "composite_score": round(self.composite_score, 6),
        }


class FreeEnergyMinimizer:
    """Active inference engine — proactive navigation agent.

    Implements §3 of the PEM paper:

                        T
        π* = arg min   Σ   G(π, τ)
               π      τ=t

        G = -(Epistemic_value + Pragmatic_value)

    The minimizer scores candidate navigation trajectories by
    how well they balance two objectives:

        1. Epistemic: maximize information gain (reduce uncertainty)
        2. Pragmatic: maintain psychological safety (allostatic zone)

    The balance between these objectives is controlled by the
    epistemic_weight parameter:
        α → 1: prioritize truth discovery
        α → 0: prioritize psychological safety

    Args:
        epistemic_weight: α ∈ [0, 1] — balance between objectives.
                          Default: 0.6 (slightly favor truth).
        allostatic_zone:  Safety zone specification.
        manifold:         Cognitive manifold for state simulation.
    """

    def __init__(
        self,
        epistemic_weight: float = 0.6,
        allostatic_zone: AllostaticZone | None = None,
        manifold: CognitiveManifold | None = None,
    ) -> None:
        if not (0.0 <= epistemic_weight <= 1.0):
            raise ValueError(
                f"Epistemic weight must be in [0, 1], got {epistemic_weight}"
            )
        self.epistemic_weight = epistemic_weight
        self.pragmatic_weight = 1.0 - epistemic_weight
        self._epistemic = EpistemicValue()
        self._pragmatic = PragmaticValue(allostatic_zone, manifold)

    def score_trajectory(
        self,
        trajectory_id: str,
        density: DensityMatrix,
        state: CognitiveState,
        projectors: list[list[list[float]]],
        signals: list[InteractionSignal],
    ) -> TrajectoryScore:
        """Score a candidate navigation trajectory by expected free energy.

        Computes:
            E = epistemic_weight · E_trajectory
            P = pragmatic_weight · P_trajectory
            G = -(E + P)

        Lower G = better trajectory.

        Args:
            trajectory_id: Identifier for this candidate.
            density:       Current density matrix ρ.
            state:         Current cognitive state ψ.
            projectors:    Evidence projectors [Π₁, Π₂, ...] along the path.
            signals:       Anticipated interaction signals along the path.

        Returns:
            TrajectoryScore with epistemic, pragmatic, and free energy values.
        """
        e_value = self._epistemic.compute_trajectory(density, projectors)
        p_value = self._pragmatic.compute_trajectory(state, signals)

        return TrajectoryScore(
            trajectory_id=trajectory_id,
            epistemic_value=self.epistemic_weight * e_value,
            pragmatic_value=self.pragmatic_weight * p_value,
        )

    def rank_trajectories(
        self,
        scores: list[TrajectoryScore],
    ) -> list[TrajectoryScore]:
        """Rank trajectories by composite score (highest first).

        The optimal trajectory is:
            π* = arg max composite_score = arg min free_energy
        """
        return sorted(scores, key=lambda s: s.composite_score, reverse=True)

    def select_optimal(
        self,
        scores: list[TrajectoryScore],
    ) -> TrajectoryScore | None:
        """Select the trajectory with highest composite score.

        Returns:
            The optimal trajectory, or None if no candidates.
        """
        if not scores:
            return None
        return max(scores, key=lambda s: s.composite_score)

    def is_trajectory_safe(
        self,
        state: CognitiveState,
        signals: list[InteractionSignal],
    ) -> bool:
        """Quick check: will this trajectory keep the user safe?

        Returns True if the pragmatic value is non-negative
        (i.e., no allostatic violations anticipated).
        """
        p_value = self._pragmatic.compute_trajectory(state, signals)
        return p_value >= -1e-10

    def to_dict(self) -> dict[str, Any]:
        """Serialize configuration to dictionary."""
        return {
            "epistemic_weight": self.epistemic_weight,
            "pragmatic_weight": self.pragmatic_weight,
        }
