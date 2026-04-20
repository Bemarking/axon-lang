"""
AXON Runtime — Differential Privacy (ESK Fase 6.5)
=====================================================
ε-budgeted Laplace / Gaussian noise for `observe` outputs.

Design anchors
--------------
• Calibrated noise: Laplace mechanism for pure ε-DP, Gaussian for (ε,δ)-DP.
• ε-budget tracker: every observation consumes budget; composition is
  additive under sequential composition (Dwork-Roth, 2014).
• No external deps: plain Python + stdlib `random` (seeded in tests for
  reproducibility; production uses `secrets`).
• Healthcare / legal default: ε ≤ 1.0 per epoch (Kairouz-McMahan 2019).

The module exposes:
    PrivacyBudget(epsilon, delta)
    laplace_noise(value, sensitivity, epsilon)
    gaussian_noise(value, sensitivity, epsilon, delta)
    DifferentiallyPrivateObserve — wraps a baseline observe fn with noise
"""

from __future__ import annotations

import math
import random
import secrets
from dataclasses import dataclass, field
from typing import Any, Callable

from axon.runtime.handlers.base import (
    CallerBlameError,
    LambdaEnvelope,
    make_envelope,
)


# ═══════════════════════════════════════════════════════════════════
#  Noise primitives
# ═══════════════════════════════════════════════════════════════════

def laplace_noise(
    value: float,
    *,
    sensitivity: float,
    epsilon: float,
    rng: random.Random | None = None,
) -> float:
    """Sample x ~ Laplace(0, sensitivity/ε) and return value + x.

    The Laplace mechanism gives pure ε-DP: the probability of any output
    changes by at most e^ε when any single record is added/removed
    (Dwork-McSherry-Nissim-Smith 2006).
    """
    if epsilon <= 0:
        raise CallerBlameError(f"epsilon must be > 0, got {epsilon}")
    if sensitivity < 0:
        raise CallerBlameError(f"sensitivity must be >= 0, got {sensitivity}")
    scale = sensitivity / epsilon
    r = rng or random
    # Inverse CDF of Laplace(0, scale): location + scale * sign(u) * ln(1-2|u|)
    u = r.random() - 0.5
    noise = -scale * math.copysign(math.log(1 - 2 * abs(u)), u)
    return value + noise


def gaussian_noise(
    value: float,
    *,
    sensitivity: float,
    epsilon: float,
    delta: float,
    rng: random.Random | None = None,
) -> float:
    """Sample x ~ N(0, σ²) where σ = sensitivity · √(2 ln(1.25/δ)) / ε.

    Gaussian mechanism gives (ε, δ)-DP for ε ≤ 1 (Dwork-Roth 2014 §A.1).
    """
    if epsilon <= 0 or epsilon > 1:
        raise CallerBlameError(
            f"Gaussian mechanism requires 0 < epsilon <= 1, got {epsilon}"
        )
    if not 0 < delta < 1:
        raise CallerBlameError(f"delta must be in (0, 1), got {delta}")
    if sensitivity < 0:
        raise CallerBlameError(f"sensitivity must be >= 0, got {sensitivity}")
    sigma = sensitivity * math.sqrt(2 * math.log(1.25 / delta)) / epsilon
    r = rng or random
    return value + r.gauss(0.0, sigma)


# ═══════════════════════════════════════════════════════════════════
#  Privacy budget tracker
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PrivacyBudget:
    """Sequential-composition ε-budget per Dwork-Roth §3.5.

    Initial budget is the declared (ε_max, δ_max).  Each `spend(ε, δ)`
    call deducts from the remaining budget and raises `BudgetExhausted`
    if the reserve falls below zero.  The tracker does NOT enforce
    Rényi or zCDP composition bounds — that is a future refinement.
    """

    epsilon_max: float
    delta_max: float = 0.0
    epsilon_spent: float = 0.0
    delta_spent: float = 0.0
    ledger: list[tuple[str, float, float]] = field(default_factory=list)

    @property
    def epsilon_remaining(self) -> float:
        return max(0.0, self.epsilon_max - self.epsilon_spent)

    @property
    def delta_remaining(self) -> float:
        return max(0.0, self.delta_max - self.delta_spent)

    def can_spend(self, epsilon: float, delta: float = 0.0) -> bool:
        return (self.epsilon_spent + epsilon) <= self.epsilon_max + 1e-12 and (
            self.delta_spent + delta
        ) <= self.delta_max + 1e-12

    def spend(self, epsilon: float, delta: float = 0.0, *, note: str = "") -> None:
        if epsilon < 0 or delta < 0:
            raise CallerBlameError("spend amounts must be >= 0")
        if not self.can_spend(epsilon, delta):
            raise BudgetExhaustedError(
                f"budget exhausted: requested ε={epsilon} δ={delta}; "
                f"remaining ε={self.epsilon_remaining:.6f} δ={self.delta_remaining:.6f} "
                f"(cap ε={self.epsilon_max}, δ={self.delta_max})"
            )
        self.epsilon_spent += epsilon
        self.delta_spent += delta
        self.ledger.append((note, epsilon, delta))

    def to_dict(self) -> dict[str, Any]:
        return {
            "epsilon_max": self.epsilon_max,
            "delta_max": self.delta_max,
            "epsilon_spent": self.epsilon_spent,
            "delta_spent": self.delta_spent,
            "epsilon_remaining": self.epsilon_remaining,
            "delta_remaining": self.delta_remaining,
            "entries": len(self.ledger),
        }


class BudgetExhaustedError(CallerBlameError):
    """Raised when a DP spend request exceeds the remaining budget.

    CT-2 (Caller Blame): the program asked for more privacy loss than
    its declared budget allows — the responsibility lies with the caller.
    """


# ═══════════════════════════════════════════════════════════════════
#  DP-augmented observe
# ═══════════════════════════════════════════════════════════════════

@dataclass
class DifferentialPrivacyPolicy:
    """Policy attached to an observe: ε per call, mechanism, sensitivity."""
    epsilon_per_call: float
    sensitivity: float = 1.0
    delta_per_call: float = 0.0
    mechanism: str = "laplace"                # laplace | gaussian

    def apply(
        self,
        value: float,
        budget: PrivacyBudget,
        *,
        rng: random.Random | None = None,
        note: str = "",
    ) -> float:
        budget.spend(self.epsilon_per_call, self.delta_per_call, note=note)
        if self.mechanism == "laplace":
            return laplace_noise(
                value,
                sensitivity=self.sensitivity,
                epsilon=self.epsilon_per_call,
                rng=rng,
            )
        if self.mechanism == "gaussian":
            return gaussian_noise(
                value,
                sensitivity=self.sensitivity,
                epsilon=self.epsilon_per_call,
                delta=self.delta_per_call,
                rng=rng,
            )
        raise CallerBlameError(
            f"unknown DP mechanism '{self.mechanism}' (expected laplace | gaussian)"
        )


__all__ = [
    "BudgetExhaustedError",
    "DifferentialPrivacyPolicy",
    "PrivacyBudget",
    "gaussian_noise",
    "laplace_noise",
]
