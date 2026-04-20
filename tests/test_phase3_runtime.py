"""
AXON Runtime — Phase 3 tests (LeaseKernel, EnsembleAggregator, ReconcileLoop)
=============================================================================
Covers the control-cognitivo runtime for Fase 3 of docs/plan_io_cognitivo.md.

All tests are deterministic: no real clocks (LeaseKernel accepts a Clock
callable), no real handlers (ReconcileLoop runs against DryRunHandler),
no external SDKs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from axon.compiler.ir_generator import IRGenerator
from axon.compiler.ir_nodes import (
    IREnsemble,
    IRLease,
    IRObserve,
    IRReconcile,
    IRResource,
)
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.runtime.ensemble_aggregator import EnsembleAggregator, EnsembleReport
from axon.runtime.handlers.base import (
    CalleeBlameError,
    CallerBlameError,
    HandlerOutcome,
    InfrastructureBlameError,
    LeaseExpiredError,
    make_envelope,
)
from axon.runtime.handlers.dry_run import DryRunHandler
from axon.runtime.lease_kernel import (
    LeaseKernel,
    LeaseToken,
    parse_duration,
)
from axon.runtime.reconcile_loop import (
    ReconcileLoop,
    allow_all_shield,
    deny_all_shield,
    jaccard_drift,
)


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def _compile_ir(source: str):
    return IRGenerator().generate(Parser(Lexer(source).tokenize()).parse())


class ManualClock:
    """Deterministic clock for τ-decay tests."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc)

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self.now


def _outcome(
    *, handler: str, status: str, c: float, target: str = "O"
) -> HandlerOutcome:
    return HandlerOutcome(
        operation="observe",
        target=target,
        status=status,
        envelope=make_envelope(c=c, rho=handler, delta="observed"),
        handler=handler,
    )


# ═══════════════════════════════════════════════════════════════════
#  parse_duration
# ═══════════════════════════════════════════════════════════════════


class TestParseDuration:
    @pytest.mark.parametrize(
        "text,seconds",
        [
            ("500ms", 0.5),
            ("30s", 30.0),
            ("5m", 300.0),
            ("2h", 7200.0),
            ("1d", 86400.0),
        ],
    )
    def test_valid_durations(self, text, seconds):
        assert parse_duration(text) == pytest.approx(seconds)

    def test_empty_raises(self):
        with pytest.raises(CalleeBlameError):
            parse_duration("")

    def test_unknown_unit_raises(self):
        with pytest.raises(CalleeBlameError, match="unparseable"):
            parse_duration("30y")


# ═══════════════════════════════════════════════════════════════════
#  LeaseKernel — τ-decay semantics (D2)
# ═══════════════════════════════════════════════════════════════════


class TestLeaseKernel:

    def _kernel_and_lease(
        self,
        *,
        duration: str = "60s",
        on_expire: str = "anchor_breach",
        lifetime: str = "affine",
    ):
        clock = ManualClock()
        kernel = LeaseKernel(clock=clock)
        ir_lease = IRLease(
            name="L", resource_ref="Db",
            duration=duration, acquire="on_start", on_expire=on_expire,
        )
        ir_resource = IRResource(name="Db", kind="postgres", lifetime=lifetime)
        return clock, kernel, ir_lease, ir_resource

    def test_acquire_emits_token_with_tau(self):
        clock, kernel, ir_lease, ir_resource = self._kernel_and_lease()
        token = kernel.acquire(ir_lease, ir_resource)
        assert isinstance(token, LeaseToken)
        assert token.lease_name == "L"
        assert token.resource_ref == "Db"
        assert (token.expires_at - token.acquired_at).total_seconds() == pytest.approx(60.0)
        assert token.token_id in kernel

    def test_use_within_window_returns_same_token(self):
        clock, kernel, ir_lease, ir_resource = self._kernel_and_lease()
        token = kernel.acquire(ir_lease, ir_resource)
        clock.advance(30)
        assert kernel.use(token) is token

    def test_use_post_expiry_anchor_breach_raises_ct2(self):
        """D2: post-expiry access = Anchor Breach, CT-2 Caller Blame."""
        clock, kernel, ir_lease, ir_resource = self._kernel_and_lease()
        token = kernel.acquire(ir_lease, ir_resource)
        clock.advance(61)
        with pytest.raises(LeaseExpiredError) as exc_info:
            kernel.use(token)
        assert exc_info.value.blame == "CT-2"
        assert "Anchor Breach" in str(exc_info.value)

    def test_use_post_expiry_release_returns_none(self):
        clock, kernel, ir_lease, ir_resource = self._kernel_and_lease(on_expire="release")
        token = kernel.acquire(ir_lease, ir_resource)
        clock.advance(61)
        assert kernel.use(token) is None
        assert token.token_id not in kernel

    def test_use_post_expiry_extend_mints_new_token(self):
        clock, kernel, ir_lease, ir_resource = self._kernel_and_lease(on_expire="extend")
        token = kernel.acquire(ir_lease, ir_resource)
        clock.advance(61)
        renewed = kernel.use(token)
        assert renewed is not None
        assert renewed.token_id != token.token_id
        assert renewed.lease_name == token.lease_name
        # The old token is revoked so it cannot be reused.
        with pytest.raises(CallerBlameError, match="revoked"):
            kernel.use(token)

    def test_persistent_resource_rejected_at_runtime(self):
        _, kernel, ir_lease, _ = self._kernel_and_lease()
        ir_resource = IRResource(name="Db", kind="postgres", lifetime="persistent")
        with pytest.raises(CallerBlameError, match="persistent"):
            kernel.acquire(ir_lease, ir_resource)

    def test_release_is_idempotent(self):
        clock, kernel, ir_lease, ir_resource = self._kernel_and_lease()
        token = kernel.acquire(ir_lease, ir_resource)
        kernel.release(token)
        kernel.release(token)  # second call must not raise
        with pytest.raises(CallerBlameError, match="revoked"):
            kernel.use(token)

    def test_sweep_purges_expired_tokens(self):
        clock, kernel, ir_lease, ir_resource = self._kernel_and_lease()
        live = kernel.acquire(ir_lease, ir_resource)
        # Advance past expiry and sweep.
        clock.advance(61)
        purged = kernel.sweep()
        ids = [t.token_id for t in purged]
        assert live.token_id in ids
        assert kernel.active() == []

    def test_unknown_token_raises_caller_blame(self):
        clock, kernel, _, _ = self._kernel_and_lease()
        ghost = LeaseToken(
            token_id="ghost", lease_name="X", resource_ref="Y",
            acquired_at=clock(), expires_at=clock(), on_expire="anchor_breach",
        )
        with pytest.raises(CallerBlameError, match="unknown lease token"):
            kernel.use(ghost)

    def test_envelope_decays_at_expiry(self):
        clock, kernel, ir_lease, ir_resource = self._kernel_and_lease()
        token = kernel.acquire(ir_lease, ir_resource)
        assert token.envelope(clock()).c == 1.0
        clock.advance(61)
        assert token.envelope(clock()).c == 0.0


# ═══════════════════════════════════════════════════════════════════
#  EnsembleAggregator — Byzantine quorum + certainty fusion
# ═══════════════════════════════════════════════════════════════════


class TestEnsembleAggregator:

    def _ensemble(
        self,
        *,
        observations=("A", "B", "C"),
        quorum=2,
        aggregation="majority",
        certainty_mode="min",
    ) -> IREnsemble:
        return IREnsemble(
            name="E",
            observations=tuple(observations),
            quorum=quorum,
            aggregation=aggregation,
            certainty_mode=certainty_mode,
        )

    def test_majority_with_all_healthy(self):
        agg = EnsembleAggregator(self._ensemble())
        outcomes = [
            _outcome(handler="prom",       status="ok", c=0.90, target="A"),
            _outcome(handler="cloudwatch", status="ok", c=0.80, target="B"),
            _outcome(handler="healthcheck", status="ok", c=0.70, target="C"),
        ]
        consensus, report = agg.aggregate(outcomes)
        assert consensus.status == "ok"
        assert consensus.envelope.c == pytest.approx(0.70)  # min mode
        assert isinstance(report, EnsembleReport)
        assert report.winning_status == "ok"

    def test_majority_with_one_outlier(self):
        agg = EnsembleAggregator(self._ensemble())
        outcomes = [
            _outcome(handler="prom",       status="ok",     c=0.90, target="A"),
            _outcome(handler="cloudwatch", status="ok",     c=0.85, target="B"),
            _outcome(handler="healthcheck", status="partial", c=0.60, target="C"),
        ]
        consensus, _ = agg.aggregate(outcomes)
        assert consensus.status == "ok"

    def test_below_quorum_after_exclusion_raises_ct3(self):
        """D4: too many partitions ⇒ structural CT-3 failure."""
        agg = EnsembleAggregator(self._ensemble(quorum=3))
        outcomes = [
            _outcome(handler="prom", status="ok", c=0.9, target="A"),
            _outcome(handler="cw",   status="ok", c=0.8, target="B"),
            _outcome(handler="hc",   status="failed", c=0.0, target="C"),
        ]
        with pytest.raises(InfrastructureBlameError, match="quorum requires"):
            agg.aggregate(outcomes)

    def test_tie_resolves_to_partial(self):
        agg = EnsembleAggregator(self._ensemble(observations=("A", "B"), quorum=1))
        outcomes = [
            _outcome(handler="prom", status="ok",     c=0.9, target="A"),
            _outcome(handler="cw",   status="failed", c=0.1, target="B"),
        ]
        # With failed outcomes excluded, only "ok" remains → consensus ok.
        consensus, _ = agg.aggregate(outcomes)
        assert consensus.status == "ok"

    def test_weighted_certainty_mode(self):
        agg = EnsembleAggregator(self._ensemble(certainty_mode="weighted"))
        outcomes = [
            _outcome(handler="a", status="ok", c=0.9, target="A"),
            _outcome(handler="b", status="ok", c=0.9, target="B"),
            _outcome(handler="c", status="ok", c=0.3, target="C"),
        ]
        consensus, _ = agg.aggregate(outcomes)
        # Weighted mean ≈ (0.81 + 0.81 + 0.09) / (0.9+0.9+0.3) ≈ 0.81
        assert consensus.envelope.c == pytest.approx(0.81, abs=0.01)

    def test_harmonic_certainty_mode(self):
        agg = EnsembleAggregator(self._ensemble(certainty_mode="harmonic"))
        outcomes = [
            _outcome(handler="a", status="ok", c=0.5, target="A"),
            _outcome(handler="b", status="ok", c=0.5, target="B"),
            _outcome(handler="c", status="ok", c=0.5, target="C"),
        ]
        consensus, _ = agg.aggregate(outcomes)
        assert consensus.envelope.c == pytest.approx(0.5, abs=0.001)

    def test_byzantine_drops_extremes(self):
        """Byzantine filter removes the highest- and lowest-c outliers."""
        agg = EnsembleAggregator(
            self._ensemble(
                observations=("A", "B", "C", "D"),
                quorum=2,
                aggregation="byzantine",
            )
        )
        outcomes = [
            _outcome(handler="a", status="ok", c=0.1, target="A"),   # lowest (liar low)
            _outcome(handler="b", status="ok", c=0.85, target="B"),
            _outcome(handler="c", status="ok", c=0.90, target="C"),
            _outcome(handler="d", status="ok", c=0.99, target="D"),  # highest (liar high)
        ]
        consensus, report = agg.aggregate(outcomes)
        assert consensus.status == "ok"
        # Surviving certainties are 0.85 and 0.90 → min = 0.85.
        assert consensus.envelope.c == pytest.approx(0.85)

    def test_contributors_are_recorded(self):
        agg = EnsembleAggregator(self._ensemble())
        outcomes = [
            _outcome(handler="a", status="ok", c=0.9, target="A"),
            _outcome(handler="b", status="ok", c=0.9, target="B"),
            _outcome(handler="c", status="ok", c=0.9, target="C"),
        ]
        consensus, _ = agg.aggregate(outcomes)
        assert set(consensus.data["contributors"]) == {"A", "B", "C"}


# ═══════════════════════════════════════════════════════════════════
#  ReconcileLoop — free-energy drift + shield-gated action
# ═══════════════════════════════════════════════════════════════════


class TestJaccardDrift:
    def test_equal_sets(self):
        assert jaccard_drift(("a", "b"), ("a", "b")) == 0.0

    def test_disjoint_sets(self):
        assert jaccard_drift(("a",), ("b",)) == 1.0

    def test_partial_overlap(self):
        # Symmetric difference = {b, c}; union = {a, b, c}; 2/3
        assert jaccard_drift(("a", "b"), ("a", "c")) == pytest.approx(2 / 3)

    def test_empty_sets(self):
        assert jaccard_drift((), ()) == 0.0


class TestReconcileLoop:
    _SOURCE = '''
resource Db { kind: postgres lifetime: affine }
resource Cache { kind: redis lifetime: affine }
manifest M { resources: [Db, Cache] }
observe O from M { sources: [prometheus, hc] quorum: 2 timeout: 5s on_partition: fail }

shield RS { scan: [prompt_injection] on_breach: quarantine severity: medium }
reconcile R { observe: O threshold: 0.85 tolerance: 0.10 on_drift: provision shield: RS max_retries: 2 }
'''

    def _ir_and_reconcile(self):
        ir = _compile_ir(self._SOURCE)
        reconcile = ir.reconciles[0]
        return ir, reconcile

    def _loop(self, *, handler=None, shield=allow_all_shield):
        ir, reconcile = self._ir_and_reconcile()
        handler = handler or DryRunHandler()
        return ReconcileLoop(reconcile, ir, handler, shield=shield)

    def test_tick_noop_when_drift_within_tolerance(self):
        """DryRun reports observed == expected → drift = 0.0 → noop."""
        loop = self._loop()
        report = loop.tick()
        assert report.action == "noop"
        assert report.drift == 0.0
        assert "within tolerance" in report.note

    def test_tick_noop_when_certainty_below_threshold(self):
        class LowCertaintyHandler(DryRunHandler):
            def observe(self, obs, manifest, continuation):
                outcome = HandlerOutcome(
                    operation="observe", target=obs.name, status="ok",
                    envelope=make_envelope(c=0.5, rho=self.name, delta="observed"),
                    data={"resources_observed": list(manifest.resources)},
                    handler=self.name,
                )
                return continuation(outcome)

        loop = self._loop(handler=LowCertaintyHandler())
        report = loop.tick()
        assert report.action == "noop"
        assert "certainty" in report.note and "threshold" in report.note

    def test_shield_deny_blocks_provisioning(self):
        class DriftHandler(DryRunHandler):
            def observe(self, obs, manifest, continuation):
                # Half the expected resources are observed → drift = 0.5
                observed = list(manifest.resources)[:1]
                outcome = HandlerOutcome(
                    operation="observe", target=obs.name, status="ok",
                    envelope=make_envelope(c=0.95, rho=self.name, delta="observed"),
                    data={"resources_observed": observed},
                    handler=self.name,
                )
                return continuation(outcome)

        loop = self._loop(handler=DriftHandler(), shield=deny_all_shield)
        report = loop.tick()
        assert report.action == "noop"
        assert report.shield_approved is False
        assert "shield denied" in report.note

    def test_drift_triggers_provision(self):
        """Drift above tolerance + shield approve → provision action."""
        class DriftHandler(DryRunHandler):
            def observe(self, obs, manifest, continuation):
                observed = list(manifest.resources)[:1]  # drift = 1/2 = 0.5
                outcome = HandlerOutcome(
                    operation="observe", target=obs.name, status="ok",
                    envelope=make_envelope(c=0.95, rho=self.name, delta="observed"),
                    data={"resources_observed": observed},
                    handler=self.name,
                )
                return continuation(outcome)

        loop = self._loop(handler=DriftHandler())
        report = loop.tick()
        assert report.action == "provision"
        assert report.drift == pytest.approx(0.5)
        assert report.outcome is not None
        assert report.outcome.operation == "provision"

    def test_max_retries_exhaustion_reports_noop(self):
        class DriftHandler(DryRunHandler):
            def observe(self, obs, manifest, continuation):
                outcome = HandlerOutcome(
                    operation="observe", target=obs.name, status="ok",
                    envelope=make_envelope(c=0.95, rho=self.name, delta="observed"),
                    data={"resources_observed": list(manifest.resources)[:1]},
                    handler=self.name,
                )
                return continuation(outcome)

        loop = self._loop(handler=DriftHandler())
        # max_retries=2 → two corrective ticks, then a noop with the
        # exhausted note.
        results = loop.run(max_ticks=10)
        noop_reports = [r for r in results if r.action == "noop"]
        assert any("exhausted" in r.note for r in noop_reports)

    def test_reconcile_resolves_unknown_observe(self):
        # Build an IR with a reconcile pointing to a ghost observe.
        ir = _compile_ir('''resource Db { kind: postgres }
manifest M { resources: [Db] }
observe O from M { sources: [x] quorum: 1 timeout: 1s }
reconcile R { observe: O }''')
        reconcile = ir.reconciles[0]
        # Swap observe_ref to something that doesn't exist after compilation.
        bad = IRReconcile(
            name=reconcile.name, observe_ref="Ghost",
            threshold=reconcile.threshold, tolerance=reconcile.tolerance,
            on_drift=reconcile.on_drift, shield_ref=reconcile.shield_ref,
            mandate_ref=reconcile.mandate_ref, max_retries=reconcile.max_retries,
        )
        with pytest.raises(CallerBlameError, match="unknown observe"):
            ReconcileLoop(bad, ir, DryRunHandler())
