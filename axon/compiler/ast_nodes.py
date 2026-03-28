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
    description: str = ""
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
      effects: <io, network, epistemic:speculate>
    }

    An external capability the model can invoke.

    Convergence Theorem 2 extension:
      The ``effects`` field declares the algebraic effect row for this tool.
      This enables the type checker to verify epistemic compatibility
      between tools and anchors (e.g., a ``require: source_citation``
      anchor rejects tools with ``epistemic:speculate`` without shield).
    """
    name: str = ""
    provider: str = ""
    max_results: int | None = None
    filter_expr: str = ""
    timeout: str = ""  # duration string
    runtime: str = ""
    sandbox: bool | None = None
    effects: EffectRowNode | None = None  # Convergence Theorem 2


# ═══════════════════════════════════════════════════════════════════
#  STREAMING & EFFECT NODES — Convergence Theorems 1 & 2
# ═══════════════════════════════════════════════════════════════════

@dataclass
class EffectRowNode(ASTNode):
    """
    effects: <io, network, epistemic:speculate>

    An algebraic effect row declaration for a tool or step.

    Theoretical basis — Convergence Theorem 2:
      Effects are first-class citizens with epistemic signatures.
      The effect row is a Koka-style row type that declares:
        - Side-effect categories: io, network, pure
        - Epistemic classification: know, believe, speculate, doubt

    The type checker uses effect rows to enforce:
      1. Anchors requiring citations reject speculate-level tools
      2. Taint propagation follows the Denning security lattice
      3. Pure tools (no I/O) are statically verified as deterministic
    """
    effects: list[str] = field(default_factory=list)  # ["io", "network"]
    epistemic_level: str = ""  # "know" | "believe" | "speculate" | "doubt"


@dataclass
class StreamHandlerNode(ASTNode):
    """
    on_chunk(chunk) { shield.scan_incremental(chunk) }
    on_complete(full_response) { promote(believe → know) }

    Handler for co-inductive stream evaluation.

    Theoretical basis — Convergence Theorem 1:
      Streams are coinductive structures (νX. StreamChunk × X).
      Handlers evaluate the stream co-inductively: the safety
      property holds for the head AND recursively for the tail.
    """
    handler_type: str = ""  # "on_chunk" | "on_complete"
    param_name: str = ""    # parameter name for the handler
    body: list[ASTNode] = field(default_factory=list)


@dataclass
class StreamDefinition(ASTNode):
    """
    stream<Diagnosis> {
      epistemic_gradient: doubt → speculate → believe → know

      on_chunk(chunk) {
        shield.scan_incremental(chunk)
      }

      on_complete(full_response) {
        if anchor.validate(full_response) and contracts.satisfied():
          promote(believe → know)
      }
    }

    A semantic streaming declaration with epistemic gradient.

    Theoretical basis — Convergence Theorem 1:
      Stream(τ) = νX. (StreamChunk × EpistemicState × X)
      where EpistemicState ∈ {⊥, doubt, speculate, believe, know}
      and the transition is monotonic on the epistemic lattice.

      The gradient defines the valid progression path for epistemic
      state during streaming. Backpressure is modeled as a linear
      type: Budget(n) ⊸ Stream(τ) → (Chunk × Budget(n-1)).
    """
    name: str = ""                                          # element type name
    element_type: TypeExprNode | None = None                # generic parameter
    epistemic_gradient: list[str] = field(default_factory=list)  # ["doubt", "speculate", ...]
    handlers: list[StreamHandlerNode] = field(default_factory=list)
    shield_ref: str = ""                                    # optional shield for co-inductive eval


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
    persona_ref: str = ""                          # step X use Persona { }
    given: str = ""  # input expression
    ask: str = ""  # instruction string
    use_tool: UseToolNode | None = None
    probe: ProbeDirective | None = None
    reason: ReasonChain | None = None
    weave: WeaveNode | None = None
    output_type: str = ""
    confidence_floor: float | None = None
    navigate_ref: str = ""                         # navigate: pix.document_tree
    apply_ref: str = ""                            # apply: AnchorName
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
    then_body: list[ASTNode] = field(default_factory=list)  # block { }
    else_body: list[ASTNode] = field(default_factory=list)
    conditions: list[tuple[str, str, str]] = field(default_factory=list)  # compound
    conjunctor: str = ""  # "or" | "and"



@dataclass
class ForInStatement(ASTNode):
    """
    for chapter in thesis.chapters {
        step AnalyzeChapter { ... }
    }

    Cognitive iteration — systematic traversal of a structured
    collection.  Each element is bound to `variable` and the
    body steps are executed per-element.

    The iterable is a dotted path expression resolved at runtime
    (e.g. ``thesis.chapters``, ``corpus.documents``).
    """
    variable: str = ""                              # loop binding name
    iterable: str = ""                              # dotted path expression
    body: list[ASTNode] = field(default_factory=list)


@dataclass
class LetStatement(ASTNode):
    """
    let draft_path = "workspace/drafts/tesis_completa.md"

    SSA immutable binding — a lexical axiom that cannot be rebound.
    Equivalent to λ-calculus ``let x = v in E``: a static,
    referentially transparent substitution.

    The value_expr is a compile-time constant: a string literal,
    numeric literal, boolean, dotted identifier path, or a list
    literal of such values.
    """
    identifier: str = ""                            # binding name
    value_expr: str | int | float | bool | list = field(default_factory=str)


@dataclass
class ReturnStatement(ASTNode):
    """return expr — Early Exit Sink in the cognitive DAG.

    The flow collapses when epistemic certainty is achieved.
    The value_expr is a sub-tree (ASTNode), not a primitive —
    parsed via the expression method for structural integrity.
    """
    value_expr: ASTNode | None = None


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
#  CREATIVE SYNTHESIS NODES — the forge engine
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ForgeBlock(ASTNode):
    """
    forge Painting(seed: "aurora boreal") -> Visual {
        mode: combinatory
        novelty: 0.8
        constraints: GoldenRatio
        depth: 3
        branches: 5
        step Compose { ... }
    }

    Directed creative synthesis — orchestrates the full Poincaré
    pipeline (Preparation → Incubation → Illumination → Verification)
    with mathematical control of the novelty-utility tradeoff (Boden).

    The forge primitive does NOT claim imagination. It formalizes
    the mathematical operation of directed movement through a
    conceptual space, maximizing compression and novelty — exactly
    what human creativity does (Friston, Schmidhuber, Bennett).

    Fields:
        name:         identifier for the forge block
        seed:         input seed concept (string expression)
        output_type:  declared output type name
        mode:         "combinatory" | "exploratory" | "transformational"
        novelty:      0.0..1.0 — creative freedom vs constraint adherence
        constraints:  anchor name for quality/beauty/coherence criteria
        depth:        incubation depth (Poincaré phase 2 iterations)
        branches:     Best-of-N branch count for illumination (phase 3)
    """
    name: str = ""
    seed: str = ""
    output_type: str = ""
    mode: str = "combinatory"
    novelty: float = 0.7
    constraints: str = ""
    depth: int = 3
    branches: int = 5
    body: list[ASTNode] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
#  ONTOLOGICAL TOOL SYNTHESIS (OTS) NODES
# ═══════════════════════════════════════════════════════════════════

@dataclass
class OtsDefinition(ASTNode):
    """
    ots DataExtractor<InputType, OutputType> {
        teleology: "Consume fragmented PDF invoice files to strictly emit normalized SQL inserts"
        homotopy_search: deep
        linear_constraints: {
            Consumption: strictly_once
        }
        loss_function: L_accuracy + 0.1 * L_complexity
    }

    The **ots** primitive — Ontological Tool Synthesis.
    Moves beyond static/dynamic tool binding to a continual capability space.
    """
    name: str = ""
    input_type: TypeExprNode | None = None
    output_type: TypeExprNode | None = None
    teleology: str = ""
    homotopy_search: str = "shallow"  # shallow | deep | speculative
    linear_constraints: dict[str, str] = field(default_factory=dict)
    loss_function: str = ""
    body: list[ASTNode] = field(default_factory=list)


@dataclass
class OtsApplyNode(ASTNode):
    """
    ots DataExtractor(invoice_data) -> SqlInserts

    Application of a synthesized tool with ephemeral execution.
    """
    ots_name: str = ""
    target: str = ""
    output_type: str = ""


# ═══════════════════════════════════════════════════════════════════
#  AGENT NODES — BDI autonomous agent primitive
# ═══════════════════════════════════════════════════════════════════

@dataclass
class AgentBudget(ASTNode):
    """
    budget: {
        max_iterations: 10
        max_tokens: 50000
        max_time: 120s
        max_cost: 0.50
    }

    Resource constraints for the agent's deliberation cycle.

    Theoretical grounding — **Linear Logic** (Girard, 1987):
      Each resource token is *consumed* by an action and cannot be
      duplicated or discarded. This prevents unbounded computation
      and guarantees termination (unlike LangChain's max_iterations
      which is a soft cap with no formal resource semantics).

    Formal invariant:
      ∀ iteration i: Σ(cost_i) ≤ max_cost ∧ Σ(tokens_i) ≤ max_tokens
    """
    max_iterations: int = 10
    max_tokens: int = 0          # 0 = unlimited
    max_time: str = ""           # duration string (e.g., "120s", "5m")
    max_cost: float = 0.0        # 0.0 = unlimited, in fractional currency


@dataclass
class AgentDefinition(ASTNode):
    """
    agent LeadQualifier(prospect: ProspectData) -> QualifiedLead {
        goal: "Qualify and score the prospect using all available data"
        tools: [WebSearch, CRMQuery, EmailVerifier]
        budget: { max_iterations: 10, max_tokens: 50000 }
        memory: ConversationMemory
        strategy: react
        on_stuck: forge
        step GatherInfo { ... }
        step ScoreLead { ... }
    }

    The **agent** primitive — a first-class BDI cognitive entity.

    ╔══════════════════════════════════════════════════════════════╗
    ║  THEORETICAL FOUNDATIONS                                     ║
    ╠══════════════════════════════════════════════════════════════╣
    ║                                                              ║
    ║  BDI Architecture (Bratman, 1987; Rao & Georgeff, 1995):     ║
    ║    Agent = ⟨B, D, I, Plan_Library, Deliberation_Cycle⟩      ║
    ║    • Beliefs  = working memory + tool results                ║
    ║    • Desires  = goal string (Davidson's pro-attitude)        ║
    ║    • Intentions = body steps (plan library)                  ║
    ║                                                              ║
    ║  Coalgebraic Semantics:                                      ║
    ║    Agent = (S, O, step: S × Action → S, obs: S → O)         ║
    ║    Bisimulation equivalence ensures compositionality.        ║
    ║                                                              ║
    ║  Convergence — Fixed-Point (Tarski/Knaster):                 ║
    ║    T(σ*) = σ* on the epistemic lattice:                      ║
    ║    doubt ⊏ speculate ⊏ believe ⊏ know                       ║
    ║                                                              ║
    ║  Concurrency — π-Calculus (Milner, 1999):                    ║
    ║    Agent ≡ goal.( ν ch )( tool₁⟨ch⟩ | tool₂⟨ch⟩ | … )     ║
    ║                                                              ║
    ║  Self-Regulation — Ashby's Law of Requisite Variety:         ║
    ║    V(regulator) ≥ V(disturbance)                             ║
    ║    6+ regulatory mechanisms: anchors, validation, budget,    ║
    ║    refine, forge, epistemic modes, on_stuck, deliberate.     ║
    ║                                                              ║
    ║  Recovery — STIT Logic (Belnap, Perloff, Xu, 2001):          ║
    ║    [agent stit: φ] — "agent sees to it that φ"               ║
    ║    When ¬◇φ (no available option achieves φ), invoke         ║
    ║    on_stuck to escalate, forge, or hibernate.                ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝

    Fields:
        name:        unique identifier for the agent definition
        parameters:  typed inputs (reuses FlowDefinition's ParameterNode)
        return_type: declared output type (optional)
        goal:        natural-language objective — Davidson's pro-attitude
        tools:       list of tool names available to the agent
        budget:      resource constraints (AgentBudget)
        memory_ref:  reference to a declared memory {} block
        strategy:    deliberation strategy:
                       "react"             — ReAct loop (Yao et al., 2023)
                       "reflexion"         — Reflexion with self-critique
                       "plan_and_execute"  — plan first, then execute
                       "custom"            — user-defined via body steps
        on_stuck:    recovery when no progress is detected:
                       "forge"     — creative synthesis to find new angles
                       "hibernate" — suspend and wait for external input
                       "escalate"  — raise to human operator
                       "retry"     — retry with modified parameters
        body:        list of flow steps (the agent's plan library)
    """
    name: str = ""
    parameters: list[ParameterNode] = field(default_factory=list)
    return_type: TypeExprNode | None = None
    goal: str = ""
    tools: list[str] = field(default_factory=list)
    budget: AgentBudget | None = None
    memory_ref: str = ""                   # reference to a memory {} block
    strategy: str = "react"                # react | reflexion | plan_and_execute | custom
    on_stuck: str = "escalate"             # forge | hibernate | escalate | retry
    shield_ref: str = ""                   # reference to a declared shield
    body: list[ASTNode] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
#  SHIELD NODES — compiler-level LLM security
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ShieldDefinition(ASTNode):
    """
    shield InputGuard {
        scan:     [prompt_injection, jailbreak, data_exfil, pii_leak]
        strategy: dual_llm
        quarantine: untrusted_input
        on_breach: halt
        severity: critical
    }

    shield ToolPolicy {
        allow: [WebSearch, Calculator]
        deny:  [CodeExecutor, FileWriter]
        sandbox: true
    }

    A **compiled security boundary** that the AXON compiler verifies
    and the runtime enforces.

    ╔══════════════════════════════════════════════════════════════╗
    ║  THEORETICAL FOUNDATIONS                                     ║
    ╠══════════════════════════════════════════════════════════════╣
    ║                                                              ║
    ║  Information Flow Control (Denning, 1976):                   ║
    ║    Trust Lattice (SC, →, ⊕):                                ║
    ║    Untrusted → Quarantined → Sanitized → Validated → Trusted ║
    ║    Legal flow: data may only flow UP the lattice.            ║
    ║                                                              ║
    ║  Noninterference (Goguen & Meseguer, 1982):                  ║
    ║    Untrusted variations cannot change Trusted execution.     ║
    ║    ∀ u,u' ∈ Untrusted : P(s|u) = P(s|u')                   ║
    ║                                                              ║
    ║  Taint Analysis:                                             ║
    ║    Source → Propagation → Sink                               ║
    ║    Vulnerability ≡ ∃ path from Source to Sink with no shield ║
    ║    Shield = type transformer: Untrusted → Sanitized          ║
    ║                                                              ║
    ║  Capability-Based Security (WASI/OCM):                       ║
    ║    Principle of Least Privilege — agents only access          ║
    ║    tools explicitly granted by their shield's allow list.    ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝

    Shield operates at three levels:
      1. Input shields  — sanitize data before LLM context
      2. Output shields — validate LLM responses before consumption
      3. Capability shields — restrict tool access to declared permissions

    Strategies:
      pattern     — regex/heuristic scan (fast, low cost)
      classifier  — fine-tuned classifier model (Llama Guard style)
      dual_llm    — privileged/quarantined model architecture
      canary      — inject traceable tokens, detect if leaked
      perplexity  — statistical anomaly detection
      ensemble    — multiple strategies with majority voting

    Fields:
        name:                 shield identifier
        scan:                 list of threat categories to scan for
        strategy:             detection mechanism
        on_breach:            action on threat detection
        severity:             severity level for logging/alerting
        quarantine:           label for quarantined data
        max_retries:          retry count for sanitize_and_retry
        confidence_threshold: minimum confidence for pass decision
        allow_tools:          permitted tools (capability shield)
        deny_tools:           forbidden tools (capability shield)
        sandbox:              whether to sandbox tool execution
        redact:               PII fields to auto-redact before LLM
        log:                  logging directive
        deflect_message:      canned response for deflect on_breach
        budget:               optional resource constraints
    """
    name: str = ""
    scan: list[str] = field(default_factory=list)
    strategy: str = "pattern"          # pattern|classifier|dual_llm|canary|perplexity|ensemble
    on_breach: str = "halt"            # halt|sanitize_and_retry|escalate|quarantine|deflect
    severity: str = "critical"         # low|medium|high|critical
    quarantine: str = ""               # quarantine label
    max_retries: int = 0               # for sanitize_and_retry
    confidence_threshold: float | None = None
    allow_tools: list[str] = field(default_factory=list)
    deny_tools: list[str] = field(default_factory=list)
    sandbox: bool | None = None
    redact: list[str] = field(default_factory=list)
    log: str = ""                      # logging directive
    deflect_message: str = ""          # canned response for deflect
    budget: AgentBudget | None = None  # optional resource constraints
    taint: str = ""                    # EMCP: expected taint label


@dataclass
class ShieldApplyNode(ASTNode):
    """
    shield InputGuard on user_input

    Applies a declared shield to a target expression within a flow step.
    This is the in-flow application point — the source → sink sanitizer.

    The compiler verifies that this node exists on every path from
    untrusted sources to trusted sinks (taint analysis).

    Fields:
        shield_name:   reference to a declared shield
        target:        expression/identifier to shield
        output_type:   optional explicit output type after shielding
    """
    shield_name: str = ""
    target: str = ""
    output_type: str = ""


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
#  PIX NODES — Structured Cognitive Retrieval
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PixDefinition(ASTNode):
    """
    pix ContractIndex {
        source: "contracts/master_agreement.pdf"
        depth: 4
        branching: 3
        model: fast
    }

    The **pix** primitive — structured cognitive retrieval via
    navigational semantics.

    ╔══════════════════════════════════════════════════════════════╗
    ║  THEORETICAL FOUNDATIONS                                     ║
    ╠══════════════════════════════════════════════════════════════╣
    ║                                                              ║
    ║  Document Tree: D = (N, E, ρ, κ)                            ║
    ║    Properties: acyclicity, exhaustive coverage,             ║
    ║    controlled disjunction between siblings.                 ║
    ║                                                              ║
    ║  Monotonic Entropy Reduction:                                ║
    ║    H(R|Q, n₁..nₜ) ≤ H(R|Q, n₁..nₜ₋₁)                    ║
    ║    Each navigation step reduces answer uncertainty.         ║
    ║                                                              ║
    ║  Bayesian Navigation:                                        ║
    ║    P(nᵢ relevant|Q, evidence) ∝                             ║
    ║      P(Q|nᵢ relevant) · P(nᵢ relevant|evidence)            ║
    ║                                                              ║
    ║  Information Foraging (Pirolli & Card, 1999):               ║
    ║    LLM follows information scent through summaries.         ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
    """
    name: str = ""
    source: str = ""
    depth: int = 4
    branching: int = 3
    model: str = "fast"
    effects: EffectRowNode | None = None  # optional effect declaration


@dataclass
class NavigateNode(ASTNode):
    """
    navigate ContractIndex with query: question
    trail: enabled

    LLM-guided tree traversal — the core PIX retrieval primitive.
    Produces a set of relevant leaf nodes and a reasoning path (trail).

    Epistemic level: output is always 'believe' (external I/O involved).
    """
    pix_name: str = ""         # reference to declared pix definition
    corpus_name: str = ""      # NEW: corpus reference (multi-doc mode, §5.3)
    query_expr: str = ""       # query expression (string or reference)
    trail_enabled: bool = False  # whether to record reasoning path
    output_name: str = ""      # named output
    budget_depth: int | None = None    # NEW: override budget max_depth
    budget_nodes: int | None = None    # NEW: override budget max_nodes
    edge_filter: list[str] = field(default_factory=list)  # NEW: relation type filter


@dataclass
class DrillNode(ASTNode):
    """
    drill ContractIndex into "Section3.Liabilities" with query: question

    Explicit descent into a named subtree — bypasses root navigation.
    Useful when the user knows which section is relevant.
    """
    pix_name: str = ""         # reference to declared pix definition
    subtree_path: str = ""     # node ID or title path to drill into
    query_expr: str = ""       # query expression
    output_name: str = ""      # named output


@dataclass
class TrailNode(ASTNode):
    """
    trail Navigate.reasoning_path

    Access the reasoning path — the explainability backbone.
    Every PIX retrieval produces a complete trace of navigational
    decisions, enabling 'why was this retrieved?' auditing.
    """
    navigate_ref: str = ""     # reference to a navigate step's output


# ═══════════════════════════════════════════════════════════════════
#  MDN NODES — Multi-Document Navigation (§5.3)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class CorpusDocEntry(ASTNode):
    """
    A document entry in a corpus definition.

    References a previously declared PIX index and annotates it
    with a document type and optional role within the corpus.
    """
    pix_ref: str = ""          # reference to declared pix definition
    doc_type: str = ""         # document classification (e.g., "Statute", "CaseLaw")
    role: str = ""             # optional role (e.g., "primary", "supporting")


@dataclass
class CorpusEdgeEntry(ASTNode):
    """
    An edge definition in a corpus — (source, target, relation_type).

    Represents a typed, directed edge: r ∈ R ⊆ D × D × L
    from Definition 1 (§2.1).
    """
    source_ref: str = ""       # source document identifier
    target_ref: str = ""       # target document identifier
    relation_type: str = ""    # edge label (e.g., "cite", "implement", "contradict")


@dataclass
class CorpusDefinition(ASTNode):
    """
    corpus LegalCorpus {
        documents: [statute_A, case_law_B, regulation_C]
        relationships: [
            (case_law_B, statute_A, cite)
            (regulation_C, statute_A, implement)
        ]
        weights: {
            (case_law_B, statute_A, cite): 0.9
        }
    }

    The **corpus** primitive — multi-document knowledge graph
    construction. Maps to C = (D, R, τ, ω, σ) from §2.1.

    ╔══════════════════════════════════════════════════════════════╗
    ║  FORMAL BASIS                                                ║
    ╠══════════════════════════════════════════════════════════════╣
    ║                                                              ║
    ║  Definition 1 (§2.1): C = (D, R, τ, ω, σ)                  ║
    ║    D = finite set of documents                               ║
    ║    R ⊆ D × D × L = typed, directed edges                   ║
    ║    τ : R → L = edge type assignment                          ║
    ║    ω : R → (0, 1] = edge weight function                    ║
    ║    σ : D → R^m = summary embedding                          ║
    ║                                                              ║
    ║  Invariants G1–G4 enforced at build time.                    ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
    """
    name: str = ""
    documents: list[CorpusDocEntry] = field(default_factory=list)
    edges: list[CorpusEdgeEntry] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    mcp_server: str = ""
    mcp_resource_uri: str = ""


@dataclass
class CorroborateNode(ASTNode):
    """
    corroborate nav_result as: verified_claims

    Cross-path verification — implements the Principle of Epistemic
    Corroboration from §4.2. Checks independent provenance paths
    for claim confirmation.

    Formal basis (Proposition 6, §4.1):
      C(D₀, φ, π) = ∏ᵢ ω(rᵢ) · EPR(D_last)
    """
    navigate_ref: str = ""     # reference to a navigate result
    output_name: str = ""      # named output for corroborated claims


# ═══════════════════════════════════════════════════════════════════
#  PSYCHE PRIMITIVE — Psychological-Epistemic Modeling (§PEM)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PsycheDefinition(ASTNode):
    """
    psyche TherapeuticProfile {
        dimensions: [affect, cognitive_load, certainty, openness, trust]
        manifold: {
            curvature: { certainty: 0.8, trust: 0.9 }
            noise: 0.05
            momentum: 0.7
        }
        safety: [non_diagnostic, non_prescriptive]
        quantum: enabled
        inference: active
    }

    The **psyche** primitive — Psychological-Epistemic Modeling.

    Models mental states as epistemological objects with structured
    uncertainty, grounded in 4 mathematical pillars:

    ╔══════════════════════════════════════════════════════════════╗
    ║  §1  Riemannian Manifold — state dynamics with inertia      ║
    ║  §2  Density Operators — quantum cognitive probability       ║
    ║  §3  Active Inference — free energy minimization             ║
    ║  §4  Dependent Types — NonDiagnostic safety constraint       ║
    ╚══════════════════════════════════════════════════════════════╝

    Formal basis:
      ψ ∈ M  (cognitive state on Riemannian manifold)
      dψ_t = -∇U(ψ_t, I_t)dt + σ·dW_t  (SDE dynamics)
      P(D|ψ) = Tr(Π_D · ρ_ψ · Π_D)    (Born's rule projection)
      G(π,τ) = E_q[DKL[q||p] - ln p(o_τ|s_τ)]  (expected free energy)

    Safety invariant: ∀ output ∈ Results(q') : ¬IsClinicalDiagnosis(output)
    """
    name: str = ""
    dimensions: list[str] = field(default_factory=list)
    manifold_curvature: dict[str, float] = field(default_factory=dict)
    manifold_noise: float = 0.05
    manifold_momentum: float = 0.7
    safety_constraints: list[str] = field(default_factory=list)
    quantum_enabled: bool = False
    inference_mode: str = ""  # "active" | "passive" | ""


# ═══════════════════════════════════════════════════════════════════
#  MANDATE PRIMITIVE — Cybernetic Refinement Calculus (§CRC)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class MandateDefinition(ASTNode):
    """
    mandate StrictJSON {
        constraint: "Output must be valid JSON with keys: name, score, reasoning"
        kp: 10.0
        ki: 0.1
        kd: 0.05
        tolerance: 0.01
        max_steps: 50
        on_violation: coerce
    }

    The **mandate** primitive — Cybernetic Refinement Calculus.

    Operationalizes the CRC framework (paper_mandate.md) by embedding
    deterministic control of LLM outputs directly in the compiler.
    Unifies three mathematical pillars:

    ╔══════════════════════════════════════════════════════════════╗
    ║  Vía C — Refinement Type (Curry-Howard Isomorphism):        ║
    ║    T_M = { x ∈ Σ* | M(x) ⊢ ⊤ }                           ║
    ║    Γ ⊢ generate(prompt) : T_M                               ║
    ║    Inference: (Γ ⊢ e : Σ*)  ∧  (M(e) ⇓ ⊤)                 ║
    ║             ――――――――――――――――――――――――――――                    ║
    ║                  Γ ⊢ e : T_M                                ║
    ║                                                              ║
    ║  Vía A — Lyapunov Stability (PID Control):                   ║
    ║    u(t) = Kp·e(t) + Ki·∫e(τ)dτ + Kd·de/dt                  ║
    ║    V(e) = ½e²  →  V̇(e) ≈ -λe² < 0  (asymptotic conv.)     ║
    ║                                                              ║
    ║  Vía B — Thermodynamic Logit Bias:                           ║
    ║    ΔL_t collapses violating token probability mass           ║
    ║    before Softmax via negative logit injection.              ║
    ╚══════════════════════════════════════════════════════════════╝

    Theorem 1 (Convergence): Under Kp,Ki,Kd > 0 and
    L-Lipschitz error function, V̇(e) < 0 ∀ e ≠ 0,
    guaranteeing asymptotic convergence to mandate setpoint.
    """
    name: str = ""
    constraint: str = ""           # M(x) — the semantic constraint predicate
    kp: float = 10.0               # Kp — proportional gain
    ki: float = 0.1                # Ki — integral gain
    kd: float = 0.05               # Kd — derivative gain
    tolerance: float = 0.01        # convergence tolerance ε
    max_steps: int = 50            # max PID correction steps N
    on_violation: str = "coerce"   # policy: coerce | halt | retry


@dataclass
class MandateApplyNode(ASTNode):
    """
    mandate StrictJSON on llm_output
    mandate StrictJSON on raw_data -> ValidatedData

    Applies a declared mandate to constrain a target expression
    within a flow body. The compiler verifies the refinement type
    T_M at compile time, and the runtime applies PID control
    at inference time to enforce convergence.
    """
    mandate_name: str = ""
    target: str = ""
    output_type: str = ""


# ═══════════════════════════════════════════════════════════════════
#  LAMBDA DATA NODES — Epistemic State Vectors (§ΛD)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class LambdaDataDefinition(ASTNode):
    """
    lambda Currency {
        ontology: Measure
        certainty: 0.95
        temporal_frame: ["2024-01-01", "2024-12-31"]
        provenance: "exchange_api_v2"
        derivation: observed
    }

    Declares an Epistemic State Vector ψ = ⟨T, V, E⟩ where:
      T — Ontological type from the type universe O  (Invariant 1)
      V — Valid value domain (enforced at runtime)
      E = ⟨c, τ, ρ, δ⟩ — Epistemic tensor encoding:
          c — certainty scalar c ∈ [0,1]          (Invariant 4)
          τ — temporal validity frame
          ρ — provenance EntityRef (origin)
          δ — derivation ∈ Δ = {axiomatic, observed, inferred, mutated}

    ╔══════════════════════════════════════════════════════════════╗
    ║  Invariant 1 — Ontological Rigidity:                        ║
    ║    ∀ ψ = ⟨T, V, E⟩ : T ∈ O ∧ T ≠ ⊥                       ║
    ║                                                              ║
    ║  Invariant 2 — Semantic Interpretation:                      ║
    ║    V ∈ Domain(T) ⊂ Universe(O)                              ║
    ║                                                              ║
    ║  Invariant 3 — Semantic Conservation:                        ║
    ║    f(ψ) ≠ ⊥ ⟹ T(f(ψ)) ⊇ T(ψ) ∨ explicit_cast            ║
    ║                                                              ║
    ║  Invariant 4 — Epistemic Bounding:                           ║
    ║    c ∈ [0,1] ∧ |τ| ≥ 0 ∧ ρ ∈ EntityRef ∧ δ ∈ Δ            ║
    ╚══════════════════════════════════════════════════════════════╝

    Theorem 5.1 (Epistemic Degradation):
      For any transformation f operating on ΛD inputs,
        c_out ≤ min(c_in₁, c_in₂, …, c_inₙ)
      Output certainty cannot exceed the minimum input certainty.
      This is enforced at compile time for static compositions.
    """
    name: str = ""
    ontology: str = ""                     # T ∈ O — ontological type
    certainty: float = 1.0                 # c ∈ [0,1] — epistemic certainty scalar
    temporal_frame_start: str = ""         # τ_start — temporal validity window start
    temporal_frame_end: str = ""           # τ_end — temporal validity window end
    provenance: str = ""                   # ρ ∈ EntityRef — causal origin
    derivation: str = ""                   # δ ∈ Δ = {raw, derived, inferred, aggregated, transformed}


@dataclass
class LambdaDataApplyNode(ASTNode):
    """
    lambda Currency on raw_amount
    lambda Currency on raw_amount -> TypedAmount

    Applies a declared ΛD epistemic projection to a target expression
    within a flow body. This binds the epistemic state vector ψ to
    the data flowing through the pipeline, enabling the compiler to:

      1. Track certainty propagation (Theorem 5.1: Epistemic Degradation)
      2. Enforce ontological consistency (Invariant 1)
      3. Verify temporal validity windows (Invariant 4)
      4. Preserve provenance chains across transformations (Invariant 3)

    The resulting typed expression carries its full epistemic context,
    enabling the runtime to project to JSON (lossy) or maintain
    full ΛD fidelity internally.
    """
    lambda_data_name: str = ""             # reference to LambdaDataDefinition
    target: str = ""                       # expression to bind
    output_type: str = ""                  # result type after epistemic binding


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
