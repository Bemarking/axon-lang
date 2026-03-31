"""APX Phase 2 tests: parser, IR generation, and type checker integration."""

from __future__ import annotations

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker
from axon.compiler.ir_generator import IRGenerator
from axon.compiler.ast_nodes import ImportNode, ProgramNode


def _parse(source: str) -> ProgramNode:
    tokens = Lexer(source).tokenize()
    return Parser(tokens).parse()


def test_import_with_apx_policy_parses() -> None:
    tree = _parse(
        """
import axon.stdlib with apx {
  min_epr: 0.7
  on_low_rank: quarantine
  trust_floor: cited_fact
  ffi_mode: taint
  require_pcc: true
  allow_scopes: [@trusted, axon]
}
""".strip()
    )

    node = tree.declarations[0]
    assert isinstance(node, ImportNode)
    assert node.module_path == ["axon", "stdlib"]
    assert node.apx_enabled is True
    assert node.apx_policy["min_epr"] == 0.7
    assert node.apx_policy["on_low_rank"] == "quarantine"
    assert node.apx_policy["require_pcc"] is True
    assert node.apx_policy["allow_scopes"] == ["@trusted", "axon"]


def test_import_with_apx_without_block_parses() -> None:
    tree = _parse("import axon.anchors with apx")
    node = tree.declarations[0]
    assert isinstance(node, ImportNode)
    assert node.apx_enabled is True
    assert node.apx_policy == {}


def test_import_ir_contains_apx_policy() -> None:
    tree = _parse(
        """
import axon.stdlib with apx {
  min_epr: 0.55
  on_low_rank: warn
}
""".strip()
    )
    ir = IRGenerator().generate(tree)
    imp = ir.imports[0]

    assert imp.apx_enabled is True
    assert dict(imp.apx_policy)["min_epr"] == 0.55
    assert dict(imp.apx_policy)["on_low_rank"] == "warn"


def test_typechecker_accepts_valid_apx_policy() -> None:
    tree = _parse(
        """
import axon.stdlib with apx {
  min_epr: 0.8
  on_low_rank: block
  trust_floor: factual_claim
  ffi_mode: strict
  require_pcc: false
}
""".strip()
    )
    errors = TypeChecker(tree).check()
    assert errors == []


def test_typechecker_rejects_invalid_min_epr() -> None:
    tree = _parse(
        """
import axon.stdlib with apx {
  min_epr: 1.5
}
""".strip()
    )
    errors = TypeChecker(tree).check()
    assert any("min_epr" in e.message for e in errors)


def test_typechecker_rejects_unknown_apx_key() -> None:
    tree = _parse(
        """
import axon.stdlib with apx {
  unknown_policy: foo
}
""".strip()
    )
    errors = TypeChecker(tree).check()
    assert any("Unknown APX policy key" in e.message for e in errors)
