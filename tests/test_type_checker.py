"""
AXON Type Checker — Unit Tests
================================
Verifies epistemic type validation rules.
"""

import pytest

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker
from axon.compiler.ast_nodes import ProgramNode


def _check(source: str) -> list:
    """Helper: lex → parse → type-check. Returns error list."""
    tokens = Lexer(source).tokenize()
    tree = Parser(tokens).parse()
    return TypeChecker(tree).check()


class TestValidPrograms:
    """Programs that should pass type checking with zero errors."""

    def test_minimal_valid_program(self):
        source = '''persona Expert {
  tone: precise
}

context Review {
  memory: session
}

flow Analyze(doc: Document) -> Report {
  step Extract {
    given: doc
    ask: "Extract facts"
    output: EntityMap
  }
}

run Analyze(myDoc)
  as Expert
  within Review'''
        errors = _check(source)
        assert errors == []

    def test_empty_program(self):
        tree = ProgramNode(line=1, column=1)
        errors = TypeChecker(tree).check()
        assert errors == []

    def test_anchor_with_valid_fields(self):
        source = '''anchor Safety {
  require: source_citation
  confidence_floor: 0.75
  on_violation: raise SafetyError
}'''
        errors = _check(source)
        assert errors == []


class TestPersonaValidation:
    """Type checker validates persona fields."""

    def test_invalid_tone(self):
        source = '''persona Bad {
  tone: screaming
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "tone" in errors[0].message
        assert "screaming" in errors[0].message

    def test_confidence_threshold_out_of_range(self):
        source = '''persona Bad {
  confidence_threshold: 1.5
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "confidence_threshold" in errors[0].message


class TestContextValidation:
    """Type checker validates context fields."""

    def test_invalid_memory_scope(self):
        source = '''context Bad {
  memory: quantum
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "memory scope" in errors[0].message

    def test_invalid_depth(self):
        source = '''context Bad {
  depth: infinite
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "depth" in errors[0].message

    def test_temperature_too_high(self):
        source = '''context Bad {
  temperature: 5.0
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "temperature" in errors[0].message


class TestAnchorValidation:
    """Type checker validates anchor constraints."""

    def test_confidence_floor_out_of_range(self):
        source = '''anchor Bad {
  confidence_floor: -0.5
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "confidence_floor" in errors[0].message

    def test_raise_without_target(self):
        source = '''anchor Bad {
  on_violation: raise
}'''
        # This would fail at parse time since 'raise' expects an identifier
        # Type checker catches the case where on_violation_target is empty
        # but on_violation is "raise" — only reachable via direct AST construction
        from axon.compiler.ast_nodes import AnchorConstraint
        node = AnchorConstraint(
            name="Bad", on_violation="raise", on_violation_target="",
            line=1, column=1,
        )
        tree = ProgramNode(declarations=[node], line=1, column=1)
        errors = TypeChecker(tree).check()
        assert len(errors) == 1
        assert "raise" in errors[0].message


class TestDuplicateDeclarations:
    """Type checker catches duplicate names."""

    def test_duplicate_persona(self):
        source = '''persona Expert {
  tone: precise
}
persona Expert {
  tone: formal
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "Duplicate" in errors[0].message

    def test_duplicate_across_kinds(self):
        source = '''persona Foo {
  tone: precise
}
context Foo {
  memory: session
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "Duplicate" in errors[0].message


class TestRunValidation:
    """Type checker validates run statement wiring."""

    def test_undefined_flow(self):
        source = "run NoSuchFlow()"
        errors = _check(source)
        assert any("Undefined flow" in e.message for e in errors)

    def test_undefined_persona(self):
        source = '''flow Analyze(doc: Document) -> Report {
  step Extract {
    given: doc
    ask: "Extract"
    output: EntityMap
  }
}
run Analyze(myDoc) as NoSuchPersona'''
        errors = _check(source)
        assert any("Undefined persona" in e.message for e in errors)

    def test_undefined_context(self):
        source = '''flow Analyze(doc: Document) -> Report {
  step Extract {
    given: doc
    ask: "Extract"
    output: EntityMap
  }
}
run Analyze(myDoc) within NoSuchContext'''
        errors = _check(source)
        assert any("Undefined context" in e.message for e in errors)

    def test_undefined_anchor(self):
        source = '''flow Analyze(doc: Document) -> Report {
  step Extract {
    given: doc
    ask: "Extract"
    output: EntityMap
  }
}
run Analyze(myDoc) constrained_by [GhostAnchor]'''
        errors = _check(source)
        assert any("Undefined anchor" in e.message for e in errors)

    def test_wrong_kind_for_persona(self):
        source = '''context NotAPersona {
  memory: session
}
flow Analyze(doc: Document) -> Report {
  step Extract {
    given: doc
    ask: "Extract"
    output: EntityMap
  }
}
run Analyze(myDoc) as NotAPersona'''
        errors = _check(source)
        assert any("not a persona" in e.message for e in errors)

    def test_invalid_effort(self):
        source = '''flow Analyze(doc: Document) -> Report {
  step Extract {
    given: doc
    ask: "Extract"
    output: EntityMap
  }
}
run Analyze(myDoc) effort: extreme'''
        errors = _check(source)
        assert any("effort" in e.message for e in errors)


class TestTypeCompatibility:
    """Type checker enforces epistemic type rules."""

    def test_opinion_cannot_be_factual(self):
        checker = TypeChecker(ProgramNode(line=1, column=1))
        assert checker.check_type_compatible("Opinion", "FactualClaim") is False

    def test_factual_can_be_string(self):
        checker = TypeChecker(ProgramNode(line=1, column=1))
        assert checker.check_type_compatible("FactualClaim", "String") is True

    def test_riskscore_can_be_float(self):
        checker = TypeChecker(ProgramNode(line=1, column=1))
        assert checker.check_type_compatible("RiskScore", "Float") is True

    def test_float_cannot_be_riskscore(self):
        checker = TypeChecker(ProgramNode(line=1, column=1))
        assert checker.check_type_compatible("Float", "RiskScore") is False

    def test_uncertainty_propagates(self):
        checker = TypeChecker(ProgramNode(line=1, column=1))
        # Uncertainty is always compatible (it propagates/taints)
        assert checker.check_type_compatible("Uncertainty", "FactualClaim") is True
        assert checker.check_type_compatible("Uncertainty", "RiskScore") is True

    def test_uncertainty_propagation_function(self):
        checker = TypeChecker(ProgramNode(line=1, column=1))
        assert checker.check_uncertainty_propagation("Uncertainty") == "Uncertainty"
        assert checker.check_uncertainty_propagation("FactualClaim") == "FactualClaim"

    def test_speculation_cannot_be_factual(self):
        checker = TypeChecker(ProgramNode(line=1, column=1))
        assert checker.check_type_compatible("Speculation", "FactualClaim") is False

    def test_identity_always_compatible(self):
        checker = TypeChecker(ProgramNode(line=1, column=1))
        assert checker.check_type_compatible("Opinion", "Opinion") is True
        assert checker.check_type_compatible("RiskScore", "RiskScore") is True

    def test_structured_report_satisfies_any(self):
        checker = TypeChecker(ProgramNode(line=1, column=1))
        assert checker.check_type_compatible("StructuredReport", "AnyOutput") is True


class TestFlowValidation:
    """Type checker validates flow internals."""

    def test_duplicate_step_names(self):
        source = '''flow TestFlow(doc: Document) -> Report {
  step Extract {
    given: doc
    ask: "Extract"
    output: EntityMap
  }
  step Extract {
    given: doc
    ask: "Extract again"
    output: EntityMap
  }
}'''
        errors = _check(source)
        assert any("Duplicate step" in e.message for e in errors)

    def test_probe_without_fields(self):
        from axon.compiler.ast_nodes import ProbeDirective, FlowDefinition, ParameterNode, TypeExprNode
        probe = ProbeDirective(target="doc", fields=[], line=3, column=3)
        flow = FlowDefinition(
            name="Test",
            parameters=[ParameterNode(name="doc", type_expr=TypeExprNode(name="Document"))],
            body=[probe],
            line=1, column=1,
        )
        tree = ProgramNode(declarations=[flow], line=1, column=1)
        errors = TypeChecker(tree).check()
        assert any("missing extraction fields" in e.message for e in errors)

    def test_weave_needs_two_sources(self):
        from axon.compiler.ast_nodes import WeaveNode, FlowDefinition, ParameterNode, TypeExprNode
        weave = WeaveNode(sources=["only_one"], target="out", line=3, column=3)
        flow = FlowDefinition(
            name="Test",
            parameters=[ParameterNode(name="x", type_expr=TypeExprNode(name="Data"))],
            body=[weave],
            line=1, column=1,
        )
        tree = ProgramNode(declarations=[flow], line=1, column=1)
        errors = TypeChecker(tree).check()
        assert any("at least 2 sources" in e.message for e in errors)


class TestAxonEndpointValidation:
    """Type checker validates axonendpoint declarations."""

    def test_valid_axonendpoint(self):
        source = '''type ContractInput
type ContractReport

flow AnalyzeContract(doc: Document) -> ContractReport {
  step S {
    ask: "Analyze"
    output: ContractReport
  }
}

shield EdgeShield {
  scan: [prompt_injection]
  on_breach: halt
  severity: high
}

axonendpoint ContractsAPI {
  method: post
  path: "/api/contracts/analyze"
  body: ContractInput
  execute: AnalyzeContract
  output: ContractReport
  shield: EdgeShield
  retries: 1
}'''
        errors = _check(source)
        assert errors == []

    def test_axonendpoint_invalid_method_and_path(self):
        source = '''flow Analyze(doc: Document) -> Report {
  step S { ask: "x" output: Report }
}

axonendpoint BadEndpoint {
  method: fetch
  path: "api/no-leading-slash"
  execute: Analyze
}'''
        errors = _check(source)
        assert any("Unknown HTTP method" in e.message for e in errors)
        assert any("path must start with '/'" in e.message for e in errors)

    def test_axonendpoint_undefined_flow(self):
        source = '''axonendpoint Broken {
  method: post
  path: "/api/run"
  execute: MissingFlow
}'''
        errors = _check(source)
        assert any("undefined flow" in e.message.lower() for e in errors)


# ═══════════════════════════════════════════════════════════════════
#  I/O COGNITIVO — Fase 1: Linear Logic + Separation Logic checks
# ═══════════════════════════════════════════════════════════════════


class TestResourcePrimitives:
    """Type checker validates resource/fabric/manifest/observe declarations."""

    def test_valid_io_cognitivo_program(self):
        source = '''resource DatabasePool {
  kind: postgres
  endpoint: "db.internal:5432"
  lifetime: linear
  certainty_floor: 0.85
}

resource RedisCache {
  kind: redis
  lifetime: affine
}

fabric AWS_VPC {
  provider: aws
  region: "us-east-1"
  zones: 3
  ephemeral: false
}

manifest ProductionCluster {
  resources: [DatabasePool, RedisCache]
  fabric: AWS_VPC
  zones: 3
  compliance: [HIPAA, PCI_DSS]
}

observe ClusterState from ProductionCluster {
  sources: [prometheus, healthcheck]
  quorum: 2
  timeout: 5s
  on_partition: fail
  certainty_floor: 0.90
}'''
        errors = _check(source)
        assert errors == []

    def test_resource_invalid_certainty_floor(self):
        source = '''resource R {
  kind: redis
  certainty_floor: 1.5
}'''
        errors = _check(source)
        assert any("certainty_floor must be in [0.0, 1.0]" in e.message for e in errors)

    def test_resource_missing_kind(self):
        source = '''resource R {
  endpoint: "x:1"
}'''
        errors = _check(source)
        assert any("requires 'kind:" in e.message for e in errors)

    def test_fabric_invalid_provider(self):
        source = '''fabric F {
  provider: heroku
  region: "us"
}'''
        errors = _check(source)
        assert any("unknown provider 'heroku'" in e.message for e in errors)

    def test_manifest_references_undefined_resource(self):
        source = '''manifest M {
  resources: [GhostDB]
}'''
        errors = _check(source)
        assert any("undefined resource 'GhostDB'" in e.message for e in errors)

    def test_manifest_references_wrong_kind(self):
        source = '''persona P {
  tone: precise
}

manifest M {
  resources: [P]
}'''
        errors = _check(source)
        assert any("is a persona, not a resource" in e.message for e in errors)

    def test_manifest_duplicate_resource_rejected_separation_logic(self):
        """Separation Logic: same resource name twice in a manifest is a disjointness violation."""
        source = '''resource Db {
  kind: postgres
}

manifest M {
  resources: [Db, Db]
}'''
        errors = _check(source)
        assert any("more than once" in e.message for e in errors)
        assert any("Separation Logic disjointness" in e.message for e in errors)

    def test_affine_resource_aliased_across_manifests_rejected(self):
        """Linear Logic: an affine resource cannot be referenced from two manifests."""
        source = '''resource SharedDb {
  kind: postgres
  lifetime: affine
}

manifest A {
  resources: [SharedDb]
}

manifest B {
  resources: [SharedDb]
}'''
        errors = _check(source)
        assert any("aliased across multiple manifests" in e.message for e in errors)

    def test_linear_resource_aliased_across_manifests_rejected(self):
        """Linear Logic: a linear resource must be referenced from exactly one manifest."""
        source = '''resource OneShot {
  kind: custom
  lifetime: linear
}

manifest A { resources: [OneShot] }
manifest B { resources: [OneShot] }'''
        errors = _check(source)
        assert any("aliased across multiple manifests" in e.message for e in errors)
        assert any("lifetime: linear" in e.message for e in errors)

    def test_persistent_resource_can_be_shared(self):
        """Linear Logic: persistent (!A) resources are freely shareable."""
        source = '''resource Shared {
  kind: custom
  lifetime: persistent
}

manifest A { resources: [Shared] }
manifest B { resources: [Shared] }'''
        errors = _check(source)
        linearity_errors = [e for e in errors if "aliased" in e.message]
        assert linearity_errors == []

    def test_manifest_undefined_fabric_rejected(self):
        source = '''manifest M {
  resources: [Db]
  fabric: GhostFabric
}

resource Db { kind: postgres }'''
        errors = _check(source)
        assert any("undefined fabric 'GhostFabric'" in e.message for e in errors)

    def test_observe_undefined_manifest_rejected(self):
        source = '''observe S from GhostManifest {
  sources: [prometheus]
}'''
        errors = _check(source)
        assert any("undefined manifest 'GhostManifest'" in e.message for e in errors)

    def test_observe_quorum_exceeds_sources(self):
        source = '''resource Db { kind: postgres }
manifest M { resources: [Db] }
observe S from M {
  sources: [prometheus]
  quorum: 5
}'''
        errors = _check(source)
        assert any("exceeds number of sources" in e.message for e in errors)

    def test_observe_without_sources_rejected(self):
        source = '''resource Db { kind: postgres }
manifest M { resources: [Db] }
observe S from M {
  timeout: 5s
}'''
        errors = _check(source)
        assert any("at least one source" in e.message for e in errors)


# ═══════════════════════════════════════════════════════════════════
#  CONTROL COGNITIVO — Fase 3 (reconcile, lease, ensemble)
# ═══════════════════════════════════════════════════════════════════


_PROLOGUE = '''
resource Db { kind: postgres lifetime: affine }
resource Db2 { kind: postgres lifetime: affine }
manifest M { resources: [Db] }
manifest M2 { resources: [Db2] }
observe O from M { sources: [prometheus] quorum: 1 timeout: 5s }
observe O2 from M2 { sources: [prometheus] quorum: 1 timeout: 5s }
'''


class TestReconcileValidation:

    def test_valid_reconcile(self):
        source = _PROLOGUE + '''
reconcile R { observe: O threshold: 0.85 tolerance: 0.1 on_drift: provision max_retries: 3 }
'''
        assert _check(source) == []

    def test_reconcile_undefined_observe(self):
        source = '''reconcile R { observe: Ghost }'''
        errors = _check(source)
        assert any("undefined observe 'Ghost'" in e.message for e in errors)

    def test_reconcile_wrong_kind_observe(self):
        source = '''resource X { kind: redis }
reconcile R { observe: X }'''
        errors = _check(source)
        assert any("is a resource, not an observe" in e.message for e in errors)

    def test_reconcile_threshold_out_of_range(self):
        source = _PROLOGUE + '''reconcile R { observe: O threshold: 1.5 }'''
        errors = _check(source)
        assert any("threshold must be in [0.0, 1.0]" in e.message for e in errors)

    def test_reconcile_tolerance_out_of_range(self):
        source = _PROLOGUE + '''reconcile R { observe: O tolerance: -0.1 }'''
        errors = _check(source)
        assert any("tolerance must be in [0.0, 1.0]" in e.message for e in errors)

    def test_reconcile_undefined_shield(self):
        source = _PROLOGUE + '''reconcile R { observe: O shield: Ghost }'''
        errors = _check(source)
        assert any("undefined shield 'Ghost'" in e.message for e in errors)

    def test_reconcile_shield_wrong_kind(self):
        source = _PROLOGUE + '''reconcile R { observe: O shield: Db }'''
        errors = _check(source)
        assert any("is a resource, not a shield" in e.message for e in errors)


class TestLeaseValidation:

    def test_valid_lease(self):
        source = _PROLOGUE + '''
lease L { resource: Db duration: 30s acquire: on_start on_expire: anchor_breach }
'''
        assert _check(source) == []

    def test_lease_undefined_resource(self):
        source = '''lease L { resource: Ghost duration: 1s }'''
        errors = _check(source)
        assert any("undefined resource 'Ghost'" in e.message for e in errors)

    def test_lease_wrong_kind(self):
        source = '''persona P { tone: precise }
lease L { resource: P duration: 1s }'''
        errors = _check(source)
        assert any("is a persona, not a resource" in e.message for e in errors)

    def test_lease_on_persistent_resource_rejected(self):
        """D2: persistent (!A) resources are unbounded — lease is meaningless."""
        source = '''resource R { kind: custom lifetime: persistent }
lease L { resource: R duration: 30s }'''
        errors = _check(source)
        assert any("persistent (!A) resources do not require leasing" in e.message for e in errors)

    def test_lease_missing_duration(self):
        source = _PROLOGUE + '''lease L { resource: Db }'''
        errors = _check(source)
        assert any("requires a 'duration'" in e.message for e in errors)


class TestEnsembleValidation:

    def test_valid_ensemble(self):
        source = _PROLOGUE + '''
ensemble E { observations: [O, O2] quorum: 2 aggregation: majority certainty_mode: min }
'''
        assert _check(source) == []

    def test_ensemble_fewer_than_two_observations_rejected(self):
        source = _PROLOGUE + '''ensemble E { observations: [O] }'''
        errors = _check(source)
        assert any("at least 2 observations" in e.message for e in errors)

    def test_ensemble_duplicate_observations_rejected(self):
        """Separation Logic: same observation twice = fake quorum."""
        source = _PROLOGUE + '''ensemble E { observations: [O, O] }'''
        errors = _check(source)
        assert any("more than once" in e.message for e in errors)

    def test_ensemble_undefined_observation(self):
        source = _PROLOGUE + '''ensemble E { observations: [O, Ghost] }'''
        errors = _check(source)
        assert any("undefined observe 'Ghost'" in e.message for e in errors)

    def test_ensemble_quorum_exceeds_observations(self):
        source = _PROLOGUE + '''ensemble E { observations: [O, O2] quorum: 5 }'''
        errors = _check(source)
        assert any("exceeds number of observations" in e.message for e in errors)

    def test_ensemble_member_wrong_kind(self):
        source = '''resource R { kind: redis }
resource R2 { kind: redis }
ensemble E { observations: [R, R2] }'''
        errors = _check(source)
        assert any("is a resource, not an observe" in e.message for e in errors)


# ═══════════════════════════════════════════════════════════════════
#  TOPOLOGY & SESSION TYPES — Fase 4 (π-calculus binary sessions)
# ═══════════════════════════════════════════════════════════════════


class TestSessionValidation:

    def test_valid_dual_session(self):
        source = '''session DbSession {
  client: [send Query, receive Result, end]
  server: [receive Query, send Result, end]
}'''
        assert _check(source) == []

    def test_session_must_have_exactly_two_roles(self):
        source = '''session OneRole { client: [end] }'''
        errors = _check(source)
        assert any("exactly 2 roles" in e.message for e in errors)

    def test_session_three_roles_rejected(self):
        source = '''session Triad {
  a: [end]
  b: [end]
  c: [end]
}'''
        errors = _check(source)
        assert any("exactly 2 roles" in e.message for e in errors)

    def test_session_duplicate_role_rejected(self):
        source = '''session Same {
  client: [send X, end]
  client: [receive X, end]
}'''
        errors = _check(source)
        assert any("duplicate role name 'client'" in e.message for e in errors)

    def test_session_duality_violation_send_send(self):
        """Both roles `send X` at same position → not dual."""
        source = '''session Bad {
  client: [send Q, end]
  server: [send Q, end]
}'''
        errors = _check(source)
        assert any("duality violation" in e.message for e in errors)

    def test_session_duality_violation_message_type_mismatch(self):
        """send Q vs receive R with different types is not dual."""
        source = '''session Bad {
  client: [send Q, end]
  server: [receive R, end]
}'''
        errors = _check(source)
        assert any("duality violation" in e.message for e in errors)

    def test_session_duality_violation_length_mismatch(self):
        source = '''session Bad {
  client: [send Q, receive R, end]
  server: [receive Q, end]
}'''
        errors = _check(source)
        assert any("different lengths" in e.message for e in errors)

    def test_session_loop_duality(self):
        """loop ↔ loop is dual; end ↔ end is dual."""
        source = '''session Stream {
  producer: [send Event, loop]
  consumer: [receive Event, loop]
}'''
        assert _check(source) == []

    def test_session_send_without_message_type_rejected(self):
        # The parser would normally catch this, but test the type-checker
        # path by constructing the AST directly with an empty message_type.
        from axon.compiler.ast_nodes import (
            ProgramNode, SessionDefinition, SessionRole, SessionStep,
        )
        from axon.compiler.type_checker import TypeChecker
        prog = ProgramNode(line=1, column=1, declarations=[
            SessionDefinition(
                name="S", line=1, column=1,
                roles=[
                    SessionRole(name="a", line=1, column=1, steps=[
                        SessionStep(op="send", message_type="", line=1, column=1),
                        SessionStep(op="end", line=1, column=1),
                    ]),
                    SessionRole(name="b", line=1, column=1, steps=[
                        SessionStep(op="receive", message_type="", line=1, column=1),
                        SessionStep(op="end", line=1, column=1),
                    ]),
                ],
            ),
        ])
        errors = TypeChecker(prog).check()
        assert any("requires a message type" in e.message for e in errors)


class TestTopologyValidation:

    _PROLOGUE = '''
resource A { kind: postgres }
resource B { kind: redis }
resource C { kind: compute }
session DualSess {
  client: [send Q, receive R, end]
  server: [receive Q, send R, end]
}
'''

    def test_valid_topology(self):
        source = self._PROLOGUE + '''
topology T {
  nodes: [A, B, C]
  edges: [A -> B : DualSess, B -> C : DualSess]
}'''
        assert _check(source) == []

    def test_topology_undefined_node_rejected(self):
        source = '''topology T {
  nodes: [Ghost]
  edges: []
}'''
        errors = _check(source)
        assert any("undefined node 'Ghost'" in e.message for e in errors)

    def test_topology_node_wrong_kind_rejected(self):
        source = '''persona P { tone: precise }
topology T { nodes: [P] edges: [] }'''
        errors = _check(source)
        assert any("not a valid topology entity" in e.message for e in errors)

    def test_topology_duplicate_node_rejected(self):
        source = self._PROLOGUE + '''
topology T { nodes: [A, A, B] edges: [] }'''
        errors = _check(source)
        assert any("more than once" in e.message for e in errors)

    def test_topology_edge_endpoint_not_in_nodes(self):
        source = self._PROLOGUE + '''
topology T {
  nodes: [A, B]
  edges: [A -> Ghost : DualSess]
}'''
        errors = _check(source)
        assert any("not in the topology's nodes list" in e.message for e in errors)

    def test_topology_self_loop_rejected(self):
        """π-calculus binary sessions need two distinct endpoints."""
        source = self._PROLOGUE + '''
topology T {
  nodes: [A]
  edges: [A -> A : DualSess]
}'''
        errors = _check(source)
        assert any("self-loop" in e.message for e in errors)

    def test_topology_edge_undefined_session(self):
        source = self._PROLOGUE + '''
topology T {
  nodes: [A, B]
  edges: [A -> B : GhostSess]
}'''
        errors = _check(source)
        assert any("undefined session 'GhostSess'" in e.message for e in errors)

    def test_topology_edge_session_wrong_kind(self):
        source = self._PROLOGUE + '''
topology T {
  nodes: [A, B]
  edges: [A -> B : A]
}'''
        errors = _check(source)
        assert any("is a resource, not a session" in e.message for e in errors)


class TestTopologyLiveness:
    """Compile-time deadlock detection — Fase 4 closing criterion."""

    _PROLOGUE = '''
resource A { kind: postgres }
resource B { kind: redis }
'''

    def test_static_deadlock_cycle_with_receive_first_rejected(self):
        """Both endpoints wait → no progress → static deadlock."""
        source = self._PROLOGUE + '''
session WaitSess {
  client: [receive X, send Y, end]
  server: [send X, receive Y, end]
}
topology Stuck {
  nodes: [A, B]
  edges: [A -> B : WaitSess, B -> A : WaitSess]
}'''
        errors = _check(source)
        assert any("static deadlock" in e.message for e in errors)
        assert any("Honda liveness" in e.message for e in errors)

    def test_cycle_with_send_first_passes(self):
        """At least one edge has progress → liveness preserved."""
        source = self._PROLOGUE + '''
session SendSess {
  client: [send X, receive Y, end]
  server: [receive X, send Y, end]
}
topology Live {
  nodes: [A, B]
  edges: [A -> B : SendSess, B -> A : SendSess]
}'''
        errors = _check(source)
        # Send-first cycle has progress at every step → no deadlock error.
        liveness_errors = [e for e in errors if "static deadlock" in e.message]
        assert liveness_errors == []

    def test_acyclic_topology_passes(self):
        source = self._PROLOGUE + '''
resource C { kind: compute }
session Sess {
  client: [send Q, receive R, end]
  server: [receive Q, send R, end]
}
topology Tree {
  nodes: [A, B, C]
  edges: [A -> B : Sess, B -> C : Sess]
}'''
        errors = _check(source)
        liveness_errors = [e for e in errors if "deadlock" in e.message]
        assert liveness_errors == []


# ═══════════════════════════════════════════════════════════════════
#  COGNITIVE IMMUNE SYSTEM — Fase 5 (paper_inmune.md)
# ═══════════════════════════════════════════════════════════════════


class TestImmuneValidation:

    def test_valid_immune(self):
        source = '''immune V { watch: [A, B] sensitivity: 0.9 scope: tenant tau: 300s }'''
        assert _check(source) == []

    def test_missing_scope_rejected(self):
        """Paper §8.2 — scope is mandatory, no implicit default."""
        source = '''immune V { watch: [A] sensitivity: 0.9 }'''
        errors = _check(source)
        assert any("requires an explicit 'scope'" in e.message for e in errors)
        assert any("paper §8.2" in e.message for e in errors)

    def test_empty_watch_rejected(self):
        # A missing watch field is the proper way to test this; literal
        # `[]` would be a parse error in _parse_bracketed_identifiers.
        source = '''immune V { scope: tenant }'''
        errors = _check(source)
        assert any("non-empty 'watch'" in e.message for e in errors)

    def test_sensitivity_out_of_range_rejected(self):
        source = '''immune V { watch: [A] sensitivity: 1.5 scope: tenant }'''
        errors = _check(source)
        assert any("sensitivity must be in [0.0, 1.0]" in e.message for e in errors)

    def test_window_must_be_positive(self):
        source = '''immune V { watch: [A] scope: tenant window: 0 }'''
        errors = _check(source)
        assert any("window must be >= 1" in e.message for e in errors)


class TestReflexValidation:

    _PROLOGUE = '''
immune V { watch: [A] sensitivity: 0.9 scope: tenant }
'''

    def test_valid_reflex(self):
        source = self._PROLOGUE + '''
reflex R { trigger: V on_level: doubt action: drop scope: tenant sla: 1ms }'''
        assert _check(source) == []

    def test_missing_scope_rejected(self):
        source = self._PROLOGUE + '''
reflex R { trigger: V on_level: doubt action: drop }'''
        errors = _check(source)
        assert any("requires an explicit 'scope'" in e.message for e in errors)

    def test_trigger_wrong_kind(self):
        source = '''resource R { kind: postgres }
reflex X { trigger: R on_level: doubt action: drop scope: tenant }'''
        errors = _check(source)
        assert any("is a resource, not an immune" in e.message for e in errors)

    def test_trigger_undefined(self):
        source = '''reflex X { trigger: Ghost on_level: doubt action: drop scope: tenant }'''
        errors = _check(source)
        assert any("undefined trigger 'Ghost'" in e.message for e in errors)

    def test_missing_action(self):
        source = self._PROLOGUE + '''
reflex R { trigger: V on_level: doubt scope: tenant }'''
        errors = _check(source)
        assert any("requires an 'action'" in e.message for e in errors)


class TestHealValidation:

    _PROLOGUE = '''
immune V { watch: [A] sensitivity: 0.9 scope: tenant }
shield S { scan: [prompt_injection] on_breach: quarantine severity: medium }
'''

    def test_valid_heal(self):
        source = self._PROLOGUE + '''
heal H { source: V on_level: doubt mode: human_in_loop scope: tenant shield: S max_patches: 3 }'''
        assert _check(source) == []

    def test_missing_scope_rejected(self):
        source = self._PROLOGUE + '''
heal H { source: V mode: human_in_loop }'''
        errors = _check(source)
        assert any("requires an explicit 'scope'" in e.message for e in errors)

    def test_source_wrong_kind(self):
        source = '''resource R { kind: postgres }
heal H { source: R mode: human_in_loop scope: tenant }'''
        errors = _check(source)
        assert any("is a resource, not an immune" in e.message for e in errors)

    def test_adversarial_requires_shield(self):
        """Paper §7.3 — adversarial mode needs explicit Risk Acceptance (shield gate)."""
        source = self._PROLOGUE + '''
heal H { source: V mode: adversarial scope: tenant }'''
        errors = _check(source)
        assert any("mode='adversarial' requires a 'shield' gate" in e.message for e in errors)

    def test_adversarial_with_shield_ok(self):
        source = self._PROLOGUE + '''
heal H { source: V mode: adversarial scope: tenant shield: S }'''
        assert _check(source) == []

    def test_audit_only_mode_valid(self):
        """Paper §7.1 — audit_only is the default for regulated industries."""
        source = self._PROLOGUE + '''
heal H { source: V mode: audit_only scope: tenant }'''
        assert _check(source) == []

    def test_max_patches_positive(self):
        source = self._PROLOGUE + '''
heal H { source: V mode: human_in_loop scope: tenant max_patches: 0 }'''
        errors = _check(source)
        assert any("max_patches must be >= 1" in e.message for e in errors)
