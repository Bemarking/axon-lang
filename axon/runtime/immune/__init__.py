"""
AXON Runtime — Cognitive Immune System Package
=================================================
Public API for the three Fase 5 primitives:
  • `immune`  (AnomalyDetector + HealthReport)
  • `reflex`  (ReflexEngine + ReflexOutcome)
  • `heal`    (HealKernel + Patch)

See docs/paper_inmune.md for the formal specification.
"""

from __future__ import annotations

from axon.compiler.ir_nodes import IRHeal, IRImmune, IRReflex, IRProgram

from .detector import AnomalyDetector, KLDistribution
from .health_report import (
    EPOCH,
    EpistemicLevel,
    HealthReport,
    LEVEL_ORDER,
    ONE_SECOND,
    certainty_from_kl,
    level_at_least,
    level_from_kl,
    make_health_report,
)
from .heal import (
    ApplyFn,
    HealDecision,
    HealKernel,
    Patch,
    PatchState,
    ShieldApproveFn,
    SynthesizeFn,
    default_apply,
    default_shield_approve,
    default_synthesize,
)
from .reflex import ReflexEngine, ReflexOutcome


# ═══════════════════════════════════════════════════════════════════
#  ImmuneRuntime — one-stop integration for immune/reflex/heal + shield
# ═══════════════════════════════════════════════════════════════════

class ImmuneRuntime:
    """
    Convenience wrapper that wires `AnomalyDetector` → `ReflexEngine`
    → `HealKernel` for a single `IRProgram`.

    This is the Fase 5.4 integration layer: one object per `immune`,
    and a single `observe(sample)` call propagates through detector →
    dispatch(reflex) → tick(heal).  The shield of each heal is routed
    to `ShieldApproveFn` (defaulting to "always allow" until the shield
    runtime lands in Fase 4+/ESK Fase 6).
    """

    def __init__(
        self,
        program: IRProgram,
        *,
        shield_approve: ShieldApproveFn = default_shield_approve,
        synthesize: SynthesizeFn = default_synthesize,
        apply: ApplyFn = default_apply,
    ) -> None:
        self.program = program
        self.detectors: dict[str, AnomalyDetector] = {
            imm.name: AnomalyDetector(ir=imm) for imm in program.immunes
        }
        self.reflex_engine = ReflexEngine()
        for reflex in program.reflexes:
            self.reflex_engine.register(reflex)
        self.heal_kernel = HealKernel(
            synthesize=synthesize,
            apply=apply,
            shield_approve=shield_approve,
        )
        for heal in program.heals:
            self.heal_kernel.register(heal)

    def detector(self, name: str) -> AnomalyDetector:
        if name not in self.detectors:
            raise KeyError(f"no immune named '{name}' in program")
        return self.detectors[name]

    def observe(self, immune_name: str, sample) -> tuple[HealthReport, list[ReflexOutcome], list[HealDecision]]:
        """End-to-end: observe → HealthReport → reflexes → heals."""
        report = self.detector(immune_name).observe(sample)
        reflex_outcomes = self.reflex_engine.dispatch(report)
        heal_decisions = self.heal_kernel.tick(report)
        return report, reflex_outcomes, heal_decisions

    def train(self, immune_name: str, samples) -> None:
        self.detector(immune_name).train(samples)


__all__ = [
    # Core types
    "AnomalyDetector",
    "ApplyFn",
    "EPOCH",
    "EpistemicLevel",
    "HealDecision",
    "HealKernel",
    "HealthReport",
    "ImmuneRuntime",
    "KLDistribution",
    "LEVEL_ORDER",
    "ONE_SECOND",
    "Patch",
    "PatchState",
    "ReflexEngine",
    "ReflexOutcome",
    "ShieldApproveFn",
    "SynthesizeFn",
    # Factories / helpers
    "certainty_from_kl",
    "default_apply",
    "default_shield_approve",
    "default_synthesize",
    "level_at_least",
    "level_from_kl",
    "make_health_report",
    # IR re-exports (convenience)
    "IRHeal",
    "IRImmune",
    "IRReflex",
]
