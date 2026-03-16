"""
AXON PIX Primitive — Compiler Tests
=======================================
Verifies the PIX primitive through all compiler stages:
Lexer, Parser, Type Checker, and IR Generator.

Mirrors the structure of test_shield.py for consistency.
"""

import pytest

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker
from axon.compiler.ir_generator import IRGenerator
from axon.compiler import ast_nodes as ast
from axon.compiler.ir_nodes import IRPixSpec, IRNavigate, IRDrill, IRTrail, IRProgram
from axon.compiler.tokens import TokenType


# ═══════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════


def _lex(source: str) -> list:
    """Tokenize source code."""
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


def _program(*declarations) -> ast.ProgramNode:
    return ast.ProgramNode(line=0, column=0, declarations=list(declarations))


# ═══════════════════════════════════════════════════════════════════
#  LEXER TESTS
# ═══════════════════════════════════════════════════════════════════


class TestPixLexer:
    """Lexer correctly tokenizes PIX keywords."""

    def test_pix_keyword(self):
        tokens = _lex("pix")
        assert tokens[0].type == TokenType.PIX

    def test_navigate_keyword(self):
        tokens = _lex("navigate")
        assert tokens[0].type == TokenType.NAVIGATE

    def test_drill_keyword(self):
        tokens = _lex("drill")
        assert tokens[0].type == TokenType.DRILL

    def test_trail_keyword(self):
        tokens = _lex("trail")
        assert tokens[0].type == TokenType.TRAIL

    def test_pix_block_tokens(self):
        src = 'pix ContractIndex { source: "file.pdf" }'
        tokens = _lex(src)
        types = [t.type for t in tokens[:-1]]  # skip EOF
        assert types[0] == TokenType.PIX
        assert types[1] == TokenType.IDENTIFIER
        assert types[2] == TokenType.LBRACE

    def test_navigate_in_flow_tokens(self):
        src = 'navigate ContractIndex'
        tokens = _lex(src)
        assert tokens[0].type == TokenType.NAVIGATE
        assert tokens[1].type == TokenType.IDENTIFIER

    def test_drill_in_flow_tokens(self):
        src = 'drill ContractIndex'
        tokens = _lex(src)
        assert tokens[0].type == TokenType.DRILL
        assert tokens[1].type == TokenType.IDENTIFIER


# ═══════════════════════════════════════════════════════════════════
#  PARSER TESTS — PIX DEFINITION
# ═══════════════════════════════════════════════════════════════════


class TestPixParser:
    """Parser produces valid PixDefinition AST nodes."""

    def test_pix_minimal(self):
        tree = _parse('pix Index { source: "data.md" }')
        p = tree.declarations[0]
        assert isinstance(p, ast.PixDefinition)
        assert p.name == "Index"
        assert p.source == "data.md"

    def test_pix_full(self):
        source = '''pix ContractIndex {
    source: "contracts/master_agreement.pdf"
    depth: 6
    branching: 5
    model: fast
}'''
        tree = _parse(source)
        p = tree.declarations[0]
        assert isinstance(p, ast.PixDefinition)
        assert p.name == "ContractIndex"
        assert p.source == "contracts/master_agreement.pdf"
        assert p.depth == 6
        assert p.branching == 5
        assert p.model == "fast"

    def test_pix_defaults(self):
        tree = _parse('pix Index { source: "data.md" }')
        p = tree.declarations[0]
        assert p.depth == 4      # default
        assert p.branching == 3  # default
        assert p.model == "fast" # default

    def test_pix_custom_depth(self):
        tree = _parse('pix Index { source: "data.md" depth: 8 }')
        p = tree.declarations[0]
        assert p.depth == 8

    def test_pix_custom_branching(self):
        tree = _parse('pix Index { source: "data.md" branching: 7 }')
        p = tree.declarations[0]
        assert p.branching == 7

    def test_pix_custom_model(self):
        tree = _parse('pix Index { source: "data.md" model: precise }')
        p = tree.declarations[0]
        assert p.model == "precise"

    def test_pix_source_location(self):
        tree = _parse('pix Index { source: "data.md" }')
        p = tree.declarations[0]
        assert p.line >= 1

    def test_multiple_pix(self):
        source = '''pix Contracts { source: "contracts.md" }
pix Policies { source: "policies.md" }'''
        tree = _parse(source)
        assert len(tree.declarations) == 2
        assert tree.declarations[0].name == "Contracts"
        assert tree.declarations[1].name == "Policies"


# ═══════════════════════════════════════════════════════════════════
#  PARSER TESTS — NAVIGATE, DRILL, TRAIL (in-flow)
# ═══════════════════════════════════════════════════════════════════


class TestPixFlowParser:
    """Parser handles navigate/drill/trail inside flows."""

    def test_navigate_basic(self):
        source = '''flow Search() -> Result {
    navigate ContractIndex with query: "What are the liabilities?"
    step Analyze {
        ask: "Analyze"
        output: Result
    }
}'''
        tree = _parse(source)
        flow = tree.declarations[0]
        nav = flow.body[0]
        assert isinstance(nav, ast.NavigateNode)
        assert nav.pix_name == "ContractIndex"
        assert nav.query_expr == "What are the liabilities?"

    def test_navigate_with_trail(self):
        source = '''flow Search() -> Result {
    navigate ContractIndex with query: "question" trail: enabled
    step Analyze {
        ask: "Analyze"
        output: Result
    }
}'''
        tree = _parse(source)
        nav = tree.declarations[0].body[0]
        assert isinstance(nav, ast.NavigateNode)
        assert nav.trail_enabled is True

    def test_navigate_with_output(self):
        source = '''flow Search() -> Result {
    navigate ContractIndex with query: "question" as: nav_result
    step Analyze {
        ask: "Analyze"
        output: Result
    }
}'''
        tree = _parse(source)
        nav = tree.declarations[0].body[0]
        assert nav.output_name == "nav_result"

    def test_drill_basic(self):
        source = '''flow DeepSearch() -> Result {
    drill ContractIndex into "Section3.Liabilities" with query: "damages"
    step Analyze {
        ask: "Analyze"
        output: Result
    }
}'''
        tree = _parse(source)
        flow = tree.declarations[0]
        drill = flow.body[0]
        assert isinstance(drill, ast.DrillNode)
        assert drill.pix_name == "ContractIndex"
        assert drill.subtree_path == "Section3.Liabilities"
        assert drill.query_expr == "damages"

    def test_drill_with_output(self):
        source = '''flow Search() -> Result {
    drill Index into "path" with query: "q" as: drill_result
    step Analyze {
        ask: "Analyze"
        output: Result
    }
}'''
        tree = _parse(source)
        drill = tree.declarations[0].body[0]
        assert drill.output_name == "drill_result"

    def test_trail_basic(self):
        source = '''flow Audit() -> Result {
    trail nav_result
    step Report {
        ask: "Generate audit"
        output: Result
    }
}'''
        tree = _parse(source)
        trail = tree.declarations[0].body[0]
        assert isinstance(trail, ast.TrailNode)
        assert trail.navigate_ref == "nav_result"


# ═══════════════════════════════════════════════════════════════════
#  TYPE CHECKER TESTS
# ═══════════════════════════════════════════════════════════════════


class TestPixTypeChecker:
    """Type checker validates PIX definitions."""

    def test_valid_pix_passes(self):
        source = '''pix Index {
    source: "data.md"
    depth: 4
    branching: 3
    model: fast
}'''
        errors = _check(source)
        assert errors == []

    def test_depth_too_low(self):
        pix = ast.PixDefinition(line=1, column=0, name="Bad", source="x.md", depth=0)
        tree = _program(pix)
        errors = TypeChecker(tree).check()
        assert any("depth" in e.message for e in errors)

    def test_depth_too_high(self):
        pix = ast.PixDefinition(line=1, column=0, name="Bad", source="x.md", depth=9)
        tree = _program(pix)
        errors = TypeChecker(tree).check()
        assert any("depth" in e.message for e in errors)

    def test_depth_boundary_valid(self):
        pix1 = ast.PixDefinition(line=1, column=0, name="Min", source="x.md", depth=1)
        pix2 = ast.PixDefinition(line=2, column=0, name="Max", source="x.md", depth=8)
        tree = _program(pix1, pix2)
        errors = TypeChecker(tree).check()
        depth_errors = [e for e in errors if "depth" in e.message]
        assert depth_errors == []

    def test_branching_too_low(self):
        pix = ast.PixDefinition(line=1, column=0, name="Bad", source="x.md", branching=0)
        tree = _program(pix)
        errors = TypeChecker(tree).check()
        assert any("branching" in e.message for e in errors)

    def test_branching_too_high(self):
        pix = ast.PixDefinition(line=1, column=0, name="Bad", source="x.md", branching=11)
        tree = _program(pix)
        errors = TypeChecker(tree).check()
        assert any("branching" in e.message for e in errors)

    def test_branching_boundary_valid(self):
        pix1 = ast.PixDefinition(line=1, column=0, name="Min", source="x.md", branching=1)
        pix2 = ast.PixDefinition(line=2, column=0, name="Max", source="x.md", branching=10)
        tree = _program(pix1, pix2)
        errors = TypeChecker(tree).check()
        branching_errors = [e for e in errors if "branching" in e.message]
        assert branching_errors == []

    def test_multiple_pix_errors(self):
        pix = ast.PixDefinition(
            line=1, column=0, name="Bad", source="x.md",
            depth=0, branching=15,
        )
        tree = _program(pix)
        errors = TypeChecker(tree).check()
        assert len(errors) >= 2

    def test_duplicate_pix_name(self):
        source = '''pix Index { source: "a.md" }
pix Index { source: "b.md" }'''
        errors = _check(source)
        assert any("Duplicate" in e.message for e in errors)


class TestPixFlowTypeChecker:
    """Type checker validates navigate/drill/trail references."""

    def test_navigate_wrong_kind(self):
        """Using a persona name where pix is expected."""
        persona = ast.PersonaDefinition(line=1, column=0, name="Expert")
        nav = ast.NavigateNode(
            line=5, column=0, pix_name="Expert", query_expr="question",
        )
        flow = ast.FlowDefinition(
            line=3, column=0, name="TestFlow",
            parameters=[ast.ParameterNode(
                line=3, column=15, name="doc",
                type_expr=ast.TypeExprNode(name="Document"),
            )],
            body=[nav],
        )
        tree = _program(persona, flow)
        errors = TypeChecker(tree).check()
        assert any("not a pix" in e.message for e in errors)

    def test_drill_wrong_kind(self):
        """Using a persona name where pix is expected for drill."""
        persona = ast.PersonaDefinition(line=1, column=0, name="Expert")
        drill = ast.DrillNode(
            line=5, column=0, pix_name="Expert",
            subtree_path="section1", query_expr="question",
        )
        flow = ast.FlowDefinition(
            line=3, column=0, name="TestFlow",
            parameters=[ast.ParameterNode(
                line=3, column=15, name="doc",
                type_expr=ast.TypeExprNode(name="Document"),
            )],
            body=[drill],
        )
        tree = _program(persona, flow)
        errors = TypeChecker(tree).check()
        assert any("not a pix" in e.message for e in errors)


# ═══════════════════════════════════════════════════════════════════
#  IR GENERATOR TESTS
# ═══════════════════════════════════════════════════════════════════


class TestPixIRGenerator:
    """PIX AST → IR transformation."""

    def test_pix_produces_ir(self):
        pix = ast.PixDefinition(
            line=1, column=0, name="ContractIndex",
            source="contracts.md", depth=6, branching=5, model="precise",
        )
        gen = IRGenerator()
        prog = gen.generate(_program(pix))
        # PIX specs should be stored internally
        assert "ContractIndex" in gen._pix_specs
        ir = gen._pix_specs["ContractIndex"]
        assert isinstance(ir, IRPixSpec)
        assert ir.name == "ContractIndex"
        assert ir.source == "contracts.md"
        assert ir.max_depth == 6
        assert ir.max_branching == 5
        assert ir.model == "precise"

    def test_pix_source_location(self):
        pix = ast.PixDefinition(
            line=42, column=5, name="Index", source="data.md",
        )
        gen = IRGenerator()
        gen.generate(_program(pix))
        ir = gen._pix_specs["Index"]
        assert ir.source_line == 42
        assert ir.source_column == 5

    def test_minimal_pix_ir(self):
        pix = ast.PixDefinition(line=1, column=0, name="Min", source="x.md")
        gen = IRGenerator()
        gen.generate(_program(pix))
        ir = gen._pix_specs["Min"]
        assert ir.name == "Min"
        assert ir.max_depth == 4   # default
        assert ir.max_branching == 3  # default
        assert ir.effect_row is None

    def test_multiple_pix_ir(self):
        p1 = ast.PixDefinition(line=1, column=0, name="Index1", source="a.md")
        p2 = ast.PixDefinition(line=2, column=0, name="Index2", source="b.md")
        gen = IRGenerator()
        gen.generate(_program(p1, p2))
        assert len(gen._pix_specs) == 2
        assert "Index1" in gen._pix_specs
        assert "Index2" in gen._pix_specs

    def test_navigate_ir(self):
        pix = ast.PixDefinition(line=1, column=0, name="Index", source="data.md")
        nav = ast.NavigateNode(
            line=5, column=0, pix_name="Index",
            query_expr="What are the risks?",
            trail_enabled=True, output_name="nav_result",
        )
        flow = ast.FlowDefinition(
            line=3, column=0, name="TestFlow",
            parameters=[ast.ParameterNode(
                line=3, column=15, name="doc",
                type_expr=ast.TypeExprNode(name="Document"),
            )],
            body=[nav, ast.StepNode(
                line=10, column=4, name="Process",
                ask="Do work", output_type="Result",
            )],
        )
        gen = IRGenerator()
        prog = gen.generate(_program(pix, flow))
        ir_flow = prog.flows[0]
        ir_nav = ir_flow.steps[0]
        assert isinstance(ir_nav, IRNavigate)
        assert ir_nav.pix_ref == "Index"
        assert ir_nav.query == "What are the risks?"
        assert ir_nav.trail_enabled is True
        assert ir_nav.output_name == "nav_result"

    def test_drill_ir(self):
        pix = ast.PixDefinition(line=1, column=0, name="Index", source="data.md")
        drill = ast.DrillNode(
            line=5, column=0, pix_name="Index",
            subtree_path="Section3.Liabilities",
            query_expr="damages", output_name="drill_result",
        )
        flow = ast.FlowDefinition(
            line=3, column=0, name="TestFlow",
            parameters=[ast.ParameterNode(
                line=3, column=15, name="doc",
                type_expr=ast.TypeExprNode(name="Document"),
            )],
            body=[drill, ast.StepNode(
                line=10, column=4, name="Process",
                ask="Do work", output_type="Result",
            )],
        )
        gen = IRGenerator()
        prog = gen.generate(_program(pix, flow))
        ir_flow = prog.flows[0]
        ir_drill = ir_flow.steps[0]
        assert isinstance(ir_drill, IRDrill)
        assert ir_drill.pix_ref == "Index"
        assert ir_drill.subtree_path == "Section3.Liabilities"
        assert ir_drill.query == "damages"
        assert ir_drill.output_name == "drill_result"

    def test_trail_ir(self):
        pix = ast.PixDefinition(line=1, column=0, name="Index", source="data.md")
        trail = ast.TrailNode(
            line=5, column=0, navigate_ref="nav_result",
        )
        flow = ast.FlowDefinition(
            line=3, column=0, name="TestFlow",
            parameters=[ast.ParameterNode(
                line=3, column=15, name="doc",
                type_expr=ast.TypeExprNode(name="Document"),
            )],
            body=[trail, ast.StepNode(
                line=10, column=4, name="Process",
                ask="Do work", output_type="Result",
            )],
        )
        gen = IRGenerator()
        prog = gen.generate(_program(pix, flow))
        ir_flow = prog.flows[0]
        ir_trail = ir_flow.steps[0]
        assert isinstance(ir_trail, IRTrail)
        assert ir_trail.navigate_ref == "nav_result"


# ═══════════════════════════════════════════════════════════════════
#  IR NODE SERIALIZATION
# ═══════════════════════════════════════════════════════════════════


class TestPixIRSerialization:
    """PIX IR nodes serialize to dict correctly."""

    def test_pix_spec_to_dict(self):
        ir = IRPixSpec(
            source_line=1, source_column=0,
            name="Index", source="data.md",
            max_depth=6, max_branching=5, model="precise",
        )
        d = ir.to_dict()
        assert d["node_type"] == "pix_spec"
        assert d["name"] == "Index"
        assert d["source"] == "data.md"
        assert d["max_depth"] == 6
        assert d["max_branching"] == 5
        assert d["model"] == "precise"

    def test_navigate_to_dict(self):
        ir = IRNavigate(
            source_line=5, source_column=0,
            pix_ref="Index", query="What?",
            trail_enabled=True, output_name="result",
        )
        d = ir.to_dict()
        assert d["node_type"] == "navigate"
        assert d["pix_ref"] == "Index"
        assert d["query"] == "What?"
        assert d["trail_enabled"] is True
        assert d["output_name"] == "result"

    def test_drill_to_dict(self):
        ir = IRDrill(
            source_line=5, source_column=0,
            pix_ref="Index", subtree_path="s3.liabilities",
            query="damages", output_name="result",
        )
        d = ir.to_dict()
        assert d["node_type"] == "drill"
        assert d["subtree_path"] == "s3.liabilities"

    def test_trail_to_dict(self):
        ir = IRTrail(
            source_line=5, source_column=0,
            navigate_ref="nav_result",
        )
        d = ir.to_dict()
        assert d["node_type"] == "trail"
        assert d["navigate_ref"] == "nav_result"


# ═══════════════════════════════════════════════════════════════════
#  FULL PIPELINE INTEGRATION
# ═══════════════════════════════════════════════════════════════════


class TestPixPipeline:
    """End-to-end: source → lex → parse → check → IR."""

    def test_full_pipeline(self):
        source = '''pix ContractIndex {
    source: "contracts/master_agreement.pdf"
    depth: 6
    branching: 5
    model: precise
}

persona Analyst {
    role: "contract analyst"
}

flow AnalyzeContract() -> Analysis {
    navigate ContractIndex with query: "What are the liability limits?"
    step Summarize {
        ask: "Summarize the findings"
        output: Analysis
    }
}

run AnalyzeContract()
    as Analyst'''
        # Must not raise
        errors = _check(source)
        assert errors == []

        ir = _generate(source)
        # Check PIX IR was generated
        gen = IRGenerator()
        gen.generate(Parser(Lexer(source).tokenize()).parse())
        assert "ContractIndex" in gen._pix_specs
        pix_ir = gen._pix_specs["ContractIndex"]
        assert pix_ir.source == "contracts/master_agreement.pdf"
        assert pix_ir.max_depth == 6
        assert pix_ir.max_branching == 5

        # Flow contains navigate step
        flow = ir.flows[0]
        assert isinstance(flow.steps[0], IRNavigate)
        assert flow.steps[0].pix_ref == "ContractIndex"

    def test_pipeline_with_pix_errors(self):
        source = '''pix Bad {
    source: "data.md"
    depth: 0
    branching: 15
}'''
        errors = _check(source)
        assert len(errors) >= 2

    def test_pipeline_drill_and_trail(self):
        source = '''pix Index {
    source: "data.md"
    depth: 4
}

flow DeepSearch() -> Result {
    drill Index into "section3" with query: "damages"
    trail drill_result
    step Analyze {
        ask: "Analyze"
        output: Result
    }
}'''
        errors = _check(source)
        assert errors == []
