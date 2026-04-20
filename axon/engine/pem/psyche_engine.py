"""
AXON Engine — PEM Psyche Engine (Integration Layer)
=====================================================
Orchestrates all four pillars of Psychological-Epistemic Modeling
into a unified processing pipeline.

Architecture:

    User Input → PsycheEngine.process() → Modulated Query + Score
                       ↕
                 CognitiveState evolves      (§1 — Manifold SDE)
                 DensityMatrix updates       (§2 — Quantum Projection)
                 Navigation bias computed    (§3 — Active Inference)
                 Safety constraints enforced (§4 — Dependent Types)

The PsycheEngine is the runtime implementation of the `psyche` primitive.
It operates as a middleware between user interaction and the MDN navigator,
modulating the navigation process based on the user's inferred
psychological-epistemic state.

Lifecycle:
    1. Initialize with a psyche profile (dimensions, safety, quantum config)
    2. For each interaction:
       a. Receive interaction signal → evolve cognitive state (§1)
       b. Convert state to density matrix → project evidence (§2)
       c. Score candidate paths by free energy (§3)
       d. Validate outputs against safety constraints (§4)
    3. Return modulated result with full PEM metadata

Mathematical references:
    See docs/psychological_epistemic_modeling.md §1-§4.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from axon.engine.pem.cognitive_state import (
    CognitiveDimension,
    CognitiveManifold,
    CognitiveState,
    InteractionSignal,
    StateTrajectory,
    STANDARD_DIMENSIONS,
)
from axon.engine.pem.density_matrix import (
    DensityMatrix,
    EvidenceProjector,
    cognitive_state_to_density,
)
from axon.engine.pem.active_inference import (
    AllostaticBound,
    AllostaticZone,
    FreeEnergyMinimizer,
    TrajectoryScore,
)
from axon.engine.pem.safety_types import (
    SafetyConstraint,
    SafetyRegistry,
    SafetyViolation,
    ViolationSeverity,
    therapeutic_registry,
    research_registry,
    sales_registry,
    NON_DIAGNOSTIC,
    NON_PRESCRIPTIVE,
    NON_MANIPULATIVE,
)


# ═══════════════════════════════════════════════════════════════════
#  PSYCHE PROFILE — Configuration for a psyche primitive instance
# ═══════════════════════════════════════════════════════════════════


@dataclass
class PsycheProfile:
    """Configuration for a `psyche` primitive instance.

    Defines the complete cognitive-epistemic modeling parameters:
        - Which dimensions to track
        - How the manifold evolves
        - What safety constraints apply
        - Whether quantum mode is enabled
        - Active inference parameters

    This corresponds to the compile-time configuration of a
    `psyche` block in the AXON language:

        psyche TherapeuticProfile {
            dimensions: [affect, cognitive_load, certainty, openness, trust]
            manifold: { curvature: { ... }, noise: 0.05, momentum: 0.7 }
            safety: [non_diagnostic, non_prescriptive]
            quantum: enabled
            inference: active
        }
    """

    name: str
    dimensions: tuple[CognitiveDimension, ...] = STANDARD_DIMENSIONS
    step_size: float = 0.1
    momentum_decay: float = 0.7
    noise_level: float = 0.02
    quantum_enabled: bool = True
    active_inference: bool = True
    epistemic_weight: float = 0.6
    safety_constraints: list[str] = field(default_factory=list)
    attractor: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "dimensions": [d.name for d in self.dimensions],
            "step_size": self.step_size,
            "momentum_decay": self.momentum_decay,
            "noise_level": self.noise_level,
            "quantum_enabled": self.quantum_enabled,
            "active_inference": self.active_inference,
            "epistemic_weight": self.epistemic_weight,
            "safety_constraints": self.safety_constraints,
        }


# ═══════════════════════════════════════════════════════════════════
#  PSYCHE RESULT — Output from one PEM processing step
# ═══════════════════════════════════════════════════════════════════


@dataclass
class PsycheResult:
    """Result of a PsycheEngine processing step.

    Contains the full PEM metadata alongside the modulated output:
        - The evolved cognitive state
        - Density matrix information
        - Safety check results
        - Trajectory scores (if active inference enabled)

    This is the runtime return type that carries the NonDiagnostic
    proof (or violations if unsafe).
    """

    state: CognitiveState
    density_info: dict[str, Any]
    is_safe: bool
    violations: list[SafetyViolation]
    trajectory_scores: list[TrajectoryScore] | None = None
    output_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "state": self.state.to_dict(),
            "density_info": self.density_info,
            "is_safe": self.is_safe,
            "violations": [v.to_dict() for v in self.violations],
            "trajectory_scores": (
                [t.to_dict() for t in self.trajectory_scores]
                if self.trajectory_scores else None
            ),
            "output_text": self.output_text,
            "metadata": self.metadata,
        }


# ═══════════════════════════════════════════════════════════════════
#  PSYCHE ENGINE — The unified PEM processing pipeline
# ═══════════════════════════════════════════════════════════════════


class PsycheEngine:
    """Complete PEM engine — runtime for the `psyche` primitive.

    Orchestrates the four pillars:
        1. CognitiveManifold — state evolution (§1)
        2. DensityMatrix     — quantum probability (§2)
        3. FreeEnergyMinimizer — active navigation (§3)
        4. SafetyRegistry    — type-safe output (§4)

    The engine maintains persistent state across interactions,
    tracking the cognitive trajectory and evolving the density
    matrix as evidence is presented.

    Usage:
        >>> profile = PsycheProfile("therapy", safety_constraints=["non_diagnostic"])
        >>> engine = PsycheEngine(profile)
        >>> signal = InteractionSignal({"affect": -0.3, "certainty": 0.2})
        >>> result = engine.process_signal(signal)
        >>> print(result.state)
        >>> print(result.is_safe)

    Args:
        profile: PsycheProfile configuration.
    """

    def __init__(self, profile: PsycheProfile) -> None:
        self._profile = profile

        # §1 — Cognitive Manifold
        self._state = CognitiveState(profile.dimensions)
        self._manifold = CognitiveManifold(
            step_size=profile.step_size,
            momentum_decay=profile.momentum_decay,
            noise_level=profile.noise_level,
            attractor=profile.attractor if profile.attractor else None,
        )
        self._trajectory = StateTrajectory()

        # §2 — Density Matrix (quantum mode)
        self._density: DensityMatrix | None = None
        self._projector = EvidenceProjector(k=len(profile.dimensions))
        if profile.quantum_enabled:
            self._density = DensityMatrix.maximally_mixed(
                len(profile.dimensions)
            )

        # §3 — Active Inference
        self._minimizer: FreeEnergyMinimizer | None = None
        if profile.active_inference:
            self._minimizer = FreeEnergyMinimizer(
                epistemic_weight=profile.epistemic_weight,
                manifold=self._manifold,
            )

        # §4 — Safety
        self._safety = self._build_safety_registry(
            profile.safety_constraints
        )

        # Statistics
        self._interaction_count: int = 0

    # ── Properties ────────────────────────────────────────────────

    @property
    def profile(self) -> PsycheProfile:
        """The psyche profile configuration."""
        return self._profile

    @property
    def state(self) -> CognitiveState:
        """Current cognitive state ψ."""
        return self._state

    @property
    def density(self) -> DensityMatrix | None:
        """Current density matrix ρ (None if quantum disabled)."""
        return self._density

    @property
    def trajectory(self) -> StateTrajectory:
        """The full state trajectory."""
        return self._trajectory

    @property
    def interaction_count(self) -> int:
        """Number of interactions processed."""
        return self._interaction_count

    @property
    def is_quantum_enabled(self) -> bool:
        """Whether quantum cognitive probability is active."""
        return self._density is not None

    @property
    def is_active_inference(self) -> bool:
        """Whether active inference is enabled."""
        return self._minimizer is not None

    @property
    def safety_constraints(self) -> list[str]:
        """Names of active safety constraints."""
        return self._safety.constraint_names

    # ── Core Processing Pipeline ──────────────────────────────────

    def process_signal(
        self,
        signal: InteractionSignal,
    ) -> PsycheResult:
        """Process one interaction signal through the full PEM pipeline.

        Pipeline:
            1. Evolve cognitive state: ψ_{t+1} = SDE(ψ_t, I_t)    (§1)
            2. Update density matrix: ρ' = project(ρ, I_t)         (§2)
            3. Record trajectory snapshot
            4. Return result with PEM metadata

        Args:
            signal: The interaction signal I_t.

        Returns:
            PsycheResult with evolved state and metadata.
        """
        # §1 — Evolve state on manifold
        self._manifold.evolve(self._state, signal)

        # §2 — Update density matrix (if quantum enabled)
        density_info: dict[str, Any] = {}
        if self._density is not None:
            # Convert evolved state to density matrix
            state_vector = self._state.normalized_vector()
            if any(v != 0 for v in state_vector):
                self._density = cognitive_state_to_density(state_vector)
            density_info = self._density.to_dict()

        # Record trajectory
        self._trajectory.record(self._state)
        self._interaction_count += 1

        return PsycheResult(
            state=self._state.copy(),
            density_info=density_info,
            is_safe=True,
            violations=[],
            metadata={
                "interaction_count": self._interaction_count,
                "kinetic_energy": self._state.kinetic_energy(),
                "equilibrium_distance": self._manifold.equilibrium_distance(
                    self._state
                ),
            },
        )

    def check_output_safety(
        self,
        output_text: str,
    ) -> PsycheResult:
        """Check an output text against all safety constraints.

        This implements the runtime layer of §4 (Dependent Types).
        The compile-time layer prevents the generation of diagnostic
        types; this layer catches anything that slips through.

        Args:
            output_text: The text to validate.

        Returns:
            PsycheResult with safety information.
        """
        violations = self._safety.check_all(output_text)
        is_safe = len(violations) == 0

        sanitized_text = output_text
        if not is_safe:
            sanitized_text, _ = self._safety.sanitize(output_text)

        return PsycheResult(
            state=self._state.copy(),
            density_info=self._density.to_dict() if self._density else {},
            is_safe=is_safe,
            violations=violations,
            output_text=sanitized_text,
            metadata={"original_blocked": not is_safe},
        )

    def score_trajectories(
        self,
        candidates: list[dict[str, Any]],
    ) -> list[TrajectoryScore]:
        """Score candidate navigation trajectories by free energy.

        Uses §3 Active Inference to rank paths that balance
        information gain (epistemic) with safety (pragmatic).

        Args:
            candidates: List of dicts with:
                - "id": trajectory identifier
                - "projectors": list of evidence projectors
                - "signals": list of anticipated interaction signals

        Returns:
            Ranked list of TrajectoryScore (best first).
        """
        if self._minimizer is None or self._density is None:
            return []

        scores: list[TrajectoryScore] = []
        for candidate in candidates:
            score = self._minimizer.score_trajectory(
                trajectory_id=candidate["id"],
                density=self._density,
                state=self._state,
                projectors=candidate.get("projectors", []),
                signals=candidate.get("signals", []),
            )
            scores.append(score)

        return self._minimizer.rank_trajectories(scores)

    def process_and_validate(
        self,
        signal: InteractionSignal,
        output_text: str,
    ) -> PsycheResult:
        """Full pipeline: process signal + validate output.

        Combines signal processing (§1-§3) with safety validation (§4)
        in a single call.

        Args:
            signal:      The interaction signal I_t.
            output_text: The generated output to validate.

        Returns:
            PsycheResult with full PEM metadata and safety status.
        """
        # Process signal (§1, §2)
        signal_result = self.process_signal(signal)

        # Check safety (§4)
        safety_result = self.check_output_safety(output_text)

        return PsycheResult(
            state=signal_result.state,
            density_info=signal_result.density_info,
            is_safe=safety_result.is_safe,
            violations=safety_result.violations,
            output_text=safety_result.output_text,
            metadata={
                **signal_result.metadata,
                "original_blocked": not safety_result.is_safe,
            },
        )

    # ── Analysis ──────────────────────────────────────────────────

    def has_converged(
        self,
        window: int = 10,
        epsilon: float = 0.01,
    ) -> bool:
        """Check if the cognitive state has converged."""
        return self._trajectory.has_converged(window, epsilon)

    def phase_transitions(
        self,
        threshold: float = 0.3,
    ) -> list[int]:
        """Detect phase transitions in the cognitive trajectory."""
        return self._trajectory.detect_phase_transition(threshold)

    def current_entropy(self) -> float:
        """Current Von Neumann entropy of the density matrix.

        Low entropy = high certainty about cognitive state.
        High entropy = high uncertainty (mixed state).
        """
        if self._density is None:
            return 0.0
        return self._density.von_neumann_entropy()

    def current_coherence(self) -> float:
        """Current off-diagonal coherence of the density matrix.

        Positive coherence = quantum-like interference between
        cognitive dimensions.
        """
        if self._density is None:
            return 0.0
        return self._density.coherence()

    # ── Reset ─────────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset engine to initial state."""
        self._state = CognitiveState(self._profile.dimensions)
        self._trajectory = StateTrajectory()
        self._interaction_count = 0
        if self._profile.quantum_enabled:
            self._density = DensityMatrix.maximally_mixed(
                len(self._profile.dimensions)
            )

    # ── Serialization ─────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize engine state to dictionary."""
        return {
            "profile": self._profile.to_dict(),
            "state": self._state.to_dict(),
            "density": self._density.to_dict() if self._density else None,
            "interaction_count": self._interaction_count,
            "has_converged": self.has_converged(),
            "safety_constraints": self._safety.to_dict(),
        }

    # ── Internal ──────────────────────────────────────────────────

    @staticmethod
    def _build_safety_registry(
        constraint_names: list[str],
    ) -> SafetyRegistry:
        """Build a SafetyRegistry from constraint name strings.

        Maps predefined constraint names to their implementations.
        Unknown names are silently ignored (compile-time validation
        should catch them first).
        """
        name_map: dict[str, SafetyConstraint] = {
            "non_diagnostic": NON_DIAGNOSTIC,
            "non_prescriptive": NON_PRESCRIPTIVE,
            "non_manipulative": NON_MANIPULATIVE,
        }

        constraints = []
        for name in constraint_names:
            constraint = name_map.get(name)
            if constraint:
                constraints.append(constraint)

        return SafetyRegistry(constraints)

    def __repr__(self) -> str:
        return (
            f"PsycheEngine(profile='{self._profile.name}', "
            f"k={self._state.k}, "
            f"quantum={'on' if self.is_quantum_enabled else 'off'}, "
            f"active_inference={'on' if self.is_active_inference else 'off'}, "
            f"interactions={self._interaction_count})"
        )


# ═══════════════════════════════════════════════════════════════════
#  CONVENIENCE FACTORIES — Predefined engine configurations
# ═══════════════════════════════════════════════════════════════════


def create_therapeutic_engine(
    name: str = "TherapeuticPsyche",
) -> PsycheEngine:
    """Create a PsycheEngine configured for therapeutic context.

    Safety: non_diagnostic + non_prescriptive + non_manipulative
    Quantum: enabled
    Active inference: enabled (epistemic_weight=0.4, favor safety)
    High curvature on certainty and trust (resistant to rapid change)
    """
    return PsycheEngine(PsycheProfile(
        name=name,
        quantum_enabled=True,
        active_inference=True,
        epistemic_weight=0.4,     # favor psychological safety
        noise_level=0.01,         # low noise (stable sessions)
        momentum_decay=0.8,       # high inertia (gradual change)
        safety_constraints=["non_diagnostic", "non_prescriptive", "non_manipulative"],
    ))


def create_research_engine(
    name: str = "ResearchPsyche",
) -> PsycheEngine:
    """Create a PsycheEngine configured for research context.

    Safety: non_manipulative only (research may discuss diagnoses)
    Quantum: enabled
    Active inference: enabled (epistemic_weight=0.8, favor truth)
    Lower curvature (open to rapid state changes)
    """
    return PsycheEngine(PsycheProfile(
        name=name,
        quantum_enabled=True,
        active_inference=True,
        epistemic_weight=0.8,     # favor truth discovery
        noise_level=0.03,         # moderate noise (exploratory)
        momentum_decay=0.5,       # moderate inertia
        safety_constraints=["non_manipulative"],
    ))


def create_sales_engine(
    name: str = "SalesPsyche",
) -> PsycheEngine:
    """Create a PsycheEngine configured for sales context.

    Safety: non_manipulative (persuasion ok, manipulation not)
    Quantum: enabled (track prospect's cognitive state)
    Active inference: enabled (epistemic_weight=0.5, balanced)
    Focus on trust and openness dimensions
    """
    return PsycheEngine(PsycheProfile(
        name=name,
        quantum_enabled=True,
        active_inference=True,
        epistemic_weight=0.5,     # balanced
        noise_level=0.02,
        momentum_decay=0.6,
        safety_constraints=["non_manipulative"],
    ))
