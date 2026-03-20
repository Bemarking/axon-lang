"""
AXON Mandate Primitive — Compiler Tests
==========================================
Verifies the mandate primitive (Cybernetic Refinement Calculus)
through all compiler stages: Lexer, Parser, Type Checker, and IR Generator.

Based on paper_mandate.md — the CRC framework unifies:
  Vía C — Axiomatic Semantics / Refinement Types
  Vía A — Lyapunov-stable PID Control
  Vía B — Thermodynamic Logit Bias
"""

import pytest

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker
from axon.compiler.ir_generator import IRGenerator
from axon.compiler import ast_nodes as ast
from axon.compiler.ir_nodes import IRMandate, IRMandateApply, IRProgram
from axon.compiler.tokens import TokenType


# ═══════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════


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


def _mandate_ast(**kw) -> ast.MandateDefinition:
    """Create a MandateDefinition AST node with defaults."""
    defaults = dict(
        line=1, column=0, name="StrictJSON",
        constraint="Output must be valid JSON",
        kp=10.0, ki=0.1, kd=0.05,
        tolerance=0.01, max_steps=50,
        on_violation="coerce",
    )
    defaults.update(kw)
    return ast.MandateDefinition(**defaults)


def _program(*declarations) -> ast.ProgramNode:
    return ast.ProgramNode(line=0, column=0, declarations=list(declarations))


# ═══════════════════════════════════════════════════════════════════
#  LEXER TESTS
# ═══════════════════════════════════════════════════════════════════


class TestMandateLexer:
    """Lexer correctly tokenizes mandate-related keywords."""

    def test_mandate_keyword(self):
        tokens = Lexer("mandate").tokenize()
        assert tokens[0].type == TokenType.MANDATE

    def test_constraint_keyword(self):
        tokens = Lexer("constraint").tokenize()
        assert tokens[0].type == TokenType.CONSTRAINT

    def test_kp_keyword(self):
        tokens = Lexer("kp").tokenize()
        assert tokens[0].type == TokenType.KP

    def test_ki_keyword(self):
        tokens = Lexer("ki").tokenize()
        assert tokens[0].type == TokenType.KI

    def test_kd_keyword(self):
        tokens = Lexer("kd").tokenize()
        assert tokens[0].type == TokenType.KD

    def test_tolerance_keyword(self):
        tokens = Lexer("tolerance").tokenize()
        assert tokens[0].type == TokenType.TOLERANCE

    def test_max_steps_keyword(self):
        tokens = Lexer("max_steps").tokenize()
        assert tokens[0].type == TokenType.MAX_STEPS

    def test_on_violation_keyword(self):
        tokens = Lexer("on_violation").tokenize()
        assert tokens[0].type == TokenType.ON_VIOLATION

    def test_mandate_block_tokens(self):
        src = 'mandate StrictJSON { constraint: "valid JSON" }'
        tokens = Lexer(src).tokenize()
        types = [t.type for t in tokens[:-1]]  # skip EOF
        assert types == [
            TokenType.MANDATE, TokenType.IDENTIFIER, TokenType.LBRACE,
            TokenType.CONSTRAINT, TokenType.COLON, TokenType.STRING,
            TokenType.RBRACE,
        ]


# ═══════════════════════════════════════════════════════════════════
#  PARSER TESTS — MANDATE DEFINITION
# ═══════════════════════════════════════════════════════════════════


class TestMandateParser:
    """Parser produces valid MandateDefinition AST nodes."""

    def test_mandate_minimal(self):
        tree = _parse("mandate Guard { }")
        m = tree.declarations[0]
        assert isinstance(m, ast.MandateDefinition)
        assert m.name == "Guard"
        assert m.constraint == ""  # default empty
        assert m.kp == 10.0       # default
        assert m.ki == 0.1        # default
        assert m.kd == 0.05       # default

    def test_mandate_full(self):
        source = '''mandate StrictJSON {
    constraint: "Output must be valid JSON with keys: name, score, reasoning"
    kp: 10.0
    ki: 0.1
    kd: 0.05
    tolerance: 0.01
    max_steps: 50
    on_violation: coerce
}'''
        tree = _parse(source)
        m = tree.declarations[0]
        assert isinstance(m, ast.MandateDefinition)
        assert m.name == "StrictJSON"
        assert m.constraint == "Output must be valid JSON with keys: name, score, reasoning"
        assert m.kp == 10.0
        assert m.ki == 0.1
        assert m.kd == 0.05
        assert m.tolerance == 0.01
        assert m.max_steps == 50
        assert m.on_violation == "coerce"

    def test_mandate_custom_pid_gains(self):
        source = '''mandate FastConverge {
    constraint: "Must be a positive number"
    kp: 25.0
    ki: 0.5
    kd: 0.2
}'''
        tree = _parse(source)
        m = tree.declarations[0]
        assert m.kp == 25.0
        assert m.ki == 0.5
        assert m.kd == 0.2

    def test_mandate_halt_policy(self):
        source = '''mandate Strict {
    constraint: "No ambiguity allowed"
    on_violation: halt
}'''
        tree = _parse(source)
        m = tree.declarations[0]
        assert m.on_violation == "halt"

    def test_mandate_retry_policy(self):
        source = '''mandate Retry {
    constraint: "Must contain keyword"
    on_violation: retry
}'''
        tree = _parse(source)
        m = tree.declarations[0]
        assert m.on_violation == "retry"

    def test_mandate_source_location(self):
        tree = _parse("mandate Guard { }")
        m = tree.declarations[0]
        assert m.line == 1
        assert m.column == 1

    def test_multiple_mandates(self):
        source = '''mandate JSON { constraint: "valid json" }
mandate CSV { constraint: "valid csv" }'''
        tree = _parse(source)
        assert len(tree.declarations) == 2
        assert tree.declarations[0].name == "JSON"
        assert tree.declarations[1].name == "CSV"


# ═══════════════════════════════════════════════════════════════════
#  PARSER TESTS — MANDATE APPLY (in-flow)
# ═══════════════════════════════════════════════════════════════════


class TestMandateApplyParser:
    """Parser handles 'mandate X on Y' in flow steps."""

    def test_mandate_apply_basic(self):
        source = '''flow Test() -> Result {
    mandate StrictJSON on llm_output
    step Process {
        ask: "Process the input"
        output: Result
    }
}'''
        tree = _parse(source)
        flow = tree.declarations[0]
        assert isinstance(flow.body[0], ast.MandateApplyNode)
        ma = flow.body[0]
        assert ma.mandate_name == "StrictJSON"
        assert ma.target == "llm_output"
        assert ma.output_type == ""

    def test_mandate_apply_with_output_type(self):
        source = '''flow Test() -> Result {
    mandate StrictJSON on raw_data -> ValidatedJSON
    step Process {
        ask: "Process"
        output: Result
    }
}'''
        tree = _parse(source)
        ma = tree.declarations[0].body[0]
        assert ma.mandate_name == "StrictJSON"
        assert ma.target == "raw_data"
        assert ma.output_type == "ValidatedJSON"


# ═══════════════════════════════════════════════════════════════════
#  TYPE CHECKER TESTS
# ═══════════════════════════════════════════════════════════════════


class TestMandateTypeChecker:
    """Type checker validates mandate CRC constraints."""

    def test_valid_mandate_passes(self):
        source = '''mandate StrictJSON {
    constraint: "Output must be valid JSON"
    kp: 10.0
    ki: 0.1
    kd: 0.05
    tolerance: 0.01
    max_steps: 50
    on_violation: coerce
}'''
        errors = _check(source)
        assert errors == []

    def test_missing_constraint(self):
        """Vía C: constraint is mandatory (T_M refinement type)."""
        mandate = _mandate_ast(constraint="")
        tree = _program(mandate)
        errors = TypeChecker(tree).check()
        assert any("constraint" in e.message for e in errors)

    def test_kp_must_be_positive(self):
        """Vía A: Kp > 0 for control law stability."""
        mandate = _mandate_ast(kp=0.0)
        tree = _program(mandate)
        errors = TypeChecker(tree).check()
        assert any("Kp" in e.message for e in errors)

    def test_kp_negative_rejected(self):
        mandate = _mandate_ast(kp=-1.0)
        tree = _program(mandate)
        errors = TypeChecker(tree).check()
        assert any("Kp" in e.message for e in errors)

    def test_ki_negative_rejected(self):
        """Vía A: Ki ≥ 0 for integral error accumulation."""
        mandate = _mandate_ast(ki=-0.5)
        tree = _program(mandate)
        errors = TypeChecker(tree).check()
        assert any("Ki" in e.message for e in errors)

    def test_ki_zero_is_valid(self):
        """Ki = 0 is valid (pure PD control)."""
        mandate = _mandate_ast(ki=0.0)
        tree = _program(mandate)
        errors = TypeChecker(tree).check()
        assert errors == []

    def test_kd_negative_rejected(self):
        """Vía A: Kd ≥ 0 for derivative damping."""
        mandate = _mandate_ast(kd=-0.1)
        tree = _program(mandate)
        errors = TypeChecker(tree).check()
        assert any("Kd" in e.message for e in errors)

    def test_kd_zero_is_valid(self):
        """Kd = 0 is valid (pure PI control)."""
        mandate = _mandate_ast(kd=0.0)
        tree = _program(mandate)
        errors = TypeChecker(tree).check()
        assert errors == []

    def test_tolerance_zero_rejected(self):
        """Tolerance ε must be in (0, 1]."""
        mandate = _mandate_ast(tolerance=0.0)
        tree = _program(mandate)
        errors = TypeChecker(tree).check()
        assert any("Tolerance" in e.message or "tolerance" in e.message for e in errors)

    def test_tolerance_negative_rejected(self):
        mandate = _mandate_ast(tolerance=-0.1)
        tree = _program(mandate)
        errors = TypeChecker(tree).check()
        assert any("Tolerance" in e.message or "tolerance" in e.message for e in errors)

    def test_tolerance_above_one_rejected(self):
        mandate = _mandate_ast(tolerance=1.5)
        tree = _program(mandate)
        errors = TypeChecker(tree).check()
        assert any("Tolerance" in e.message or "tolerance" in e.message for e in errors)

    def test_tolerance_one_is_valid(self):
        """ε = 1.0 is valid (maximum tolerance)."""
        mandate = _mandate_ast(tolerance=1.0)
        tree = _program(mandate)
        errors = TypeChecker(tree).check()
        assert errors == []

    def test_max_steps_zero_rejected(self):
        """max_steps N must be ≥ 1."""
        mandate = _mandate_ast(max_steps=0)
        tree = _program(mandate)
        errors = TypeChecker(tree).check()
        assert any("max_steps" in e.message for e in errors)

    def test_max_steps_negative_rejected(self):
        mandate = _mandate_ast(max_steps=-5)
        tree = _program(mandate)
        errors = TypeChecker(tree).check()
        assert any("max_steps" in e.message for e in errors)

    def test_invalid_on_violation_policy(self):
        """Vía B: on_violation must be coerce|halt|retry."""
        mandate = _mandate_ast(on_violation="explode")
        tree = _program(mandate)
        errors = TypeChecker(tree).check()
        assert any("on_violation" in e.message and "explode" in e.message for e in errors)

    def test_valid_policies(self):
        """All three policies should pass validation."""
        for policy in ("coerce", "halt", "retry"):
            mandate = _mandate_ast(on_violation=policy)
            tree = _program(mandate)
            errors = TypeChecker(tree).check()
            assert errors == [], f"Policy '{policy}' should be valid"

    def test_mandate_apply_wrong_kind(self):
        """Applying a non-mandate name should error."""
        source = '''shield Guard { }
flow Test() -> Result {
    mandate Guard on user_input
    step Process {
        ask: "Process"
        output: Result
    }
}'''
        errors = _check(source)
        assert any("not a mandate" in e.message for e in errors)


# ═══════════════════════════════════════════════════════════════════
#  IR GENERATOR TESTS
# ═══════════════════════════════════════════════════════════════════


class TestMandateIRGenerator:
    """IR Generator correctly transforms mandate AST → IR nodes."""

    def test_mandate_definition_ir(self):
        source = '''mandate StrictJSON {
    constraint: "Output must be valid JSON"
    kp: 10.0
    ki: 0.1
    kd: 0.05
    tolerance: 0.01
    max_steps: 50
    on_violation: coerce
}'''
        ir = _generate(source)
        assert len(ir.mandate_specs) == 1
        m = ir.mandate_specs[0]
        assert isinstance(m, IRMandate)
        assert m.name == "StrictJSON"
        assert m.constraint == "Output must be valid JSON"
        assert m.kp == 10.0
        assert m.ki == 0.1
        assert m.kd == 0.05
        assert m.tolerance == 0.01
        assert m.max_steps == 50
        assert m.on_violation == "coerce"

    def test_mandate_definition_source_location(self):
        source = 'mandate Guard { constraint: "test" }'
        ir = _generate(source)
        m = ir.mandate_specs[0]
        assert m.source_line == 1

    def test_multiple_mandates_ir(self):
        source = '''mandate JSON { constraint: "valid json" }
mandate CSV { constraint: "valid csv" }'''
        ir = _generate(source)
        assert len(ir.mandate_specs) == 2
        names = {m.name for m in ir.mandate_specs}
        assert names == {"JSON", "CSV"}

    def test_mandate_apply_ir(self):
        source = '''mandate StrictJSON {
    constraint: "Must be JSON"
}
flow Test() -> Result {
    mandate StrictJSON on llm_output
    step Process {
        ask: "Process"
        output: Result
    }
}'''
        ir = _generate(source)
        # mandate_specs should have the definition
        assert len(ir.mandate_specs) == 1
        # The flow should contain the apply node
        flow = ir.flows[0]
        apply_node = flow.steps[0]
        assert isinstance(apply_node, IRMandateApply)
        assert apply_node.mandate_name == "StrictJSON"
        assert apply_node.target == "llm_output"

    def test_mandate_apply_with_output_type_ir(self):
        source = '''mandate StrictJSON {
    constraint: "Must be JSON"
}
flow Test() -> Result {
    mandate StrictJSON on raw_data -> ValidatedJSON
    step Process {
        ask: "Process"
        output: Result
    }
}'''
        ir = _generate(source)
        flow = ir.flows[0]
        apply_node = flow.steps[0]
        assert isinstance(apply_node, IRMandateApply)
        assert apply_node.output_type == "ValidatedJSON"

    def test_empty_mandate_specs_when_none_declared(self):
        source = '''persona Bot { role: "helper" }'''
        ir = _generate(source)
        assert ir.mandate_specs == ()


# ═══════════════════════════════════════════════════════════════════
#  AST NODE TESTS
# ═══════════════════════════════════════════════════════════════════


class TestMandateASTNodes:
    """Verify MandateDefinition and MandateApplyNode dataclass defaults."""

    def test_mandate_definition_defaults(self):
        m = ast.MandateDefinition(line=1, column=0)
        assert m.name == ""
        assert m.constraint == ""
        assert m.kp == 10.0
        assert m.ki == 0.1
        assert m.kd == 0.05
        assert m.tolerance == 0.01
        assert m.max_steps == 50
        assert m.on_violation == "coerce"

    def test_mandate_definition_custom(self):
        m = ast.MandateDefinition(
            line=5, column=3,
            name="Custom",
            constraint="Must answer in Spanish",
            kp=20.0, ki=0.5, kd=0.3,
            tolerance=0.05, max_steps=100,
            on_violation="halt",
        )
        assert m.name == "Custom"
        assert m.kp == 20.0
        assert m.max_steps == 100
        assert m.on_violation == "halt"

    def test_mandate_apply_defaults(self):
        ma = ast.MandateApplyNode(line=1, column=0)
        assert ma.mandate_name == ""
        assert ma.target == ""
        assert ma.output_type == ""

    def test_mandate_apply_custom(self):
        ma = ast.MandateApplyNode(
            line=3, column=4,
            mandate_name="StrictJSON",
            target="raw_output",
            output_type="ValidJSON",
        )
        assert ma.mandate_name == "StrictJSON"
        assert ma.target == "raw_output"
        assert ma.output_type == "ValidJSON"


# ═══════════════════════════════════════════════════════════════════
#  INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════


class TestMandateIntegration:
    """End-to-end tests: mandate definition + apply through full pipeline."""

    def test_full_pipeline_mandate_and_apply(self):
        """mandate definition + apply → lex → parse → type-check → IR."""
        source = '''mandate StrictJSON {
    constraint: "Output must be valid JSON with keys: name, score"
    kp: 10.0
    ki: 0.1
    kd: 0.05
    tolerance: 0.01
    max_steps: 50
    on_violation: coerce
}

flow AnalyzeData(input: String) -> StructuredReport {
    mandate StrictJSON on input -> ValidatedJSON
    step Analyze {
        ask: "Analyze this data: {input}"
        output: StructuredReport
    }
}'''
        # Type check should pass
        errors = _check(source)
        assert errors == [], f"Unexpected errors: {errors}"

        # IR generation should succeed
        ir = _generate(source)
        assert len(ir.mandate_specs) == 1
        assert ir.mandate_specs[0].name == "StrictJSON"
        assert len(ir.flows) == 1
        assert isinstance(ir.flows[0].steps[0], IRMandateApply)

    def test_mandate_coexists_with_shield(self):
        """mandate and shield can coexist in the same program."""
        source = '''shield InputGuard {
    scan: [prompt_injection]
    on_breach: halt
}

mandate StrictJSON {
    constraint: "Must be JSON"
    on_violation: coerce
}

flow Secure(input: String) -> StructuredReport {
    shield InputGuard on input
    mandate StrictJSON on input -> ValidatedJSON
    step Process {
        ask: "Process"
        output: StructuredReport
    }
}'''
        errors = _check(source)
        assert errors == []
        ir = _generate(source)
        assert len(ir.mandate_specs) == 1
        assert len(ir.shields) == 1
