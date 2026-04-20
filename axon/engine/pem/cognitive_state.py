"""
AXON Engine — PEM Cognitive State Module
==========================================
§1 — State Dynamics: Riemannian Manifold with SDE Momentum.

Extends flat psychological vectors ψ ∈ ℝᵏ to states on a
Riemannian manifold M with momentum, curvature, and stochastic
perturbation.

SDE dynamics (Eq. 1 from the PEM paper):

    dψₜ = -∇U(ψₜ, Iₜ)dt + σ·dWₜ

Discrete-time approximation (Euler-Maruyama):

    ψ_{t+1} = ψ_t + α·(-∇U + momentum) + σ·ε
    momentum_{t+1} = β·momentum + (1-β)·(-∇U)

where:
    U(ψ, I)   — potential function modeling belief landscape
    ∇U        — gradient of potential (drives state evolution)
    σ         — noise amplitude (cognitive variability)
    ε ~ N(0,1) — standard Gaussian noise
    α         — step size (learning rate)
    β         — momentum decay factor

Key properties:
    - Belief rigidity: modeled as curvature κ(d) per dimension
    - Cognitive inertia: momentum β persists direction of change
    - Bounded states: each dimension clamped to valid range
    - Attractor dynamics: potential U creates stable basins

Mathematical references:
    See docs/psychological_epistemic_modeling.md §1.

"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator


# ═══════════════════════════════════════════════════════════════════
#  COGNITIVE DIMENSION — A single axis of the psychological state
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CognitiveDimension:
    """A named axis in the cognitive state space M.

    Each dimension has:
        - A valid range [lower, upper]
        - A default (resting) value
        - A curvature κ ∈ (0, ∞) modeling resistance to change
          (higher κ = more rigid beliefs)

    Predefined dimensions:
        affect:         [-1, 1]  — emotional valence (neg ↔ pos)
        cognitive_load: [0, 1]   — processing burden
        certainty:      [0, 1]   — subjective confidence
        openness:       [0, 1]   — receptivity to new information
        trust:          [0, 1]   — trust in system output
    """

    name: str
    lower: float = 0.0
    upper: float = 1.0
    default: float = 0.5
    curvature: float = 1.0    # κ — resistance to change

    def __post_init__(self) -> None:
        if self.lower >= self.upper:
            raise ValueError(
                f"Dimension '{self.name}': lower ({self.lower}) "
                f"must be < upper ({self.upper})"
            )
        if not (self.lower <= self.default <= self.upper):
            raise ValueError(
                f"Dimension '{self.name}': default ({self.default}) "
                f"must be in [{self.lower}, {self.upper}]"
            )
        if self.curvature <= 0:
            raise ValueError(
                f"Dimension '{self.name}': curvature ({self.curvature}) "
                f"must be > 0"
            )

    def clamp(self, value: float) -> float:
        """Clamp value to [lower, upper]."""
        return max(self.lower, min(self.upper, value))

    def normalize(self, value: float) -> float:
        """Normalize to [0, 1] range."""
        span = self.upper - self.lower
        return (self.clamp(value) - self.lower) / span if span > 0 else 0.5


# ═══════════════════════════════════════════════════════════════════
#  STANDARD COGNITIVE DIMENSIONS — Default k=5 state space
# ═══════════════════════════════════════════════════════════════════

AFFECT = CognitiveDimension(
    name="affect", lower=-1.0, upper=1.0, default=0.0, curvature=0.5,
)
COGNITIVE_LOAD = CognitiveDimension(
    name="cognitive_load", lower=0.0, upper=1.0, default=0.3, curvature=0.8,
)
CERTAINTY = CognitiveDimension(
    name="certainty", lower=0.0, upper=1.0, default=0.5, curvature=1.2,
)
OPENNESS = CognitiveDimension(
    name="openness", lower=0.0, upper=1.0, default=0.7, curvature=0.6,
)
TRUST = CognitiveDimension(
    name="trust", lower=0.0, upper=1.0, default=0.5, curvature=1.5,
)

STANDARD_DIMENSIONS: tuple[CognitiveDimension, ...] = (
    AFFECT, COGNITIVE_LOAD, CERTAINTY, OPENNESS, TRUST,
)


# ═══════════════════════════════════════════════════════════════════
#  INTERACTION SIGNAL — Iₜ input that drives state evolution
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class InteractionSignal:
    """I_t — exogenous signal from a user interaction.

    An interaction signal carries the external stimulus that drives
    the state evolution dψ = -∇U(ψ, I)dt.

    Each dimension receives an independent stimulus intensity:
        - Positive values push the dimension upward
        - Negative values push it downward
        - Zero means no effect on that dimension

    The surprise factor measures how unexpected the interaction is
    (high surprise = more stochastic perturbation).

    Args:
        stimuli:  Dict mapping dimension name → stimulus intensity.
        surprise: Expected surprise ∈ [0, 1]. Scales noise.
        metadata: Optional context (e.g., query text, source).
    """

    stimuli: dict[str, float]
    surprise: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (0.0 <= self.surprise <= 1.0):
            raise ValueError(
                f"Surprise must be in [0, 1], got {self.surprise}"
            )

    def stimulus_for(self, dimension_name: str) -> float:
        """Get the stimulus for a specific dimension (default 0)."""
        return self.stimuli.get(dimension_name, 0.0)


# ═══════════════════════════════════════════════════════════════════
#  COGNITIVE STATE — ψ ∈ M, position on the cognitive manifold
# ═══════════════════════════════════════════════════════════════════


class CognitiveState:
    """ψ ∈ M — state on the cognitive manifold.

    A k-dimensional vector where each dimension corresponds to a
    CognitiveDimension. The state carries both position and momentum,
    enabling the SDE dynamics from §1:

        ψ_{t+1} = ψ_t + α·(-∇U + momentum) + σ·ε

    Position: current psychological configuration
    Momentum: accumulated velocity (direction of recent change)

    The state is always clamped to valid ranges.

    Args:
        dimensions: Ordered list of CognitiveDimension specifications.
        values:     Initial values per dimension. Defaults to dimension defaults.
    """

    def __init__(
        self,
        dimensions: tuple[CognitiveDimension, ...] = STANDARD_DIMENSIONS,
        values: dict[str, float] | None = None,
    ) -> None:
        self._dimensions = dimensions
        self._dim_index: dict[str, int] = {
            d.name: i for i, d in enumerate(dimensions)
        }
        self._k = len(dimensions)

        # Position: ψ_t
        if values:
            self._values = [
                d.clamp(values.get(d.name, d.default))
                for d in dimensions
            ]
        else:
            self._values = [d.default for d in dimensions]

        # Momentum: v_t (initialized to zero)
        self._momentum = [0.0] * self._k
        self._timestamp: int = 0

    # ── Properties ────────────────────────────────────────────────

    @property
    def k(self) -> int:
        """Dimensionality of the state space."""
        return self._k

    @property
    def dimensions(self) -> tuple[CognitiveDimension, ...]:
        """The cognitive dimensions specifying this state space."""
        return self._dimensions

    @property
    def values(self) -> dict[str, float]:
        """Current state values as {dimension_name: value}."""
        return {d.name: self._values[i] for i, d in enumerate(self._dimensions)}

    @property
    def momentum(self) -> dict[str, float]:
        """Current momentum as {dimension_name: momentum}."""
        return {d.name: self._momentum[i] for i, d in enumerate(self._dimensions)}

    @property
    def timestamp(self) -> int:
        """Number of state updates applied."""
        return self._timestamp

    def value(self, dimension: str) -> float:
        """Get the current value for a dimension by name."""
        idx = self._dim_index.get(dimension)
        if idx is None:
            raise KeyError(f"Unknown dimension: {dimension}")
        return self._values[idx]

    def momentum_for(self, dimension: str) -> float:
        """Get the current momentum for a dimension."""
        idx = self._dim_index.get(dimension)
        if idx is None:
            raise KeyError(f"Unknown dimension: {dimension}")
        return self._momentum[idx]

    # ── Vector representation ─────────────────────────────────────

    def as_vector(self) -> list[float]:
        """ψ as a flat k-dimensional vector (ordered by dimension index)."""
        return list(self._values)

    def normalized_vector(self) -> list[float]:
        """ψ normalized to [0, 1] per dimension."""
        return [
            d.normalize(self._values[i])
            for i, d in enumerate(self._dimensions)
        ]

    # ── Mutation (controlled) ─────────────────────────────────────

    def _set(self, dimension: str, value: float) -> None:
        """Internal: set a dimension value (clamped)."""
        idx = self._dim_index[dimension]
        self._values[idx] = self._dimensions[idx].clamp(value)

    def _set_momentum(self, dimension: str, value: float) -> None:
        """Internal: set momentum for a dimension."""
        idx = self._dim_index[dimension]
        self._momentum[idx] = value

    def _increment_timestamp(self) -> None:
        """Internal: advance the state clock."""
        self._timestamp += 1

    # ── Copy ──────────────────────────────────────────────────────

    def copy(self) -> CognitiveState:
        """Create a deep copy of this state."""
        new = CognitiveState(self._dimensions)
        new._values = list(self._values)
        new._momentum = list(self._momentum)
        new._timestamp = self._timestamp
        return new

    # ── Metrics ───────────────────────────────────────────────────

    def distance_to(self, other: CognitiveState) -> float:
        """Weighted Euclidean distance incorporating curvature.

        d(ψ₁, ψ₂) = √(Σ κ(d) · (ψ₁(d) - ψ₂(d))²)

        Curvature-weighted distance means changes in rigid dimensions
        (high κ) contribute more to the perceived distance.
        """
        if self._k != other._k:
            raise ValueError("States have different dimensionality")
        total = 0.0
        for i, d in enumerate(self._dimensions):
            diff = self._values[i] - other._values[i]
            total += d.curvature * diff * diff
        return math.sqrt(total)

    def kinetic_energy(self) -> float:
        """½ Σ m_i · v_i² — kinetic energy of the momentum.

        Higher energy = state is changing rapidly.
        """
        return 0.5 * sum(v * v for v in self._momentum)

    def total_energy(self, attractor: CognitiveState | None = None) -> float:
        """Total energy = kinetic + potential (distance from attractor).

        If no attractor given, uses the default resting state.
        """
        ke = self.kinetic_energy()
        if attractor is None:
            # Potential = distance from default state
            pe = sum(
                d.curvature * (self._values[i] - d.default) ** 2
                for i, d in enumerate(self._dimensions)
            )
        else:
            pe = self.distance_to(attractor) ** 2
        return ke + pe

    # ── Serialization ─────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "values": self.values,
            "momentum": self.momentum,
            "timestamp": self._timestamp,
            "k": self._k,
            "kinetic_energy": round(self.kinetic_energy(), 6),
        }

    def __repr__(self) -> str:
        vals = ", ".join(
            f"{d.name}={self._values[i]:.3f}"
            for i, d in enumerate(self._dimensions)
        )
        return f"CognitiveState(t={self._timestamp}, {vals})"


# ═══════════════════════════════════════════════════════════════════
#  COGNITIVE MANIFOLD — M with metric tensor, potential, and SDE
# ═══════════════════════════════════════════════════════════════════


class CognitiveManifold:
    """M — Riemannian manifold for psychological state evolution.

    Implements the SDE dynamics from Eq. 1 (PEM paper §1):

        dψₜ = -∇U(ψₜ, Iₜ)dt + σ·dWₜ

    Discretized via Euler-Maruyama with momentum:

        gradient_t    = -κ(d) · (ψ(d) - attractor(d)) + stimulus(d)
        momentum_{t+1} = β · momentum_t + (1 - β) · gradient_t
        ψ_{t+1}(d)    = ψ_t(d) + α · momentum_{t+1} + σ · surprise · ε

    The curvature κ(d) acts as a dimension-specific "resistance"
    to change, creating the Riemannian metric structure:

        g_{ij} = κ(i) · δ_{ij}    (diagonal metric tensor)

    The potential U creates attractor basins (resting states) that
    model belief rigidity — the user's cognitive system naturally
    returns to stable configurations unless actively driven away.

    Args:
        step_size:      α — controls how fast the state moves.
                        Default: 0.1
        momentum_decay: β — how fast momentum decays.
                        Default: 0.7 (strong inertia)
        noise_level:    σ — base noise amplitude.
                        Default: 0.02
        attractor:      The resting-state attractor. Default: dimension defaults.

    Formal properties:
        - Bounded: ψ(d) ∈ [lower(d), upper(d)] for all d, all t
        - Continuous: small inputs → small state changes (Lipschitz)
        - Convergent: without input, ψ → attractor (Lyapunov stable)
        - Stochastic: noise σ ≠ 0 prevents deterministic lock-in
    """

    def __init__(
        self,
        step_size: float = 0.1,
        momentum_decay: float = 0.7,
        noise_level: float = 0.02,
        attractor: dict[str, float] | None = None,
    ) -> None:
        if not (0.0 < step_size <= 1.0):
            raise ValueError(f"Step size α must be in (0, 1], got {step_size}")
        if not (0.0 <= momentum_decay < 1.0):
            raise ValueError(
                f"Momentum decay β must be in [0, 1), got {momentum_decay}"
            )
        if noise_level < 0:
            raise ValueError(
                f"Noise level σ must be ≥ 0, got {noise_level}"
            )

        self.step_size = step_size
        self.momentum_decay = momentum_decay
        self.noise_level = noise_level
        self._attractor = attractor or {}

    def evolve(
        self,
        state: CognitiveState,
        signal: InteractionSignal,
    ) -> CognitiveState:
        """Apply one step of the SDE dynamics: ψ_t → ψ_{t+1}.

        Implements Euler-Maruyama discretization of Eq. 1:

            1. Compute ∇U for each dimension (potential gradient)
            2. Add interaction stimulus from signal
            3. Update momentum with decay β
            4. Update position: ψ + α·momentum + σ·noise
            5. Clamp to valid ranges

        Args:
            state:  Current state ψ_t.
            signal: Interaction signal I_t.

        Returns:
            New state ψ_{t+1} (state is modified in place and returned).
        """
        for i, dim in enumerate(state.dimensions):
            # ── 1. Potential gradient: ∇U = κ(d) · (ψ(d) - attractor(d))
            attractor_val = self._attractor.get(dim.name, dim.default)
            potential_grad = dim.curvature * (state._values[i] - attractor_val)

            # ── 2. Stimulus from interaction signal
            stimulus = signal.stimulus_for(dim.name)

            # ── 3. Combined gradient (negative potential + stimulus)
            gradient = -potential_grad + stimulus

            # ── 4. Momentum update: v_{t+1} = β·v_t + (1-β)·gradient
            old_momentum = state._momentum[i]
            new_momentum = (
                self.momentum_decay * old_momentum
                + (1 - self.momentum_decay) * gradient
            )
            state._momentum[i] = new_momentum

            # ── 5. Position update with noise: ψ + α·v + σ·surprise·ε
            noise = 0.0
            if self.noise_level > 0:
                effective_noise = self.noise_level * (1.0 + signal.surprise)
                noise = effective_noise * random.gauss(0, 1)

            new_value = state._values[i] + self.step_size * new_momentum + noise

            # ── 6. Clamp to valid range
            state._values[i] = dim.clamp(new_value)

        state._increment_timestamp()
        return state

    def evolve_sequence(
        self,
        state: CognitiveState,
        signals: list[InteractionSignal],
    ) -> list[CognitiveState]:
        """Apply a sequence of signals, returning trajectory.

        Returns a list of state snapshots after each evolution step.
        """
        trajectory = []
        for signal in signals:
            self.evolve(state, signal)
            trajectory.append(state.copy())
        return trajectory

    def equilibrium_distance(self, state: CognitiveState) -> float:
        """Distance from the nearest attractor basin.

        d_eq = √(Σ κ(d) · (ψ(d) - attractor(d))²)

        Low distance = state is near resting equilibrium.
        High distance = state is far from attractor (unstable).
        """
        total = 0.0
        for i, dim in enumerate(state.dimensions):
            attractor_val = self._attractor.get(dim.name, dim.default)
            diff = state._values[i] - attractor_val
            total += dim.curvature * diff * diff
        return math.sqrt(total)


# ═══════════════════════════════════════════════════════════════════
#  STATE TRAJECTORY — History of ψ evolution
# ═══════════════════════════════════════════════════════════════════


class StateTrajectory:
    """Records the trajectory of ψ through M over time.

    Captures snapshots of the cognitive state at each timestep,
    enabling analysis of:
        - Convergence to attractors
        - Oscillation detection
        - Energy dissipation over time
        - Phase transitions (rapid state changes)

    Args:
        max_length: Maximum number of snapshots to retain.
                    Default: 500.
    """

    def __init__(self, max_length: int = 500) -> None:
        if max_length < 1:
            raise ValueError(f"max_length must be ≥ 1, got {max_length}")
        self._max_length = max_length
        self._snapshots: list[CognitiveState] = []

    @property
    def length(self) -> int:
        """Number of recorded snapshots."""
        return len(self._snapshots)

    @property
    def is_empty(self) -> bool:
        """Whether the trajectory contains no snapshots."""
        return len(self._snapshots) == 0

    def record(self, state: CognitiveState) -> None:
        """Append a state snapshot (copy) to the trajectory."""
        self._snapshots.append(state.copy())
        if len(self._snapshots) > self._max_length:
            self._snapshots.pop(0)

    def latest(self) -> CognitiveState | None:
        """Return the most recent state snapshot."""
        return self._snapshots[-1] if self._snapshots else None

    def iter_snapshots(self) -> Iterator[CognitiveState]:
        """Iterate over all recorded snapshots in order."""
        yield from self._snapshots

    def energy_series(
        self,
        attractor: CognitiveState | None = None,
    ) -> list[float]:
        """Compute total energy at each timestep.

        For convergence analysis: energy should decrease monotonically
        without external input (Lyapunov stability).
        """
        return [s.total_energy(attractor) for s in self._snapshots]

    def dimension_series(self, dimension: str) -> list[float]:
        """Extract the time series for a single dimension.

        Useful for visualizing how a specific cognitive dimension
        evolved over time.
        """
        return [s.value(dimension) for s in self._snapshots]

    def detect_phase_transition(
        self,
        threshold: float = 0.3,
    ) -> list[int]:
        """Detect phase transitions — timesteps with large state jumps.

        A phase transition occurs at timestep t if:
            d(ψ_t, ψ_{t-1}) > threshold

        Returns:
            List of timestep indices where transitions occurred.
        """
        transitions: list[int] = []
        for i in range(1, len(self._snapshots)):
            dist = self._snapshots[i].distance_to(self._snapshots[i - 1])
            if dist > threshold:
                transitions.append(i)
        return transitions

    def has_converged(
        self,
        window: int = 10,
        epsilon: float = 0.01,
    ) -> bool:
        """Check if the state has converged (stable for `window` steps).

        Convergence criterion:
            ∀ i ∈ [n-window, n] : d(ψ_i, ψ_{i-1}) < ε

        Args:
            window:  Number of consecutive steps to check.
            epsilon: Maximum allowed change per step.

        Returns:
            True if state has been stable for `window` steps.
        """
        if len(self._snapshots) < window + 1:
            return False

        for i in range(len(self._snapshots) - window, len(self._snapshots)):
            dist = self._snapshots[i].distance_to(self._snapshots[i - 1])
            if dist >= epsilon:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "length": self.length,
            "max_length": self._max_length,
            "snapshots": [s.to_dict() for s in self._snapshots],
        }
