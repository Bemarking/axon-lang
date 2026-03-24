"""
AXON Lambda Data (ΛD) Primitive — Compiler Tests
===================================================
Verifies the Lambda Data primitive (Epistemic Data Enrichment)
through all compiler stages: Lexer, Parser, Type Checker, and IR Generator.

Based on paper_lambda_data.md — the ΛD formalism:
  ΛD: V → (V × O × C × T)
  ψ = ⟨T, V, E⟩  — Epistemic State Vector

Key invariants tested:
  1. Ontological Rigidity     — ontology field is mandatory
  2. Epistemic Bounding       — certainty c ∈ [0, 1]
  3. Derivation validity      — derivation ∈ {raw, derived, inferred, aggregated, transformed}
  4. Epistemic Degradation Theorem — c=1.0 only for 'raw' data
"""

import pytest

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker
from axon.compiler.ir_generator import IRGenerator
from axon.compiler import ast_nodes as ast
from axon.compiler.ir_nodes import IRLambdaData, IRLambdaDataApply, IRProgram
from axon.compiler.tokens import TokenType


# ═══════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════


def _lex(source: str) -> list:
    """Helper: tokenize source."""
    return Lexer(source).tokenize()


def _parse(source: str) -> ast.ProgramNode:
    """Helper: tokenize + parse in one step."""
    tokens = Lexer(source).tokenize()
    return Parser(tokens).parse()


def _check(source: str) -> list:
    """Helper: lex → parse → type-check. Returns error list."""
    tokens = Lexer(source).tokenize()
    tree = Parser(tokens).parse()
    return TypeChecker(tree).check()


def _generate(source: str) -> IRProgram:
    """Helper: lex → parse → IR generate. Returns IRProgram."""
    tokens = Lexer(source).tokenize()
    tree = Parser(tokens).parse()
    return IRGenerator().generate(tree)


# ═══════════════════════════════════════════════════════════════════
#  LEXER TESTS
# ═══════════════════════════════════════════════════════════════════


class TestLambdaDataLexer:
    """Lexer correctly tokenizes lambda data keywords."""

    def test_lambda_keyword(self):
        tokens = _lex("lambda")
        assert tokens[0].type == TokenType.LAMBDA

    def test_ontology_keyword(self):
        tokens = _lex("ontology")
        assert tokens[0].type == TokenType.ONTOLOGY

    def test_certainty_keyword(self):
        tokens = _lex("certainty")
        assert tokens[0].type == TokenType.CERTAINTY

    def test_temporal_frame_keyword(self):
        tokens = _lex("temporal_frame")
        assert tokens[0].type == TokenType.TEMPORAL_FRAME

    def test_provenance_keyword(self):
        tokens = _lex("provenance")
        assert tokens[0].type == TokenType.PROVENANCE

    def test_derivation_keyword(self):
        tokens = _lex("derivation")
        assert tokens[0].type == TokenType.DERIVATION

    def test_lambda_block_tokens(self):
        """Full lambda block tokenizes into expected token sequence."""
        src = 'lambda SensorReading { ontology: "measurement" }'
        tokens = _lex(src)
        types = [t.type for t in tokens[:-1]]  # skip EOF
        assert types == [
            TokenType.LAMBDA, TokenType.IDENTIFIER, TokenType.LBRACE,
            TokenType.ONTOLOGY, TokenType.COLON, TokenType.STRING,
            TokenType.RBRACE,
        ]


# ═══════════════════════════════════════════════════════════════════
#  PARSER TESTS — LAMBDA DATA DEFINITION
# ═══════════════════════════════════════════════════════════════════


class TestLambdaDataParser:
    """Parser produces valid LambdaDataDefinition AST nodes."""

    def test_lambda_minimal(self):
        """Minimal lambda block with just ontology."""
        tree = _parse('lambda Sensor { ontology: "measurement" }')
        ld = tree.declarations[0]
        assert isinstance(ld, ast.LambdaDataDefinition)
        assert ld.name == "Sensor"
        assert ld.ontology == "measurement"
        assert ld.certainty == 1.0  # default
        assert ld.derivation == ""  # default

    def test_lambda_full(self):
        """Full lambda block with all fields populated."""
        source = '''lambda SensorReading {
    ontology: "measurement.temperature"
    certainty: 0.95
    temporal_frame: "2024-01-01/2024-12-31"
    provenance: "IoT sensor array Alpha-7"
    derivation: raw
}'''
        tree = _parse(source)
        ld = tree.declarations[0]
        assert isinstance(ld, ast.LambdaDataDefinition)
        assert ld.name == "SensorReading"
        assert ld.ontology == "measurement.temperature"
        assert ld.certainty == 0.95
        assert ld.temporal_frame_start == "2024-01-01/2024-12-31"
        assert ld.provenance == "IoT sensor array Alpha-7"
        assert ld.derivation == "raw"

    def test_lambda_float_certainty(self):
        """Certainty parsed as float."""
        tree = _parse('lambda X { ontology: "test" certainty: 0.5 }')
        ld = tree.declarations[0]
        assert ld.certainty == 0.5

    def test_lambda_integer_certainty(self):
        """Certainty can also be an integer (0 or 1)."""
        tree = _parse('lambda X { ontology: "test" certainty: 1 }')
        ld = tree.declarations[0]
        assert ld.certainty == 1.0

    def test_lambda_temporal_frame_two_strings(self):
        """Temporal frame with separate start and end strings."""
        tree = _parse('lambda X { ontology: "test" temporal_frame: "2024-01-01" "2024-12-31" }')
        ld = tree.declarations[0]
        assert ld.temporal_frame_start == "2024-01-01"
        assert ld.temporal_frame_end == "2024-12-31"

    def test_lambda_temporal_frame_single_string(self):
        """Temporal frame with a single ISO 8601 interval string."""
        tree = _parse('lambda X { ontology: "test" temporal_frame: "2024-01-01/2024-12-31" }')
        ld = tree.declarations[0]
        assert ld.temporal_frame_start == "2024-01-01/2024-12-31"
        assert ld.temporal_frame_end == ""

    def test_lambda_empty_block(self):
        """Empty lambda block is syntactically valid (type checker catches missing ontology)."""
        tree = _parse("lambda Empty { }")
        ld = tree.declarations[0]
        assert isinstance(ld, ast.LambdaDataDefinition)
        assert ld.name == "Empty"
        assert ld.ontology == ""

    def test_lambda_derivation_options(self):
        """Derivation accepts all valid categories."""
        for deriv in ("raw", "derived", "inferred", "aggregated", "transformed"):
            tree = _parse(f'lambda X {{ ontology: "test" derivation: {deriv} }}')
            ld = tree.declarations[0]
            assert ld.derivation == deriv


# ═══════════════════════════════════════════════════════════════════
#  PARSER TESTS — LAMBDA DATA APPLY
# ═══════════════════════════════════════════════════════════════════


class TestLambdaDataApplyParser:
    """Parser produces valid LambdaDataApplyNode for in-flow usage."""

    def test_apply_basic(self):
        """Basic lambda apply inside a flow."""
        source = '''lambda SensorReading {
    ontology: "measurement"
}

flow Process() {
    lambda SensorReading on raw_data
}'''
        tree = _parse(source)
        flow = tree.declarations[1]
        apply_node = flow.body[0]
        assert isinstance(apply_node, ast.LambdaDataApplyNode)
        assert apply_node.lambda_data_name == "SensorReading"
        assert apply_node.target == "raw_data"
        assert apply_node.output_type == ""

    def test_apply_with_output_type(self):
        """Lambda apply with explicit output type arrow."""
        source = '''lambda SensorReading {
    ontology: "measurement"
}

flow Process() {
    lambda SensorReading on raw_data -> ValidatedReading
}'''
        tree = _parse(source)
        flow = tree.declarations[1]
        apply_node = flow.body[0]
        assert isinstance(apply_node, ast.LambdaDataApplyNode)
        assert apply_node.lambda_data_name == "SensorReading"
        assert apply_node.target == "raw_data"
        assert apply_node.output_type == "ValidatedReading"


# ═══════════════════════════════════════════════════════════════════
#  TYPE CHECKER TESTS — VALID PROGRAMS
# ═══════════════════════════════════════════════════════════════════


class TestLambdaDataTypeCheckerValid:
    """Type checker accepts valid lambda data programs."""

    def test_valid_full_definition(self):
        """Full valid lambda data definition passes type checking."""
        source = '''lambda SensorReading {
    ontology: "measurement.temperature"
    certainty: 0.95
    temporal_frame: "2024-01-01/2024-12-31"
    provenance: "IoT sensor array Alpha-7"
    derivation: raw
}'''
        errors = _check(source)
        assert errors == []

    def test_valid_raw_certainty_one(self):
        """Raw data with certainty=1.0 is valid (only raw may carry absolute certainty)."""
        source = '''lambda RawSensor {
    ontology: "measurement"
    certainty: 1.0
    derivation: raw
}'''
        errors = _check(source)
        assert errors == []

    def test_valid_derived_certainty_below_one(self):
        """Derived data with certainty < 1.0 is valid."""
        source = '''lambda ProcessedData {
    ontology: "analytics"
    certainty: 0.85
    derivation: derived
}'''
        errors = _check(source)
        assert errors == []

    def test_valid_no_derivation(self):
        """Lambda without derivation is valid (defaults to empty, no degradation check)."""
        source = '''lambda SimpleData {
    ontology: "general"
    certainty: 1.0
}'''
        errors = _check(source)
        assert errors == []

    def test_valid_minimal(self):
        """Minimal valid lambda with just ontology."""
        source = '''lambda MinData {
    ontology: "domain"
}'''
        errors = _check(source)
        assert errors == []

    def test_valid_apply_references_lambda(self):
        """Lambda apply referencing a declared lambda passes."""
        source = '''lambda SensorReading {
    ontology: "measurement"
}

flow Process() {
    lambda SensorReading on raw_data
}'''
        errors = _check(source)
        assert errors == []


# ═══════════════════════════════════════════════════════════════════
#  TYPE CHECKER TESTS — INVALID PROGRAMS
# ═══════════════════════════════════════════════════════════════════


class TestLambdaDataTypeCheckerInvalid:
    """Type checker catches invalid lambda data declarations."""

    def test_missing_ontology(self):
        """Ontological Rigidity: missing ontology field is an error."""
        source = '''lambda NoOntology {
    certainty: 0.5
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "ontology" in errors[0].message
        assert "Ontological Rigidity" in errors[0].message

    def test_certainty_out_of_bounds_negative(self):
        """Epistemic Bounding: certainty < 0 is caught."""
        source = '''lambda BadCert {
    ontology: "test"
    certainty: -0.5
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "certainty" in errors[0].message.lower()
        assert "Epistemic Bounding" in errors[0].message

    def test_certainty_out_of_bounds_above_one(self):
        """Epistemic Bounding: certainty > 1.0 is caught."""
        source = '''lambda BadCert {
    ontology: "test"
    certainty: 1.5
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "certainty" in errors[0].message.lower()

    def test_invalid_derivation(self):
        """Invalid derivation category is caught."""
        source = '''lambda BadDeriv {
    ontology: "test"
    certainty: 0.5
    derivation: imagined
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "derivation" in errors[0].message.lower()
        assert "imagined" in errors[0].message

    def test_epistemic_degradation_theorem_violation(self):
        """EPD Theorem: c=1.0 with non-raw derivation is a violation."""
        source = '''lambda DerivedPerfect {
    ontology: "analytics"
    certainty: 1.0
    derivation: derived
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "Epistemic Degradation Theorem" in errors[0].message

    def test_epd_with_inferred(self):
        """EPD Theorem: c=1.0 with 'inferred' derivation is also a violation."""
        source = '''lambda InferredPerfect {
    ontology: "analytics"
    certainty: 1.0
    derivation: inferred
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "Epistemic Degradation Theorem" in errors[0].message

    def test_epd_with_aggregated(self):
        """EPD Theorem: c=1.0 with 'aggregated' derivation is also a violation."""
        source = '''lambda AggPerfect {
    ontology: "analytics"
    certainty: 1.0
    derivation: aggregated
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "Epistemic Degradation Theorem" in errors[0].message

    def test_apply_wrong_kind(self):
        """Lambda apply referencing non-lambda symbol is an error."""
        source = '''persona Expert {
    domain: ["physics"]
}

flow Process() {
    lambda Expert on raw_data
}'''
        errors = _check(source)
        assert len(errors) >= 1
        assert any("lambda apply" in e.message for e in errors)

    def test_multiple_errors(self):
        """Multiple violations produce multiple errors."""
        source = '''lambda MultiError {
    certainty: -0.5
    derivation: imagined
}'''
        errors = _check(source)
        # Should have: missing ontology + certainty out of bounds + invalid derivation
        assert len(errors) >= 3


# ═══════════════════════════════════════════════════════════════════
#  IR GENERATOR TESTS
# ═══════════════════════════════════════════════════════════════════


class TestLambdaDataIRGenerator:
    """IR generator correctly lowers lambda data AST nodes to IR."""

    def test_ir_lambda_data_specs(self):
        """Lambda definitions appear in IRProgram.lambda_data_specs."""
        source = '''lambda SensorReading {
    ontology: "measurement.temperature"
    certainty: 0.95
    temporal_frame: "2024-01-01/2024-12-31"
    provenance: "IoT sensor array Alpha-7"
    derivation: raw
}'''
        ir = _generate(source)
        assert len(ir.lambda_data_specs) == 1
        spec = ir.lambda_data_specs[0]
        assert isinstance(spec, IRLambdaData)
        assert spec.name == "SensorReading"
        assert spec.ontology == "measurement.temperature"
        assert spec.certainty == 0.95
        assert spec.temporal_frame_start == "2024-01-01/2024-12-31"
        assert spec.provenance == "IoT sensor array Alpha-7"
        assert spec.derivation == "raw"

    def test_ir_lambda_data_multiple(self):
        """Multiple lambda definitions all appear in lambda_data_specs."""
        source = '''lambda A {
    ontology: "domain.a"
}
lambda B {
    ontology: "domain.b"
    certainty: 0.5
}'''
        ir = _generate(source)
        assert len(ir.lambda_data_specs) == 2
        names = {s.name for s in ir.lambda_data_specs}
        assert names == {"A", "B"}

    def test_ir_lambda_data_apply_in_flow(self):
        """Lambda apply nodes appear in flow steps as IRLambdaDataApply."""
        source = '''lambda SensorReading {
    ontology: "measurement"
}

flow Process() {
    lambda SensorReading on raw_data -> ValidatedReading
}'''
        ir = _generate(source)
        assert len(ir.flows) == 1
        flow = ir.flows[0]
        assert len(flow.steps) >= 1
        apply_node = flow.steps[0]
        assert isinstance(apply_node, IRLambdaDataApply)
        assert apply_node.lambda_data_name == "SensorReading"
        assert apply_node.target == "raw_data"
        assert apply_node.output_type == "ValidatedReading"

    def test_ir_lambda_data_defaults(self):
        """IR preserves default values for missing fields."""
        source = '''lambda Minimal {
    ontology: "test"
}'''
        ir = _generate(source)
        spec = ir.lambda_data_specs[0]
        assert spec.certainty == 1.0
        assert spec.temporal_frame_start == ""
        assert spec.temporal_frame_end == ""
        assert spec.provenance == ""
        assert spec.derivation == ""


# ═══════════════════════════════════════════════════════════════════
#  INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════


class TestLambdaDataIntegration:
    """End-to-end tests combining lambda data with other AXON primitives."""

    def test_lambda_with_persona_and_flow(self):
        """Lambda data coexists with persona and flow declarations."""
        source = '''persona Analyst {
    domain: ["data science"]
    tone: analytical
}

lambda SensorReading {
    ontology: "measurement"
    certainty: 0.9
    derivation: raw
}

flow AnalyzeSensors() {
    lambda SensorReading on raw_data
}'''
        errors = _check(source)
        assert errors == []
        ir = _generate(source)
        assert len(ir.personas) == 1
        assert len(ir.lambda_data_specs) == 1
        assert len(ir.flows) == 1

    def test_lambda_does_not_affect_other_specs(self):
        """Adding lambda data doesn't break existing IRProgram fields."""
        source = '''lambda A {
    ontology: "test"
}'''
        ir = _generate(source)
        # These should all be empty tuples, not affected by lambda
        assert ir.personas == ()
        assert ir.contexts == ()
        assert ir.anchors == ()
        assert ir.tools == ()
        assert ir.mandate_specs == ()
        # Lambda should be populated
        assert len(ir.lambda_data_specs) == 1
