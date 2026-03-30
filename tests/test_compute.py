"""
AXON Compute Primitive — Compiler Tests
==========================================
Verifies the compute primitive (Deterministic Muscle — §CM)
through all compiler stages: Lexer, Parser, Type Checker, IR Generator,
Backend, and NativeComputeDispatcher.

Based on paper_compute.md — the compute primitive implements
System 1 (Kahneman): fast, automatic, deterministic execution
that bypasses the LLM entirely via the Fast-Path.
"""

import asyncio

import pytest

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker
from axon.compiler.ir_generator import IRGenerator
from axon.compiler import ast_nodes as ast
from axon.compiler.ir_nodes import IRCompute, IRComputeApply, IRProgram
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


# ═══════════════════════════════════════════════════════════════════
#  LEXER TESTS
# ═══════════════════════════════════════════════════════════════════


class TestComputeLexer:
    """Verify that the lexer produces COMPUTE and LOGIC tokens."""

    def test_compute_keyword_token(self):
        tokens = Lexer("compute").tokenize()
        assert tokens[0].type == TokenType.COMPUTE
        assert tokens[0].value == "compute"

    def test_logic_keyword_token(self):
        tokens = Lexer("logic").tokenize()
        assert tokens[0].type == TokenType.LOGIC
        assert tokens[0].value == "logic"

    def test_compute_definition_tokens(self):
        source = 'compute Calc { }'
        tokens = Lexer(source).tokenize()
        assert tokens[0].type == TokenType.COMPUTE
        assert tokens[1].type == TokenType.IDENTIFIER
        assert tokens[1].value == "Calc"
        assert tokens[2].type == TokenType.LBRACE
        assert tokens[3].type == TokenType.RBRACE


# ═══════════════════════════════════════════════════════════════════
#  PARSER TESTS — COMPUTE DEFINITION
# ═══════════════════════════════════════════════════════════════════


class TestComputeDefinitionParser:
    """Verify parsing of top-level compute definitions."""

    def test_minimal_compute(self):
        source = '''compute Add {
    input: a (Float), b (Float)
    output: Float
    logic {
        let result = a + b
        return result
    }
}'''
        tree = _parse(source)
        decl = tree.declarations[0]
        assert isinstance(decl, ast.ComputeDefinition)
        assert decl.name == "Add"
        assert len(decl.inputs) == 2
        assert decl.inputs[0].name == "a"
        assert decl.inputs[0].type_expr.name == "Float"
        assert decl.inputs[1].name == "b"
        assert decl.inputs[1].type_expr.name == "Float"
        assert decl.output_type is not None
        assert decl.output_type.name == "Float"
        assert len(decl.logic_body) == 2  # let + return

    def test_compute_with_shield(self):
        source = '''compute Multiply {
    input: x (Float), y (Float)
    output: Float
    shield: TypeSafety
    logic {
        let result = x * y
        return result
    }
}'''
        tree = _parse(source)
        decl = tree.declarations[0]
        assert isinstance(decl, ast.ComputeDefinition)
        assert decl.shield_ref == "TypeSafety"

    def test_compute_single_input(self):
        source = '''compute Double {
    input: val (Integer)
    output: Integer
    logic {
        let result = val * 2
        return result
    }
}'''
        tree = _parse(source)
        decl = tree.declarations[0]
        assert isinstance(decl, ast.ComputeDefinition)
        assert len(decl.inputs) == 1
        assert decl.inputs[0].name == "val"
        assert decl.inputs[0].type_expr.name == "Integer"

    def test_compute_generic_output_type(self):
        source = '''compute Transform {
    input: data (String)
    output: List<String>
    logic {
        return data
    }
}'''
        tree = _parse(source)
        decl = tree.declarations[0]
        assert decl.output_type.name == "List"
        assert decl.output_type.generic_param == "String"


# ═══════════════════════════════════════════════════════════════════
#  PARSER TESTS — COMPUTE APPLY
# ═══════════════════════════════════════════════════════════════════


class TestComputeApplyParser:
    """Verify parsing of in-flow compute applications."""

    def test_compute_apply_basic(self):
        source = '''compute Add {
    input: a (Float), b (Float)
    output: Float
    logic {
        let result = a + b
        return result
    }
}
flow Test() -> Float {
    compute Add on price, 0.19 -> total
    step Report {
        ask: "Report"
        output: Float
    }
}'''
        tree = _parse(source)
        flow = [d for d in tree.declarations if isinstance(d, ast.FlowDefinition)][0]
        apply_node = flow.body[0]
        assert isinstance(apply_node, ast.ComputeApplyNode)
        assert apply_node.compute_name == "Add"
        assert apply_node.arguments == ["price", "0.19"]
        assert apply_node.output_name == "total"

    def test_compute_apply_dotted_arguments(self):
        source = '''compute Calc {
    input: a (Float), b (Float)
    output: Float
    logic {
        return a
    }
}
flow Test() -> Float {
    compute Calc on order.price, tax.rate -> result
    step Report {
        ask: "Report"
        output: Float
    }
}'''
        tree = _parse(source)
        flow = [d for d in tree.declarations if isinstance(d, ast.FlowDefinition)][0]
        apply_node = flow.body[0]
        assert isinstance(apply_node, ast.ComputeApplyNode)
        assert apply_node.arguments == ["order.price", "tax.rate"]
        assert apply_node.output_name == "result"

    def test_compute_apply_no_output_binding(self):
        source = '''compute Noop {
    input: x (String)
    output: String
    logic {
        return x
    }
}
flow Test() -> String {
    compute Noop on data
    step Report {
        ask: "Report"
        output: String
    }
}'''
        tree = _parse(source)
        flow = [d for d in tree.declarations if isinstance(d, ast.FlowDefinition)][0]
        apply_node = flow.body[0]
        assert isinstance(apply_node, ast.ComputeApplyNode)
        assert apply_node.output_name == ""


# ═══════════════════════════════════════════════════════════════════
#  TYPE CHECKER TESTS
# ═══════════════════════════════════════════════════════════════════


class TestComputeTypeChecker:
    """Verify type checking of compute definitions."""

    def test_compute_passes_type_check(self):
        source = '''compute Add {
    input: a (Float), b (Float)
    output: Float
    logic {
        let result = a + b
        return result
    }
}'''
        errors = _check(source)
        assert errors == [], f"Unexpected type errors: {errors}"

    def test_compute_with_flow_passes(self):
        source = '''compute CalculateTax {
    input: amount (Float), rate (Float)
    output: Float
    logic {
        let tax = amount * rate
        let total = amount + tax
        return total
    }
}
flow Process(input: String) -> Float {
    compute CalculateTax on 100.0, 0.19 -> tax_result
    step Report {
        ask: "Report result"
        output: Float
    }
}'''
        errors = _check(source)
        assert errors == [], f"Unexpected type errors: {errors}"


# ═══════════════════════════════════════════════════════════════════
#  IR GENERATOR TESTS
# ═══════════════════════════════════════════════════════════════════


class TestComputeIRGenerator:
    """Verify IR generation for compute primitives."""

    def test_compute_definition_ir(self):
        source = '''compute CalculateTax {
    input: amount (Float), rate (Float)
    output: Float
    logic {
        let tax = amount * rate
        let total = amount + tax
        return total
    }
}'''
        ir = _generate(source)
        assert len(ir.compute_specs) == 1
        spec = ir.compute_specs[0]
        assert isinstance(spec, IRCompute)
        assert spec.name == "CalculateTax"
        assert len(spec.inputs) == 2
        assert spec.inputs[0].name == "amount"
        assert spec.inputs[0].type_name == "Float"
        assert spec.inputs[1].name == "rate"
        assert spec.inputs[1].type_name == "Float"
        assert spec.output_type == "Float"
        assert "tax" in spec.logic_source
        assert "total" in spec.logic_source

    def test_compute_apply_ir(self):
        source = '''compute Add {
    input: a (Float), b (Float)
    output: Float
    logic {
        let result = a + b
        return result
    }
}
flow Test() -> Float {
    compute Add on 10.0, 20.0 -> sum
    step Report {
        ask: "Report"
        output: Float
    }
}'''
        ir = _generate(source)
        assert len(ir.compute_specs) == 1
        flow = ir.flows[0]
        apply_node = flow.steps[0]
        assert isinstance(apply_node, IRComputeApply)
        assert apply_node.compute_name == "Add"
        assert apply_node.arguments == ("10.0", "20.0")
        assert apply_node.output_name == "sum"

    def test_compute_with_shield_verified(self):
        source = '''shield TypeSafety {
    scan: [bias]
}
compute Multiply {
    input: x (Float), y (Float)
    output: Float
    shield: TypeSafety
    logic {
        let result = x * y
        return result
    }
}'''
        ir = _generate(source)
        spec = ir.compute_specs[0]
        assert spec.shield_ref == "TypeSafety"
        assert spec.verified is True

    def test_compute_without_shield_not_verified(self):
        source = '''compute Simple {
    input: x (Float)
    output: Float
    logic {
        return x
    }
}'''
        ir = _generate(source)
        spec = ir.compute_specs[0]
        assert spec.shield_ref == ""
        assert spec.verified is False

    def test_empty_compute_specs_when_none_declared(self):
        source = '''persona Bot { role: "helper" }'''
        ir = _generate(source)
        assert ir.compute_specs == ()

    def test_multiple_compute_definitions(self):
        source = '''compute Add {
    input: a (Float), b (Float)
    output: Float
    logic {
        let result = a + b
        return result
    }
}
compute Multiply {
    input: x (Float), y (Float)
    output: Float
    logic {
        let result = x * y
        return result
    }
}'''
        ir = _generate(source)
        assert len(ir.compute_specs) == 2
        names = {s.name for s in ir.compute_specs}
        assert names == {"Add", "Multiply"}


# ═══════════════════════════════════════════════════════════════════
#  AST NODE TESTS
# ═══════════════════════════════════════════════════════════════════


class TestComputeASTNodes:
    """Verify ComputeDefinition and ComputeApplyNode dataclass defaults."""

    def test_compute_definition_defaults(self):
        c = ast.ComputeDefinition(line=1, column=0)
        assert c.name == ""
        assert c.inputs == []
        assert c.output_type is None
        assert c.logic_body == []
        assert c.shield_ref == ""

    def test_compute_apply_defaults(self):
        ca = ast.ComputeApplyNode(line=1, column=0)
        assert ca.compute_name == ""
        assert ca.arguments == []
        assert ca.output_name == ""

    def test_compute_apply_custom(self):
        ca = ast.ComputeApplyNode(
            line=3, column=4,
            compute_name="CalculateTax",
            arguments=["amount", "0.19"],
            output_name="tax",
        )
        assert ca.compute_name == "CalculateTax"
        assert ca.arguments == ["amount", "0.19"]
        assert ca.output_name == "tax"


# ═══════════════════════════════════════════════════════════════════
#  NATIVE COMPUTE DISPATCHER TESTS
# ═══════════════════════════════════════════════════════════════════


class TestNativeComputeDispatcher:
    """Verify the deterministic Fast-Path compute execution."""

    def _run_async(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_simple_addition(self):
        from axon.runtime.compute_dispatcher import NativeComputeDispatcher
        dispatcher = NativeComputeDispatcher()

        meta = {
            "compute_name": "Add",
            "arguments": ["10.0", "20.0"],
            "output_name": "result",
            "compute_definition": {
                "name": "Add",
                "inputs": [
                    {"name": "a", "type": "Float"},
                    {"name": "b", "type": "Float"},
                ],
                "output_type": "Float",
                "logic_source": "let result = a + b\nreturn result",
                "shield_ref": "",
                "verified": False,
            },
        }

        result = self._run_async(dispatcher.dispatch(meta, {}))
        assert result["output_name"] == "result"
        assert result["result"] == 30.0

    def test_multiplication(self):
        from axon.runtime.compute_dispatcher import NativeComputeDispatcher
        dispatcher = NativeComputeDispatcher()

        meta = {
            "compute_name": "Multiply",
            "arguments": ["5.0", "3.0"],
            "output_name": "product",
            "compute_definition": {
                "name": "Multiply",
                "inputs": [
                    {"name": "x", "type": "Float"},
                    {"name": "y", "type": "Float"},
                ],
                "output_type": "Float",
                "logic_source": "let result = x * y\nreturn result",
                "shield_ref": "",
                "verified": False,
            },
        }

        result = self._run_async(dispatcher.dispatch(meta, {}))
        assert result["result"] == 15.0

    def test_tax_calculation(self):
        from axon.runtime.compute_dispatcher import NativeComputeDispatcher
        dispatcher = NativeComputeDispatcher()

        meta = {
            "compute_name": "CalculateTax",
            "arguments": ["100.0", "0.19"],
            "output_name": "tax_result",
            "compute_definition": {
                "name": "CalculateTax",
                "inputs": [
                    {"name": "amount", "type": "Float"},
                    {"name": "rate", "type": "Float"},
                ],
                "output_type": "Float",
                "logic_source": (
                    "let tax = amount * rate\n"
                    "let total = amount + tax\n"
                    "return total"
                ),
                "shield_ref": "",
                "verified": False,
            },
        }

        result = self._run_async(dispatcher.dispatch(meta, {}))
        assert result["output_name"] == "tax_result"
        assert abs(result["result"] - 119.0) < 0.001

    def test_argument_from_context(self):
        from axon.runtime.compute_dispatcher import NativeComputeDispatcher
        dispatcher = NativeComputeDispatcher()

        meta = {
            "compute_name": "Add",
            "arguments": ["order.price", "0.19"],
            "output_name": "total",
            "compute_definition": {
                "name": "Add",
                "inputs": [
                    {"name": "a", "type": "Float"},
                    {"name": "b", "type": "Float"},
                ],
                "output_type": "Float",
                "logic_source": "let result = a + b\nreturn result",
                "shield_ref": "",
                "verified": False,
            },
        }

        context = {"order": {"price": 50.0}}
        result = self._run_async(dispatcher.dispatch(meta, context))
        assert result["result"] == 50.19

    def test_division(self):
        from axon.runtime.compute_dispatcher import NativeComputeDispatcher
        dispatcher = NativeComputeDispatcher()

        meta = {
            "compute_name": "Divide",
            "arguments": ["100.0", "4.0"],
            "output_name": "quotient",
            "compute_definition": {
                "name": "Divide",
                "inputs": [
                    {"name": "a", "type": "Float"},
                    {"name": "b", "type": "Float"},
                ],
                "output_type": "Float",
                "logic_source": "let result = a / b\nreturn result",
                "shield_ref": "",
                "verified": False,
            },
        }

        result = self._run_async(dispatcher.dispatch(meta, {}))
        assert result["result"] == 25.0

    def test_no_logic_returns_none(self):
        from axon.runtime.compute_dispatcher import NativeComputeDispatcher
        dispatcher = NativeComputeDispatcher()

        meta = {
            "compute_name": "Empty",
            "arguments": [],
            "output_name": "out",
            "compute_definition": {
                "name": "Empty",
                "inputs": [],
                "output_type": "String",
                "logic_source": "",
                "shield_ref": "",
                "verified": False,
            },
        }

        result = self._run_async(dispatcher.dispatch(meta, {}))
        assert result["result"] is None


# ═══════════════════════════════════════════════════════════════════
#  INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════


class TestComputeIntegration:
    """End-to-end tests: compute definition + apply through full pipeline."""

    def test_full_pipeline_compute_and_apply(self):
        """compute definition + apply → lex → parse → type-check → IR."""
        source = '''compute CalculateTax {
    input: amount (Float), rate (Float)
    output: Float
    logic {
        let tax = amount * rate
        let total = amount + tax
        return total
    }
}

flow ProcessInvoice(input: String) -> Float {
    compute CalculateTax on 100.0, 0.19 -> tax_result
    step Summarize {
        ask: "Summarize"
        output: Float
    }
}'''
        # Type check should pass
        errors = _check(source)
        assert errors == [], f"Unexpected errors: {errors}"

        # IR generation should succeed
        ir = _generate(source)
        assert len(ir.compute_specs) == 1
        assert ir.compute_specs[0].name == "CalculateTax"
        assert len(ir.flows) == 1
        assert isinstance(ir.flows[0].steps[0], IRComputeApply)

    def test_compute_coexists_with_mandate(self):
        """compute and mandate can coexist in the same program."""
        source = '''mandate StrictJSON {
    constraint: "Must be JSON"
}
compute Add {
    input: a (Float), b (Float)
    output: Float
    logic {
        let result = a + b
        return result
    }
}
flow Test() -> Float {
    compute Add on 1.0, 2.0 -> sum
    step Report {
        ask: "Report"
        output: Float
    }
}'''
        errors = _check(source)
        assert errors == [], f"Unexpected errors: {errors}"
        ir = _generate(source)
        assert len(ir.mandate_specs) == 1
        assert len(ir.compute_specs) == 1

    def test_compute_coexists_with_shield(self):
        """compute and shield can coexist in the same program."""
        source = '''shield TypeSafety {
    scan: [bias]
}
compute Calc {
    input: x (Float)
    output: Float
    shield: TypeSafety
    logic {
        return x
    }
}'''
        errors = _check(source)
        assert errors == [], f"Unexpected errors: {errors}"
        ir = _generate(source)
        assert len(ir.compute_specs) == 1
        assert ir.compute_specs[0].verified is True


# ═══════════════════════════════════════════════════════════════════
#  BACKEND TESTS
# ═══════════════════════════════════════════════════════════════════


class TestComputeBackend:
    """Verify backend compilation of compute steps."""

    def test_compute_compiled_as_metadata_step(self):
        """Compute apply nodes should be compiled into metadata-only steps."""
        source = '''compute Add {
    input: a (Float), b (Float)
    output: Float
    logic {
        let result = a + b
        return result
    }
}

persona Helper { role: "helper" }
context General { domain: "general" }

flow Test() -> Float {
    compute Add on 1.0, 2.0 -> sum
    step Report {
        ask: "Report"
        output: Float
    }
}

run Test() as Helper within General'''
        from axon.backends.anthropic_backend import AnthropicBackend
        ir = _generate(source)
        backend = AnthropicBackend()
        compiled = backend.compile_program(ir)

        assert len(compiled.execution_units) == 1
        unit = compiled.execution_units[0]

        # First step should be the compute metadata step
        compute_step = unit.steps[0]
        assert compute_step.step_name == "compute:Add"
        assert compute_step.user_prompt == ""
        assert "compute" in compute_step.metadata
        meta = compute_step.metadata["compute"]
        assert meta["compute_name"] == "Add"
        assert meta["arguments"] == ["1.0", "2.0"]
        assert meta["output_name"] == "sum"
        assert meta["compute_definition"]["name"] == "Add"
        assert meta["compute_definition"]["output_type"] == "Float"
