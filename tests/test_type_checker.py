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
