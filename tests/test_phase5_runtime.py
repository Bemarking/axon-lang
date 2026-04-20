"""
AXON Runtime — Phase 5 tests (AnomalyDetector, ReflexEngine, HealKernel)
==========================================================================
Unit tests for the Cognitive Immune System runtime per docs/paper_inmune.md.

All tests are deterministic: no real clocks (HealKernel accepts a Clock),
no external SDKs, no LLMs (per reflex contract §4.2).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from axon.compiler.ir_nodes import IRHeal, IRImmune, IRReflex
from axon.runtime.handlers.base import CallerBlameError, CalleeBlameError
from axon.runtime.immune.detector import AnomalyDetector, KLDistribution
from axon.runtime.immune.health_report import (
    HealthReport,
    certainty_from_kl,
    level_at_least,
    level_from_kl,
    make_health_report,
)
from axon.runtime.immune.heal import HealKernel, Patch, default_shield_approve
from axon.runtime.immune.reflex import ReflexEngine


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════


def _immune(name="V", *, watch=("A",), sensitivity=0.5, window=20, tau="300s"):
    return IRImmune(
        name=name, watch=watch, sensitivity=sensitivity,
        window=window, scope="tenant", tau=tau, decay="exponential",
    )


def _reflex(name="R", *, trigger="V", on_level="doubt", action="drop"):
    return IRReflex(
        name=name, trigger=trigger, on_level=on_level,
        action=action, scope="tenant", sla="1ms",
    )


def _heal(name="H", *, source="V", on_level="doubt", mode="human_in_loop", max_patches=3):
    return IRHeal(
        name=name, source=source, on_level=on_level, mode=mode,
        scope="tenant", review_sla="24h", shield_ref="", max_patches=max_patches,
    )


# ═══════════════════════════════════════════════════════════════════
#  Epistemic mapping (paper §5.2)
# ═══════════════════════════════════════════════════════════════════


class TestEpistemicMapping:

    @pytest.mark.parametrize("kl,expected", [
        (0.0,  "know"),
        (0.15, "know"),
        (0.29, "know"),
        (0.31, "believe"),
        (0.5,  "believe"),
        (0.59, "believe"),
        (0.61, "speculate"),
        (0.8,  "speculate"),
        (0.89, "speculate"),
        (0.91, "doubt"),
        (2.0,  "doubt"),
    ])
    def test_level_from_kl_matches_paper_table(self, kl, expected):
        assert level_from_kl(kl) == expected

    @pytest.mark.parametrize("kl,lo,hi", [
        (0.0,   1.0, 1.0),    # know
        (0.45,  0.85, 0.99),  # believe band
        (0.75,  0.50, 0.85),  # speculate band
        (0.95,  0.0,  0.50),  # doubt band
    ])
    def test_certainty_from_kl_is_within_paper_bands(self, kl, lo, hi):
        c = certainty_from_kl(kl)
        assert lo <= c <= hi, f"c={c} outside [{lo}, {hi}] for KL={kl}"

    def test_level_at_least_ordering(self):
        assert level_at_least("doubt", "believe")
        assert level_at_least("speculate", "speculate")
        assert not level_at_least("know", "doubt")


# ═══════════════════════════════════════════════════════════════════
#  KLDistribution math
# ═══════════════════════════════════════════════════════════════════


class TestKLDistribution:

    def test_kl_identical_distributions_is_zero(self):
        a = KLDistribution(window=100)
        b = KLDistribution(window=100)
        for _ in range(50):
            a.observe("x"); a.observe("y"); a.observe("z")
            b.observe("x"); b.observe("y"); b.observe("z")
        assert a.kl_against(b) == pytest.approx(0.0, abs=1e-6)

    def test_kl_is_non_negative(self):
        a = KLDistribution(window=50); b = KLDistribution(window=50)
        for i in range(30):
            a.observe(i % 3)
            b.observe(i % 5)
        kl = a.kl_against(b)
        assert kl >= 0.0

    def test_kl_grows_with_divergence(self):
        baseline = KLDistribution(window=100)
        for v in ["a", "b", "c"] * 30:
            baseline.observe(v)

        mild = KLDistribution(window=100)
        for v in ["a"] * 60 + ["b"] * 20 + ["c"] * 10:
            mild.observe(v)

        severe = KLDistribution(window=100)
        for _ in range(90):
            severe.observe("unseen_token")

        kl_mild = mild.kl_against(baseline)
        kl_severe = severe.kl_against(baseline)
        assert kl_severe > kl_mild > 0.0


# ═══════════════════════════════════════════════════════════════════
#  AnomalyDetector
# ═══════════════════════════════════════════════════════════════════


class TestAnomalyDetector:

    def _train_normal(self, detector: AnomalyDetector, n: int = 300) -> None:
        # Uniform baseline over 10 common tokens.
        detector.train([f"token_{i%10}" for i in range(n)])

    def test_normal_observation_is_know_level(self):
        det = AnomalyDetector(ir=_immune(sensitivity=0.3))
        self._train_normal(det)
        for i in range(20):
            report = det.observe(f"token_{i%10}")
        assert report.classification in {"know", "believe"}
        assert report.envelope.c >= 0.50

    def test_anomalous_observation_raises_level(self):
        det = AnomalyDetector(ir=_immune(sensitivity=0.9, window=30))
        self._train_normal(det, n=300)
        for _ in range(30):
            report = det.observe("AXON_ZERO_DAY_TOKEN")
        # KL should be dramatic → doubt classification.
        assert report.classification in {"speculate", "doubt"}
        assert report.kl_divergence > 0.6

    def test_score_is_non_mutating(self):
        det = AnomalyDetector(ir=_immune(window=50))
        self._train_normal(det)
        before = len(det.current.samples)
        det.score("anything")
        assert len(det.current.samples) == before

    def test_report_carries_immune_name_and_window(self):
        det = AnomalyDetector(ir=_immune(name="CustomVigil", watch=("Net", "DB")))
        self._train_normal(det)
        report = det.observe("token_0")
        assert report.immune_name == "CustomVigil"
        assert report.observation_window == ("Net", "DB")


# ═══════════════════════════════════════════════════════════════════
#  ReflexEngine — determinism + O(1) latency + idempotency
# ═══════════════════════════════════════════════════════════════════


class TestReflexEngine:

    def _doubt_report(self) -> HealthReport:
        return make_health_report(
            immune_name="V",
            kl_divergence=0.95,
            signature="attack_sig_1",
        )

    def _know_report(self) -> HealthReport:
        return make_health_report(
            immune_name="V",
            kl_divergence=0.1,
            signature="normal_sig",
        )

    def test_fires_when_level_threshold_reached(self):
        engine = ReflexEngine()
        engine.register(_reflex(on_level="doubt"))
        outcomes = engine.dispatch(self._doubt_report())
        assert len(outcomes) == 1
        assert outcomes[0].fired is True
        assert outcomes[0].action == "drop"

    def test_noop_when_below_threshold(self):
        engine = ReflexEngine()
        engine.register(_reflex(on_level="doubt"))
        outcomes = engine.dispatch(self._know_report())
        assert len(outcomes) == 1
        assert outcomes[0].fired is False
        assert "below threshold" in outcomes[0].reason

    def test_idempotency_prevents_double_fire(self):
        engine = ReflexEngine()
        engine.register(_reflex())
        report = self._doubt_report()
        first  = engine.dispatch(report)
        second = engine.dispatch(report)
        assert first[0].fired is True
        assert second[0].fired is False
        assert "idempotent skip" in second[0].reason

    def test_sub_millisecond_latency(self):
        """Paper §4.2: reflex must complete in microseconds."""
        engine = ReflexEngine()
        engine.register(_reflex())
        outcomes = engine.dispatch(self._doubt_report())
        # 1ms budget × 1e3 μs/ms = 1000 μs.  We demand much better.
        assert outcomes[0].latency_us < 1000.0

    def test_custom_action_hook_is_called(self):
        engine = ReflexEngine()
        engine.register(_reflex(action="alert"))
        seen: list[tuple[str, str]] = []

        def hook(reflex, report):
            seen.append((reflex.name, report.anomaly_signature))

        engine.register_action_hook("alert", hook)
        engine.dispatch(self._doubt_report())
        assert seen == [("R", "attack_sig_1")]

    def test_signed_trace_included(self):
        engine = ReflexEngine(trace_secret=b"secret1")
        engine.register(_reflex())
        outcomes = engine.dispatch(self._doubt_report())
        assert outcomes[0].signed_trace
        assert len(outcomes[0].signed_trace) >= 16

    def test_unknown_action_rejected_on_register(self):
        engine = ReflexEngine()
        with pytest.raises(CalleeBlameError, match="unknown action"):
            engine.register(_reflex(action="implode"))

    def test_no_reflex_for_other_immune(self):
        engine = ReflexEngine()
        engine.register(_reflex(trigger="OtherImmune"))
        outcomes = engine.dispatch(self._doubt_report())
        assert outcomes == []


# ═══════════════════════════════════════════════════════════════════
#  HealKernel — Linear Logic patch lifecycle
# ═══════════════════════════════════════════════════════════════════


class TestHealKernel:

    def _doubt_report(self) -> HealthReport:
        return make_health_report(
            immune_name="V", kl_divergence=0.95, signature="sig-1",
        )

    def test_audit_only_synthesizes_and_collapses(self):
        """Paper §7.1: audit_only never applies."""
        kernel = HealKernel()
        kernel.register(_heal(mode="audit_only"))
        decisions = kernel.tick(self._doubt_report())
        assert decisions[0].outcome == "synthesized"
        assert decisions[0].patch.state == "collapsed"
        assert "without application" in decisions[0].reason

    def test_human_in_loop_waits_for_approval(self):
        kernel = HealKernel()
        kernel.register(_heal(mode="human_in_loop"))
        decisions = kernel.tick(self._doubt_report())
        assert decisions[0].outcome == "synthesized"
        assert decisions[0].patch.state == "synthesized"
        assert "waiting" in decisions[0].reason.lower()

    def test_approval_transitions_through_applied_to_collapsed(self):
        """Linear Logic: Synthesized ⊸ Applied ⊸ Collapsed."""
        applied_payloads: list[str] = []

        def fake_apply(patch):
            applied_payloads.append(patch.patch_id)
            return {"ok": True}

        kernel = HealKernel(apply=fake_apply)
        kernel.register(_heal(mode="human_in_loop"))
        [decision] = kernel.tick(self._doubt_report())
        patch_id = decision.patch.patch_id

        final = kernel.approve(patch_id, approver="alice")
        assert final.outcome == "applied"
        assert final.patch.state == "collapsed"
        assert applied_payloads == [patch_id]
        # Linear Logic — same token cannot be re-approved.
        with pytest.raises(CallerBlameError, match="state 'collapsed'"):
            kernel.approve(patch_id, approver="bob")

    def test_reject_produces_rolled_back_terminal(self):
        kernel = HealKernel()
        kernel.register(_heal(mode="human_in_loop"))
        [decision] = kernel.tick(self._doubt_report())
        rolled = kernel.reject(decision.patch.patch_id, approver="alice")
        assert rolled.outcome == "rolled_back"
        assert rolled.patch.state == "rejected"

    def test_adversarial_autonomous_with_shield_approve(self):
        applied_calls: list[str] = []

        def fake_apply(patch):
            applied_calls.append(patch.patch_id)
            return {"ok": True}

        def shield_ok(_ir, _patch):
            return True

        kernel = HealKernel(apply=fake_apply, shield_approve=shield_ok)
        kernel.register(_heal(mode="adversarial"))
        [decision] = kernel.tick(self._doubt_report())
        assert decision.outcome == "applied"
        assert decision.patch.state == "collapsed"
        assert applied_calls

    def test_adversarial_shield_deny_blocks(self):
        def shield_no(_ir, _patch):
            return False

        kernel = HealKernel(shield_approve=shield_no)
        kernel.register(_heal(mode="adversarial"))
        [decision] = kernel.tick(self._doubt_report())
        assert decision.outcome == "denied"
        assert decision.patch.state == "rejected"

    def test_max_patches_respected(self):
        kernel = HealKernel()
        kernel.register(_heal(mode="audit_only", max_patches=2))
        kernel.tick(self._doubt_report())
        kernel.tick(self._doubt_report())
        decisions = kernel.tick(self._doubt_report())
        assert decisions[0].outcome == "skipped"
        assert "max_patches" in decisions[0].reason

    def test_skipped_when_below_level_threshold(self):
        kernel = HealKernel()
        kernel.register(_heal(on_level="doubt"))
        mild = make_health_report(immune_name="V", kl_divergence=0.5)
        decisions = kernel.tick(mild)
        assert decisions[0].outcome == "skipped"
        assert "below heal threshold" in decisions[0].reason

    def test_approve_unknown_patch_raises(self):
        kernel = HealKernel()
        kernel.register(_heal())
        with pytest.raises(CallerBlameError, match="unknown patch"):
            kernel.approve("ghost-id", approver="alice")


# ═══════════════════════════════════════════════════════════════════
#  HealthReport temporal decay (paper §5.3)
# ═══════════════════════════════════════════════════════════════════


class TestHealthReportDecay:

    def test_exponential_decay_at_half_life(self):
        report = make_health_report(
            immune_name="V", kl_divergence=0.95,
            tau_half_life=100.0, decay="exponential",
        )
        emitted = datetime.fromisoformat(report.envelope.tau)
        # After exactly one half-life, certainty should be ~half.
        future = emitted + timedelta(seconds=100)
        decayed = report.c_at(future)
        assert decayed == pytest.approx(report.envelope.c / 2, abs=1e-3)

    def test_is_active_purges_after_5_tau(self):
        report = make_health_report(
            immune_name="V", kl_divergence=0.95, tau_half_life=10.0,
        )
        emitted = datetime.fromisoformat(report.envelope.tau)
        assert report.is_active(emitted + timedelta(seconds=49))
        assert not report.is_active(emitted + timedelta(seconds=51))

    def test_decay_none_preserves_certainty(self):
        report = make_health_report(
            immune_name="V", kl_divergence=0.95,
            tau_half_life=10.0, decay="none",
        )
        emitted = datetime.fromisoformat(report.envelope.tau)
        future = emitted + timedelta(seconds=10000)
        assert report.c_at(future) == report.envelope.c
