"""
AXON Runtime — ReconcileLoop
=============================
Free-energy-minimizing control loop for the `reconcile` primitive
(Fase 3.1).

Semantics
---------
Each tick closes one step of the Active Inference loop:

  1. OBSERVE  — invoke the handler's `observe` to snapshot real state,
                producing an outcome with ΛD envelope E = ⟨c, τ, ρ, δ⟩.
  2. MEASURE  — compute a *free-energy proxy*, the symmetric Jaccard
                distance between expected-resources (manifest belief)
                and observed-resources (evidence).  This is the drift.
  3. GATE     — skip the corrective action unless ALL hold:
                  • certainty c > threshold    (epistemic gate)
                  • drift     > tolerance      (action worth the cost)
                  • shield.approve(...)         (governance gate)
  4. ACT      — apply `on_drift ∈ {provision, alert, refine}`:
                  • provision  → handler.provision(manifest)
                  • alert      → record a ReconcileAlert; no mutation
                  • refine     → record a ReconcileRefinement (placeholder
                                 for belief revision in Fase 4+)
  5. BOUND    — cap retries at `max_retries`.

Integration with Fase 2
-----------------------
ReconcileLoop holds a `Handler` (or `HandlerRegistry`) instance and
delegates all side-effecting work to it.  The loop itself is pure
Python — no subprocess, no SDK — so it is unit-testable with
`DryRunHandler` + a `ManualClock`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from axon.compiler.ir_nodes import (
    IRFabric,
    IRManifest,
    IRObserve,
    IRProgram,
    IRReconcile,
    IRResource,
)

from .handlers.base import (
    CallerBlameError,
    Handler,
    HandlerOutcome,
    LambdaEnvelope,
    identity_continuation,
    make_envelope,
)


# ═══════════════════════════════════════════════════════════════════
#  REPORTS — structured outputs of each tick
# ═══════════════════════════════════════════════════════════════════

TickAction = Literal["provision", "alert", "refine", "noop"]


@dataclass(frozen=True)
class ReconcileTickReport:
    """One iteration of the control loop — fully serializable."""
    reconcile_name: str
    observation: HandlerOutcome | None
    action: TickAction
    drift: float
    certainty: float
    shield_approved: bool
    retries_remaining: int
    outcome: HandlerOutcome | None
    note: str = ""


# ═══════════════════════════════════════════════════════════════════
#  SHIELD ADAPTER — opt-in governance gate
# ═══════════════════════════════════════════════════════════════════

ShieldApprove = Callable[[str, HandlerOutcome, float], bool]
"""
A shield adapter: `(reconcile_name, observation, drift) → approved`.

The default adapter always approves.  Real shields (Fase 2.1.a onwards)
will plug into this contract once the ShieldApplyNode runtime wiring
lands in Fase 4.  Meanwhile, reconcile is already testable under shield-
deny scenarios via a fake adapter.
"""


def allow_all_shield(_name: str, _obs: HandlerOutcome, _drift: float) -> bool:
    return True


def deny_all_shield(_name: str, _obs: HandlerOutcome, _drift: float) -> bool:
    return False


# ═══════════════════════════════════════════════════════════════════
#  DRIFT METRIC — free-energy proxy
# ═══════════════════════════════════════════════════════════════════

def jaccard_drift(expected: tuple[str, ...], observed: tuple[str, ...]) -> float:
    """
    Symmetric Jaccard distance on resource-name sets.

    F ≈ |A △ B| / |A ∪ B| — zero when belief and evidence agree,
    approaches 1.0 as they diverge.  A principled proxy for D_KL on
    unstructured resource inventories where we lack priors yet.  Richer
    free-energy computations land with the psyche integration in Fase 4+.
    """
    a, b = set(expected), set(observed)
    union = a | b
    if not union:
        return 0.0
    return len(a ^ b) / len(union)


# ═══════════════════════════════════════════════════════════════════
#  RECONCILE LOOP
# ═══════════════════════════════════════════════════════════════════

class ReconcileLoop:
    """
    Executes `tick()` or `run()` against a Handler to close the belief-
    evidence gap for a single `reconcile` declaration.

    Parameters
    ----------
    ir_reconcile : IRReconcile
        The compiled reconcile spec (from IRProgram.reconciles).
    program : IRProgram
        Needed so the loop can resolve the observe → manifest chain.
    handler : Handler
        Consumes `observe` and `provision` intentions.  Typically a
        DryRunHandler in tests, a TerraformHandler / AwsHandler /
        KubernetesHandler / DockerHandler in production.
    shield : ShieldApprove
        Optional governance gate.  Defaults to allow-all.
    """

    def __init__(
        self,
        ir_reconcile: IRReconcile,
        program: IRProgram,
        handler: Handler,
        *,
        shield: ShieldApprove = allow_all_shield,
    ) -> None:
        self.ir = ir_reconcile
        self.program = program
        self.handler = handler
        self.shield = shield
        self._threshold = ir_reconcile.threshold if ir_reconcile.threshold is not None else 0.85
        self._tolerance = ir_reconcile.tolerance if ir_reconcile.tolerance is not None else 0.10
        self._retries_left = ir_reconcile.max_retries
        self._ticks: list[ReconcileTickReport] = []

        # Resolve the observe → manifest chain once (static wiring).
        self._observe = self._resolve_observe(ir_reconcile.observe_ref)
        self._manifest = self._resolve_manifest(self._observe.target)
        self._resources = {r.name: r for r in program.resources}
        self._fabrics = {f.name: f for f in program.fabrics}

    # ── Public API ──────────────────────────────────────────────

    def tick(self) -> ReconcileTickReport:
        if self._retries_left <= 0:
            # Budget exhausted — report a noop with an explanation.
            report = ReconcileTickReport(
                reconcile_name=self.ir.name,
                observation=None,
                action="noop",
                drift=0.0,
                certainty=0.0,
                shield_approved=False,
                retries_remaining=self._retries_left,
                outcome=None,
                note="max_retries exhausted",
            )
            self._ticks.append(report)
            return report

        observation = self.handler.observe(
            self._observe, self._manifest, identity_continuation
        )
        observed_resources = tuple(
            observation.data.get("resources_observed", self._manifest.resources)
        )
        expected = tuple(self._manifest.resources)
        drift = jaccard_drift(expected, observed_resources)
        certainty = observation.envelope.c

        if certainty < self._threshold:
            report = self._record(
                observation, action="noop", drift=drift, certainty=certainty,
                shield_approved=False,
                note=f"certainty {certainty:.2f} below threshold {self._threshold:.2f}",
            )
            return report

        if drift <= self._tolerance:
            report = self._record(
                observation, action="noop", drift=drift, certainty=certainty,
                shield_approved=True,
                note=f"drift {drift:.3f} within tolerance {self._tolerance:.3f}",
            )
            return report

        approved = self.shield(self.ir.name, observation, drift)
        if not approved:
            report = self._record(
                observation, action="noop", drift=drift, certainty=certainty,
                shield_approved=False,
                note="shield denied corrective action",
            )
            return report

        outcome = self._apply_action(observation, drift, certainty)
        self._retries_left -= 1
        action: TickAction
        if self.ir.on_drift == "provision":
            action = "provision"
        elif self.ir.on_drift == "alert":
            action = "alert"
        else:
            action = "refine"
        report = ReconcileTickReport(
            reconcile_name=self.ir.name,
            observation=observation,
            action=action,
            drift=drift,
            certainty=certainty,
            shield_approved=True,
            retries_remaining=self._retries_left,
            outcome=outcome,
            note=f"drift {drift:.3f} > tolerance {self._tolerance:.3f}; applied {action}",
        )
        self._ticks.append(report)
        return report

    def run(self, max_ticks: int | None = None) -> list[ReconcileTickReport]:
        """Tick until either quiescence (two consecutive noops), budget
        exhaustion, or `max_ticks`."""
        limit = max_ticks if max_ticks is not None else self.ir.max_retries + 2
        results: list[ReconcileTickReport] = []
        consecutive_noops = 0
        for _ in range(limit):
            report = self.tick()
            results.append(report)
            if report.action == "noop":
                consecutive_noops += 1
                if consecutive_noops >= 2 or "exhausted" in report.note:
                    break
            else:
                consecutive_noops = 0
        return results

    @property
    def history(self) -> list[ReconcileTickReport]:
        return list(self._ticks)

    # ── Internals ───────────────────────────────────────────────

    def _resolve_observe(self, name: str) -> IRObserve:
        for obs in self.program.observations:
            if obs.name == name:
                return obs
        raise CallerBlameError(
            f"reconcile '{self.ir.name}' references unknown observe '{name}'"
        )

    def _resolve_manifest(self, name: str) -> IRManifest:
        for m in self.program.manifests:
            if m.name == name:
                return m
        raise CallerBlameError(
            f"reconcile '{self.ir.name}': observe '{self.ir.observe_ref}' "
            f"targets unknown manifest '{name}'"
        )

    def _apply_action(
        self,
        observation: HandlerOutcome,
        drift: float,
        certainty: float,
    ) -> HandlerOutcome:
        if self.ir.on_drift == "provision":
            return self.handler.provision(
                self._manifest, self._resources, self._fabrics,
                identity_continuation,
            )
        if self.ir.on_drift == "alert":
            return HandlerOutcome(
                operation="alert",
                target=self.ir.name,
                status="ok",
                envelope=make_envelope(c=certainty, rho="reconcile", delta="inferred"),
                data={
                    "reconcile": self.ir.name,
                    "drift": drift,
                    "source_observation": observation.target,
                },
                handler=f"reconcile:{self.ir.name}",
            )
        # refine — belief-revision placeholder (Fase 4+)
        return HandlerOutcome(
            operation="refine",
            target=self.ir.name,
            status="partial",
            envelope=make_envelope(c=certainty, rho="reconcile", delta="inferred"),
            data={
                "reconcile": self.ir.name,
                "drift": drift,
                "note": "belief revision reserved for Fase 4 (psyche integration)",
            },
            handler=f"reconcile:{self.ir.name}",
        )

    def _record(
        self,
        observation: HandlerOutcome | None,
        *,
        action: TickAction,
        drift: float,
        certainty: float,
        shield_approved: bool,
        note: str,
    ) -> ReconcileTickReport:
        report = ReconcileTickReport(
            reconcile_name=self.ir.name,
            observation=observation,
            action=action,
            drift=drift,
            certainty=certainty,
            shield_approved=shield_approved,
            retries_remaining=self._retries_left,
            outcome=None,
            note=note,
        )
        self._ticks.append(report)
        return report


__all__ = [
    "ReconcileLoop",
    "ReconcileTickReport",
    "ShieldApprove",
    "TickAction",
    "allow_all_shield",
    "deny_all_shield",
    "jaccard_drift",
]
