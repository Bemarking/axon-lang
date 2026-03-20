"""
AXON Engine — Psychological-Epistemic Modeling (PEM)
=====================================================
Complete engine for the `psyche` language primitive.

Implements the theoretical framework from:
    "Transcending Static Epistemology: A Quantum-Active
    Architecture for Psychological-Epistemic Modeling"
    (Velit, 2026)

4 Pillars:
    §1 — State Dynamics:     Riemannian Manifold + SDE     (cognitive_state)
    §2 — Quantum Probability: Density Matrix + Born's Rule  (density_matrix)
    §3 — Active Inference:    Free Energy Minimization      (active_inference)
    §4 — Safety Types:        Dependent Type Constraints    (safety_types)

Integration:
    PsycheEngine — Unified pipeline orchestrating all 4 pillars.
    PsycheProfile — Configuration for `psyche` blocks.
    PsycheResult — Runtime output with safety proof.

Usage:
    >>> from axon.engine.pem import PsycheEngine, PsycheProfile
    >>> engine = PsycheEngine(PsycheProfile("therapy",
    ...     safety_constraints=["non_diagnostic", "non_prescriptive"]))
    >>> result = engine.process_signal(InteractionSignal({"affect": -0.3}))
    >>> print(result.state)

    >>> # Or use predefined configs:
    >>> from axon.engine.pem import create_therapeutic_engine
    >>> engine = create_therapeutic_engine()

Author: Ricardo Velit (theoretical framework)
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════
#  §1 — Cognitive State (Riemannian Manifold + SDE)
# ═══════════════════════════════════════════════════════════════════

from axon.engine.pem.cognitive_state import (
    CognitiveDimension,
    CognitiveManifold,
    CognitiveState,
    InteractionSignal,
    StateTrajectory,
    STANDARD_DIMENSIONS,
)

# ═══════════════════════════════════════════════════════════════════
#  §2 — Density Matrix (Quantum Cognitive Probability)
# ═══════════════════════════════════════════════════════════════════

from axon.engine.pem.density_matrix import (
    DensityMatrix,
    EvidenceProjector,
    cognitive_state_to_density,
    density_to_probabilities,
)

# ═══════════════════════════════════════════════════════════════════
#  §3 — Active Inference (Free Energy Minimization)
# ═══════════════════════════════════════════════════════════════════

from axon.engine.pem.active_inference import (
    AllostaticBound,
    AllostaticZone,
    EpistemicValue,
    FreeEnergyMinimizer,
    PragmaticValue,
    TrajectoryScore,
)

# ═══════════════════════════════════════════════════════════════════
#  §4 — Safety Types (Dependent Type Constraints)
# ═══════════════════════════════════════════════════════════════════

from axon.engine.pem.safety_types import (
    SafetyConstraint,
    SafetyRegistry,
    SafetyViolation,
    ViolationSeverity,
    NON_DIAGNOSTIC,
    NON_MANIPULATIVE,
    NON_PRESCRIPTIVE,
    therapeutic_registry,
    research_registry,
    sales_registry,
)

# ═══════════════════════════════════════════════════════════════════
#  Integration — PsycheEngine
# ═══════════════════════════════════════════════════════════════════

from axon.engine.pem.psyche_engine import (
    PsycheEngine,
    PsycheProfile,
    PsycheResult,
    create_therapeutic_engine,
    create_research_engine,
    create_sales_engine,
)

# ═══════════════════════════════════════════════════════════════════
#  §5 — PID Controller (Cybernetic Refinement Calculus)
# ═══════════════════════════════════════════════════════════════════

from axon.engine.pem.pid_controller import (
    PIDController,
    PIDResult,
    PIDStep,
)

# ═══════════════════════════════════════════════════════════════════

__all__ = [
    # §1 — Cognitive State
    "CognitiveDimension",
    "CognitiveManifold",
    "CognitiveState",
    "InteractionSignal",
    "StateTrajectory",
    "STANDARD_DIMENSIONS",
    # §2 — Density Matrix
    "DensityMatrix",
    "EvidenceProjector",
    "cognitive_state_to_density",
    "density_to_probabilities",
    # §3 — Active Inference
    "AllostaticBound",
    "AllostaticZone",
    "EpistemicValue",
    "FreeEnergyMinimizer",
    "PragmaticValue",
    "TrajectoryScore",
    # §4 — Safety Types
    "SafetyConstraint",
    "SafetyRegistry",
    "SafetyViolation",
    "ViolationSeverity",
    "NON_DIAGNOSTIC",
    "NON_MANIPULATIVE",
    "NON_PRESCRIPTIVE",
    "therapeutic_registry",
    "research_registry",
    "sales_registry",
    # Integration
    "PsycheEngine",
    "PsycheProfile",
    "PsycheResult",
    "create_therapeutic_engine",
    "create_research_engine",
    "create_sales_engine",
    # §5 — PID Controller (CRC)
    "PIDController",
    "PIDResult",
    "PIDStep",
]
