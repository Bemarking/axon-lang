"""
AXON Runtime — Phase 3 Auto-Healing Acceptance Test
====================================================
Verifies the closing criterion of Fase 3 in docs/plan_io_cognitivo.md:

    Demo de auto-healing donde el sistema detecta drift, reconcilia con
    gate epistémico (c > 0.85) y requiere shield.approve antes de actuar.

Scenario
--------
A production cluster is declared with two resources (`Db`, `Cache`).  At
the first tick, one of the resources has "drifted" (the DriftingHandler
observes only `Db`, not `Cache`) — the loop must detect drift = 0.5,
pass the epistemic gate (c = 0.95 > 0.85), consult the shield, and
trigger `provision`.  At the second tick, after healing, observations
include both resources, drift falls to 0.0, and the loop quiesces with
a `noop`.

The test asserts the FULL cycle: drift → shield-approve → provision →
convergence — which is the Active Inference loop in microcosm.
"""

from __future__ import annotations

import pytest

from axon.compiler.ir_generator import IRGenerator
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.runtime.handlers.base import HandlerOutcome, make_envelope
from axon.runtime.handlers.dry_run import DryRunHandler
from axon.runtime.reconcile_loop import (
    ReconcileLoop,
    allow_all_shield,
    deny_all_shield,
)


_AUTOHEAL_PROGRAM = '''
resource Db    { kind: postgres lifetime: linear }
resource Cache { kind: redis    lifetime: affine }

fabric ProdVpc { provider: aws region: "us-east-1" zones: 3 ephemeral: false }

manifest ProductionCluster {
  resources: [Db, Cache]
  fabric: ProdVpc
  region: "us-east-1"
  zones: 3
  compliance: [SOC2]
}

observe ClusterHealth from ProductionCluster {
  sources: [prometheus, healthcheck]
  quorum: 2
  timeout: 5s
  on_partition: fail
  certainty_floor: 0.85
}

shield ReconcileShield {
  scan: [prompt_injection]
  on_breach: quarantine
  severity: medium
}

reconcile ProductionReconciler {
  observe: ClusterHealth
  threshold: 0.85
  tolerance: 0.10
  on_drift: provision
  shield: ReconcileShield
  max_retries: 3
}
'''


class DriftingHandler(DryRunHandler):
    """A DryRun variant that simulates a missing resource until provision heals it."""

    def __init__(self) -> None:
        super().__init__()
        self.healed: bool = False

    def observe(self, obs, manifest, continuation):
        # Before healing: only one of the two resources is observed.
        # After a provision call, the state is healed and all resources appear.
        observed = list(manifest.resources) if self.healed else list(manifest.resources)[:1]
        record = {
            "observe": obs.name,
            "manifest": manifest.name,
            "sources": list(obs.sources),
            "quorum": obs.quorum or len(obs.sources),
            "resources_observed": observed,
        }
        self.state.observations.append(record)
        outcome = HandlerOutcome(
            operation="observe",
            target=obs.name,
            status="ok",
            envelope=make_envelope(c=0.95, rho=self.name, delta="observed"),
            data=record,
            handler=self.name,
        )
        self.state.outcomes.append(outcome)
        return continuation(outcome)

    def provision(self, manifest, resources, fabrics, continuation):
        # Calling provision heals the drift.
        self.healed = True
        return super().provision(manifest, resources, fabrics, continuation)


def _compile():
    return IRGenerator().generate(
        Parser(Lexer(_AUTOHEAL_PROGRAM).tokenize()).parse()
    )


class TestAutoHealingAcceptance:
    """End-to-end acceptance of the Fase 3 closing criterion."""

    def test_detect_drift_shield_approve_provision_converge(self):
        """Full auto-healing cycle under shield approval."""
        ir = _compile()
        reconciler = ir.reconciles[0]
        handler = DriftingHandler()
        loop = ReconcileLoop(reconciler, ir, handler, shield=allow_all_shield)

        results = loop.run(max_ticks=5)

        # Expected trajectory:
        #   tick 0 → drift 0.5, certainty 0.95 > 0.85, shield approves → provision
        #   tick 1 → drift 0.0 (healed)                                 → noop
        #   tick 2 → drift 0.0                                          → noop (quiesce)
        assert len(results) >= 2
        first = results[0]
        assert first.action == "provision"
        assert first.shield_approved is True
        assert first.drift == pytest.approx(0.5)
        assert first.certainty == pytest.approx(0.95)

        # Convergence: at least one noop after provision, with drift ≈ 0.
        post_heal = [r for r in results[1:] if r.action == "noop"]
        assert post_heal, "expected a noop tick after provisioning healed drift"
        assert post_heal[0].drift == 0.0

        # The DryRun handler recorded exactly one provision call.
        assert "ProductionCluster" in handler.state.provisioned

    def test_detect_drift_shield_deny_blocks_provision(self):
        """Epistemic gate passes but shield denies: no mutation."""
        ir = _compile()
        reconciler = ir.reconciles[0]
        handler = DriftingHandler()
        loop = ReconcileLoop(reconciler, ir, handler, shield=deny_all_shield)

        results = loop.run(max_ticks=3)
        # Every tick is a noop because the shield keeps rejecting.
        assert all(r.action == "noop" for r in results)
        assert all(r.shield_approved is False for r in results)
        assert "ProductionCluster" not in handler.state.provisioned

    def test_epistemic_gate_blocks_low_certainty(self):
        """Below-threshold certainty is the gate — no shield consultation."""

        class LowCertaintyHandler(DriftingHandler):
            def observe(self, obs, manifest, continuation):
                outcome = HandlerOutcome(
                    operation="observe",
                    target=obs.name,
                    status="ok",
                    envelope=make_envelope(c=0.5, rho=self.name, delta="observed"),
                    data={
                        "resources_observed": list(manifest.resources)[:1],
                    },
                    handler=self.name,
                )
                return continuation(outcome)

        ir = _compile()
        reconciler = ir.reconciles[0]
        handler = LowCertaintyHandler()

        shield_calls = []

        def recording_shield(name, outcome, drift):
            shield_calls.append((name, drift))
            return True

        loop = ReconcileLoop(reconciler, ir, handler, shield=recording_shield)
        report = loop.tick()

        assert report.action == "noop"
        assert shield_calls == [], "shield must not be consulted when below epistemic gate"

    def test_max_retries_bounds_the_loop(self):
        """Budget exhaustion: loop halts even if drift persists."""

        class PersistentDriftHandler(DriftingHandler):
            def provision(self, manifest, resources, fabrics, continuation):
                # Do NOT heal — simulate an infrastructure failure where
                # provisioning keeps failing to reach the target state.
                outcome = HandlerOutcome(
                    operation="provision",
                    target=manifest.name,
                    status="partial",
                    envelope=make_envelope(c=0.80, rho=self.name, delta="observed"),
                    data={},
                    handler=self.name,
                )
                return continuation(outcome)

        ir = _compile()
        reconciler = ir.reconciles[0]
        handler = PersistentDriftHandler()
        loop = ReconcileLoop(reconciler, ir, handler, shield=allow_all_shield)
        results = loop.run(max_ticks=10)

        provisions = [r for r in results if r.action == "provision"]
        assert len(provisions) <= reconciler.max_retries
        assert any("exhausted" in r.note for r in results)
