"""
AXON Parser — Unit Tests
==========================
Verifies parsing of all AXON language constructs into cognitive AST nodes.
"""

import pytest

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.ast_nodes import (
    AxonEndpointDefinition,
    AnchorConstraint,
    ChannelDefinition,
    ConditionalNode,
    ContextDefinition,
    DaemonDefinition,
    DiscoverStatement,
    EmitStatement,
    EnsembleDefinition,
    FabricDefinition,
    FlowDefinition,
    ForInStatement,
    HealDefinition,
    ImmuneDefinition,
    ImportNode,
    LeaseDefinition,
    LetStatement,
    IntentNode,
    ManifestDefinition,
    MemoryDefinition,
    ObserveDefinition,
    PersonaDefinition,
    ProbeDirective,
    ProgramNode,
    PublishStatement,
    ReasonChain,
    RecallNode,
    ReconcileDefinition,
    ReflexDefinition,
    RememberNode,
    ResourceDefinition,
    RunStatement,
    SessionDefinition,
    StepNode,
    ToolDefinition,
    TopologyDefinition,
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


class TestAxonEndpoint:
    """Parser handles axonendpoint declarations and alias syntax."""

    def test_axonendpoint_full(self):
        source = '''axonendpoint ContractsAPI {
  method: post
  path: "/api/contracts/analyze"
  body: ContractInput
  execute: AnalyzeContract
  output: ContractReport
  shield: EdgeShield
  retries: 2
  timeout: 10s
}'''
        tree = _parse(source)
        endpoint = tree.declarations[0]
        assert isinstance(endpoint, AxonEndpointDefinition)
        assert endpoint.name == "ContractsAPI"
        assert endpoint.method == "POST"
        assert endpoint.path == "/api/contracts/analyze"
        assert endpoint.body_type == "ContractInput"
        assert endpoint.execute_flow == "AnalyzeContract"
        assert endpoint.output_type == "ContractReport"
        assert endpoint.shield_ref == "EdgeShield"
        assert endpoint.retries == 2
        assert endpoint.timeout == "10s"

    def test_axpoint_alias(self):
        tree = _parse('''axpoint QuickAPI {
  method: get
  path: "/api/ping"
  execute: PingFlow
}''')
        endpoint = tree.declarations[0]
        assert isinstance(endpoint, AxonEndpointDefinition)
        assert endpoint.name == "QuickAPI"
        assert endpoint.method == "GET"


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


# ═══════════════════════════════════════════════════════════════
#  v0.25.4 — COGNITIVE FLOW EXTENSIONS
# ═══════════════════════════════════════════════════════════════

class TestStepPersonaBinding:
    """Gap 1: step X use Persona { } — epistemic persona binding."""

    def test_step_use_persona(self):
        source = '''
persona Analyst {
    role: "Data analyst"
}
flow AnalyzeData() {
    step Gather use Analyst {
        ask: "Collect the data"
    }
}
'''
        tree = _parse(source)
        flow = tree.declarations[1]
        step = flow.body[0]
        assert isinstance(step, StepNode)
        assert step.name == "Gather"
        assert step.persona_ref == "Analyst"
        assert step.ask == "Collect the data"

    def test_step_without_persona(self):
        source = '''
flow SimpleFlow() {
    step DoWork {
        ask: "Do the work"
    }
}
'''
        tree = _parse(source)
        step = tree.declarations[0].body[0]
        assert step.persona_ref == ""


class TestStepFieldExtensions:
    """Gap 2: navigate: / apply: in step bodies."""

    def test_step_navigate_field(self):
        source = '''
flow ResearchFlow() {
    step Browse {
        navigate: pix.document_tree
        ask: "Browse the tree"
    }
}
'''
        tree = _parse(source)
        step = tree.declarations[0].body[0]
        assert step.navigate_ref == "pix.document_tree"

    def test_step_apply_field(self):
        source = '''
anchor SafetyCheck {
    constraint: "Be safe"
}
flow GuardedFlow() {
    step Validate {
        apply: SafetyCheck
        ask: "Check safety"
    }
}
'''
        tree = _parse(source)
        step = tree.declarations[1].body[0]
        assert step.apply_ref == "SafetyCheck"


class TestReturnStatement:
    """Gap 3: return expression — Early Exit Sink."""

    def test_return_string(self):
        from axon.compiler.ast_nodes import ReturnStatement as RS
        source = '''
flow BuildReport() {
    step Write {
        ask: "Write it"
    }
    return "workspace/report.md"
}
'''
        tree = _parse(source)
        ret = tree.declarations[0].body[1]
        assert isinstance(ret, RS)
        assert ret.value_expr is not None

    def test_return_dotted_path(self):
        from axon.compiler.ast_nodes import ReturnStatement as RS
        source = '''
flow GetData() {
    step Fetch {
        ask: "Fetch data"
    }
    return results.final_output
}
'''
        tree = _parse(source)
        ret = tree.declarations[0].body[1]
        assert isinstance(ret, RS)

    def test_return_outside_flow_raises_type_error(self):
        """Semantic cortafuegos: return in top-level is invalid."""
        from axon.compiler.type_checker import TypeChecker
        source = '''
flow TestFlow() {
    step A {
        ask: "test"
    }
}
'''
        # return at top level would be a parse error, tested via type checker
        # when placed inside flow it should be valid (no error)
        tree = _parse(source)
        errors = TypeChecker(tree).check()
        return_errors = [e for e in errors if "return" in str(e).lower()]
        assert len(return_errors) == 0


class TestBlockStyleConditionals:
    """Gap 4: if cond { body } with compound or conditions."""

    def test_if_block_body(self):
        source = '''
flow DecisionFlow() {
    if status == "ready" {
        step Execute {
            ask: "Execute now"
        }
    }
}
'''
        tree = _parse(source)
        cond = tree.declarations[0].body[0]
        assert isinstance(cond, ConditionalNode)
        assert cond.condition == "status"
        assert cond.comparison_op == "=="
        assert cond.comparison_value == "ready"
        assert len(cond.then_body) == 1
        assert isinstance(cond.then_body[0], StepNode)

    def test_if_else_block(self):
        source = '''
flow BranchFlow() {
    if confidence >= 0.9 {
        step Accept {
            ask: "Accept result"
        }
    } else {
        step Retry {
            ask: "Retry analysis"
        }
    }
}
'''
        tree = _parse(source)
        cond = tree.declarations[0].body[0]
        assert len(cond.then_body) == 1
        assert len(cond.else_body) == 1

    def test_compound_or_condition(self):
        source = '''
flow MultiCheck() {
    if status == "complete" or quality == "high" -> step Done {
        ask: "Finalize"
    }
}
'''
        tree = _parse(source)
        cond = tree.declarations[0].body[0]
        assert cond.condition == "status"
        assert cond.conjunctor == "or"
        assert len(cond.conditions) == 1
        assert cond.conditions[0][0] == "quality"

    def test_string_comparison_value(self):
        source = '''
flow StringCompare() {
    if mode == "research" -> step Research {
        ask: "Do research"
    }
}
'''
        tree = _parse(source)
        cond = tree.declarations[0].body[0]
        assert cond.comparison_value == "research"

    def test_legacy_arrow_still_works(self):
        """Backward compatibility: if cond -> step still parses."""
        source = '''
flow LegacyFlow() {
    if ready -> step Go {
        ask: "Go ahead"
    }
}
'''
        tree = _parse(source)
        cond = tree.declarations[0].body[0]
        assert cond.then_step is not None


# ═══════════════════════════════════════════════════════════════
#  v0.25.5 — STATIC TOOL BINDING
# ═══════════════════════════════════════════════════════════════

class TestStaticToolBinding:
    """Parser handles use tool(key=value, ...) static binding (v0.25.5)."""

    def test_use_tool_static_args(self):
        """use with named key=value string parameters."""
        source = '''flow F() -> R {
  step S {
    use create_markdown(path="./out.md", mode="append")
    ask: "Save the chapter"
    output: string
  }
}'''
        tree = _parse(source)
        step = tree.declarations[0].body[0]
        assert isinstance(step, StepNode)
        assert step.use_tool is not None
        assert step.use_tool.static_args == {"path": "./out.md", "mode": "append"}
        assert step.use_tool.argument == ""

    def test_use_tool_mixed_types(self):
        """use with integer, float, and boolean parameters."""
        source = '''flow F() -> R {
  step S {
    use resize_image(width=800, quality=0.95, optimize=true)
    ask: "Resize the image"
    output: string
  }
}'''
        tree = _parse(source)
        step = tree.declarations[0].body[0]
        args = step.use_tool.static_args
        assert args["width"] == 800
        assert args["quality"] == 0.95
        assert args["optimize"] is True

    def test_use_tool_positional_still_works(self):
        """Legacy use with positional string argument still works."""
        source = '''flow F() -> R {
  step S {
    use WebSearch("quantum computing")
    ask: "Search for the topic"
    output: string
  }
}'''
        tree = _parse(source)
        step = tree.declarations[0].body[0]
        assert step.use_tool.argument == "quantum computing"
        assert step.use_tool.static_args == {}

    def test_use_tool_empty_parens_still_works(self):
        """use with empty parens (no args) still works."""
        source = '''flow F() -> R {
  step S {
    use create_markdown()
    ask: "Create file"
    output: string
  }
}'''
        tree = _parse(source)
        step = tree.declarations[0].body[0]
        assert step.use_tool.argument == ""
        assert step.use_tool.static_args == {}

    def test_use_tool_dotted_value(self):
        """use with dotted identifier path value."""
        source = '''flow F() -> R {
  step S {
    use pix_navigator(strategy=pix.document_tree)
    ask: "Navigate"
    output: string
  }
}'''
        tree = _parse(source)
        step = tree.declarations[0].body[0]
        assert step.use_tool.static_args == {"strategy": "pix.document_tree"}


# ═══════════════════════════════════════════════════════════════════
#  I/O COGNITIVO — λ-L-E Fase 1 (resource, fabric, manifest, observe)
# ═══════════════════════════════════════════════════════════════════


class TestResource:
    """Parser handles resource declarations (Linear/Affine infrastructure tokens)."""

    def test_resource_full(self):
        source = '''resource DatabasePool {
  kind: postgres
  endpoint: "db.internal:5432"
  capacity: 100
  lifetime: linear
  certainty_floor: 0.85
  shield: DBShield
}'''
        tree = _parse(source)
        node = tree.declarations[0]
        assert isinstance(node, ResourceDefinition)
        assert node.name == "DatabasePool"
        assert node.kind == "postgres"
        assert node.endpoint == "db.internal:5432"
        assert node.capacity == 100
        assert node.lifetime == "linear"
        assert node.certainty_floor == 0.85
        assert node.shield_ref == "DBShield"

    def test_resource_defaults_to_affine(self):
        tree = _parse('resource Cache { kind: redis }')
        node = tree.declarations[0]
        assert isinstance(node, ResourceDefinition)
        assert node.lifetime == "affine"
        assert node.certainty_floor is None

    def test_resource_invalid_lifetime_rejected(self):
        source = '''resource Bad {
  kind: redis
  lifetime: eternal
}'''
        with pytest.raises(AxonParseError, match="Invalid lifetime"):
            _parse(source)


class TestFabric:
    """Parser handles fabric declarations (topological substrate)."""

    def test_fabric_full(self):
        source = '''fabric AWS_VPC {
  provider: aws
  region: "us-east-1"
  zones: 3
  ephemeral: true
  shield: NetworkShield
}'''
        tree = _parse(source)
        node = tree.declarations[0]
        assert isinstance(node, FabricDefinition)
        assert node.name == "AWS_VPC"
        assert node.provider == "aws"
        assert node.region == "us-east-1"
        assert node.zones == 3
        assert node.ephemeral is True
        assert node.shield_ref == "NetworkShield"


class TestManifest:
    """Parser handles manifest declarations (declarative shape beliefs)."""

    def test_manifest_full(self):
        source = '''manifest ProductionCluster {
  resources: [DatabasePool, RedisCache]
  fabric: AWS_VPC
  region: "us-east-1"
  zones: 3
  compliance: [HIPAA, PCI_DSS]
}'''
        tree = _parse(source)
        node = tree.declarations[0]
        assert isinstance(node, ManifestDefinition)
        assert node.name == "ProductionCluster"
        assert node.resources == ["DatabasePool", "RedisCache"]
        assert node.fabric_ref == "AWS_VPC"
        assert node.region == "us-east-1"
        assert node.zones == 3
        assert node.compliance == ["HIPAA", "PCI_DSS"]

    def test_manifest_single_resource(self):
        tree = _parse('manifest Single { resources: [Db] }')
        node = tree.declarations[0]
        assert node.resources == ["Db"]


class TestObserve:
    """Parser handles observe declarations (quorum-gated observation)."""

    def test_observe_full(self):
        source = '''observe ClusterState from ProductionCluster {
  sources: [prometheus, cloudwatch, healthcheck]
  quorum: 2
  timeout: 5s
  on_partition: fail
  certainty_floor: 0.90
}'''
        tree = _parse(source)
        node = tree.declarations[0]
        assert isinstance(node, ObserveDefinition)
        assert node.name == "ClusterState"
        assert node.target == "ProductionCluster"
        assert node.sources == ["prometheus", "cloudwatch", "healthcheck"]
        assert node.quorum == 2
        assert node.timeout == "5s"
        assert node.on_partition == "fail"
        assert node.certainty_floor == 0.90

    def test_observe_default_on_partition_is_fail(self):
        source = '''observe S from M {
  sources: [prometheus]
  timeout: 3s
}'''
        tree = _parse(source)
        node = tree.declarations[0]
        # D4 (plan_io_cognitivo.md): default partition policy is CT-3 failure
        assert node.on_partition == "fail"

    def test_observe_invalid_on_partition_rejected(self):
        source = '''observe S from M {
  sources: [prometheus]
  on_partition: ignore
}'''
        with pytest.raises(AxonParseError, match="Invalid on_partition"):
            _parse(source)


# ═══════════════════════════════════════════════════════════════════
#  CONTROL COGNITIVO — λ-L-E Fase 3 (reconcile, lease, ensemble)
# ═══════════════════════════════════════════════════════════════════


class TestReconcile:
    """Parser handles reconcile declarations."""

    def test_reconcile_full(self):
        source = '''reconcile ProdReconciler {
  observe: ClusterHealth
  threshold: 0.85
  tolerance: 0.10
  on_drift: provision
  shield: ReconcileShield
  mandate: ClusterPid
  max_retries: 5
}'''
        tree = _parse(source)
        node = tree.declarations[0]
        assert isinstance(node, ReconcileDefinition)
        assert node.name == "ProdReconciler"
        assert node.observe_ref == "ClusterHealth"
        assert node.threshold == 0.85
        assert node.tolerance == 0.10
        assert node.on_drift == "provision"
        assert node.shield_ref == "ReconcileShield"
        assert node.mandate_ref == "ClusterPid"
        assert node.max_retries == 5

    def test_reconcile_defaults(self):
        tree = _parse('reconcile R { observe: O }')
        node = tree.declarations[0]
        assert isinstance(node, ReconcileDefinition)
        assert node.on_drift == "provision"
        assert node.max_retries == 3
        assert node.threshold is None

    def test_reconcile_invalid_on_drift_rejected(self):
        with pytest.raises(AxonParseError, match="Invalid on_drift"):
            _parse('reconcile R { observe: O on_drift: erase }')


class TestLease:
    """Parser handles lease declarations."""

    def test_lease_full(self):
        source = '''lease DbWriteLease {
  resource: PrimaryDb
  duration: 30s
  acquire: on_start
  on_expire: anchor_breach
}'''
        tree = _parse(source)
        node = tree.declarations[0]
        assert isinstance(node, LeaseDefinition)
        assert node.name == "DbWriteLease"
        assert node.resource_ref == "PrimaryDb"
        assert node.duration == "30s"
        assert node.acquire == "on_start"
        assert node.on_expire == "anchor_breach"

    def test_lease_defaults(self):
        tree = _parse('lease L { resource: R duration: 5m }')
        node = tree.declarations[0]
        assert node.acquire == "on_start"
        assert node.on_expire == "anchor_breach"

    def test_lease_invalid_acquire_rejected(self):
        with pytest.raises(AxonParseError, match="Invalid acquire"):
            _parse('lease L { resource: R duration: 1s acquire: forever }')

    def test_lease_invalid_on_expire_rejected(self):
        with pytest.raises(AxonParseError, match="Invalid on_expire"):
            _parse('lease L { resource: R duration: 1s on_expire: explode }')


class TestEnsemble:
    """Parser handles ensemble declarations."""

    def test_ensemble_full(self):
        source = '''ensemble ClusterTruth {
  observations: [ObsA, ObsB, ObsC]
  quorum: 2
  aggregation: byzantine
  certainty_mode: harmonic
}'''
        tree = _parse(source)
        node = tree.declarations[0]
        assert isinstance(node, EnsembleDefinition)
        assert node.name == "ClusterTruth"
        assert node.observations == ["ObsA", "ObsB", "ObsC"]
        assert node.quorum == 2
        assert node.aggregation == "byzantine"
        assert node.certainty_mode == "harmonic"

    def test_ensemble_defaults(self):
        tree = _parse('ensemble E { observations: [A, B] }')
        node = tree.declarations[0]
        assert node.aggregation == "majority"
        assert node.certainty_mode == "min"

    def test_ensemble_invalid_aggregation_rejected(self):
        with pytest.raises(AxonParseError, match="Invalid aggregation"):
            _parse('ensemble E { observations: [A, B] aggregation: vote }')

    def test_ensemble_invalid_certainty_mode_rejected(self):
        with pytest.raises(AxonParseError, match="Invalid certainty_mode"):
            _parse('ensemble E { observations: [A, B] certainty_mode: mean }')


# ═══════════════════════════════════════════════════════════════════
#  TOPOLOGY & SESSION TYPES — λ-L-E Fase 4 (π-calculus)
# ═══════════════════════════════════════════════════════════════════


class TestSession:
    """Parser handles binary session declarations."""

    def test_session_full(self):
        source = '''session DbSession {
  client: [send Query, receive Result, end]
  server: [receive Query, send Result, end]
}'''
        tree = _parse(source)
        node = tree.declarations[0]
        assert isinstance(node, SessionDefinition)
        assert node.name == "DbSession"
        assert len(node.roles) == 2
        client, server = node.roles
        assert client.name == "client"
        assert [(s.op, s.message_type) for s in client.steps] == [
            ("send", "Query"), ("receive", "Result"), ("end", ""),
        ]
        assert server.name == "server"
        assert [(s.op, s.message_type) for s in server.steps] == [
            ("receive", "Query"), ("send", "Result"), ("end", ""),
        ]

    def test_session_with_loop(self):
        source = '''session EventStream {
  producer: [send Event, loop]
  consumer: [receive Event, loop]
}'''
        tree = _parse(source)
        node = tree.declarations[0]
        assert node.roles[0].steps[1].op == "loop"
        assert node.roles[1].steps[1].op == "loop"

    def test_session_invalid_step_rejected(self):
        with pytest.raises(AxonParseError, match="Invalid session step"):
            _parse('session S { client: [transmit Q] server: [end] }')


class TestTopology:
    """Parser handles topology declarations."""

    def test_topology_full(self):
        source = '''topology Prod {
  nodes: [A, B, C]
  edges: [
    A -> B : SessAB,
    B -> C : SessBC
  ]
}'''
        tree = _parse(source)
        node = tree.declarations[0]
        assert isinstance(node, TopologyDefinition)
        assert node.name == "Prod"
        assert node.nodes == ["A", "B", "C"]
        assert len(node.edges) == 2
        e1, e2 = node.edges
        assert (e1.source, e1.target, e1.session_ref) == ("A", "B", "SessAB")
        assert (e2.source, e2.target, e2.session_ref) == ("B", "C", "SessBC")

    def test_topology_single_edge(self):
        source = '''topology T {
  nodes: [X, Y]
  edges: [X -> Y : S]
}'''
        tree = _parse(source)
        node = tree.declarations[0]
        assert len(node.edges) == 1


# ═══════════════════════════════════════════════════════════════════
#  COGNITIVE IMMUNE SYSTEM — λ-L-E Fase 5 (paper_inmune.md)
# ═══════════════════════════════════════════════════════════════════


class TestImmune:
    """Parser handles immune declarations."""

    def test_immune_full(self):
        source = '''immune Vigil {
  watch: [Traffic, Queries, Auth]
  sensitivity: 0.9
  baseline: learned
  window: 200
  scope: tenant
  tau: 300s
  decay: exponential
}'''
        tree = _parse(source)
        node = tree.declarations[0]
        assert isinstance(node, ImmuneDefinition)
        assert node.name == "Vigil"
        assert node.watch == ["Traffic", "Queries", "Auth"]
        assert node.sensitivity == 0.9
        assert node.window == 200
        assert node.scope == "tenant"
        assert node.tau == "300s"
        assert node.decay == "exponential"

    def test_immune_invalid_scope_rejected(self):
        with pytest.raises(AxonParseError, match="Invalid scope"):
            _parse('immune V { watch: [A] scope: everywhere }')

    def test_immune_invalid_decay_rejected(self):
        with pytest.raises(AxonParseError, match="Invalid decay"):
            _parse('immune V { watch: [A] scope: tenant decay: quadratic }')


class TestReflex:
    """Parser handles reflex declarations."""

    def test_reflex_full(self):
        source = '''reflex Drop {
  trigger: Vigil
  on_level: doubt
  action: drop
  scope: tenant
  sla: 1ms
}'''
        tree = _parse(source)
        node = tree.declarations[0]
        assert isinstance(node, ReflexDefinition)
        assert node.name == "Drop"
        assert node.trigger == "Vigil"
        assert node.on_level == "doubt"
        assert node.action == "drop"
        assert node.scope == "tenant"
        assert node.sla == "1ms"

    def test_reflex_invalid_on_level_rejected(self):
        with pytest.raises(AxonParseError, match="Invalid on_level"):
            _parse('reflex R { trigger: V on_level: certain action: drop scope: tenant }')

    def test_reflex_invalid_action_rejected(self):
        with pytest.raises(AxonParseError, match="Invalid action"):
            _parse('reflex R { trigger: V on_level: doubt action: explode scope: tenant }')


class TestHeal:
    """Parser handles heal declarations."""

    def test_heal_full(self):
        source = '''heal Patch {
  source: Vigil
  on_level: doubt
  mode: human_in_loop
  scope: tenant
  review_sla: 24h
  shield: S
  max_patches: 3
}'''
        tree = _parse(source)
        node = tree.declarations[0]
        assert isinstance(node, HealDefinition)
        assert node.name == "Patch"
        assert node.source == "Vigil"
        assert node.mode == "human_in_loop"
        assert node.scope == "tenant"
        assert node.review_sla == "24h"
        assert node.shield_ref == "S"
        assert node.max_patches == 3

    def test_heal_invalid_mode_rejected(self):
        with pytest.raises(AxonParseError, match="Invalid mode"):
            _parse('heal H { source: V mode: reckless scope: tenant }')


# ────────────────────────────────────────────────────────────────────
# Mobile Typed Channels — Fase 13.a
# (paper_mobile_channels.md §3, plan_io_cognitivo.md / fase_13)
# ────────────────────────────────────────────────────────────────────


class TestChannelDefinition:
    """Parser handles channel declarations as affine first-class resources."""

    def test_channel_full(self):
        source = '''channel OrdersCreated {
  message: Order
  qos: at_least_once
  lifetime: affine
  persistence: ephemeral
  shield: PublicBroker
}'''
        tree = _parse(source)
        node = tree.declarations[0]
        assert isinstance(node, ChannelDefinition)
        assert node.name == "OrdersCreated"
        assert node.message == "Order"
        assert node.qos == "at_least_once"
        assert node.lifetime == "affine"
        assert node.persistence == "ephemeral"
        assert node.shield_ref == "PublicBroker"

    def test_channel_defaults_per_paper(self):
        tree = _parse('channel C { message: Order }')
        node = tree.declarations[0]
        assert isinstance(node, ChannelDefinition)
        assert node.qos == "at_least_once"          # paper §3, D1 default
        assert node.lifetime == "affine"            # D1 — affine handles
        assert node.persistence == "ephemeral"      # D3 default

    def test_channel_second_order_message_type(self):
        """A channel can carry another channel handle (paper §3.3 mobility)."""
        source = '''channel BrokerHandoff {
  message: Channel<Order>
  qos: exactly_once
}'''
        tree = _parse(source)
        node = tree.declarations[0]
        assert isinstance(node, ChannelDefinition)
        assert node.message == "Channel<Order>"
        assert node.qos == "exactly_once"

    def test_channel_nested_channel_message_type(self):
        """Mobility composes — Channel<Channel<T>> must parse."""
        tree = _parse('channel Meta { message: Channel<Channel<Order>> }')
        node = tree.declarations[0]
        assert node.message == "Channel<Channel<Order>>"

    def test_channel_invalid_qos_rejected(self):
        source = '''channel C {
  message: Order
  qos: bestEffort
}'''
        with pytest.raises(AxonParseError, match="Invalid qos"):
            _parse(source)

    def test_channel_invalid_lifetime_rejected(self):
        source = '''channel C {
  message: Order
  lifetime: eternal
}'''
        with pytest.raises(AxonParseError, match="Invalid lifetime"):
            _parse(source)

    def test_channel_invalid_persistence_rejected(self):
        source = '''channel C {
  message: Order
  persistence: forever
}'''
        with pytest.raises(AxonParseError, match="Invalid persistence"):
            _parse(source)

    def test_channel_all_qos_values_accepted(self):
        for qos in ("at_most_once", "at_least_once", "exactly_once",
                    "broadcast", "queue"):
            tree = _parse(f'channel C {{ message: T qos: {qos} }}')
            assert tree.declarations[0].qos == qos

    def test_channel_persistence_persistent_axonstore(self):
        tree = _parse(
            'channel C { message: Order persistence: persistent_axonstore }'
        )
        assert tree.declarations[0].persistence == "persistent_axonstore"

    def test_channel_explicit_linear_lifetime(self):
        """Affine is default but linear must be selectable for one-shot channels."""
        tree = _parse('channel C { message: T lifetime: linear }')
        assert tree.declarations[0].lifetime == "linear"

    def test_channel_explicit_persistent_lifetime(self):
        """Persistent (`!Channel<T>` in §2 — the bang exponential)."""
        tree = _parse('channel C { message: T lifetime: persistent }')
        assert tree.declarations[0].lifetime == "persistent"


class TestEmitStatement:
    """Output prefix `c⟨v⟩.P` (Chan-Output) and mobility (Chan-Mobility)."""

    def test_emit_value(self):
        source = '''flow f() -> Out {
  emit OrdersCreated(payload)
}'''
        tree = _parse(source)
        flow = tree.declarations[0]
        assert isinstance(flow, FlowDefinition)
        emit = flow.body[0]
        assert isinstance(emit, EmitStatement)
        assert emit.channel_ref == "OrdersCreated"
        assert emit.value_ref == "payload"

    def test_emit_channel_handle_for_mobility(self):
        """Sending a channel handle as the value — second-order mobility."""
        source = '''flow f() -> Out {
  emit BrokerHandoff(OrdersCreated)
}'''
        tree = _parse(source)
        emit = tree.declarations[0].body[0]
        assert isinstance(emit, EmitStatement)
        assert emit.channel_ref == "BrokerHandoff"
        assert emit.value_ref == "OrdersCreated"


class TestPublishStatement:
    """Capability extrusion (Publish-Ext) — D8 mandates `within <Shield>`."""

    def test_publish_within_shield(self):
        source = '''flow f() -> Cap {
  publish OrdersCreated within PublicBroker
}'''
        tree = _parse(source)
        pub = tree.declarations[0].body[0]
        assert isinstance(pub, PublishStatement)
        assert pub.channel_ref == "OrdersCreated"
        assert pub.shield_ref == "PublicBroker"

    def test_publish_without_within_rejected(self):
        """Bare `publish C` is a compile error — D8 requires shield gate."""
        source = '''flow f() -> Cap {
  publish OrdersCreated
}'''
        with pytest.raises(AxonParseError):
            _parse(source)


class TestDiscoverStatement:
    """Discover (dual of publish) — `as <alias>` is mandatory for affinity."""

    def test_discover_binds_alias(self):
        source = '''flow f() -> Out {
  discover OrdersCreated as orders_ch
}'''
        tree = _parse(source)
        disc = tree.declarations[0].body[0]
        assert isinstance(disc, DiscoverStatement)
        assert disc.capability_ref == "OrdersCreated"
        assert disc.alias == "orders_ch"

    def test_discover_without_alias_rejected(self):
        source = '''flow f() -> Out {
  discover OrdersCreated
}'''
        with pytest.raises(AxonParseError):
            _parse(source)


class TestListenDualMode:
    """D4 — dual-mode listen: typed channel ref OR legacy string topic."""

    def test_listen_typed_channel_ref(self):
        """Canonical Fase 13 form: `listen ChannelName as alias`."""
        source = '''daemon D() {
  listen OrdersCreated as ev {
    step S { ask: "process" }
  }
}'''
        tree = _parse(source)
        daemon = tree.declarations[0]
        assert isinstance(daemon, DaemonDefinition)
        listener = daemon.listeners[0]
        assert listener.channel_expr == "OrdersCreated"
        assert listener.channel_is_ref is True       # typed ref, not string
        assert listener.event_alias == "ev"

    def test_listen_string_topic_legacy(self):
        """Legacy form: `listen "topic"` — preserved (deprecated, removed in v2.0)."""
        source = '''daemon D() {
  listen "orders.created" as ev {
    step S { ask: "process" }
  }
}'''
        tree = _parse(source)
        listener = tree.declarations[0].listeners[0]
        assert listener.channel_expr == "orders.created"
        assert listener.channel_is_ref is False      # string topic
        assert listener.event_alias == "ev"

    def test_listen_dual_mode_in_same_daemon(self):
        """Both forms can coexist during the v1.4.x → v2.0 migration."""
        source = '''daemon Mixed() {
  listen OrdersCreated as canonical_ev {
    step S { ask: "process" }
  }
  listen "legacy.topic" as legacy_ev {
    step S { ask: "handle" }
  }
}'''
        tree = _parse(source)
        listeners = tree.declarations[0].listeners
        assert len(listeners) == 2
        assert listeners[0].channel_is_ref is True
        assert listeners[0].channel_expr == "OrdersCreated"
        assert listeners[1].channel_is_ref is False
        assert listeners[1].channel_expr == "legacy.topic"


class TestChannelIntegration:
    """End-to-end Fase 13.a parse criterion — paper §9 worked example."""

    def test_paper_example_parses(self):
        """The paper §9 example `hand_off` flow + OrderConsumer daemon must parse."""
        source = '''
channel OrdersCreated {
  message: Order
  qos: at_least_once
  lifetime: affine
  persistence: ephemeral
  shield: PublicBroker
}

channel BrokerHandoff {
  message: Channel<Order>
  qos: exactly_once
  lifetime: affine
  persistence: persistent_axonstore
}

daemon OrderConsumer() {
  goal: "consume orders"
  listen BrokerHandoff as ch {
    step S { ask: "delegate" }
  }
}

flow hand_off() -> Cap {
  emit BrokerHandoff(OrdersCreated)
  publish OrdersCreated within PublicBroker
}
'''
        tree = _parse(source)
        kinds = [type(d).__name__ for d in tree.declarations]
        assert kinds == [
            "ChannelDefinition", "ChannelDefinition",
            "DaemonDefinition", "FlowDefinition",
        ]
        flow = tree.declarations[3]
        body_kinds = [type(s).__name__ for s in flow.body]
        assert body_kinds == ["EmitStatement", "PublishStatement"]
