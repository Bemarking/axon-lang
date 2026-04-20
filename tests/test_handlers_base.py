"""
AXON Runtime — Handler Base Tests
===================================
Verifies the abstract Handler protocol, ΛD envelope, HandlerRegistry,
Blame Calculus (CT-1/2/3) exceptions, and the default Free-Monad
interpretation over the Intention Tree produced by IRGenerator.

These tests have NO external dependencies — they run in CI without
Docker, Kubernetes, Terraform, or AWS credentials.
"""

from __future__ import annotations

import pytest

from axon.compiler.ir_generator import IRGenerator
from axon.compiler.ir_nodes import IRManifest, IRObserve, IRProgram
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.runtime.handlers.base import (
    BLAME_CALLEE,
    BLAME_CALLER,
    BLAME_INFRASTRUCTURE,
    CalleeBlameError,
    CallerBlameError,
    Handler,
    HandlerOutcome,
    HandlerRegistry,
    InfrastructureBlameError,
    LambdaEnvelope,
    LeaseExpiredError,
    NetworkPartitionError,
    identity_continuation,
    make_envelope,
    now_iso,
)
from axon.runtime.handlers.dry_run import DryRunHandler, DryRunState


def _ir(source: str) -> IRProgram:
    return IRGenerator().generate(Parser(Lexer(source).tokenize()).parse())


_SAMPLE_IO = """
resource Db { kind: postgres endpoint: "db:5432" lifetime: linear certainty_floor: 0.9 }
resource Cache { kind: redis lifetime: affine }
fabric Vpc { provider: aws region: "us-east-1" zones: 2 ephemeral: false }
manifest Prod { resources: [Db, Cache] fabric: Vpc zones: 2 compliance: [HIPAA] }
observe Health from Prod {
  sources: [prometheus, healthcheck]
  quorum: 2
  timeout: 5s
  on_partition: fail
  certainty_floor: 0.85
}
"""


# ═══════════════════════════════════════════════════════════════════
#  LambdaEnvelope — ΛD epistemic vector contract
# ═══════════════════════════════════════════════════════════════════


class TestLambdaEnvelope:
    def test_defaults(self):
        env = LambdaEnvelope()
        assert env.c == 1.0
        assert env.delta == "observed"

    def test_c_must_be_within_unit_interval(self):
        with pytest.raises(ValueError, match=r"c must be in \[0.0, 1.0\]"):
            LambdaEnvelope(c=1.1)
        with pytest.raises(ValueError):
            LambdaEnvelope(c=-0.1)

    def test_invalid_derivation_rejected(self):
        with pytest.raises(ValueError, match="delta must be one of"):
            LambdaEnvelope(delta="fabricated")

    def test_decayed_preserves_trace(self):
        env = LambdaEnvelope(c=0.9, tau="T", rho="h", delta="observed")
        decayed = env.decayed()
        assert decayed.c == 0.0
        assert decayed.tau == "T"
        assert decayed.rho == "h"

    def test_make_envelope_auto_populates_tau(self):
        env = make_envelope(c=0.8, rho="handler_x", delta="inferred")
        assert env.c == 0.8
        assert env.rho == "handler_x"
        assert env.delta == "inferred"
        assert env.tau != ""
        # ISO format check: contains the year and 'T' separator
        assert "T" in env.tau

    def test_make_envelope_respects_explicit_tau(self):
        env = make_envelope(tau="2026-01-01T00:00:00+00:00", c=0.5)
        assert env.tau == "2026-01-01T00:00:00+00:00"

    def test_now_iso_returns_string(self):
        now = now_iso()
        assert isinstance(now, str)
        assert len(now) > 10


# ═══════════════════════════════════════════════════════════════════
#  Blame Calculus — CT-1/2/3 exception hierarchy
# ═══════════════════════════════════════════════════════════════════


class TestBlameCalculus:
    def test_blame_tags_are_distinct(self):
        assert BLAME_CALLEE != BLAME_CALLER != BLAME_INFRASTRUCTURE

    def test_callee_blame_tagged(self):
        err = CalleeBlameError("handler bug")
        assert err.blame == BLAME_CALLEE
        assert "CT-1" in str(err)

    def test_caller_blame_tagged(self):
        err = CallerBlameError("anchor breach")
        assert err.blame == BLAME_CALLER
        assert "CT-2" in str(err)

    def test_infrastructure_blame_tagged(self):
        err = InfrastructureBlameError("quota exceeded")
        assert err.blame == BLAME_INFRASTRUCTURE
        assert "CT-3" in str(err)

    def test_network_partition_is_infrastructure_blame(self):
        err = NetworkPartitionError("partition")
        assert isinstance(err, InfrastructureBlameError)
        assert err.blame == BLAME_INFRASTRUCTURE

    def test_lease_expired_is_caller_blame(self):
        err = LeaseExpiredError("lease τ elapsed")
        assert isinstance(err, CallerBlameError)
        assert err.blame == BLAME_CALLER

    def test_cause_chaining(self):
        root = RuntimeError("root")
        err = InfrastructureBlameError("wrapping", cause=root)
        assert err.__cause__ is root


# ═══════════════════════════════════════════════════════════════════
#  HandlerOutcome — contract
# ═══════════════════════════════════════════════════════════════════


class TestHandlerOutcome:
    def test_valid_outcome_round_trips_to_dict(self):
        env = make_envelope(c=0.9, rho="t")
        o = HandlerOutcome(
            operation="provision",
            target="M",
            status="ok",
            envelope=env,
            data={"k": "v"},
            handler="t",
        )
        d = o.to_dict()
        assert d["operation"] == "provision"
        assert d["target"] == "M"
        assert d["envelope"]["c"] == 0.9
        assert d["data"] == {"k": "v"}

    def test_invalid_status_rejected(self):
        env = make_envelope()
        with pytest.raises(ValueError, match="status must be one of"):
            HandlerOutcome(
                operation="x",
                target="y",
                status="weird",
                envelope=env,
            )


# ═══════════════════════════════════════════════════════════════════
#  DryRunHandler — golden path + partition simulation
# ═══════════════════════════════════════════════════════════════════


class TestDryRunHandlerInterpretation:
    def test_interpret_program_emits_provision_and_observe(self):
        ir = _ir(_SAMPLE_IO)
        h = DryRunHandler()
        outcomes = h.interpret_program(ir)
        assert len(outcomes) == 2
        ops = [o.operation for o in outcomes]
        assert ops == ["provision", "observe"]

    def test_outcomes_carry_lambda_envelope(self):
        ir = _ir(_SAMPLE_IO)
        outcomes = DryRunHandler().interpret_program(ir)
        for outcome in outcomes:
            assert isinstance(outcome.envelope, LambdaEnvelope)
            assert outcome.envelope.c == 1.0
            assert outcome.envelope.rho == "dry_run"

    def test_provision_records_resource_kinds(self):
        ir = _ir(_SAMPLE_IO)
        h = DryRunHandler()
        h.interpret_program(ir)
        record = h.state.provisioned["Prod"]
        kinds = {r["kind"] for r in record["resources"]}
        assert kinds == {"postgres", "redis"}
        assert record["fabric"]["provider"] == "aws"

    def test_observe_records_quorum(self):
        ir = _ir(_SAMPLE_IO)
        h = DryRunHandler()
        h.interpret_program(ir)
        assert len(h.state.observations) == 1
        obs = h.state.observations[0]
        assert obs["quorum"] == 2
        assert obs["on_partition"] == "fail"

    def test_simulated_partition_raises_ct3(self):
        """D4: partition is void (⊥) and raises CT-3 — not doubt."""
        ir = _ir(_SAMPLE_IO)
        h = DryRunHandler(simulate_partition=True)
        with pytest.raises(NetworkPartitionError):
            h.interpret_program(ir)

    def test_continuation_transforms_outcome(self):
        ir = _ir(_SAMPLE_IO)
        h = DryRunHandler()

        def tag_with_retry(outcome: HandlerOutcome) -> HandlerOutcome:
            return HandlerOutcome(
                operation=outcome.operation,
                target=outcome.target,
                status=outcome.status,
                envelope=outcome.envelope,
                data={**outcome.data, "retries": 0},
                handler=outcome.handler,
            )

        outcomes = h.interpret_program(ir, continuation=tag_with_retry)
        for o in outcomes:
            assert o.data.get("retries") == 0

    def test_empty_program_yields_no_outcomes(self):
        ir = _ir("persona E { tone: precise }")
        outcomes = DryRunHandler().interpret_program(ir)
        assert outcomes == []

    def test_dry_run_state_isolation_between_instances(self):
        ir = _ir(_SAMPLE_IO)
        a = DryRunHandler()
        b = DryRunHandler()
        a.interpret_program(ir)
        assert "Prod" in a.state.provisioned
        assert b.state.provisioned == {}


# ═══════════════════════════════════════════════════════════════════
#  HandlerRegistry
# ═══════════════════════════════════════════════════════════════════


class TestHandlerRegistry:
    def test_register_and_lookup(self):
        reg = HandlerRegistry()
        h = DryRunHandler()
        reg.register(h)
        assert reg.get("dry_run") is h
        assert "dry_run" in reg.names()

    def test_double_register_without_replace_raises(self):
        reg = HandlerRegistry()
        reg.register(DryRunHandler())
        with pytest.raises(CalleeBlameError, match="already registered"):
            reg.register(DryRunHandler())

    def test_replace_allowed_with_flag(self):
        reg = HandlerRegistry()
        first = DryRunHandler()
        second = DryRunHandler()
        reg.register(first)
        reg.register(second, replace=True)
        assert reg.get("dry_run") is second

    def test_missing_handler_raises_ct2(self):
        reg = HandlerRegistry()
        with pytest.raises(CallerBlameError, match="no handler registered"):
            reg.get("ghost")

    def test_close_all_is_safe_after_explicit_unregister(self):
        reg = HandlerRegistry()
        reg.register(DryRunHandler())
        reg.unregister("dry_run")
        reg.close_all()  # must not raise
        assert reg.names() == []

    def test_membership_and_iteration(self):
        reg = HandlerRegistry()
        h = DryRunHandler()
        reg.register(h)
        assert "dry_run" in reg
        assert list(reg) == [h]


# ═══════════════════════════════════════════════════════════════════
#  Handler protocol — abstract method enforcement
# ═══════════════════════════════════════════════════════════════════


class TestHandlerAbstractContract:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Handler()  # type: ignore[abstract]

    def test_observe_target_must_exist_in_manifest_dict(self):
        """If observe.target is missing from manifests dict, raise CT-2."""
        h = DryRunHandler()

        from axon.compiler.ir_nodes import IRIntentionTree

        ghost_obs = IRObserve(name="X", target="Ghost", sources=("s",), on_partition="fail")
        tree = IRIntentionTree(operations=(ghost_obs,))
        with pytest.raises(CallerBlameError, match="targets unknown manifest"):
            h.interpret(tree, manifests={})

    def test_identity_continuation_is_pass_through(self):
        env = make_envelope()
        o = HandlerOutcome(operation="p", target="t", status="ok", envelope=env)
        assert identity_continuation(o) is o
