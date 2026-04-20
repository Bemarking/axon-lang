"""
AXON Compiler — Phase 6.1 Compile-time Compliance tests
=========================================================
Verifies that the type checker rejects programs whose shields do not
cover the regulatory classes of the data they handle.

Per plan_io_cognitivo.md §6.1 this is the killer-feature moat: HIPAA,
PCI_DSS, GDPR, SOX, etc. become dependent types.  A program that
touches PHI without a HIPAA-covering shield does NOT compile — the
compiler itself is the auditor.
"""

from __future__ import annotations

import pytest

from axon.compiler.ast_nodes import (
    AxonEndpointDefinition,
    ShieldDefinition,
    TypeDefinition,
)
from axon.compiler.ir_generator import IRGenerator
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker


def _parse(source: str):
    return Parser(Lexer(source).tokenize()).parse()


def _check(source: str):
    return TypeChecker(_parse(source)).check()


def _compile(source: str):
    return IRGenerator().generate(_parse(source))


# ═══════════════════════════════════════════════════════════════════
#  Parser: compliance annotations are captured
# ═══════════════════════════════════════════════════════════════════


class TestComplianceParsing:

    def test_type_carries_compliance(self):
        tree = _parse('type PHI compliance [HIPAA, GDPR] { ssn: String }')
        t = tree.declarations[0]
        assert isinstance(t, TypeDefinition)
        assert t.compliance == ["HIPAA", "GDPR"]

    def test_type_without_compliance_defaults_to_empty(self):
        tree = _parse('type Public { name: String }')
        t = tree.declarations[0]
        assert t.compliance == []

    def test_shield_carries_compliance(self):
        tree = _parse('''shield S {
  scan: [pii_leak]
  on_breach: quarantine
  severity: high
  compliance: [HIPAA, SOC2]
}''')
        s = tree.declarations[0]
        assert isinstance(s, ShieldDefinition)
        assert s.compliance == ["HIPAA", "SOC2"]

    def test_endpoint_carries_compliance(self):
        src = '''type PHI compliance [HIPAA] { ssn: String }
flow F(rec: PHI) -> String { step S { ask: "a" output: String } }
shield S { scan: [pii_leak] on_breach: quarantine severity: high compliance: [HIPAA] }
axonendpoint A {
  method: post
  path: "/a"
  body: PHI
  execute: F
  output: String
  shield: S
  compliance: [HIPAA]
}'''
        tree = _parse(src)
        ep = tree.declarations[3]
        assert isinstance(ep, AxonEndpointDefinition)
        assert ep.compliance == ["HIPAA"]


# ═══════════════════════════════════════════════════════════════════
#  Type checker: §6.1 coverage enforcement
# ═══════════════════════════════════════════════════════════════════


_BASE = '''
type PHI compliance [HIPAA] { ssn: String }
flow Process(rec: PHI) -> String { step S { ask: "x" output: String } }
'''


class TestComplianceCoverage:

    def test_valid_coverage_compiles_clean(self):
        src = _BASE + '''
shield PhiShield { scan: [pii_leak] on_breach: quarantine severity: high compliance: [HIPAA] }
axonendpoint Api {
  method: post path: "/p" body: PHI execute: Process output: String
  shield: PhiShield compliance: [HIPAA]
}'''
        assert _check(src) == []

    def test_shield_missing_required_class_rejected(self):
        src = _BASE + '''
shield Weak { scan: [pii_leak] on_breach: quarantine severity: high compliance: [SOC2] }
axonendpoint Api {
  method: post path: "/p" body: PHI execute: Process output: String shield: Weak
}'''
        errors = _check(src)
        assert any("does not cover regulatory class" in e.message for e in errors)
        assert any("HIPAA" in e.message for e in errors)

    def test_regulated_endpoint_without_shield_rejected(self):
        src = _BASE + '''
axonendpoint Api {
  method: post path: "/p" body: PHI execute: Process output: String
}'''
        errors = _check(src)
        assert any("declares no shield" in e.message for e in errors)
        assert any("Fase 6.1" in e.message for e in errors)

    def test_unknown_regulatory_class_rejected(self):
        """Typos like HIPPA or GPPR become compile errors."""
        src = 'type X compliance [HIPPA] { ssn: String }'
        errors = _check(src)
        assert any("unknown regulatory class 'HIPPA'" in e.message for e in errors)

    def test_endpoint_compliance_union_with_body_type(self):
        """Endpoint.compliance ∪ body_type.compliance must all be covered."""
        src = '''type PHI compliance [HIPAA] { ssn: String }
flow F(rec: PHI) -> String { step S { ask: "x" output: String } }
shield HIPAAShield { scan: [pii_leak] on_breach: quarantine severity: high compliance: [HIPAA] }
axonendpoint Api {
  method: post path: "/p" body: PHI execute: F output: String
  shield: HIPAAShield
  compliance: [PCI_DSS]
}'''
        errors = _check(src)
        # HIPAA covered by shield; PCI_DSS required by endpoint but not covered.
        assert any("PCI_DSS" in e.message for e in errors)

    def test_non_regulated_type_does_not_require_shield(self):
        src = '''type Open { x: String }
flow F(v: Open) -> String { step S { ask: "x" output: String } }
axonendpoint Api {
  method: post path: "/p" body: Open execute: F output: String
}'''
        assert _check(src) == []

    def test_output_type_compliance_also_enforced(self):
        src = '''type Result compliance [GDPR] { data: String }
type Input { x: String }
flow F(i: Input) -> Result { step S { ask: "x" output: Result } }
axonendpoint Api {
  method: post path: "/p" body: Input execute: F output: Result
}'''
        errors = _check(src)
        assert any("GDPR" in e.message for e in errors)


# ═══════════════════════════════════════════════════════════════════
#  IR: compliance fields make it into IRType / IRShield / IREndpoint
# ═══════════════════════════════════════════════════════════════════


class TestComplianceIR:

    _SRC = '''
type PHI compliance [HIPAA] { ssn: String }
flow F(x: PHI) -> String { step S { ask: "x" output: String } }
shield S { scan: [pii_leak] on_breach: quarantine severity: high compliance: [HIPAA, SOC2] }
axonendpoint A {
  method: post path: "/p" body: PHI execute: F output: String
  shield: S compliance: [HIPAA]
}
'''

    def test_ir_type_has_compliance(self):
        ir = _compile(self._SRC)
        phi = next(t for t in ir.types if t.name == "PHI")
        assert phi.compliance == ("HIPAA",)

    def test_ir_shield_has_compliance(self):
        ir = _compile(self._SRC)
        s = next(s for s in ir.shields if s.name == "S")
        assert set(s.compliance) == {"HIPAA", "SOC2"}

    def test_ir_endpoint_has_compliance(self):
        ir = _compile(self._SRC)
        a = next(e for e in ir.endpoints if e.name == "A")
        assert a.compliance == ("HIPAA",)
