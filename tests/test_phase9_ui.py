"""
AXON — Fase 9 UI Cognitiva declarativa tests
=============================================
Compile-time contracts for the `component` + `view` primitives.

Scope:
  * §9.1  Parser + AST + IR for component / view.
  * §9.2  Type-checker rules: renders→type, on_interact→flow signature,
          via_shield→shield, view.components→component.
  * §9.5  Regulated-render contract: shield must cover κ of type.
  * §9.6  Reference program `examples/ui/healthcare_console.axon`
          compiles cleanly end-to-end.
"""

from __future__ import annotations

import pytest

from axon.compiler import frontend
from axon.compiler.ir_generator import IRGenerator
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

def compile_ir(source: str):
    tree = Parser(Lexer(source).tokenize()).parse()
    return IRGenerator().generate(tree)


def check(source: str):
    return frontend.check_source(source, "ui_test.axon")


_OK_PREAMBLE = """
type PatientRecord compliance [HIPAA] { id: String }
flow SummarizeRecord(rec: PatientRecord) -> PatientRecord {
    step Review { ask: "s" output: PatientRecord }
}
shield PHIShield {
    scan: [pii_leak]
    on_breach: halt
    severity: critical
    compliance: [HIPAA]
}
"""


# ═══════════════════════════════════════════════════════════════════
#  §9.1 — Parser + AST + IR
# ═══════════════════════════════════════════════════════════════════

class TestComponentParsing:

    def test_minimal_component_parses(self):
        src = "type T { f: String }\ncomponent C { renders: T render_hint: card }"
        ir = compile_ir(src)
        assert len(ir.components) == 1
        c = ir.components[0]
        assert c.name == "C"
        assert c.renders == "T"
        assert c.render_hint == "card"
        assert c.via_shield == ""
        assert c.on_interact == ""

    def test_full_component_fields_round_trip(self):
        src = _OK_PREAMBLE + """
            component PatientCard {
                renders: PatientRecord
                via_shield: PHIShield
                on_interact: SummarizeRecord
                render_hint: card
            }
        """
        ir = compile_ir(src)
        c = ir.components[0]
        assert c.renders == "PatientRecord"
        assert c.via_shield == "PHIShield"
        assert c.on_interact == "SummarizeRecord"
        assert c.render_hint == "card"

    def test_invalid_render_hint_rejected_by_parser(self):
        src = "type T { f: String }\ncomponent C { renders: T render_hint: sculpture }"
        with pytest.raises(Exception):
            compile_ir(src)


class TestViewParsing:

    def test_minimal_view_parses(self):
        src = (
            "type T { f: String }\n"
            "component C { renders: T }\n"
            'view V { title: "Home" components: [C] }'
        )
        ir = compile_ir(src)
        assert len(ir.views) == 1
        v = ir.views[0]
        assert v.name == "V"
        assert v.title == "Home"
        assert v.components == ("C",)

    def test_view_with_route_round_trips(self):
        src = (
            "type T { f: String }\n"
            "component C { renders: T }\n"
            'view Home { title: "Home" components: [C] route: "/home" }'
        )
        ir = compile_ir(src)
        assert ir.views[0].route == "/home"

    def test_view_composes_multiple_components(self):
        src = """
            type T { f: String }
            component A { renders: T }
            component B { renders: T }
            view V { components: [A, B] }
        """
        ir = compile_ir(src)
        assert ir.views[0].components == ("A", "B")


# ═══════════════════════════════════════════════════════════════════
#  §9.2 — Type-checker rules
# ═══════════════════════════════════════════════════════════════════

class TestComponentTypeCheck:

    def test_component_must_have_renders(self):
        src = "component C { render_hint: card }"
        diags = check(src).diagnostics
        assert any("requires 'renders" in d.message for d in diags)

    def test_renders_must_resolve_to_a_type(self):
        src = "component C { renders: Ghost }"
        diags = check(src).diagnostics
        assert any("undefined type 'Ghost'" in d.message for d in diags)

    def test_renders_wrong_kind_is_rejected(self):
        src = """
            flow F() -> String { step S { ask: "x" output: String } }
            component C { renders: F }
        """
        diags = check(src).diagnostics
        assert any("is a flow, not a type" in d.message for d in diags)

    def test_unknown_shield_ref_is_rejected(self):
        src = "type T { f: String }\ncomponent C { renders: T via_shield: Ghost }"
        diags = check(src).diagnostics
        assert any("undefined shield 'Ghost'" in d.message for d in diags)

    def test_on_interact_must_be_a_flow(self):
        src = "type T { f: String }\ncomponent C { renders: T on_interact: T }"
        diags = check(src).diagnostics
        assert any("is a type, not a flow" in d.message for d in diags)

    def test_on_interact_flow_signature_must_match_renders(self):
        src = """
            type T { f: String }
            type U { f: String }
            flow G(u: U) -> U { step S { ask: "x" output: U } }
            component C { renders: T on_interact: G }
        """
        diags = check(src).diagnostics
        assert any(
            "Signatures must match" in d.message or "expects first parameter of type 'U'" in d.message
            for d in diags
        )


class TestViewTypeCheck:

    def test_empty_components_is_rejected(self):
        src = 'view V { title: "Empty" components: [] }'
        # Parser rejects empty brackets, so use omission instead.
        src = 'view V { title: "Empty" }'
        diags = check(src).diagnostics
        assert any("empty components list" in d.message for d in diags)

    def test_unknown_component_ref_is_rejected(self):
        src = 'view V { components: [Ghost] }'
        diags = check(src).diagnostics
        assert any("undefined component 'Ghost'" in d.message for d in diags)

    def test_wrong_kind_component_ref_is_rejected(self):
        src = """
            type T { f: String }
            view V { components: [T] }
        """
        diags = check(src).diagnostics
        assert any("is a type, not a component" in d.message for d in diags)

    def test_duplicate_component_in_view_is_rejected(self):
        src = """
            type T { f: String }
            component A { renders: T }
            view V { components: [A, A] }
        """
        diags = check(src).diagnostics
        assert any("more than once" in d.message for d in diags)


# ═══════════════════════════════════════════════════════════════════
#  §9.5 — Regulated-render contract (shield ⊇ type.κ)
# ═══════════════════════════════════════════════════════════════════

class TestRegulatedRender:

    def test_regulated_type_requires_via_shield(self):
        src = _OK_PREAMBLE + """
            component BadCard { renders: PatientRecord }
        """
        diags = check(src).diagnostics
        assert any(
            "renders regulated type" in d.message and "no 'via_shield'" in d.message
            for d in diags
        )

    def test_shield_must_cover_full_kappa(self):
        src = """
            type PatientRecord compliance [HIPAA, GDPR] { id: String }
            shield PartialShield {
                scan: [pii_leak]
                on_breach: halt
                severity: critical
                compliance: [HIPAA]
            }
            component HalfCard { renders: PatientRecord via_shield: PartialShield }
        """
        diags = check(src).diagnostics
        assert any(
            "does not cover" in d.message and "GDPR" in d.message
            for d in diags
        )

    def test_shield_covering_exactly_the_kappa_is_accepted(self):
        src = _OK_PREAMBLE + """
            component PatientCard {
                renders: PatientRecord
                via_shield: PHIShield
                render_hint: card
            }
        """
        diags = check(src).diagnostics
        assert not diags, f"expected clean compile, got {diags}"

    def test_shield_covering_superset_of_kappa_is_accepted(self):
        src = """
            type PatientRecord compliance [HIPAA] { id: String }
            shield SuperShield {
                scan: [pii_leak]
                on_breach: halt
                severity: critical
                compliance: [HIPAA, GDPR, SOC2]
            }
            component PatientCard {
                renders: PatientRecord
                via_shield: SuperShield
                render_hint: card
            }
        """
        diags = check(src).diagnostics
        assert not diags, f"expected clean compile, got {diags}"

    def test_unregulated_type_does_not_require_shield(self):
        src = """
            type Note { text: String }
            component NoteCard { renders: Note render_hint: card }
        """
        diags = check(src).diagnostics
        assert not diags, f"expected clean compile, got {diags}"


# ═══════════════════════════════════════════════════════════════════
#  §9.6 — Reference UI program end-to-end
# ═══════════════════════════════════════════════════════════════════

_HEALTHCARE_UI = "examples/ui/healthcare_console.axon"


class TestHealthcareConsoleReference:

    @pytest.fixture(scope="class")
    def ir(self):
        from pathlib import Path
        source = Path(_HEALTHCARE_UI).read_text(encoding="utf-8")
        return compile_ir(source)

    def test_compiles_clean(self, ir):
        from pathlib import Path
        source = Path(_HEALTHCARE_UI).read_text(encoding="utf-8")
        diags = check(source).diagnostics
        assert not diags, f"healthcare_console must compile clean, got {diags}"

    def test_has_three_regulated_components(self, ir):
        # PatientCard, TrialEntry, DiagnosticPanel
        assert len(ir.components) == 3
        names = {c.name for c in ir.components}
        assert names == {"PatientCard", "TrialEntry", "DiagnosticPanel"}

    def test_regulated_components_carry_shield(self, ir):
        by_name = {c.name: c for c in ir.components}
        assert by_name["PatientCard"].via_shield == "PHIShield"
        assert by_name["TrialEntry"].via_shield == "TrialShield"
        # Unregulated component: no shield required.
        assert by_name["DiagnosticPanel"].via_shield == ""

    def test_two_top_level_views(self, ir):
        assert len(ir.views) == 2
        names = {v.name for v in ir.views}
        assert names == {"ClinicianDashboard", "TrialOversight"}

    def test_views_have_routes(self, ir):
        by_name = {v.name: v for v in ir.views}
        assert by_name["ClinicianDashboard"].route == "/clinician"
        assert by_name["TrialOversight"].route == "/trials"

    def test_on_interact_wiring_matches_flow_signatures(self, ir):
        by_name = {c.name: c for c in ir.components}
        # PatientCard → SummarizeRecord(rec: PatientRecord)
        assert by_name["PatientCard"].on_interact == "SummarizeRecord"
        # TrialEntry → AnalyzeTrial(entry: ClinicalTrial)
        assert by_name["TrialEntry"].on_interact == "AnalyzeTrial"
