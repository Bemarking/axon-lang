"""
AXON Ontological Tool Synthesis (OTS) Primitive — Compiler Tests
================================================================
Verifies the OTS primitive through all compiler stages:
Lexer, Parser, Type Checker, and IR Generator.
"""

import pytest

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker
from axon.compiler.ir_generator import IRGenerator
from axon.compiler import ast_nodes as ast
from axon.compiler.ir_nodes import IROtsDefinition, IROtsApply, IRProgram
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

def _program(*declarations) -> ast.ProgramNode:
    return ast.ProgramNode(line=0, column=0, declarations=list(declarations))

# ═══════════════════════════════════════════════════════════════════
#  LEXER TESTS
# ═══════════════════════════════════════════════════════════════════

class TestOtsLexer:
    """Lexer correctly tokenizes ots keywords."""

    def test_ots_keyword(self):
        tokens = Lexer("ots").tokenize()
        assert tokens[0].type == TokenType.OTS

    def test_teleology_keyword(self):
        tokens = Lexer("teleology").tokenize()
        assert tokens[0].type == TokenType.TELEOLOGY

    def test_linear_constraints_keyword(self):
        tokens = Lexer("linear_constraints").tokenize()
        assert tokens[0].type == TokenType.LINEAR_CONSTRAINTS

    def test_homotopy_search_keyword(self):
        tokens = Lexer("homotopy_search").tokenize()
        assert tokens[0].type == TokenType.HOMOTOPY_SEARCH

    def test_loss_function_keyword(self):
        tokens = Lexer("loss_function").tokenize()
        assert tokens[0].type == TokenType.LOSS_FUNCTION

    def test_ots_block_tokens(self):
        src = 'ots DataProcessor<RawData, CleanData> { teleology: "Clean it" }'
        tokens = Lexer(src).tokenize()
        types = [t.type for t in tokens[:-1]]  # skip EOF
        assert types == [
            TokenType.OTS, TokenType.IDENTIFIER, TokenType.LT, 
            TokenType.IDENTIFIER, TokenType.COMMA, TokenType.IDENTIFIER, 
            TokenType.GT, TokenType.LBRACE,
            TokenType.TELEOLOGY, TokenType.COLON, TokenType.STRING, TokenType.RBRACE,
        ]

# ═══════════════════════════════════════════════════════════════════
#  PARSER TESTS
# ═══════════════════════════════════════════════════════════════════

class TestOtsParser:
    """Parser produces valid OtsDefinition AST nodes."""

    def test_ots_minimal(self):
        tree = _parse('ots Processor { teleology: "Process" }')
        o = tree.declarations[0]
        assert isinstance(o, ast.OtsDefinition)
        assert o.name == "Processor"
        assert o.input_type is None
        assert o.output_type is None
        assert o.teleology == "Process"
        assert o.linear_constraints == {}
        assert o.homotopy_search == "shallow"
        assert o.loss_function == ""
        assert o.body == []

    def test_ots_full(self):
        source = '''ots ContentSynthesizer<Raw, Structured> {
    teleology: "Mute noise"
    linear_constraints: {
        complexity: low,
        verbosity: minimal
    }
    homotopy_search: deep
    loss_function: L2
    step Parser {
        ask: "Parse it"
        output: Structured
    }
}'''
        tree = _parse(source)
        o = tree.declarations[0]
        assert isinstance(o, ast.OtsDefinition)
        assert o.name == "ContentSynthesizer"
        assert o.input_type.name == "Raw"
        assert o.output_type.name == "Structured"
        assert o.teleology == "Mute noise"
        assert o.linear_constraints == {"complexity": "low", "verbosity": "minimal"}
        assert o.homotopy_search == "deep"
        assert o.loss_function == "L2"
        assert len(o.body) == 1

# ═══════════════════════════════════════════════════════════════════
#  PARSER — OTS APPLY (in-flow)
# ═══════════════════════════════════════════════════════════════════

class TestOtsApplyParser:
    """Parser handles ots X(Y) -> Z in flow steps."""

    def test_ots_apply_basic(self):
        source = '''flow Test() -> Result {
    ots Processor(input) -> OutputType
}'''
        tree = _parse(source)
        flow = tree.declarations[0]
        assert isinstance(flow.body[0], ast.OtsApplyNode)
        oa = flow.body[0]
        assert oa.ots_name == "Processor"
        assert oa.target == "input"
        assert oa.output_type == "OutputType"

# ═══════════════════════════════════════════════════════════════════
#  TYPE CHECKER TESTS
# ═══════════════════════════════════════════════════════════════════

class TestOtsTypeChecker:
    """Type checker validates OTS configuration fields."""

    def test_valid_ots_passes(self):
        source = '''ots Synthesizer<A, B> {
    teleology: "Teleological goal"
}'''
        errors = _check(source)
        assert errors == []

    def test_missing_teleology(self):
        source = '''ots Synthesizer<A, B> {
    loss_function: L2
}'''
        errors = _check(source)
        assert len(errors) == 1
        assert "teleology" in errors[0].message

# ═══════════════════════════════════════════════════════════════════
#  IR GENERATOR TESTS
# ═══════════════════════════════════════════════════════════════════

class TestOtsIRGenerator:
    """OTS AST → IR transformation."""

    def test_ots_produces_ir_and_apply(self):
        source = '''ots Synthesizer<InputType, OutputType> {
    teleology: "Do something"
    linear_constraints: { a: strictly_once }
    homotopy_search: deep
    loss_function: L1
}

flow TestFlow() -> OutputType {
    ots Synthesizer(data) -> OutputType
}'''
        prog = _generate(source)
        assert len(prog.ots_specs) == 1
        ir_ots = prog.ots_specs[0]
        assert isinstance(ir_ots, IROtsDefinition)
        assert ir_ots.name == "Synthesizer"
        assert ir_ots.types == ("InputType", "OutputType")
        assert ir_ots.teleology == "Do something"
        assert ir_ots.linear_constraints == (("a", "strictly_once"),)
        assert ir_ots.homotopy_search == "deep"
        assert ir_ots.loss_function == "L1"
        assert ir_ots.children == ()

        # Flow contains ots apply step
        flow = prog.flows[0]
        assert isinstance(flow.steps[0], IROtsApply)
        assert flow.steps[0].ots_name == "Synthesizer"
        assert flow.steps[0].target == "data"
        assert flow.steps[0].output_type == "OutputType"
