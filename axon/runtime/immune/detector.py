"""
AXON Runtime — AnomalyDetector
================================
KL-divergence + Free-Energy anomaly detector for the `immune` primitive
(Fase 5, paper_inmune.md §3 and §4.1).

The detector maintains a baseline empirical distribution over observables
(via a rolling window of samples) and, for each new sample, computes:

    D_KL(baseline || current) = Σ q_i log(q_i / p_i)

where p_i is the current-sample-augmented distribution and q_i is the
learned baseline.  The KL magnitude drives the epistemic classification
per paper §5.2; the detector emits `HealthReport`s that encode this.

Design anchors
--------------
• Paper §3.3 — reuses the variational solver shape already present in
  `psyche`; no new mathematics, new configuration only.
• Paper §4.1 — detector takes NO action; it is a pure sensor.
• Paper §5.3 — every report carries a τ half-life for temporal decay.

The detector is intentionally dependency-free: it runs on plain Python
with float histograms so that CI can exercise the math without numpy.
"""

from __future__ import annotations

import hashlib
import math
from collections import deque
from dataclasses import dataclass
from typing import Any, Hashable, Iterable

from axon.compiler.ir_nodes import IRImmune

from axon.runtime.lease_kernel import parse_duration

from .health_report import HealthReport, make_health_report


# ═══════════════════════════════════════════════════════════════════
#  Discrete distribution over observables
# ═══════════════════════════════════════════════════════════════════

@dataclass
class KLDistribution:
    """A rolling-window histogram over hashable observation values.

    Provides `kl_against(other)` — discrete KL divergence with Laplace
    smoothing so that zero counts don't blow the log to infinity.
    """

    window: int = 100
    samples: deque = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.samples is None:
            self.samples = deque(maxlen=self.window)

    @property
    def size(self) -> int:
        return len(self.samples)

    def observe(self, value: Hashable) -> None:
        self.samples.append(value)

    def observe_many(self, values: Iterable[Hashable]) -> None:
        for v in values:
            self.samples.append(v)

    def probabilities(self, *, laplace: float = 1.0) -> dict[Hashable, float]:
        counts: dict[Hashable, int] = {}
        for v in self.samples:
            counts[v] = counts.get(v, 0) + 1
        total = sum(counts.values()) + laplace * max(1, len(counts))
        if total == 0:
            return {}
        # Laplace smoothing spreads one pseudo-count across every observed key.
        return {
            k: (c + laplace) / total for k, c in counts.items()
        }

    def kl_against(self, other: "KLDistribution", *, laplace: float = 1.0) -> float:
        """D_KL(self || other) with Laplace smoothing on both sides.

        Keys not in `other` receive a smoothed probability based on the
        smallest observed mass; this yields a finite, bounded divergence
        even when the two windows share no keys.
        """
        p = self.probabilities(laplace=laplace)
        q = other.probabilities(laplace=laplace)
        if not p:
            return 0.0
        # For keys in p but not q, back them off to the smallest q mass.
        q_floor = min(q.values()) if q else laplace / max(1, len(p))
        kl = 0.0
        for k, p_k in p.items():
            q_k = q.get(k, q_floor)
            if p_k > 0 and q_k > 0:
                kl += p_k * math.log(p_k / q_k)
        # Clamp negatives from smoothing noise; KL is non-negative analytically.
        return max(0.0, kl)


# ═══════════════════════════════════════════════════════════════════
#  The detector itself
# ═══════════════════════════════════════════════════════════════════

def _signature(values: Iterable[Any], n: int = 8) -> str:
    h = hashlib.sha256()
    for v in values:
        h.update(repr(v).encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()[:n]


@dataclass
class AnomalyDetector:
    """Continuous anomaly detector for one `immune` declaration.

    Lifecycle
    ---------
    • `train(samples)` populates the baseline window.
    • `observe(sample)` appends to the current window AND evaluates the
      KL divergence against the baseline; returns a HealthReport.
    • `score(sample)` evaluates without committing — useful for red-team
      rehearsal or dry-run inspection.
    """

    ir: IRImmune
    baseline: KLDistribution = None  # type: ignore[assignment]
    current: KLDistribution = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        w = max(1, self.ir.window)
        if self.baseline is None:
            self.baseline = KLDistribution(window=w)
        if self.current is None:
            self.current = KLDistribution(window=max(1, w // 2))

    # ── Public API ────────────────────────────────────────────────

    def train(self, samples: Iterable[Hashable]) -> None:
        """Seed the baseline window (paper §3.1 — variational prior)."""
        self.baseline.observe_many(samples)

    def observe(self, sample: Hashable) -> HealthReport:
        """Commit a new sample and return its HealthReport."""
        self.current.observe(sample)
        return self._report_for_current()

    def observe_many(self, samples: Iterable[Hashable]) -> HealthReport:
        """Commit a batch and return a single rolled-up HealthReport."""
        self.current.observe_many(samples)
        return self._report_for_current()

    def score(self, sample: Hashable) -> float:
        """Return the KL divergence the detector WOULD report without
        mutating state.  Useful for red-teaming rehearsal."""
        snapshot = KLDistribution(window=self.current.window)
        snapshot.samples = deque(self.current.samples, maxlen=self.current.window)
        snapshot.observe(sample)
        return snapshot.kl_against(self.baseline)

    def reset_current(self) -> None:
        """Clear the rolling observation window without touching the baseline.

        Used by red-teaming harnesses and reconciliation loops to classify
        independent batches (each batch = one evaluation window).
        """
        self.current.samples.clear()

    def classify_batch(self, samples: Iterable[Hashable]) -> HealthReport:
        """Convenience: reset the current window, observe every sample in
        the batch, and return the resulting HealthReport.  This is the
        per-window classifier the paper §3.2 formalism calls for —
        `D_KL(q_baseline || p_observed)` over a *window* of observations."""
        self.reset_current()
        return self.observe_many(samples)

    # ── Internals ─────────────────────────────────────────────────

    def _report_for_current(self) -> HealthReport:
        raw_kl = self.current.kl_against(self.baseline)
        # Sensitivity ∈ (0, 1.0] amplifies the raw KL — the higher the
        # sensitivity, the lower the KL needed to reach a given band.
        sens = self.ir.sensitivity if self.ir.sensitivity is not None else 0.5
        sens = max(min(sens, 1.0), 0.01)
        adjusted_kl = min(raw_kl / (1.0 - sens) if sens < 1.0 else raw_kl * 10, 2.0)
        tau_seconds = self._tau_seconds()
        return make_health_report(
            immune_name=self.ir.name,
            kl_divergence=adjusted_kl,
            observation_window=tuple(self.ir.watch),
            signature=_signature(list(self.current.samples)[-8:]),
            tau_half_life=tau_seconds,
            decay=self.ir.decay,
            provenance=f"immune:{self.ir.name}",
        )

    def _tau_seconds(self) -> float:
        if not self.ir.tau:
            return 300.0
        try:
            return parse_duration(self.ir.tau)
        except Exception:  # noqa: BLE001
            return 300.0


__all__ = ["AnomalyDetector", "KLDistribution"]
