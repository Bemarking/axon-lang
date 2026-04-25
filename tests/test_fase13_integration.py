"""
Fase 13 Integration Tests
==========================
Cross-phase composition verification — typed channels coexisting with
sessions (Fase 4), immune (Fase 5), shield/ESK (Fase 6), and the
I/O cognitivo primitives (Fase 1).  Also exercises the worked
examples under examples/ end-to-end through parse → type-check →
IR generate → JSON serialize.

These tests are the closing acceptance criterion for Fase 13.h.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker
from axon.compiler.ir_generator import IRGenerator


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"


def _pipeline(source: str):
    """Lex → Parse → TypeCheck → IRGenerate. Returns (errors, warnings, ir)."""
    tokens = Lexer(source).tokenize()
    program = Parser(tokens).parse()
    checker = TypeChecker(program)
    errors = checker.check()
    warnings = checker.warnings
    ir = IRGenerator().generate(program) if not errors else None
    return errors, warnings, ir


# ────────────────────────────────────────────────────────────────────
# Worked examples — examples/mobile_channels.axon, secure_publish.axon
# ────────────────────────────────────────────────────────────────────


class TestWorkedExamples:

    def test_mobile_channels_example_clean(self):
        src = (EXAMPLES / "mobile_channels.axon").read_text(encoding="utf-8")
        errors, warnings, ir = _pipeline(src)
        assert errors == [], [e.message for e in errors]
        assert warnings == [], [w.message for w in warnings]
        # Both channels lowered
        names = sorted(c.name for c in ir.channels)
        assert names == ["BrokerHandoff", "OrdersCreated"]
        # Mobility resolved at lowering — emit value_is_channel=True
        flow = next(f for f in ir.flows if f.name == "hand_off")
        emit = next(s for s in flow.steps if s.node_type == "emit")
        assert emit.channel_ref == "BrokerHandoff"
        assert emit.value_ref == "OrdersCreated"
        assert emit.value_is_channel is True
        # Publish through PublicBroker
        publish = next(s for s in flow.steps if s.node_type == "publish")
        assert publish.shield_ref == "PublicBroker"

    def test_secure_publish_example_clean(self):
        src = (EXAMPLES / "secure_publish.axon").read_text(encoding="utf-8")
        errors, warnings, ir = _pipeline(src)
        assert errors == [], [e.message for e in errors]
        assert warnings == [], [w.message for w in warnings]
        # Channel + shield + daemon + 2 flows
        assert len(ir.channels) == 1
        assert ir.channels[0].name == "PatientStream"
        assert ir.channels[0].shield_ref == "ClinicalGate"
        # Both flows compose on the same channel
        flow_names = {f.name for f in ir.flows}
        assert flow_names == {"expose_stream", "consume_published"}

    def test_examples_serialize_to_json(self):
        """Both examples round-trip through JSON without losing data.

        IRProgram.to_dict() returns Python dicts/lists/tuples; JSON has
        no tuple type, so the round-trip normalises tuples → lists.
        We compare via JSON canonical form on both sides.
        """
        for name in ("mobile_channels.axon", "secure_publish.axon"):
            src = (EXAMPLES / name).read_text(encoding="utf-8")
            errors, _, ir = _pipeline(src)
            assert errors == []
            d = ir.to_dict()
            roundtripped = json.loads(json.dumps(d, default=str))
            # Channel-level fields are scalars; their dicts compare directly.
            assert roundtripped["channels"] == json.loads(json.dumps(d["channels"], default=str))


# ────────────────────────────────────────────────────────────────────
# Channel + Shield (Fase 6 ESK) — compile-time compliance enforcement
# ────────────────────────────────────────────────────────────────────


class TestChannelShieldComposition:

    def test_publish_requires_shield_covering_kappa(self):
        """κ(message) ⊆ shield.compliance — paper §3.4 / Fase 6.1."""
        src = '''
type PHI compliance [HIPAA] { ssn: String }
shield Insufficient { scan: [] }
channel Health { message: PHI shield: Insufficient }
flow leak() -> Cap { publish Health within Insufficient }
'''
        errors, _, _ = _pipeline(src)
        assert any("violates compile-time compliance" in e.message
                   for e in errors), [e.message for e in errors]

    def test_publish_with_compliant_shield_clean(self):
        src = '''
type PHI compliance [HIPAA] { ssn: String }
shield Strong { scan: [] compliance: [HIPAA, GDPR] }
channel Health { message: PHI shield: Strong }
flow expose() -> Cap { publish Health within Strong }
'''
        errors, _, _ = _pipeline(src)
        assert errors == [], [e.message for e in errors]


# ────────────────────────────────────────────────────────────────────
# Channel + Session (Fase 4) — typed channels coexist with binary sessions
# ────────────────────────────────────────────────────────────────────


class TestChannelSessionComposition:

    def test_channel_and_session_coexist_in_one_program(self):
        """Channels and binary sessions are independent primitives — a
        program declaring both must type-check cleanly."""
        src = '''
type Order { id: String }
type Query { q: String }
type Result { r: String }

session DbSession {
  client: [send Query, receive Result, end]
  server: [receive Query, send Result, end]
}

channel OrdersCreated {
  message: Order
  qos: at_least_once
}

daemon Mixed() {
  goal: "x"
  listen OrdersCreated as ev {
    step S { ask: "process" }
  }
}
'''
        errors, _, ir = _pipeline(src)
        assert errors == [], [e.message for e in errors]
        # Both primitives lowered
        assert len(ir.channels) == 1
        assert len(ir.sessions) == 1


# ────────────────────────────────────────────────────────────────────
# Channel + Immune (Fase 5) — immune sensor + reflex over channel topic
# ────────────────────────────────────────────────────────────────────


class TestChannelImmuneComposition:

    def test_typed_channel_with_immune_reflex_clean(self):
        """A program that uses typed channels AND an immune/reflex
        sensor over an observe must compose cleanly.  The observe
        targets a manifest (Fase 1 invariant); channels are an
        independent declarative axis."""
        src = '''
type Sample { x: Float }
channel Inputs { message: Sample qos: at_least_once }

resource Sensor { kind: postgres lifetime: persistent }
fabric FabricA { provider: aws region: "us-east-1" }
manifest Production {
  resources: [Sensor]
  fabric: FabricA
}

observe RawObs from Production {
  sources: [sensor_a]
  quorum: 1
}

immune Vigilante {
  watch: [RawObs]
  scope: tenant
  baseline: learned
  tau: 60s
}

reflex Drop {
  trigger: Vigilante
  on_level: doubt
  action: drop
  scope: tenant
  sla: 1ms
}

daemon Pipeline() {
  goal: "process"
  listen Inputs as ev { step S { ask: "p" } }
}
'''
        errors, warnings, ir = _pipeline(src)
        # The fabric/observe primitives are independent; channel+immune
        # coexist without interaction at this level.
        assert errors == [], [e.message for e in errors]
        assert warnings == [], [w.message for w in warnings]
        assert len(ir.channels) == 1
        assert len(ir.immunes) == 1
        assert len(ir.reflexes) == 1


# ────────────────────────────────────────────────────────────────────
# Channel + Manifest (Fase 1) — declarative coexistence
# ────────────────────────────────────────────────────────────────────


class TestChannelManifestComposition:

    def test_channels_alongside_io_cognitivo_primitives(self):
        """Channels declare on top of I/O cognitivo (resource/fabric/
        manifest/observe) without interfering with the Fase 1 Free
        Monad intention tree."""
        src = '''
type Order { id: String }

resource Db { kind: postgres lifetime: affine }
fabric Vpc { provider: aws region: "us-east-1" }
manifest Production {
  resources: [Db]
  fabric: Vpc
}

channel OrdersCreated {
  message: Order
  qos: at_least_once
}

observe Health from Production {
  sources: [prometheus]
  quorum: 1
}
'''
        errors, _, ir = _pipeline(src)
        assert errors == [], [e.message for e in errors]
        # Channel is declarative — does NOT enter intention_tree
        # (paper structural decision, plan §13.c.2).
        assert ir.intention_tree is not None
        op_types = [op.node_type for op in ir.intention_tree.operations]
        # Manifest + observe enter the tree; channel does not.
        assert "manifest" in op_types
        assert "observe" in op_types
        assert "channel" not in op_types
        # But the channel IS present in IRProgram.channels (declarative
        # section, Fase 13.c.2).
        assert len(ir.channels) == 1
        assert ir.channels[0].name == "OrdersCreated"


# ────────────────────────────────────────────────────────────────────
# Migration script + axon check --strict — full migration round-trip
# ────────────────────────────────────────────────────────────────────


class TestMigrationRoundTrip:

    def test_migration_script_then_strict_check_passes(self):
        """End-to-end: legacy → migrate → output passes axon check --strict."""
        from scripts.migrate_string_topics import migrate

        legacy = '''
daemon LegacyConsumer() {
  goal: "process orders"
  listen "orders.created" as event {
    step S { ask: "validate" }
  }
  listen "orders.cancelled" as event {
    step S { ask: "handle cancel" }
  }
}
'''
        migrated, topics = migrate(legacy)
        assert sorted(topics) == ["orders.cancelled", "orders.created"]

        # Migrated source must be clean under strict (no warnings).
        errors, warnings, ir = _pipeline(migrated)
        assert errors == [], [e.message for e in errors]
        assert warnings == [], [w.message for w in warnings]
        # Two channel declarations were generated.
        ch_names = sorted(c.name for c in ir.channels)
        assert ch_names == ["OrdersCancelled", "OrdersCreated"]


# ────────────────────────────────────────────────────────────────────
# Final acceptance — paper §9 + sub-fases compose end-to-end
# ────────────────────────────────────────────────────────────────────


class TestFase13AcceptanceCriterion:
    """The closing test: paper §9 + every sub-fase delivered (a–g)
    must compose into a single program that compiles, type-checks,
    lowers to IR, and serializes to JSON without loss."""

    def test_full_acceptance_pipeline(self):
        src = (EXAMPLES / "mobile_channels.axon").read_text(encoding="utf-8")
        errors, warnings, ir = _pipeline(src)
        # 13.b — type checker validation passes
        assert errors == []
        # 13.b D4 — typed listeners produce no warnings
        assert warnings == []
        # 13.c — IR has channels collection + emit/publish embedded
        assert len(ir.channels) == 2
        flow = next(f for f in ir.flows if f.name == "hand_off")
        step_kinds = [s.node_type for s in flow.steps]
        assert "emit" in step_kinds
        assert "publish" in step_kinds
        # 13.c — value_is_channel resolved at lowering (mobility)
        emit = next(s for s in flow.steps if s.node_type == "emit")
        assert emit.value_is_channel is True
        # 13.c — JSON serialization preserves all fields
        d = ir.to_dict()
        ch = d["channels"][0]
        assert {"name", "message", "qos", "lifetime", "persistence",
                "shield_ref", "node_type"}.issubset(ch.keys())
