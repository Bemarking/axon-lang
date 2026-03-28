"""
AXON Parser — Unit Tests
==========================
Verifies parsing of all AXON language constructs into cognitive AST nodes.
"""

import pytest

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.ast_nodes import (
    AnchorConstraint,
    ContextDefinition,
    FlowDefinition,
    ForInStatement,
    ImportNode,
    LetStatement,
    IntentNode,
    MemoryDefinition,
    PersonaDefinition,
    ProbeDirective,
    ProgramNode,
    ReasonChain,
    RecallNode,
    RememberNode,
    RunStatement,
    StepNode,
    ToolDefinition,
    TypeDefinition,
    ValidateGate,
    WeaveNode,
)
from axon.compiler.errors import AxonParseError


def _parse(source: str) -> ProgramNode:
    """Helper: tokenize + parse in one step."""
    tokens = Lexer(source).tokenize()
    return Parser(tokens).parse()


class TestImport:
    """Parser handles import declarations."""

    def test_simple_import(self):
        tree = _parse("import axon.anchors.{NoHallucination, NoBias}")
        assert len(tree.declarations) == 1
        node = tree.declarations[0]
        assert isinstance(node, ImportNode)
        assert node.module_path == ["axon", "anchors"]
        assert node.names == ["NoHallucination", "NoBias"]

    def test_import_without_names(self):
        tree = _parse("import axon.stdlib")
        node = tree.declarations[0]
        assert isinstance(node, ImportNode)
        assert node.module_path == ["axon", "stdlib"]
        assert node.names == []


class TestPersona:
    """Parser handles persona declarations."""

    def test_persona_full(self):
        source = '''persona LegalExpert {
  domain: ["contract law", "IP"]
  tone: precise
  confidence_threshold: 0.85
  cite_sources: true
}'''
        tree = _parse(source)
        p = tree.declarations[0]
        assert isinstance(p, PersonaDefinition)
        assert p.name == "LegalExpert"
        assert p.domain == ["contract law", "IP"]
        assert p.tone == "precise"
        assert p.confidence_threshold == 0.85
        assert p.cite_sources is True

    def test_persona_minimal(self):
        tree = _parse("persona Basic { }")
        p = tree.declarations[0]
        assert isinstance(p, PersonaDefinition)
        assert p.name == "Basic"


class TestContext:
    """Parser handles context declarations."""

    def test_context_full(self):
        source = '''context LegalReview {
  memory: session
  language: "es"
  depth: exhaustive
  max_tokens: 4096
  temperature: 0.3
}'''
        tree = _parse(source)
        c = tree.declarations[0]
        assert isinstance(c, ContextDefinition)
        assert c.name == "LegalReview"
        assert c.memory_scope == "session"
        assert c.language == "es"
        assert c.depth == "exhaustive"
        assert c.max_tokens == 4096
        assert c.temperature == 0.3


class TestAnchor:
    """Parser handles anchor declarations."""

    def test_anchor_with_violation(self):
        source = '''anchor NoHallucination {
  require: source_citation
  confidence_floor: 0.75
  unknown_response: "I don't have sufficient information."
  on_violation: raise AnchorBreachError
}'''
        tree = _parse(source)
        a = tree.declarations[0]
        assert isinstance(a, AnchorConstraint)
        assert a.name == "NoHallucination"
        assert a.require == "source_citation"
        assert a.confidence_floor == 0.75
        assert a.on_violation == "raise"
        assert a.on_violation_target == "AnchorBreachError"


class TestMemory:
    """Parser handles memory declarations."""

    def test_memory_full(self):
        source = '''memory LongTermKnowledge {
  store: persistent
  backend: vector_db
  retrieval: semantic
  decay: none
}'''
        tree = _parse(source)
        m = tree.declarations[0]
        assert isinstance(m, MemoryDefinition)
        assert m.name == "LongTermKnowledge"
        assert m.store == "persistent"
        assert m.backend == "vector_db"
        assert m.retrieval == "semantic"
        assert m.decay == "none"


class TestTool:
    """Parser handles tool declarations."""

    def test_tool_full(self):
        source = '''tool WebSearch {
  provider: brave
  max_results: 5
  timeout: 10s
}'''
        tree = _parse(source)
        t = tree.declarations[0]
        assert isinstance(t, ToolDefinition)
        assert t.name == "WebSearch"
        assert t.provider == "brave"
        assert t.max_results == 5
        assert t.timeout == "10s"


class TestType:
    """Parser handles type declarations."""

    def test_type_with_range(self):
        tree = _parse("type RiskScore(0.0..1.0)")
        td = tree.declarations[0]
        assert isinstance(td, TypeDefinition)
        assert td.name == "RiskScore"
        assert td.range_constraint is not None
        assert td.range_constraint.min_value == 0.0
        assert td.range_constraint.max_value == 1.0

    def test_type_with_fields(self):
        source = '''type Party {
  name: FactualClaim,
  role: FactualClaim
}'''
        tree = _parse(source)
        td = tree.declarations[0]
        assert isinstance(td, TypeDefinition)
        assert td.name == "Party"
        assert len(td.fields) == 2
        assert td.fields[0].name == "name"
        assert td.fields[0].type_expr.name == "FactualClaim"

    def test_type_optional_field(self):
        source = '''type Risk {
  score: RiskScore,
  mitigation: Opinion?
}'''
        tree = _parse(source)
        td = tree.declarations[0]
        assert td.fields[1].type_expr.optional is True


class TestIntent:
    """Parser handles intent declarations."""

    def test_intent_full(self):
        source = '''intent ExtractParties {
  given: Document
  ask: "Identify all parties in the contract"
  output: List<Party>
  confidence_floor: 0.9
}'''
        tree = _parse(source)
        i = tree.declarations[0]
        assert isinstance(i, IntentNode)
        assert i.name == "ExtractParties"
        assert i.ask == "Identify all parties in the contract"
        assert i.output_type.name == "List"
        assert i.output_type.generic_param == "Party"
        assert i.confidence_floor == 0.9


class TestFlow:
    """Parser handles flow declarations."""

    def test_flow_with_steps(self):
        source = '''flow AnalyzeContract(doc: Document) -> ContractAnalysis {
  step Extract {
    given: doc
    ask: "Extract key entities"
    output: EntityMap
  }
  step Assess {
    given: Extract.output
    ask: "Assess risks"
    output: RiskAnalysis
  }
}'''
        tree = _parse(source)
        f = tree.declarations[0]
        assert isinstance(f, FlowDefinition)
        assert f.name == "AnalyzeContract"
        assert len(f.parameters) == 1
        assert f.parameters[0].name == "doc"
        assert f.parameters[0].type_expr.name == "Document"
        assert f.return_type.name == "ContractAnalysis"
        assert len(f.body) == 2
        assert isinstance(f.body[0], StepNode)
        assert f.body[0].name == "Extract"
        assert f.body[1].name == "Assess"

    def test_flow_with_probe(self):
        source = '''flow TestFlow(doc: Document) -> Result {
  probe doc for [parties, dates, obligations]
}'''
        tree = _parse(source)
        f = tree.declarations[0]
        assert len(f.body) == 1
        p = f.body[0]
        assert isinstance(p, ProbeDirective)
        assert p.target == "doc"
        assert p.fields == ["parties", "dates", "obligations"]

    def test_flow_with_reason(self):
        source = '''flow TestFlow(data: EntityMap) -> Analysis {
  reason about Risks {
    given: data
    depth: 3
    show_work: true
    ask: "What clauses present risk?"
    output: RiskAnalysis
  }
}'''
        tree = _parse(source)
        f = tree.declarations[0]
        r = f.body[0]
        assert isinstance(r, ReasonChain)
        assert r.about == "Risks"
        assert r.depth == 3
        assert r.show_work is True

    def test_flow_with_weave(self):
        source = '''flow TestFlow(a: EntityMap) -> Report {
  weave [Extract.output, Assess.output] into FinalReport {
    format: StructuredReport
    priority: [risks, recommendations]
  }
}'''
        tree = _parse(source)
        f = tree.declarations[0]
        w = f.body[0]
        assert isinstance(w, WeaveNode)
        assert w.sources == ["Extract.output", "Assess.output"]
        assert w.target == "FinalReport"
        assert w.format_type == "StructuredReport"

    def test_flow_with_validate(self):
        source = '''flow TestFlow(x: Data) -> Result {
  validate Assess.output against RiskSchema {
    if confidence < 0.80 -> refine(max_attempts: 2)
    if structural_mismatch -> raise ValidationError
  }
}'''
        tree = _parse(source)
        f = tree.declarations[0]
        v = f.body[0]
        assert isinstance(v, ValidateGate)
        assert v.target == "Assess.output"
        assert v.schema == "RiskSchema"
        assert len(v.rules) == 2
        assert v.rules[0].action == "refine"
        assert v.rules[1].action == "raise"


class TestRun:
    """Parser handles run statements."""

    def test_run_full(self):
        source = '''run AnalyzeContract(myContract)
  as ContractLawyer
  within LegalReview
  constrained_by [NoHallucination, NoBias]
  on_failure: retry(backoff: exponential)
  output_to: "report.json"
  effort: high'''
        tree = _parse(source)
        r = tree.declarations[0]
        assert isinstance(r, RunStatement)
        assert r.flow_name == "AnalyzeContract"
        assert r.persona == "ContractLawyer"
        assert r.context == "LegalReview"
        assert r.anchors == ["NoHallucination", "NoBias"]
        assert r.on_failure == "retry"
        assert r.on_failure_params["backoff"] == "exponential"
        assert r.output_to == "report.json"
        assert r.effort == "high"

    def test_run_minimal(self):
        tree = _parse("run SimpleFlow()")
        r = tree.declarations[0]
        assert isinstance(r, RunStatement)
        assert r.flow_name == "SimpleFlow"
        assert r.persona == ""
        assert r.context == ""


class TestErrors:
    """Parser raises clear errors for invalid input."""

    def test_unexpected_top_level(self):
        with pytest.raises(AxonParseError, match="Unexpected token at top level"):
            _parse("42")

    def test_missing_brace(self):
        with pytest.raises(AxonParseError):
            _parse("persona Test {")


class TestMultipleDeclarations:
    """Parser handles complete programs with multiple declarations."""

    def test_full_program(self):
        source = '''persona Expert {
  tone: precise
}

context Review {
  memory: session
  depth: deep
}

anchor NoHallucination {
  require: source_citation
  confidence_floor: 0.75
  on_violation: raise AnchorBreachError
}

flow Analyze(doc: Document) -> Report {
  step Extract {
    given: doc
    ask: "Extract facts"
    output: EntityMap
  }
}

run Analyze(myDoc)
  as Expert
  within Review
  constrained_by [NoHallucination]'''
        tree = _parse(source)
        assert len(tree.declarations) == 5
        assert isinstance(tree.declarations[0], PersonaDefinition)
        assert isinstance(tree.declarations[1], ContextDefinition)
        assert isinstance(tree.declarations[2], AnchorConstraint)
        assert isinstance(tree.declarations[3], FlowDefinition)
        assert isinstance(tree.declarations[4], RunStatement)


class TestAtImport:
    """Parser handles @-prefixed scoped import paths (v0.24.2)."""

    def test_import_with_at_prefix(self):
        """import @axon.anchors.{NoHallucination} parses correctly."""
        tree = _parse("import @axon.anchors.{NoHallucination}")
        node = tree.declarations[0]
        assert isinstance(node, ImportNode)
        assert node.module_path == ["@axon", "anchors"]
        assert node.names == ["NoHallucination"]

    def test_import_at_without_names(self):
        """import @axon.stdlib parses correctly."""
        tree = _parse("import @axon.stdlib")
        node = tree.declarations[0]
        assert isinstance(node, ImportNode)
        assert node.module_path == ["@axon", "stdlib"]
        assert node.names == []

    def test_import_at_with_multiple_names(self):
        """import @axon.anchors.{A, B, C} parses all names."""
        tree = _parse("import @axon.anchors.{A, B, C}")
        node = tree.declarations[0]
        assert isinstance(node, ImportNode)
        assert node.module_path == ["@axon", "anchors"]
        assert node.names == ["A", "B", "C"]

    def test_regular_import_still_works(self):
        """Non-@ imports remain unchanged."""
        tree = _parse("import axon.anchors.{NoHallucination}")
        node = tree.declarations[0]
        assert node.module_path == ["axon", "anchors"]


class TestMultilineAsk:
    """Parser handles multiline strings in ask fields (v0.24.2)."""

    def test_intent_multiline_ask(self):
        """intent block accepts multiline ask string."""
        source = 'intent Extract {\n  given: Document\n  ask: "Identify all parties\nin the contract\nand their roles"\n  output: List<Party>\n}'
        tree = _parse(source)
        i = tree.declarations[0]
        assert isinstance(i, IntentNode)
        assert "parties\nin the contract\nand their roles" in i.ask

    def test_step_multiline_ask(self):
        """step block accepts multiline ask string."""
        source = 'flow Test(doc: Document) -> Result {\n  step Extract {\n    given: doc\n    ask: "Extract key entities\nfrom the document"\n    output: EntityMap\n  }\n}'
        tree = _parse(source)
        f = tree.declarations[0]
        assert isinstance(f, FlowDefinition)
        step = f.body[0]
        assert isinstance(step, StepNode)
        assert "\n" in step.ask


class TestForIn:
    """Parser handles for-in iteration loops (v0.25.2)."""

    def test_for_in_basic(self):
        """for X in Y.Z { steps } parses correctly."""
        source = '''flow ProcessThesis(thesis: Thesis) -> Report {
  for chapter in thesis.chapters {
    step Analyze {
      given: chapter
      ask: "Analyze this chapter"
      output: ChapterAnalysis
    }
  }
}'''
        tree = _parse(source)
        f = tree.declarations[0]
        assert isinstance(f, FlowDefinition)
        assert len(f.body) == 1

        for_in = f.body[0]
        assert isinstance(for_in, ForInStatement)
        assert for_in.variable == "chapter"
        assert for_in.iterable == "thesis.chapters"
        assert len(for_in.body) == 1
        assert isinstance(for_in.body[0], StepNode)
        assert for_in.body[0].name == "Analyze"

    def test_for_in_simple_iterable(self):
        """for X in Y { steps } — single identifier iterable."""
        source = '''flow Loop(items: List) -> Report {
  for item in items {
    step Process {
      given: item
      ask: "Process this item"
      output: Result
    }
  }
}'''
        tree = _parse(source)
        for_in = tree.declarations[0].body[0]
        assert isinstance(for_in, ForInStatement)
        assert for_in.variable == "item"
        assert for_in.iterable == "items"

    def test_for_in_deep_dotted_iterable(self):
        """for X in A.B.C { } — deeply nested iterable path."""
        source = '''flow DeepLoop(collection: Dataset) -> Report {
  for doc in collection.sections.documents {
    step Read {
      given: doc
      ask: "Read this document"
      output: Summary
    }
  }
}'''
        tree = _parse(source)
        for_in = tree.declarations[0].body[0]
        assert isinstance(for_in, ForInStatement)
        assert for_in.iterable == "collection.sections.documents"

    def test_for_in_with_probe_coexistence(self):
        """probe X for [...] still works when for-in is available."""
        source = '''flow TestFlow(doc: Document) -> Result {
  probe doc for [parties, dates]
  for item in doc.sections {
    step Process {
      given: item
      ask: "Process section"
      output: Result
    }
  }
}'''
        tree = _parse(source)
        f = tree.declarations[0]
        assert len(f.body) == 2
        assert isinstance(f.body[0], ProbeDirective)
        assert isinstance(f.body[1], ForInStatement)

    def test_for_in_multiple_steps(self):
        """for-in body can have multiple steps."""
        source = '''flow MultiStep(data: Data) -> Report {
  for entry in data.entries {
    step Read {
      given: entry
      ask: "Read entry"
      output: Summary
    }
    step Evaluate {
      given: Read.output
      ask: "Evaluate the reading"
      output: Evaluation
    }
  }
}'''
        tree = _parse(source)
        for_in = tree.declarations[0].body[0]
        assert isinstance(for_in, ForInStatement)
        assert len(for_in.body) == 2
        assert for_in.body[0].name == "Read"
        assert for_in.body[1].name == "Evaluate"


class TestDotNotationValues:
    """Parser handles dot-notation values in property fields (v0.25.2)."""

    def test_pix_with_dotted_value(self):
        """pix block with navigate_strategy: pix.document_tree is skipped cleanly."""
        source = '''pix ResearchCorpus {
  navigate_strategy: pix.document_tree
  max_depth: 5
}'''
        tree = _parse(source)
        from axon.compiler.ast_nodes import PixDefinition
        pix = tree.declarations[0]
        assert isinstance(pix, PixDefinition)
        assert pix.name == "ResearchCorpus"


class TestLetBindings:
    """Parser handles SSA immutable let bindings (v0.25.3)."""

    def test_let_string(self):
        """let with string literal value."""
        source = '''flow F() -> R {
  let draft_path = "workspace/drafts/tesis.md"
  step S { ask: "go" output: R }
}'''
        tree = _parse(source)
        let_node = tree.declarations[0].body[0]
        assert isinstance(let_node, LetStatement)
        assert let_node.identifier == "draft_path"
        assert let_node.value_expr == "workspace/drafts/tesis.md"

    def test_let_integer(self):
        """let with integer literal."""
        source = '''flow F() -> R {
  let max_retries = 5
  step S { ask: "go" output: R }
}'''
        tree = _parse(source)
        let_node = tree.declarations[0].body[0]
        assert isinstance(let_node, LetStatement)
        assert let_node.identifier == "max_retries"
        assert let_node.value_expr == 5

    def test_let_boolean(self):
        """let with boolean literal."""
        source = '''flow F() -> R {
  let debug = true
  step S { ask: "go" output: R }
}'''
        tree = _parse(source)
        let_node = tree.declarations[0].body[0]
        assert isinstance(let_node, LetStatement)
        assert let_node.identifier == "debug"
        assert let_node.value_expr is True

    def test_let_dotted_path(self):
        """let with dotted identifier value."""
        source = '''flow F() -> R {
  let strategy = pix.document_tree
  step S { ask: "go" output: R }
}'''
        tree = _parse(source)
        let_node = tree.declarations[0].body[0]
        assert isinstance(let_node, LetStatement)
        assert let_node.identifier == "strategy"
        assert let_node.value_expr == "pix.document_tree"

    def test_let_list_literal(self):
        """let with list literal value."""
        source = '''flow F() -> R {
  let tags = ["alpha", "beta", "gamma"]
  step S { ask: "go" output: R }
}'''
        tree = _parse(source)
        let_node = tree.declarations[0].body[0]
        assert isinstance(let_node, LetStatement)
        assert let_node.identifier == "tags"
        assert let_node.value_expr == ["alpha", "beta", "gamma"]

    def test_let_empty_list(self):
        """let with empty list literal."""
        source = '''flow F() -> R {
  let items = []
  step S { ask: "go" output: R }
}'''
        tree = _parse(source)
        let_node = tree.declarations[0].body[0]
        assert isinstance(let_node, LetStatement)
        assert let_node.identifier == "items"
        assert let_node.value_expr == []

    def test_let_top_level(self):
        """let at top-level scope works."""
        source = 'let base_path = "workspace/output"'
        tree = _parse(source)
        let_node = tree.declarations[0]
        assert isinstance(let_node, LetStatement)
        assert let_node.identifier == "base_path"
        assert let_node.value_expr == "workspace/output"

    def test_let_ssa_violation_detected_by_type_checker(self):
        """Duplicate let binding is caught by the type checker (SSA)."""
        from axon.compiler.type_checker import TypeChecker
        source = '''
let x = "first"
let x = "second"
'''
        tree = _parse(source)
        errors = TypeChecker(tree).check()
        ssa_errors = [e for e in errors if "ImmutableBindingError" in str(e)]
        assert len(ssa_errors) == 1
