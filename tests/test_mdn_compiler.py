"""
AXON Compiler — MDN Compiler Integration Tests
================================================
Tests for the Multi-Document Navigation compiler pipeline:
  Source → Lexer → Parser → AST → TypeChecker → IRGenerator → IR

Covers:
  - Lexer: CORPUS, CORROBORATE, EDGE_FILTER tokens
  - Parser: corpus definition, corroborate, extended navigate
  - Type checker: corpus validation (G1–G4), corroborate validation
  - IR generator: corpus spec, corroborate, extended navigate IR
  - Full pipeline: source → IR for MDN constructs

Each test references the formal basis from multi_document.md.
"""

import pytest

from axon.compiler.tokens import TokenType, Token
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker
from axon.compiler.ir_generator import IRGenerator
from axon.compiler.ast_nodes import (
    CorpusDefinition,
    CorpusDocEntry,
    CorpusEdgeEntry,
    CorroborateNode,
    FlowDefinition,
    NavigateNode,
    ProgramNode,
)
from axon.compiler.ir_nodes import (
    IRCorpusSpec,
    IRCorpusDocSpec,
    IRCorpusEdgeSpec,
    IRCorroborate,
    IRNavigate,
)


# ═══════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════

def _lex(source: str) -> list[Token]:
    """Tokenize a source string."""
    return Lexer(source).tokenize()


def _parse(source: str) -> ProgramNode:
    """Parse a source string into a ProgramNode."""
    tokens = _lex(source)
    return Parser(tokens).parse()


def _typecheck(source: str) -> list:
    """Type-check a source string, return errors."""
    program = _parse(source)
    checker = TypeChecker(program)
    return checker.check()


def _compile(source: str):
    """Full compilation pipeline: source → IR."""
    program = _parse(source)
    checker = TypeChecker(program)
    errors = checker.check()
    assert not errors, f"Type errors: {errors}"
    generator = IRGenerator()
    return generator.generate(program)


# ═══════════════════════════════════════════════════════════════════
#  1. LEXER TESTS — MDN Token Recognition
# ═══════════════════════════════════════════════════════════════════

class TestMDNLexer:
    """Test that MDN keywords are correctly tokenized."""

    def test_corpus_keyword(self):
        """'corpus' should lex as TokenType.CORPUS."""
        tokens = _lex("corpus")
        assert tokens[0].type == TokenType.CORPUS

    def test_corroborate_keyword(self):
        """'corroborate' should lex as TokenType.CORROBORATE."""
        tokens = _lex("corroborate")
        assert tokens[0].type == TokenType.CORROBORATE

    def test_edge_filter_keyword(self):
        """'edge_filter' should lex as TokenType.EDGE_FILTER."""
        tokens = _lex("edge_filter")
        assert tokens[0].type == TokenType.EDGE_FILTER

    def test_mdn_keywords_in_context(self):
        """MDN keywords should be recognized among other tokens."""
        tokens = _lex("corpus MyCorpus corroborate result edge_filter")
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert TokenType.CORPUS in types
        assert TokenType.CORROBORATE in types
        assert TokenType.EDGE_FILTER in types


# ═══════════════════════════════════════════════════════════════════
#  2. PARSER TESTS — Corpus Definition
# ═══════════════════════════════════════════════════════════════════

class TestCorpusParser:
    """Test corpus definition parsing."""

    CORPUS_SOURCE = """
corpus LegalCorpus {
    documents: [statute_A, case_law_B, regulation_C]
    relationships: [
        (case_law_B, statute_A, cite),
        (regulation_C, statute_A, implement)
    ]
    weights: {
        (case_law_B, statute_A, cite): 0.9,
        (regulation_C, statute_A, implement): 0.7
    }
}
"""

    def test_corpus_parse_name(self):
        """Corpus name is correctly parsed."""
        program = _parse(self.CORPUS_SOURCE)
        corpus = program.declarations[0]
        assert isinstance(corpus, CorpusDefinition)
        assert corpus.name == "LegalCorpus"

    def test_corpus_parse_documents(self):
        """Document list is correctly parsed as CorpusDocEntry nodes."""
        program = _parse(self.CORPUS_SOURCE)
        corpus = program.declarations[0]
        assert len(corpus.documents) == 3
        refs = [d.pix_ref for d in corpus.documents]
        assert refs == ["statute_A", "case_law_B", "regulation_C"]

    def test_corpus_parse_edges(self):
        """Edge list is correctly parsed as CorpusEdgeEntry nodes."""
        program = _parse(self.CORPUS_SOURCE)
        corpus = program.declarations[0]
        assert len(corpus.edges) == 2
        edge1 = corpus.edges[0]
        assert edge1.source_ref == "case_law_B"
        assert edge1.target_ref == "statute_A"
        assert edge1.relation_type == "cite"

    def test_corpus_parse_weights(self):
        """Weight map is correctly parsed."""
        program = _parse(self.CORPUS_SOURCE)
        corpus = program.declarations[0]
        assert len(corpus.weights) == 2
        assert corpus.weights["case_law_B,statute_A,cite"] == pytest.approx(0.9)
        assert corpus.weights["regulation_C,statute_A,implement"] == pytest.approx(0.7)

    def test_corpus_minimal(self):
        """Minimal corpus with only documents."""
        source = """
corpus MinCorpus {
    documents: [doc_a]
}
"""
        program = _parse(source)
        corpus = program.declarations[0]
        assert isinstance(corpus, CorpusDefinition)
        assert corpus.name == "MinCorpus"
        assert len(corpus.documents) == 1
        assert len(corpus.edges) == 0


# ═══════════════════════════════════════════════════════════════════
#  3. PARSER TESTS — Corroborate
# ═══════════════════════════════════════════════════════════════════

class TestCorroborateParser:
    """Test corroborate statement parsing within flow context."""

    def test_corroborate_basic(self):
        """Corroborate with output name parses correctly."""
        source = """
flow VerifyFlow() {
    step gather {
        ask: "gather data"
    }
    corroborate nav_result as: verified_claims
}
"""
        program = _parse(source)
        flow = program.declarations[0]
        corr = flow.body[1]
        assert isinstance(corr, CorroborateNode)
        assert corr.navigate_ref == "nav_result"
        assert corr.output_name == "verified_claims"

    def test_corroborate_without_as(self):
        """Corroborate without 'as:' output is valid."""
        source = """
flow SimpleFlow() {
    step init {
        ask: "initialize"
    }
    corroborate nav_result
}
"""
        program = _parse(source)
        flow = program.declarations[0]
        corr = flow.body[1]
        assert isinstance(corr, CorroborateNode)
        assert corr.navigate_ref == "nav_result"
        assert corr.output_name == ""


# ═══════════════════════════════════════════════════════════════════
#  4. PARSER TESTS — Extended Navigate (MDN mode)
# ═══════════════════════════════════════════════════════════════════

class TestNavigateExtended:
    """Test extended navigate with MDN parameters."""

    def test_navigate_pix_mode_unchanged(self):
        """Original PIX-mode navigate still works."""
        source = """
flow SearchFlow() {
    navigate MyPix with query: "find contracts" trail: enabled as: results
}
"""
        program = _parse(source)
        flow = program.declarations[0]
        nav = flow.body[0]
        assert isinstance(nav, NavigateNode)
        assert nav.pix_name == "MyPix"
        assert nav.corpus_name == ""
        assert nav.query_expr == "find contracts"
        assert nav.trail_enabled is True
        assert nav.output_name == "results"

    def test_navigate_with_budget_params(self):
        """Navigate with budget_depth and budget_nodes."""
        source = """
flow CorpusSearch() {
    navigate LegalCorpus with query: "liability clause" budget_depth: 5 budget_nodes: 20
}
"""
        program = _parse(source)
        flow = program.declarations[0]
        nav = flow.body[0]
        assert isinstance(nav, NavigateNode)
        assert nav.budget_depth == 5
        assert nav.budget_nodes == 20

    def test_navigate_with_edge_filter(self):
        """Navigate with edge_filter list."""
        source = """
flow FilteredSearch() {
    navigate LegalCorpus with query: "precedent" edge_filter: [cite, implement]
}
"""
        program = _parse(source)
        flow = program.declarations[0]
        nav = flow.body[0]
        assert isinstance(nav, NavigateNode)
        assert nav.edge_filter == ["cite", "implement"]


# ═══════════════════════════════════════════════════════════════════
#  5. TYPE CHECKER TESTS — Corpus Validation
# ═══════════════════════════════════════════════════════════════════

class TestCorpusTypeChecker:
    """Test type checker validation for corpus definitions."""

    def test_valid_corpus_no_errors(self):
        """Valid corpus definition should produce no errors."""
        source = """
corpus TestCorpus {
    documents: [doc_a, doc_b]
    relationships: [
        (doc_a, doc_b, cite)
    ]
    weights: {
        (doc_a, doc_b, cite): 0.8
    }
}
"""
        errors = _typecheck(source)
        assert len(errors) == 0

    def test_empty_corpus_fails_g1(self):
        """Corpus without documents violates G1: D ≠ ∅."""
        source = """
corpus EmptyCorpus {
    documents: []
}
"""
        errors = _typecheck(source)
        assert any("at least one document" in e.message for e in errors)

    def test_invalid_edge_reference(self):
        """Edge referencing undeclared document triggers error."""
        source = """
corpus BadEdgeCorpus {
    documents: [doc_a]
    relationships: [
        (doc_a, doc_b, cite)
    ]
}
"""
        errors = _typecheck(source)
        assert any("doc_b" in e.message for e in errors)

    def test_invalid_weight_range(self):
        """Weight outside (0, 1] violates G3: ω positivity."""
        source = """
corpus BadWeightCorpus {
    documents: [doc_a, doc_b]
    relationships: [
        (doc_a, doc_b, cite)
    ]
    weights: {
        (doc_a, doc_b, cite): 1.5
    }
}
"""
        errors = _typecheck(source)
        assert any("(0, 1]" in e.message for e in errors)

    def test_zero_weight_fails(self):
        """Weight = 0 violates G3: ω positivity (strictly positive)."""
        source = """
corpus ZeroWeightCorpus {
    documents: [doc_a, doc_b]
    relationships: [
        (doc_a, doc_b, cite)
    ]
    weights: {
        (doc_a, doc_b, cite): 0.0
    }
}
"""
        errors = _typecheck(source)
        assert any("(0, 1]" in e.message for e in errors)


# ═══════════════════════════════════════════════════════════════════
#  6. TYPE CHECKER TESTS — Corroborate Validation
# ═══════════════════════════════════════════════════════════════════

class TestCorroborateTypeChecker:
    """Test type checker validation for corroborate statements."""

    def test_corroborate_valid(self):
        """Valid corroborate in flow body produces no errors."""
        source = """
flow VerifyFlow() {
    step gather {
        ask: "gather"
    }
    corroborate nav_result as: verified
}
"""
        errors = _typecheck(source)
        assert len(errors) == 0

    def test_corroborate_missing_ref(self):
        """Corroborate without navigate_ref triggers error."""
        # Test the type checker directly with a synthetic AST.
        corr = CorroborateNode(navigate_ref="", line=1, column=1)
        program = ProgramNode(line=1, column=1)
        flow = FlowDefinition(name="TestFlow", line=1, column=1)
        flow.body.append(corr)
        program.declarations.append(flow)

        checker = TypeChecker(program)
        errors = checker.check()
        assert any("corroborate requires a reference" in e.message for e in errors)


# ═══════════════════════════════════════════════════════════════════
#  7. IR GENERATOR TESTS — Corpus Compilation
# ═══════════════════════════════════════════════════════════════════

class TestCorpusIRGenerator:
    """Test IR generation for corpus definitions."""

    def test_corpus_compiles_to_ir_corpus_spec(self):
        """Corpus definition produces IRCorpusSpec."""
        source = """
corpus MedicalCorpus {
    documents: [study_a, trial_b]
    relationships: [
        (trial_b, study_a, cite)
    ]
    weights: {
        (trial_b, study_a, cite): 0.85
    }
}
"""
        ir = _compile(source)
        assert len(ir.corpus_specs) == 1
        spec = ir.corpus_specs[0]
        assert spec.name == "MedicalCorpus"
        assert len(spec.documents) == 2
        assert len(spec.edges) == 1
        assert spec.edges[0].source_ref == "trial_b"
        assert spec.edges[0].target_ref == "study_a"
        assert spec.edges[0].relation_type == "cite"
        assert len(spec.weights) == 1
        assert spec.weights[0] == ("trial_b,study_a,cite", 0.85)

    def test_corpus_docs_are_ir_corpus_doc_specs(self):
        """Each document in corpus compiles to IRCorpusDocSpec."""
        source = """
corpus SmallCorpus {
    documents: [doc_x]
}
"""
        ir = _compile(source)
        assert len(ir.corpus_specs) == 1
        spec = ir.corpus_specs[0]
        assert len(spec.documents) == 1
        doc = spec.documents[0]
        assert isinstance(doc, IRCorpusDocSpec)
        assert doc.pix_ref == "doc_x"


# ═══════════════════════════════════════════════════════════════════
#  8. IR GENERATOR TESTS — Extended Navigate Compilation
# ═══════════════════════════════════════════════════════════════════

class TestNavigateIRGenerator:
    """Test IR generation for extended navigate with MDN fields."""

    def test_navigate_pix_mode_compiles(self):
        """PIX-mode navigate compiles with empty MDN fields."""
        source = """
flow SearchFlow() {
    navigate MyPix with query: "find items" trail: enabled
}
"""
        ir = _compile(source)
        flow_ir = ir.flows[0]
        nav = flow_ir.steps[0]
        assert isinstance(nav, IRNavigate)
        assert nav.pix_ref == "MyPix"
        assert nav.corpus_ref == ""
        assert nav.query == "find items"
        assert nav.trail_enabled is True
        assert nav.budget_depth is None
        assert nav.budget_nodes is None
        assert nav.edge_filter == ()

    def test_navigate_with_budget_compiles(self):
        """Navigate with budget parameters compiles to IR."""
        source = """
flow BudgetSearch() {
    navigate CorpusRef with query: "search" budget_depth: 3 budget_nodes: 15
}
"""
        ir = _compile(source)
        flow_ir = ir.flows[0]
        nav = flow_ir.steps[0]
        assert isinstance(nav, IRNavigate)
        assert nav.budget_depth == 3
        assert nav.budget_nodes == 15

    def test_navigate_with_edge_filter_compiles(self):
        """Navigate with edge_filter compiles to tuple in IR."""
        source = """
flow FilterSearch() {
    navigate CorpusRef with query: "precedent" edge_filter: [cite, support]
}
"""
        ir = _compile(source)
        flow_ir = ir.flows[0]
        nav = flow_ir.steps[0]
        assert isinstance(nav, IRNavigate)
        assert nav.edge_filter == ("cite", "support")


# ═══════════════════════════════════════════════════════════════════
#  9. IR GENERATOR TESTS — Corroborate Compilation
# ═══════════════════════════════════════════════════════════════════

class TestCorroborateIRGenerator:
    """Test IR generation for corroborate statements."""

    def test_corroborate_compiles(self):
        """Corroborate statement compiles to IRCorroborate."""
        source = """
flow VerifyFlow() {
    step init {
        ask: "initialize"
    }
    corroborate nav_result as: verified
}
"""
        ir = _compile(source)
        flow_ir = ir.flows[0]
        corr = flow_ir.steps[1]
        assert isinstance(corr, IRCorroborate)
        assert corr.navigate_ref == "nav_result"
        assert corr.output_name == "verified"


# ═══════════════════════════════════════════════════════════════════
#  10. FULL PIPELINE TESTS — End-to-End
# ═══════════════════════════════════════════════════════════════════

class TestMDNFullPipeline:
    """End-to-end tests: complete MDN programs through the full pipeline."""

    def test_full_mdn_program(self):
        """Complete MDN program with corpus, navigate, and corroborate."""
        source = """
corpus JudicialCorpus {
    documents: [constitution, civil_code, case_2024]
    relationships: [
        (case_2024, constitution, cite),
        (civil_code, constitution, implement)
    ]
    weights: {
        (case_2024, constitution, cite): 0.95,
        (civil_code, constitution, implement): 0.8
    }
}

flow LegalResearch() {
    navigate JudicialCorpus with query: "right to privacy" budget_depth: 4 budget_nodes: 30
    corroborate nav_result as: verified_claims
}
"""
        ir = _compile(source)

        # Verify corpus spec
        assert len(ir.corpus_specs) == 1
        assert ir.corpus_specs[0].name == "JudicialCorpus"
        assert len(ir.corpus_specs[0].documents) == 3
        assert len(ir.corpus_specs[0].edges) == 2

        # Verify flow with navigate + corroborate
        assert len(ir.flows) == 1
        flow = ir.flows[0]
        assert len(flow.steps) == 2
        nav = flow.steps[0]
        assert isinstance(nav, IRNavigate)
        assert nav.budget_depth == 4
        assert nav.budget_nodes == 30
        corr = flow.steps[1]
        assert isinstance(corr, IRCorroborate)
        assert corr.navigate_ref == "nav_result"

    def test_mdn_coexists_with_pix(self):
        """MDN corpus and PIX definitions coexist in the same program."""
        source = """
pix StatuteIndex {
    source: "constitution.pdf"
    depth: 4
    branching: 3
}

corpus LegalCorpus {
    documents: [StatuteIndex]
}

flow ResearchFlow() {
    navigate StatuteIndex with query: "article 1" trail: enabled
}
"""
        ir = _compile(source)
        assert len(ir.pix_specs) == 1
        assert len(ir.corpus_specs) == 1

    def test_existing_pix_navigate_unaffected(self):
        """Existing PIX navigate functionality is completely unaffected."""
        source = """
pix DocTree {
    source: "document.pdf"
    depth: 3
    branching: 2
}

flow ReadDoc() {
    navigate DocTree with query: "summary" trail: enabled as: summary
    drill DocTree into "chapter.1" with query: "details" as: detail
    trail summary
}
"""
        ir = _compile(source)
        flow = ir.flows[0]
        assert len(flow.steps) == 3
        nav = flow.steps[0]
        assert isinstance(nav, IRNavigate)
        assert nav.pix_ref == "DocTree"
        assert nav.corpus_ref == ""
        assert nav.query == "summary"
