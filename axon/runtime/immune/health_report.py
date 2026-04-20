"""
AXON Runtime — HealthReport
=============================
The typed output of every `immune` sensor (Fase 5, paper_inmune.md §5).

A HealthReport is a ΛD envelope ψ = ⟨T, V, E⟩ where:
  T = structural type "HealthReport"
  V = { kl_divergence, anomaly_signature, observation_window, classification }
  E = ⟨c, τ, ρ, δ⟩ — epistemic envelope with c derived from KL (§5.2)

The report is **pure data** — immune never acts; it only produces these
reports for downstream reflex / heal consumers.  Temporal decay is
materialized in `c_at(now)` per paper §5.3.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from axon.runtime.handlers.base import LambdaEnvelope, now_iso


EpistemicLevel = str
"""One of: 'know' | 'believe' | 'speculate' | 'doubt' (paper §5.2)."""

_VALID_LEVELS = ("know", "believe", "speculate", "doubt")


# ═══════════════════════════════════════════════════════════════════
#  KL → epistemic level mapping  (paper §5.2)
# ═══════════════════════════════════════════════════════════════════

def level_from_kl(kl: float) -> EpistemicLevel:
    """Map D_KL magnitude to the epistemic lattice per paper §5.2 Table."""
    if kl < 0.0:
        return "know"
    if kl < 0.3:
        return "know"
    if kl < 0.6:
        return "believe"
    if kl < 0.9:
        return "speculate"
    return "doubt"


def certainty_from_kl(kl: float) -> float:
    """Map D_KL to a certainty c ∈ [0.0, 1.0] using the paper §5.2 bands."""
    if kl < 0.0:
        return 1.0
    if kl <= 0.3:
        return 1.0
    if kl <= 0.6:
        # [0.3, 0.6] → linearly from 0.99 to 0.85 (believe band)
        return 0.99 - ((kl - 0.3) / 0.3) * (0.99 - 0.85)
    if kl <= 0.9:
        # [0.6, 0.9] → 0.85 down to 0.50 (speculate)
        return 0.85 - ((kl - 0.6) / 0.3) * (0.85 - 0.50)
    # [0.9, 1.0+] → 0.50 down to 0.0 (doubt), saturating at 0.0
    decayed = 0.50 - min(1.0, (kl - 0.9) / 0.1) * 0.50
    return max(0.0, decayed)


LEVEL_ORDER: dict[str, int] = {
    "know":      0,
    "believe":   1,
    "speculate": 2,
    "doubt":     3,
}


def level_at_least(observed: EpistemicLevel, threshold: EpistemicLevel) -> bool:
    """Return True iff `observed` is *as severe as or worse than* threshold.

    Reflex / heal trigger on thresholds like `on_level: doubt`: they should
    fire when the observation reaches `doubt` or higher severity.
    """
    return LEVEL_ORDER.get(observed, 0) >= LEVEL_ORDER.get(threshold, 0)


# ═══════════════════════════════════════════════════════════════════
#  HealthReport — the pure output of an `immune` sensor
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class HealthReport:
    """
    Immutable ΛD envelope emitted by `immune` per paper §5.

    Fields
    ------
    immune_name        — name of the emitting `immune` declaration
    kl_divergence      — D_KL(baseline || observed), paper §3.2
    free_energy        — variational F (KL + surprise), paper §3.1
    classification     — epistemic level derived from KL (paper §5.2)
    anomaly_signature  — hash-like string identifying the anomaly pattern
    observation_window — list of ordered observation keys that drove the KL
    envelope           — ΛD envelope ⟨c, τ, ρ, δ⟩ with decay support
    tau_half_life      — seconds after which c is halved (paper §5.3)
    decay              — "exponential" | "linear" | "none"
    """
    immune_name: str = ""
    kl_divergence: float = 0.0
    free_energy: float = 0.0
    classification: EpistemicLevel = "know"
    anomaly_signature: str = ""
    observation_window: tuple[str, ...] = ()
    envelope: LambdaEnvelope = field(default_factory=LambdaEnvelope)
    tau_half_life: float = 300.0
    decay: str = "exponential"

    def c_at(self, now: datetime) -> float:
        """Return the certainty at `now`, applying paper §5.3 decay."""
        if self.decay == "none":
            return self.envelope.c
        # Parse the envelope's τ as the emission time.
        try:
            emitted = datetime.fromisoformat(self.envelope.tau)
        except ValueError:
            return self.envelope.c
        elapsed = (now - emitted).total_seconds()
        if elapsed <= 0:
            return self.envelope.c
        if self.decay == "linear":
            # Linear decay to zero over 5×τ (paper §5.3 purge window).
            factor = max(0.0, 1.0 - elapsed / (5.0 * self.tau_half_life))
            return self.envelope.c * factor
        # exponential: half-life = tau
        factor = math.pow(0.5, elapsed / max(self.tau_half_life, 1e-9))
        return self.envelope.c * factor

    def is_active(self, now: datetime, purge_multiple: float = 5.0) -> bool:
        """Report is considered purged after `purge_multiple × τ` (paper §5.3)."""
        try:
            emitted = datetime.fromisoformat(self.envelope.tau)
        except ValueError:
            return True
        return (now - emitted).total_seconds() < purge_multiple * self.tau_half_life

    def to_dict(self) -> dict[str, Any]:
        return {
            "immune_name": self.immune_name,
            "kl_divergence": self.kl_divergence,
            "free_energy": self.free_energy,
            "classification": self.classification,
            "anomaly_signature": self.anomaly_signature,
            "observation_window": list(self.observation_window),
            "envelope": self.envelope.to_dict(),
            "tau_half_life": self.tau_half_life,
            "decay": self.decay,
        }


def make_health_report(
    *,
    immune_name: str,
    kl_divergence: float,
    observation_window: tuple[str, ...] = (),
    signature: str = "",
    tau_half_life: float = 300.0,
    decay: str = "exponential",
    provenance: str = "immune",
) -> HealthReport:
    """Factory: derive epistemic level + certainty from KL per paper §5.2."""
    level = level_from_kl(kl_divergence)
    c = certainty_from_kl(kl_divergence)
    envelope = LambdaEnvelope(
        c=c, tau=now_iso(), rho=provenance, delta="inferred",
    )
    return HealthReport(
        immune_name=immune_name,
        kl_divergence=kl_divergence,
        free_energy=kl_divergence,  # minimal proxy; a full FEP uses KL + surprise
        classification=level,
        anomaly_signature=signature,
        observation_window=observation_window,
        envelope=envelope,
        tau_half_life=tau_half_life,
        decay=decay,
    )


# Helpful constant for tests that simulate decay without waiting.
EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
ONE_SECOND = timedelta(seconds=1)


__all__ = [
    "EPOCH",
    "EpistemicLevel",
    "HealthReport",
    "LEVEL_ORDER",
    "ONE_SECOND",
    "certainty_from_kl",
    "level_at_least",
    "level_from_kl",
    "make_health_report",
]
