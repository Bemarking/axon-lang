"""
AXON Runtime — EnsembleAggregator
===================================
Byzantine quorum aggregator for the `ensemble` primitive (Fase 3.3).

Fuses N independent `HandlerOutcome`s (produced by separate observation
handlers) into a single consensus `HandlerOutcome`.  Models Fagin-
Halpern-Moses-Vardi common knowledge `Cφ`: the outcome holds iff at
least `quorum` observers independently agree.

Aggregation policies
--------------------
• **majority** — the modal `status` wins; ties resolve to "partial".
• **weighted** — each observation is weighted by its certainty `c`;
                 statuses are scored and the argmax wins.
• **byzantine** — discards the best and worst `c`-outlier and applies
                  majority to the remainder (Lamport's one-third rule).

Certainty fusion modes
----------------------
• **min**       — consensus certainty = min(c_i) (conservative default)
• **weighted**  — weighted mean of accepting c_i (strict quorum)
• **harmonic**  — harmonic mean of accepting c_i (penalizes outliers)

Partition semantics
-------------------
Per Decision D4, observations that raised `NetworkPartitionError` do
NOT appear in the input list — the caller has already reclassified them
as CT-3 exceptions.  If after exclusion the surviving count falls below
`quorum`, the aggregator itself raises `InfrastructureBlameError`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from axon.compiler.ir_nodes import IREnsemble

from .handlers.base import (
    CalleeBlameError,
    HandlerOutcome,
    InfrastructureBlameError,
    LambdaEnvelope,
    make_envelope,
)


_VALID_AGGREGATIONS = frozenset({"majority", "weighted", "byzantine"})
_VALID_CERTAINTY_MODES = frozenset({"min", "weighted", "harmonic"})


@dataclass(frozen=True)
class EnsembleReport:
    """Explanatory structure for aggregation outcomes — used in tests and logs."""
    aggregation: str
    certainty_mode: str
    contributors: tuple[str, ...]
    status_tally: dict[str, int]
    winning_status: str
    fused_certainty: float


class EnsembleAggregator:
    """Pure aggregator — stateless, hence threadsafe."""

    def __init__(self, ir_ensemble: IREnsemble) -> None:
        if ir_ensemble.aggregation not in _VALID_AGGREGATIONS:
            raise CalleeBlameError(
                f"ensemble '{ir_ensemble.name}' has invalid aggregation "
                f"'{ir_ensemble.aggregation}'"
            )
        if ir_ensemble.certainty_mode not in _VALID_CERTAINTY_MODES:
            raise CalleeBlameError(
                f"ensemble '{ir_ensemble.name}' has invalid certainty_mode "
                f"'{ir_ensemble.certainty_mode}'"
            )
        self.ir = ir_ensemble
        self.quorum: int = (
            ir_ensemble.quorum
            if ir_ensemble.quorum is not None
            else max(1, len(ir_ensemble.observations) // 2 + 1)
        )

    # ── Public API ──────────────────────────────────────────────

    def aggregate(
        self,
        outcomes: Iterable[HandlerOutcome],
    ) -> tuple[HandlerOutcome, EnsembleReport]:
        """
        Fuse outcomes into a single consensus HandlerOutcome.

        Returns a tuple of (consensus_outcome, EnsembleReport).  The
        report exists so callers (reconcile loop, tracer, audit logs)
        can inspect the fusion without re-deriving it.
        """
        survivors = [o for o in outcomes if o.status != "failed"] or list(outcomes)
        if len(survivors) < self.quorum:
            raise InfrastructureBlameError(
                f"ensemble '{self.ir.name}' has only {len(survivors)} surviving "
                f"observations; quorum requires {self.quorum}. "
                f"Decision D4: too many partitions ⇒ CT-3."
            )

        if self.ir.aggregation == "byzantine":
            survivors = self._byzantine_filter(survivors)

        status_tally = Counter(o.status for o in survivors)
        winning_status = self._select_status(survivors, status_tally)
        accepting = [o for o in survivors if o.status == winning_status]

        if len(accepting) < self.quorum:
            raise InfrastructureBlameError(
                f"ensemble '{self.ir.name}' failed Cφ consensus: only "
                f"{len(accepting)}/{self.quorum} observers agreed on "
                f"'{winning_status}'. Status tally: {dict(status_tally)}"
            )

        fused_c = self._fuse_certainty([o.envelope.c for o in accepting])
        envelope = self._fused_envelope(accepting, fused_c)

        consensus = HandlerOutcome(
            operation="ensemble",
            target=self.ir.name,
            status=winning_status,
            envelope=envelope,
            data={
                "aggregation": self.ir.aggregation,
                "certainty_mode": self.ir.certainty_mode,
                "quorum": self.quorum,
                "contributors": [o.target for o in survivors],
                "accepting": [o.target for o in accepting],
                "status_tally": dict(status_tally),
            },
            handler=f"ensemble:{self.ir.name}",
        )
        report = EnsembleReport(
            aggregation=self.ir.aggregation,
            certainty_mode=self.ir.certainty_mode,
            contributors=tuple(o.target for o in survivors),
            status_tally=dict(status_tally),
            winning_status=winning_status,
            fused_certainty=fused_c,
        )
        return consensus, report

    # ── Internals ───────────────────────────────────────────────

    def _select_status(
        self,
        survivors: list[HandlerOutcome],
        tally: Counter,
    ) -> str:
        if self.ir.aggregation == "weighted":
            scores: dict[str, float] = {}
            for o in survivors:
                scores[o.status] = scores.get(o.status, 0.0) + o.envelope.c
            return max(scores.items(), key=lambda kv: kv[1])[0]
        # majority + byzantine share the modal-status rule.  Ties resolve
        # to "partial" so a split decision does not falsely look healthy.
        ordered = tally.most_common()
        if len(ordered) >= 2 and ordered[0][1] == ordered[1][1]:
            return "partial"
        return ordered[0][0]

    def _byzantine_filter(
        self, survivors: list[HandlerOutcome]
    ) -> list[HandlerOutcome]:
        """Lamport's Byzantine rule: with N observers, tolerate ⌊(N-1)/3⌋
        arbitrary faults.  We drop the highest- and lowest-certainty
        outcomes before majority — a conservative approximation that
        excludes both spoofed-healthy and spoofed-broken liars."""
        if len(survivors) < 4:
            return survivors
        sorted_by_c = sorted(survivors, key=lambda o: o.envelope.c)
        return sorted_by_c[1:-1]

    def _fuse_certainty(self, values: list[float]) -> float:
        if not values:
            return 0.0
        if self.ir.certainty_mode == "min":
            return min(values)
        if self.ir.certainty_mode == "weighted":
            # Weighted mean where each c_i is weighted by itself — Bayesian
            # "strong voices count more" semantics.
            total = sum(values)
            if total == 0.0:
                return 0.0
            return sum(c * c for c in values) / total
        if self.ir.certainty_mode == "harmonic":
            # Harmonic mean with an ε floor so a single c=0 does not
            # annihilate the ensemble.
            eps = 1e-9
            safe = [max(c, eps) for c in values]
            return len(safe) / sum(1.0 / c for c in safe)
        # Unreachable — validated in __init__.
        raise CalleeBlameError(f"unknown certainty_mode '{self.ir.certainty_mode}'")

    def _fused_envelope(
        self,
        accepting: list[HandlerOutcome],
        fused_c: float,
    ) -> LambdaEnvelope:
        # Provenance fuses the handler tags so consumers can audit the
        # composition of the Cφ belief.
        rho = f"ensemble({','.join(sorted({o.handler for o in accepting if o.handler}))})"
        return make_envelope(
            c=fused_c,
            rho=rho or f"ensemble:{self.ir.name}",
            delta="inferred",
        )


__all__ = [
    "EnsembleAggregator",
    "EnsembleReport",
]
