"""
AXON Compiler — AST Node Definitions
======================================
The cognitive Abstract Syntax Tree of the AXON language.

KEY DESIGN PRINCIPLE:
  This AST has ZERO mechanical nodes (no ForLoop, no Variable, no AssignStmt).
  Every node represents a *cognitive* concept:
    - PersonaDefinition (not ClassDecl)
    - IntentNode        (not FunctionCall)
    - ReasonChain       (not ForLoop)
    - AnchorConstraint  (not AssertStatement)
    - ProbeDirective    (not SelectQuery)
    - WeaveNode         (not JoinExpression)

  The tree itself speaks the language of intelligence.
"""

from __future__ import annotations
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════════
#  BASE NODE
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ASTNode:
    """Base class for all AXON AST nodes."""
    line: int = 0
    column: int = 0


# ═══════════════════════════════════════════════════════════════════
#  TOP-LEVEL NODES
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ProgramNode(ASTNode):
    """Root of the AXON AST — a list of top-level declarations."""
    declarations: list[ASTNode] = field(default_factory=list)


@dataclass
class ImportNode(ASTNode):
    """
    import axon.anchors.{NoHallucination, NoBias}

    module_path: ["axon", "anchors"]
    names: ["NoHallucination", "NoBias"]  (empty = import all)
    """
    module_path: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
#  DECLARATION NODES — the "who" and "what"
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PersonaDefinition(ASTNode):
    """
    persona LegalExpert {
      domain: ["contract law", "IP"]
      tone: precise
      confidence_threshold: 0.85
      ...
    }

    The cognitive identity executing the flow.
    """
    name: str = ""
    domain: list[str] = field(default_factory=list)
    tone: str = ""
    confidence_threshold: float | None = None
    cite_sources: bool | None = None
    refuse_if: list[str] = field(default_factory=list)
    language: str = ""
    description: str = ""


@dataclass
class ContextDefinition(ASTNode):
    """
    context LegalReview {
      memory: session
      language: "es"
      depth: exhaustive
      max_tokens: 4096
      temperature: 0.3
    }

    The working memory and session configuration.
    """
    name: str = ""
    memory_scope: str = ""  # session | persistent | none
    language: str = ""
    depth: str = ""  # shallow | standard | deep | exhaustive
    max_tokens: int | None = None
    temperature: float | None = None
    cite_sources: bool | None = None


@dataclass
class AnchorConstraint(ASTNode):
    """
    anchor NoHallucination {
      require: source_citation
      confidence_floor: 0.75
      unknown_response: "I don't have sufficient information..."
      on_violation: raise AnchorBreachError
    }

    A hard constraint that can NEVER be violated.
    """
    name: str = ""
    require: str = ""
    reject: list[str] = field(default_factory=list)
    enforce: str = ""
    confidence_floor: float | None = None
    unknown_response: str = ""
    on_violation: str = ""
    on_violation_target: str = ""  # for "raise <ErrorName>" or "fallback(...)"


@dataclass
class MemoryDefinition(ASTNode):
    """
    memory LongTermKnowledge {
      store: persistent
      backend: vector_db
      retrieval: semantic
      decay: none
    }

    Persistent semantic storage.
    """
    name: str = ""
    store: str = ""  # session | persistent | ephemeral
    backend: str = ""  # vector_db | in_memory | redis | custom
    retrieval: str = ""  # semantic | exact | hybrid
    decay: str = ""  # none | daily | weekly | <duration>


@dataclass
class ToolDefinition(ASTNode):
    """
    tool WebSearch {
      provider: brave
      max_results: 5
      filter: recent(days: 30)
      timeout: 10s
    }

    An external capability the model can invoke.
    """
    name: str = ""
    provider: str = ""
    max_results: int | None = None
    filter_expr: str = ""
    timeout: str = ""  # duration string
    runtime: str = ""
    sandbox: bool | None = None


# ═══════════════════════════════════════════════════════════════════
#  TYPE SYSTEM NODES
# ═══════════════════════════════════════════════════════════════════

@dataclass
class TypeExprNode(ASTNode):
    """
    A type reference: Document, List<Party>, FactualClaim?

    name: "Document" | "List" | "FactualClaim"
    generic_param: "Party" (for List<Party>)
    optional: True (for FactualClaim?)
    """
    name: str = ""
    generic_param: str = ""
    optional: bool = False


@dataclass
class RangeConstraint(ASTNode):
    """
    (0.0..1.0) — numeric range constraint on a type.
    """
    min_value: float = 0.0
    max_value: float = 0.0


@dataclass
class WhereClause(ASTNode):
    """
    where confidence >= 0.85
    where sources.length > 0

    A constraint expression on a type.
    """
    expression: str = ""  # raw condition string for now


@dataclass
class TypeFieldNode(ASTNode):
    """
    name: FactualClaim
    role: FactualClaim
    legal_standing: Opinion?

    A single field in a structured type definition.
    """
    name: str = ""
    type_expr: TypeExprNode | None = None


@dataclass
class TypeDefinition(ASTNode):
    """
    type RiskScore(0.0..1.0)
    type Party { name: FactualClaim, role: FactualClaim }
    type HighConfidenceClaim where confidence >= 0.85

    A semantic type declaration with optional fields, range, or where clause.
    """
    name: str = ""
    fields: list[TypeFieldNode] = field(default_factory=list)
    range_constraint: RangeConstraint | None = None
    where_clause: WhereClause | None = None


# ═══════════════════════════════════════════════════════════════════
#  FLOW & STEP NODES — the "how"
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ParameterNode(ASTNode):
    """
    doc: Document
    depth: Integer

    A typed parameter for a flow.
    """
    name: str = ""
    type_expr: TypeExprNode | None = None


@dataclass
class FlowDefinition(ASTNode):
    """
    flow AnalyzeContract(doc: Document) -> ContractAnalysis {
      step Extract { ... }
      probe doc for [parties]
      reason about Risks { ... }
    }

    The "function" of AXON — a composable cognitive pipeline.
    """
    name: str = ""
    parameters: list[ParameterNode] = field(default_factory=list)
    return_type: TypeExprNode | None = None
    body: list[ASTNode] = field(default_factory=list)  # list of flow steps


@dataclass
class StepNode(ASTNode):
    """
    step Extract {
      given: doc
      probe doc for [parties, dates]
      output: EntityMap
    }

    A named cognitive step inside a flow.
    """
    name: str = ""
    given: str = ""  # input expression
    ask: str = ""  # instruction string
    use_tool: UseToolNode | None = None
    probe: ProbeDirective | None = None
    reason: ReasonChain | None = None
    weave: WeaveNode | None = None
    output_type: str = ""
    confidence_floor: float | None = None
    body: list[ASTNode] = field(default_factory=list)  # sub-steps


# ═══════════════════════════════════════════════════════════════════
#  COGNITIVE STEP NODES — the intelligence
# ═══════════════════════════════════════════════════════════════════

@dataclass
class IntentNode(ASTNode):
    """
    intent ExtractParties {
      given: Document
      ask: "Identify all parties..."
      output: List<Party>
      confidence_floor: 0.9
    }

    An atomic semantic instruction with typed I/O.
    """
    name: str = ""
    given: str = ""
    ask: str = ""
    output_type: TypeExprNode | None = None
    confidence_floor: float | None = None


@dataclass
class ProbeDirective(ASTNode):
    """
    probe document for [parties, dates, obligations, penalties]

    Targeted structured extraction — declarative "look for this".
    """
    target: str = ""  # what to probe (expression / identifier)
    fields: list[str] = field(default_factory=list)  # what to extract


@dataclass
class ReasonChain(ASTNode):
    """
    reason about Risks {
      given: EntityMap
      depth: 3
      show_work: true
      ask: "What clauses present risk?"
      output: RiskAnalysis
    }

    Explicit chain-of-thought directive with configurable depth.
    """
    name: str = ""
    about: str = ""  # topic identifier
    given: str | list[str] = ""
    depth: int = 1
    show_work: bool = False
    chain_of_thought: bool = False
    ask: str = ""
    output_type: str = ""


@dataclass
class ValidateRule(ASTNode):
    """
    if confidence < 0.80 -> refine(max_attempts: 2)
    if structural_mismatch -> raise ValidationError

    A single validation rule inside a validate block.
    """
    condition: str = ""
    comparison_op: str = ""
    comparison_value: str = ""
    action: str = ""  # "refine" | "raise" | "warn" | "pass"
    action_target: str = ""  # error class or string for warn
    action_params: dict[str, str] = field(default_factory=dict)


@dataclass
class ValidateGate(ASTNode):
    """
    validate Assess.output against RiskSchema {
      if confidence < 0.80 -> refine(max_attempts: 2)
      if structural_mismatch -> raise ValidationError
    }

    A semantic validation checkpoint.
    """
    target: str = ""  # expression to validate
    schema: str = ""  # type/schema to validate against
    rules: list[ValidateRule] = field(default_factory=list)


@dataclass
class RefineBlock(ASTNode):
    """
    refine {
      max_attempts: 3
      pass_failure_context: true
      backoff: exponential
      on_exhaustion: escalate
    }

    Adaptive retry with failure context injection.
    """
    max_attempts: int = 3
    pass_failure_context: bool = True
    backoff: str = "none"  # none | linear | exponential
    on_exhaustion: str = ""  # raise <X> | escalate | fallback(...)
    on_exhaustion_target: str = ""


@dataclass
class WeaveNode(ASTNode):
    """
    weave [EntityMap, RiskAnalysis, LegalPrecedents] into FinalReport {
      format: StructuredReport
      priority: [risks, recommendations, summary]
    }

    Semantic synthesis — combines multiple outputs into a coherent result.
    """
    sources: list[str] = field(default_factory=list)
    target: str = ""  # output identifier
    format_type: str = ""
    priority: list[str] = field(default_factory=list)
    style: str = ""


@dataclass
class UseToolNode(ASTNode):
    """
    use WebSearch("quantum computing 2025")

    Invoke an external tool capability.
    """
    tool_name: str = ""
    argument: str = ""


@dataclass
class RememberNode(ASTNode):
    """
    remember(ResearchSummary) -> ResearchKnowledge

    Store a value into semantic memory.
    """
    expression: str = ""
    memory_target: str = ""


@dataclass
class RecallNode(ASTNode):
    """
    recall("quantum computing") from ResearchKnowledge

    Retrieve from semantic memory.
    """
    query: str = ""
    memory_source: str = ""


@dataclass
class ConditionalNode(ASTNode):
    """
    if confidence < 0.5 -> step Retry { ... }
    else -> step Skip { ... }

    A cognitive conditional branching.
    """
    condition: str = ""
    comparison_op: str = ""
    comparison_value: str = ""
    then_step: ASTNode | None = None
    else_step: ASTNode | None = None


# ═══════════════════════════════════════════════════════════════════
#  PARADIGM SHIFT NODES — epistemic scoping, parallelism, yielding
# ═══════════════════════════════════════════════════════════════════

@dataclass
class EpistemicBlock(ASTNode):
    """
    know { flow SummarizeEvidence(...) -> HighConfidenceFact }
    speculate { flow Brainstorm(...) -> Opinion }

    A cognitive scope modifier that injects epistemic constraints and
    tunes LLM parameters based on the confidence state.

    Modes:
      know      — strict: low temperature, citation required
      believe   — moderate: medium temperature, no hallucination
      speculate — creative: high temperature, relaxed constraints
      doubt     — analytical: low temperature, syllogistic checks
    """
    mode: str = ""           # "know" | "believe" | "speculate" | "doubt"
    body: list[ASTNode] = field(default_factory=list)


@dataclass
class ParallelBlock(ASTNode):
    """
    par {
        step Financial { ... }
        step Legal { ... }
    }

    Concurrent cognitive dispatch — branches run in parallel via
    asyncio.gather and their results are collected into context.
    """
    branches: list[ASTNode] = field(default_factory=list)


@dataclass
class HibernateNode(ASTNode):
    """
    hibernate until "amendment_received"

    Suspends execution, serializes the cognitive state (call stack,
    local variables, IR pointer), and waits for an external event
    to resume. Creates an immortal agent checkpoint.
    """
    event_name: str = ""     # the event to wait for
    timeout: str = ""        # optional duration before auto-resume


@dataclass
class DeliberateBlock(ASTNode):
    """
    deliberate {
        budget: 8000
        depth: 3
        strategy: thorough
        step DeepAnalysis { ... }
    }

    Declares a computational budget for wrapped steps. Controls how
    much inference compute the model should allocate (System 2 depth).

    Fields:
        budget:   maximum tokens for reasoning (0 = no limit)
        depth:    maximum reasoning iterations
        strategy: "quick" | "balanced" | "thorough" | "exhaustive"
    """
    budget: int = 0
    depth: int = 1
    strategy: str = "balanced"
    body: list[ASTNode] = field(default_factory=list)


@dataclass
class ConsensusBlock(ASTNode):
    """
    consensus {
        branches: 5
        reward: AccuracyAnchor
        selection: best
        step Classify { ... }
    }

    Runs the same task N times under speculative mode and selects
    the best result via a reward anchor. Implements Best-of-N
    selection with deterministic validation.

    Fields:
        branches:       number of parallel runs (>= 2)
        reward_anchor:  anchor name used as the reward function
        selection:      "best" | "majority"
    """
    branches: int = 3
    reward_anchor: str = ""
    selection: str = "best"
    body: list[ASTNode] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
#  DATA SCIENCE NODES — the associative engine
# ═══════════════════════════════════════════════════════════════════

@dataclass
class DataSpaceDefinition(ASTNode):
    """
    dataspace SalesAnalysis { ... }

    Defines an in-memory associative data container.
    """
    name: str = ""
    body: list[ASTNode] = field(default_factory=list)


@dataclass
class IngestNode(ASTNode):
    """
    ingest "sales.csv" into SalesData
    ingest SalesAPI into SalesData

    Loads external data into a DataSpace.
    Source can be a string literal (file path) or an identifier (variable/API).
    """
    source: str = ""       # file path string or identifier
    target: str = ""       # DataSpace identifier (after "into")


@dataclass
class FocusNode(ASTNode):
    """
    focus on Sales.Region == "LATAM"
    focus on Revenue > 1000

    Sets the selection context — filters the associative engine.
    """
    expression: str = ""   # the filtering expression


@dataclass
class AssociateNode(ASTNode):
    """
    associate Sales with Products
    associate Sales with Products using ProductID

    Explicitly links two tables/dataspaces.
    """
    left: str = ""         # first table/space identifier
    right: str = ""        # second table/space identifier (after "with")
    using_field: str = ""  # optional linking field (after "using")


@dataclass
class AggregateNode(ASTNode):
    """
    aggregate Revenue by Region
    aggregate Revenue by Region, Year as AnnualReport

    Performs summary reduction on data.
    """
    target: str = ""                            # column to aggregate
    group_by: list[str] = field(default_factory=list)  # grouping columns
    alias: str = ""                             # optional result name (after "as")


@dataclass
class ExploreNode(ASTNode):
    """
    explore SalesData
    explore SalesData limit 100

    Interactive data exploration/display.
    """
    target: str = ""       # DataSpace or table to explore
    limit: int | None = None  # optional row limit


# ═══════════════════════════════════════════════════════════════════
#  EXECUTION NODE
# ═══════════════════════════════════════════════════════════════════

@dataclass
class RunStatement(ASTNode):
    """
    run AnalyzeContract(myContract.pdf)
      as ContractLawyer
      within LegalReview
      constrained_by [NoHallucination, StrictFactual, NoBias]
      on_failure: retry(backoff: exponential)
      output_to: "contract_report.json"
      effort: high

    The entry point — wires flow + persona + context + anchors.
    """
    flow_name: str = ""
    arguments: list[str] = field(default_factory=list)
    persona: str = ""  # as <Persona>
    context: str = ""  # within <Context>
    anchors: list[str] = field(default_factory=list)  # constrained_by [...]
    on_failure: str = ""  # log | retry(...) | escalate | raise <X>
    on_failure_params: dict[str, str] = field(default_factory=dict)
    output_to: str = ""  # output destination
    effort: str = ""  # low | medium | high | max
