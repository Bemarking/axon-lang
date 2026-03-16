"""
AXON Shield Primitive — Compiler Tests
=========================================
Verifies the shield primitive through all compiler stages:
Lexer, Parser, Type Checker, and IR Generator.
"""

import pytest

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker
from axon.compiler.ir_generator import IRGenerator
from axon.compiler import ast_nodes as ast
from axon.compiler.ir_nodes import IRShield, IRShieldApply, IRProgram
from axon.compiler.tokens import TokenType
from axon.compiler.errors import AxonParseError


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


def _shield_ast(**kw) -> ast.ShieldDefinition:
    """Create a ShieldDefinition AST node with defaults."""
    defaults = dict(
        line=1, column=0, name="InputGuard",
        scan=["prompt_injection", "jailbreak"],
        strategy="dual_llm",
        on_breach="halt",
        severity="critical",
    )
    defaults.update(kw)
    return ast.ShieldDefinition(**defaults)


def _program(*declarations) -> ast.ProgramNode:
    return ast.ProgramNode(line=0, column=0, declarations=list(declarations))


# ═══════════════════════════════════════════════════════════════════
#  LEXER TESTS
# ═══════════════════════════════════════════════════════════════════


class TestShieldLexer:
    """Lexer correctly tokenizes shield keywords."""

    def test_shield_keyword(self):
        tokens = Lexer("shield").tokenize()
        assert tokens[0].type == TokenType.SHIELD

    def test_scan_keyword(self):
        tokens = Lexer("scan").tokenize()
        assert tokens[0].type == TokenType.SCAN

    def test_on_breach_keyword(self):
        tokens = Lexer("on_breach").tokenize()
        assert tokens[0].type == TokenType.ON_BREACH

    def test_severity_keyword(self):
        tokens = Lexer("severity").tokenize()
        assert tokens[0].type == TokenType.SEVERITY

    def test_allow_keyword(self):
        tokens = Lexer("allow").tokenize()
        assert tokens[0].type == TokenType.ALLOW

    def test_deny_keyword(self):
        tokens = Lexer("deny").tokenize()
        assert tokens[0].type == TokenType.DENY

    def test_sandbox_keyword(self):
        tokens = Lexer("sandbox").tokenize()
        assert tokens[0].type == TokenType.SANDBOX

    def test_quarantine_keyword(self):
        tokens = Lexer("quarantine").tokenize()
        assert tokens[0].type == TokenType.QUARANTINE

    def test_redact_keyword(self):
        tokens = Lexer("redact").tokenize()
        assert tokens[0].type == TokenType.REDACT

    def test_shield_block_tokens(self):
        src = 'shield Guard { scan: [jailbreak] }'
        tokens = Lexer(src).tokenize()
        types = [t.type for t in tokens[:-1]]  # skip EOF
        assert types == [
            TokenType.SHIELD, TokenType.IDENTIFIER, TokenType.LBRACE,
            TokenType.SCAN, TokenType.COLON, TokenType.LBRACKET,
            TokenType.IDENTIFIER, TokenType.RBRACKET, TokenType.RBRACE,
        ]


# ═══════════════════════════════════════════════════════════════════
#  PARSER TESTS
# ═══════════════════════════════════════════════════════════════════


class TestShieldParser:
    """Parser produces valid ShieldDefinition AST nodes."""

    def test_shield_minimal(self):
        tree = _parse("shield Guard { }")
        s = tree.declarations[0]
        assert isinstance(s, ast.ShieldDefinition)
        assert s.name == "Guard"
        assert s.scan == []
        assert s.strategy == "pattern"   # default

    def test_shield_full(self):
        source = '''shield InputGuard {
    scan: [prompt_injection, jailbreak, pii_leak]
    strategy: dual_llm
    on_breach: halt
    severity: critical
    allow: [web_search, calculator]
    deny: [code_executor]
    sandbox: true
    redact: [email, phone]
    max_retries: 3
    confidence_threshold: 0.85
}'''
        tree = _parse(source)
        s = tree.declarations[0]
        assert isinstance(s, ast.ShieldDefinition)
        assert s.name == "InputGuard"
        assert s.scan == ["prompt_injection", "jailbreak", "pii_leak"]
        assert s.strategy == "dual_llm"
        assert s.on_breach == "halt"
        assert s.severity == "critical"
        assert s.allow_tools == ["web_search", "calculator"]
        assert s.deny_tools == ["code_executor"]
        assert s.sandbox is True
        assert s.redact == ["email", "phone"]
        assert s.max_retries == 3
        assert s.confidence_threshold == 0.85

    def test_shield_scan_empty_list(self):
        tree = _parse("shield Guard { scan: [] }")
        s = tree.declarations[0]
        assert s.scan == []

    def test_shield_allow_empty_list(self):
        tree = _parse("shield Guard { allow: [] }")
        s = tree.declarations[0]
        assert s.allow_tools == []

    def test_shield_deny_empty_list(self):
        tree = _parse("shield Guard { deny: [] }")
        s = tree.declarations[0]
        assert s.deny_tools == []

    def test_shield_redact_empty_list(self):
        tree = _parse("shield Guard { redact: [] }")
        s = tree.declarations[0]
        assert s.redact == []

    def test_shield_sandbox_false(self):
        tree = _parse("shield Guard { sandbox: false }")
        s = tree.declarations[0]
        assert s.sandbox is False

    def test_shield_quarantine_field(self):
        tree = _parse("shield Guard { quarantine: untrusted_input }")
        s = tree.declarations[0]
        assert s.quarantine == "untrusted_input"

    def test_shield_log_field(self):
        tree = _parse("shield Guard { log: verbose }")
        s = tree.declarations[0]
        assert s.log == "verbose"

    def test_shield_deflect_message(self):
        tree = _parse('shield Guard { deflect_message: "I cannot process that request." }')
        s = tree.declarations[0]
        assert s.deflect_message == "I cannot process that request."

    def test_shield_source_location(self):
        tree = _parse("shield Guard { }")
        s = tree.declarations[0]
        assert s.line == 1
        assert s.column == 1

    def test_multiple_shields(self):
        source = '''shield Input { scan: [jailbreak] }
shield Output { scan: [pii_leak] }'''
        tree = _parse(source)
        assert len(tree.declarations) == 2
        assert tree.declarations[0].name == "Input"
        assert tree.declarations[1].name == "Output"


# ═══════════════════════════════════════════════════════════════════
#  PARSER — SHIELD APPLY (in-flow)
# ═══════════════════════════════════════════════════════════════════


class TestShieldApplyParser:
    """Parser handles shield X on Y in flow steps."""

    def test_shield_apply_basic(self):
        source = '''flow Test() -> Result {
    shield Guard on user_input
    step Process {
        ask: "Process the input"
        output: Result
    }
}'''
        tree = _parse(source)
        flow = tree.declarations[0]
        assert isinstance(flow.body[0], ast.ShieldApplyNode)
        sa = flow.body[0]
        assert sa.shield_name == "Guard"
        assert sa.target == "user_input"
        assert sa.output_type == ""

    def test_shield_apply_with_output_type(self):
        source = '''flow Test() -> Result {
    shield Guard on raw_data -> SanitizedData
    step Process {
        ask: "Process"
        output: Result
    }
}'''
        tree = _parse(source)
        sa = tree.declarations[0].body[0]
        assert sa.shield_name == "Guard"
        assert sa.target == "raw_data"
        assert sa.output_type == "SanitizedData"


# ═══════════════════════════════════════════════════════════════════
#  PARSER — AGENT SHIELD REFERENCE
# ═══════════════════════════════════════════════════════════════════


class TestAgentShieldRef:
    """Agent definition carries shield_ref field."""

    def test_agent_shield_ref_field(self):
        agent = ast.AgentDefinition(
            line=1, column=0, name="Bot",
            tools=["web_search"],
            shield_ref="InputGuard",
        )
        assert agent.shield_ref == "InputGuard"

    def test_agent_shield_ref_default_empty(self):
        agent = ast.AgentDefinition(line=1, column=0, name="Bot")
        assert agent.shield_ref == ""


# ═══════════════════════════════════════════════════════════════════
#  TYPE CHECKER TESTS
# ═══════════════════════════════════════════════════════════════════


class TestShieldTypeChecker:
    """Type checker validates shield configuration fields."""

    def test_valid_shield_passes(self):
        source = '''shield Guard {
    scan: [prompt_injection, jailbreak]
    strategy: dual_llm
    on_breach: halt
    severity: critical
}'''
        errors = _check(source)
        assert errors == []

    def test_invalid_scan_category(self):
        source = '''shield Guard {
    scan: [alien_attack]
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "alien_attack" in errors[0].message
        assert "scan category" in errors[0].message

    def test_invalid_strategy(self):
        source = '''shield Guard {
    strategy: quantum_llm
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "quantum_llm" in errors[0].message
        assert "strategy" in errors[0].message

    def test_invalid_on_breach(self):
        source = '''shield Guard {
    on_breach: explode
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "explode" in errors[0].message
        assert "on_breach" in errors[0].message

    def test_invalid_severity(self):
        source = '''shield Guard {
    severity: ultra
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "ultra" in errors[0].message
        assert "severity" in errors[0].message

    def test_negative_max_retries(self):
        shield = _shield_ast(max_retries=-1)
        tree = _program(shield)
        errors = TypeChecker(tree).check()
        assert any("max_retries" in e.message and "negative" in e.message for e in errors)

    def test_confidence_threshold_too_high(self):
        shield = _shield_ast(confidence_threshold=1.5)
        tree = _program(shield)
        errors = TypeChecker(tree).check()
        assert any("confidence_threshold" in e.message for e in errors)

    def test_confidence_threshold_too_low(self):
        shield = _shield_ast(confidence_threshold=-0.1)
        tree = _program(shield)
        errors = TypeChecker(tree).check()
        assert any("confidence_threshold" in e.message for e in errors)

    def test_allow_deny_overlap(self):
        source = '''shield Guard {
    allow: [web_search, calculator]
    deny: [web_search]
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "web_search" in errors[0].message
        assert "allow" in errors[0].message and "deny" in errors[0].message

    def test_multiple_errors(self):
        source = '''shield Guard {
    scan: [alien_attack, cosmic_ray]
    strategy: unknown_strategy
    severity: mega
}'''
        errors = _check(source)
        # alien_attack, cosmic_ray, unknown_strategy, mega = 4 errors
        assert len(errors) >= 4


class TestShieldTypeCheckerCapabilities:
    """Type checker enforces capability constraints."""

    def test_agent_tool_outside_shield_allow(self):
        shield = _shield_ast(allow_tools=["web_search"])
        agent = ast.AgentDefinition(
            line=5, column=0, name="Bot",
            tools=["web_search", "code_executor"],
            shield_ref="InputGuard",
        )
        tree = _program(shield, agent)
        errors = TypeChecker(tree).check()
        assert any("code_executor" in e.message and "not permitted" in e.message for e in errors)

    def test_agent_tools_all_allowed(self):
        shield = _shield_ast(allow_tools=["web_search", "calculator"])
        agent = ast.AgentDefinition(
            line=5, column=0, name="Bot",
            tools=["web_search"],
            shield_ref="InputGuard",
        )
        tree = _program(shield, agent)
        errors = TypeChecker(tree).check()
        # No capability violation
        cap_errors = [e for e in errors if "not permitted" in e.message]
        assert cap_errors == []


class TestShieldApplyTypeChecker:
    """Type checker validates shield apply references."""

    def test_shield_apply_wrong_kind(self):
        """Using a persona name where shield is expected."""
        persona = ast.PersonaDefinition(line=1, column=0, name="Expert")
        apply_node = ast.ShieldApplyNode(
            line=5, column=0, shield_name="Expert", target="data",
        )
        flow = ast.FlowDefinition(
            line=3, column=0, name="TestFlow",
            parameters=[ast.ParameterNode(
                line=3, column=15, name="doc",
                type_expr=ast.TypeExprNode(name="Document"),
            )],
            body=[apply_node],
        )
        tree = _program(persona, flow)
        errors = TypeChecker(tree).check()
        assert any("not a shield" in e.message for e in errors)


class TestDuplicateShield:
    """Type checker catches duplicate shield names."""

    def test_duplicate_shield(self):
        source = '''shield Guard { scan: [jailbreak] }
shield Guard { scan: [pii_leak] }'''
        errors = _check(source)
        assert any("Duplicate" in e.message for e in errors)


# ═══════════════════════════════════════════════════════════════════
#  IR GENERATOR TESTS
# ═══════════════════════════════════════════════════════════════════


class TestShieldIRGenerator:
    """Shield AST → IR transformation."""

    def test_shield_produces_ir(self):
        shield = _shield_ast(
            scan=["prompt_injection", "jailbreak"],
            strategy="dual_llm",
            on_breach="halt",
            severity="critical",
            allow_tools=["web_search"],
            deny_tools=["code_executor"],
            sandbox=True,
            redact=["email", "phone"],
        )
        gen = IRGenerator()
        prog = gen.generate(_program(shield))
        assert len(prog.shields) == 1
        ir = prog.shields[0]
        assert isinstance(ir, IRShield)
        assert ir.name == "InputGuard"
        assert ir.scan == ("prompt_injection", "jailbreak")
        assert ir.strategy == "dual_llm"
        assert ir.on_breach == "halt"
        assert ir.severity == "critical"
        assert ir.allow_tools == ("web_search",)
        assert ir.deny_tools == ("code_executor",)
        assert ir.sandbox is True
        assert ir.redact == ("email", "phone")

    def test_shield_source_location(self):
        shield = _shield_ast(line=42, column=5)
        gen = IRGenerator()
        prog = gen.generate(_program(shield))
        ir = prog.shields[0]
        assert ir.source_line == 42
        assert ir.source_column == 5

    def test_minimal_shield_ir(self):
        shield = ast.ShieldDefinition(name="Min", line=1, column=0)
        gen = IRGenerator()
        prog = gen.generate(_program(shield))
        ir = prog.shields[0]
        assert ir.name == "Min"
        assert ir.scan == ()
        assert ir.strategy == "pattern"
        assert ir.sandbox is False

    def test_multiple_shields_ir(self):
        s1 = _shield_ast(name="Input")
        s2 = _shield_ast(name="Output")
        gen = IRGenerator()
        prog = gen.generate(_program(s1, s2))
        assert len(prog.shields) == 2
        names = {s.name for s in prog.shields}
        assert names == {"Input", "Output"}

    def test_shield_apply_ir(self):
        shield = _shield_ast()
        apply_node = ast.ShieldApplyNode(
            line=5, column=0,
            shield_name="InputGuard",
            target="user_input",
            output_type="SanitizedInput",
        )
        flow = ast.FlowDefinition(
            line=3, column=0, name="TestFlow",
            parameters=[ast.ParameterNode(
                line=3, column=15, name="doc",
                type_expr=ast.TypeExprNode(name="Document"),
            )],
            body=[apply_node, ast.StepNode(
                line=10, column=4, name="Process",
                ask="Do work", output_type="Result",
            )],
        )
        gen = IRGenerator()
        prog = gen.generate(_program(shield, flow))
        # The shield apply should be in the flow steps
        ir_flow = prog.flows[0]
        shield_step = ir_flow.steps[0]
        assert isinstance(shield_step, IRShieldApply)
        assert shield_step.shield_name == "InputGuard"
        assert shield_step.target == "user_input"
        assert shield_step.output_type == "SanitizedInput"

    def test_agent_shield_ref_in_ir(self):
        shield = _shield_ast()
        agent = ast.AgentDefinition(
            line=5, column=0, name="Bot",
            tools=["web_search"],
            shield_ref="InputGuard",
        )
        gen = IRGenerator()
        prog = gen.generate(_program(shield, agent))
        ir_agent = prog.agents[0]
        assert ir_agent.shield_ref == "InputGuard"


# ═══════════════════════════════════════════════════════════════════
#  FULL PIPELINE INTEGRATION
# ═══════════════════════════════════════════════════════════════════


class TestShieldPipeline:
    """End-to-end: source → lex → parse → check → IR."""

    def test_full_pipeline(self):
        source = '''shield InputGuard {
    scan: [prompt_injection, jailbreak]
    strategy: dual_llm
    on_breach: halt
    severity: critical
    allow: [web_search]
    deny: [code_executor]
    sandbox: true
    redact: [email, phone]
}

persona Tester {
    role: "security tester"
}

flow TestFlow() -> Analysis {
    shield InputGuard on user_input
    step ValidateInput {
        ask: "What is the input?"
        output: Analysis
    }
}

run TestFlow()
    as Tester'''
        # Must not raise
        errors = _check(source)
        assert errors == []

        ir = _generate(source)
        assert len(ir.shields) == 1
        assert ir.shields[0].name == "InputGuard"
        assert ir.shields[0].scan == ("prompt_injection", "jailbreak")

        # Flow contains shield apply step
        flow = ir.flows[0]
        assert isinstance(flow.steps[0], IRShieldApply)
        assert flow.steps[0].shield_name == "InputGuard"
        assert flow.steps[0].target == "user_input"

    def test_pipeline_with_shield_errors(self):
        source = '''shield Bad {
    scan: [alien_attack]
    strategy: quantum
    on_breach: explode
    severity: mega
}'''
        errors = _check(source)
        assert len(errors) >= 4
