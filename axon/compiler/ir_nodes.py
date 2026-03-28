"""
AXON Compiler — Intermediate Representation (IR) Node Definitions
==================================================================
The model-agnostic heart of the AXON compilation pipeline.

These IR nodes sit between the cognitive AST and the backend-specific
prompt compilers. They represent the *execution semantics* of an AXON
program without any dependency on a specific LLM provider.

KEY DESIGN PRINCIPLES:
  1. MODEL-AGNOSTIC — No reference to Claude, Gemini, OpenAI, etc.
  2. JSON-SERIALIZABLE — Every node has to_dict() for inspection/debug.
  3. DAG-ORIENTED — Flows are ordered step sequences with data deps.
  4. COMPLETE — Every AST cognitive concept has an IR equivalent.
  5. IMMUTABLE — Once generated, IR nodes are not mutated.

Pipeline position:
  Source → Lexer → Parser → AST → TypeChecker → IRGenerator → **IR** → Backend
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════════════
#  BASE IR NODE
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IRNode:
    """
    Base class for all AXON IR nodes.

    Every IR node carries a `node_type` string used for serialization
    dispatch and a source location for error reporting traceability.
    """
    node_type: str = ""
    source_line: int = 0
    source_column: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert this IR node to a JSON-serializable dictionary."""
        result: dict[str, Any] = {"node_type": self.node_type}

        for key, value in self.__dict__.items():
            if key == "node_type":
                continue
            result[key] = _serialize_value(value)

        return result


def _serialize_value(value: Any) -> Any:
    """Recursively serialize a value for JSON output."""
    if isinstance(value, IRNode):
        return value.to_dict()
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_serialize_value(item) for item in value)
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    return value


# ═══════════════════════════════════════════════════════════════════
#  PROGRAM ROOT
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IRProgram(IRNode):
    """
    Root of the AXON IR — the complete compiled program.

    Contains all resolved declarations, type definitions, and
    execution units (IRRun), ready for backend consumption.
    """
    node_type: str = "program"
    personas: tuple[IRPersona, ...] = ()
    contexts: tuple[IRContext, ...] = ()
    anchors: tuple[IRAnchor, ...] = ()
    tools: tuple[IRToolSpec, ...] = ()
    memories: tuple[IRMemory, ...] = ()
    types: tuple[IRType, ...] = ()
    flows: tuple[IRFlow, ...] = ()
    runs: tuple[IRRun, ...] = ()
    imports: tuple[IRImport, ...] = ()
    agents: tuple['IRAgent', ...] = ()
    shields: tuple['IRShield', ...] = ()
    ots_specs: tuple['IROtsDefinition', ...] = ()
    pix_specs: tuple['IRPixSpec', ...] = ()
    corpus_specs: tuple['IRCorpusSpec', ...] = ()
    psyche_specs: tuple['IRPsycheSpec', ...] = ()
    mandate_specs: tuple['IRMandate', ...] = ()
    lambda_data_specs: tuple['IRLambdaData', ...] = ()


# ═══════════════════════════════════════════════════════════════════
#  DECLARATION IR NODES — resolved identities and configurations
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IRImport(IRNode):
    """
    A resolved import declaration.

    Example: import axon.anchors.{NoHallucination, NoBias}
    → module_path=("axon", "anchors"), names=("NoHallucination", "NoBias")

    EMS (Epistemic Module System) fields:
      resolved:       True when symbols have been injected into local tables
      interface_hash: .axi interface hash for early cutoff (Nix/GHC-style)
    """
    node_type: str = "import"
    module_path: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    resolved: bool = False
    interface_hash: str = ""


@dataclass(frozen=True)
class IRPersona(IRNode):
    """
    Compiled persona — the cognitive identity for execution.

    Maps from AST PersonaDefinition. All fields are resolved
    and normalized for backend consumption.
    """
    node_type: str = "persona"
    name: str = ""
    domain: tuple[str, ...] = ()
    tone: str = ""
    confidence_threshold: float | None = None
    cite_sources: bool | None = None
    refuse_if: tuple[str, ...] = ()
    language: str = ""
    description: str = ""


@dataclass(frozen=True)
class IRContext(IRNode):
    """
    Compiled context — session and memory configuration.

    Maps from AST ContextDefinition. Controls the working
    environment for a flow execution.
    """
    node_type: str = "context"
    name: str = ""
    memory_scope: str = ""       # session | persistent | none
    language: str = ""
    depth: str = ""              # shallow | standard | deep | exhaustive
    max_tokens: int | None = None
    temperature: float | None = None
    cite_sources: bool | None = None


@dataclass(frozen=True)
class IRAnchor(IRNode):
    """
    Compiled anchor — a hard constraint that can NEVER be violated.

    Maps from AST AnchorConstraint. Backends inject these into
    system prompts and validation layers.
    """
    node_type: str = "anchor"
    name: str = ""
    description: str = ""
    require: str = ""
    reject: tuple[str, ...] = ()
    enforce: str = ""
    confidence_floor: float | None = None
    unknown_response: str = ""
    on_violation: str = ""           # raise | fallback | warn
    on_violation_target: str = ""    # error class or fallback reference


@dataclass(frozen=True)
class IRToolSpec(IRNode):
    """
    Compiled tool specification — an external capability descriptor.

    Maps from AST ToolDefinition. The Tool Resolver populates
    this with provider-specific binding information.
    """
    node_type: str = "tool_spec"
    name: str = ""
    provider: str = ""
    max_results: int | None = None
    filter_expr: str = ""
    timeout: str = ""
    runtime: str = ""
    sandbox: bool | None = None
    # v0.11.0 expansions (W1)
    input_schema: tuple[tuple[str, str, bool], ...] = ()  # (name, type, required)
    output_schema: str = ""
    # v0.14.0 — Convergence Theorem 2: algebraic effect row
    effect_row: IREffectRow | None = None


@dataclass(frozen=True)
class IRMemory(IRNode):
    """
    Compiled memory definition — persistent semantic storage config.

    Maps from AST MemoryDefinition.
    """
    node_type: str = "memory"
    name: str = ""
    store: str = ""          # session | persistent | ephemeral
    backend: str = ""        # vector_db | in_memory | redis | custom
    retrieval: str = ""      # semantic | exact | hybrid
    decay: str = ""          # none | daily | weekly | <duration>


# ═══════════════════════════════════════════════════════════════════
#  TYPE SYSTEM IR NODES
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IRTypeField(IRNode):
    """A single field within a structured type definition."""
    node_type: str = "type_field"
    name: str = ""
    type_name: str = ""
    generic_param: str = ""
    optional: bool = False


@dataclass(frozen=True)
class IRType(IRNode):
    """
    Compiled semantic type — defines the shape of cognitive data.

    Maps from AST TypeDefinition. Supports three flavors:
      - Structured: type Party { name: FactualClaim, ... }
      - Ranged: type RiskScore(0.0..1.0)
      - Constrained: type HighConfidence where confidence >= 0.85
    """
    node_type: str = "type_def"
    name: str = ""
    fields: tuple[IRTypeField, ...] = ()
    range_min: float | None = None
    range_max: float | None = None
    where_expression: str = ""


# ═══════════════════════════════════════════════════════════════════
#  FLOW & STEP IR NODES — the execution DAG
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IRParameter(IRNode):
    """A typed parameter for a flow."""
    node_type: str = "parameter"
    name: str = ""
    type_name: str = ""
    generic_param: str = ""
    optional: bool = False


@dataclass(frozen=True)
class IRDataEdge(IRNode):
    """A typed data dependency between two steps."""
    node_type: str = "data_edge"
    source_step: str = ""
    target_step: str = ""
    type_name: str = ""


@dataclass(frozen=True)
class IRFlow(IRNode):
    """
    Compiled flow — an ordered cognitive pipeline.

    Maps from AST FlowDefinition. The steps list represents
    the execution DAG in topological order.
    """
    node_type: str = "flow"
    name: str = ""
    parameters: tuple[IRParameter, ...] = ()
    return_type_name: str = ""
    return_type_generic: str = ""
    return_type_optional: bool = False
    steps: tuple[IRNode, ...] = ()  # ordered: IRStep, IRProbe, IRReason, etc.
    edges: tuple[IRDataEdge, ...] = ()
    execution_levels: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class IRStep(IRNode):
    """
    Compiled step — a named cognitive operation within a flow.

    A step can contain a probe, reason chain, weave, tool use,
    or a plain ask instruction. Sub-steps are recursively compiled.
    """
    node_type: str = "step"
    name: str = ""
    given: str = ""
    ask: str = ""
    use_tool: IRUseTool | None = None
    probe: IRProbe | None = None
    reason: IRReason | None = None
    weave: IRWeave | None = None
    output_type: str = ""
    confidence_floor: float | None = None
    body: tuple[IRNode, ...] = ()  # sub-steps


# ═══════════════════════════════════════════════════════════════════
#  COGNITIVE IR NODES — the intelligence primitives
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IRIntent(IRNode):
    """
    Compiled intent — an atomic semantic instruction with typed I/O.

    Maps from AST IntentNode. This is the most granular cognitive
    operation: "given X, ask Y, expect Z".
    """
    node_type: str = "intent"
    name: str = ""
    given: str = ""
    ask: str = ""
    output_type_name: str = ""
    output_type_generic: str = ""
    output_type_optional: bool = False
    confidence_floor: float | None = None


@dataclass(frozen=True)
class IRProbe(IRNode):
    """
    Compiled probe — targeted structured extraction.

    Maps from AST ProbeDirective. Declares "look at X, extract Y".
    """
    node_type: str = "probe"
    target: str = ""
    fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class IRReason(IRNode):
    """
    Compiled reason chain — explicit chain-of-thought directive.

    Maps from AST ReasonChain. Configures depth, visibility,
    and output type for multi-step reasoning.
    """
    node_type: str = "reason"
    name: str = ""
    about: str = ""
    given: tuple[str, ...] = ()  # always normalized to tuple
    depth: int = 1
    show_work: bool = False
    chain_of_thought: bool = False
    ask: str = ""
    output_type: str = ""


@dataclass(frozen=True)
class IRWeave(IRNode):
    """
    Compiled weave — semantic synthesis of multiple sources.

    Maps from AST WeaveNode. Combines outputs into a coherent
    result with priority ordering and style control.
    """
    node_type: str = "weave"
    sources: tuple[str, ...] = ()
    target: str = ""
    format_type: str = ""
    priority: tuple[str, ...] = ()
    style: str = ""


@dataclass(frozen=True)
class IRValidateRule(IRNode):
    """A single validation rule within a validate gate."""
    node_type: str = "validate_rule"
    condition: str = ""
    comparison_op: str = ""
    comparison_value: str = ""
    action: str = ""             # refine | raise | warn | pass
    action_target: str = ""
    action_params: tuple[tuple[str, str], ...] = ()  # frozen dict equivalent


@dataclass(frozen=True)
class IRValidate(IRNode):
    """
    Compiled validate gate — a semantic validation checkpoint.

    Maps from AST ValidateGate. Checks output against a schema
    with configurable violation responses.
    """
    node_type: str = "validate"
    target: str = ""
    schema: str = ""
    rules: tuple[IRValidateRule, ...] = ()


@dataclass(frozen=True)
class IRRefine(IRNode):
    """
    Compiled refine block — adaptive retry strategy.

    Maps from AST RefineBlock. Configures retry behavior with
    failure context injection and progressive backoff.
    """
    node_type: str = "refine"
    max_attempts: int = 3
    pass_failure_context: bool = True
    backoff: str = "none"        # none | linear | exponential
    on_exhaustion: str = ""      # raise <X> | escalate | fallback(...)
    on_exhaustion_target: str = ""


@dataclass(frozen=True)
class IRUseTool(IRNode):
    """
    Compiled tool invocation — a reference to an external capability.

    Maps from AST UseToolNode. Links to an IRToolSpec by name.
    """
    node_type: str = "use_tool"
    tool_name: str = ""
    argument: str = ""
    # v0.11.0 expansions (W1)
    parameters: tuple[tuple[str, str], ...] = ()  # (param_name, value)
    expected_output_type: str = ""


@dataclass(frozen=True)
class IRRemember(IRNode):
    """
    Compiled remember — store a value into semantic memory.

    Maps from AST RememberNode.
    """
    node_type: str = "remember"
    expression: str = ""
    memory_target: str = ""


@dataclass(frozen=True)
class IRRecall(IRNode):
    """
    Compiled recall — retrieve from semantic memory.

    Maps from AST RecallNode.
    """
    node_type: str = "recall"
    query: str = ""
    memory_source: str = ""


@dataclass(frozen=True)
class IRConditional(IRNode):
    """
    Compiled conditional — cognitive branching logic.

    Maps from AST ConditionalNode. Both branches are
    recursively compiled IR nodes.
    """
    node_type: str = "conditional"
    condition: str = ""
    comparison_op: str = ""
    comparison_value: str = ""
    then_branch: IRNode | None = None
    else_branch: IRNode | None = None


@dataclass(frozen=True)
class IRForIn(IRNode):
    """
    Compiled for-in iteration — systematic traversal of a structured
    collection within a cognitive flow.

    Maps from AST ForInStatement.  The variable is bound sequentially
    to each element of the iterable path at runtime.

    Example:
      for chapter in thesis.chapters { ... }
      → variable="chapter", iterable="thesis.chapters", body=(...)
    """
    node_type: str = "for_in"
    variable: str = ""                              # loop variable name
    iterable: str = ""                              # dotted path expression
    body: tuple[IRNode, ...] = ()                   # compiled body steps


@dataclass(frozen=True)
class IRLetBinding(IRNode):
    """
    Compiled SSA immutable binding — a lexical axiom injected into
    the cognitive state for static substitution at runtime.

    Maps from AST LetStatement.  The target identifier is bound
    once and cannot be rebound (Single Static Assignment).

    Example:
      let draft_path = "workspace/drafts/tesis.md"
      → target="draft_path", value="workspace/drafts/tesis.md"
    """
    node_type: str = "let_binding"
    target: str = ""                                 # binding identifier
    value: str | int | float | bool | list = ""      # resolved constant


# ═══════════════════════════════════════════════════════════════════
#  PARADIGM SHIFT IR NODES — epistemic scoping, parallelism, yielding
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IREpistemicBlock(IRNode):
    """
    Compiled epistemic scope — injects constraints and LLM tuning.

    The AXON equivalent of a "purity annotation" in Haskell. The compiler
    calculates the constraint set at compile time; the executor applies
    them as runtime overrides.

    Constraint Matrix:
      know      → temperature=0.1, top_p=0.3, anchors=[RequiresCitation, NoHallucination]
      believe   → temperature=0.3, top_p=0.5, anchors=[NoHallucination]
      speculate → temperature=0.9, top_p=0.95, anchors=[]
      doubt     → temperature=0.2, top_p=0.4, anchors=[RequiresCitation, SyllogismChecker]
    """
    node_type: str = "epistemic_block"
    mode: str = ""                              # "know"|"believe"|"speculate"|"doubt"
    injected_anchors: tuple[str, ...] = ()      # auto-injected anchor names
    temperature_override: float | None = None   # LLM temperature
    top_p_override: float | None = None         # nucleus sampling override
    children: tuple[IRNode, ...] = ()           # compiled inner declarations


@dataclass(frozen=True)
class IRParallelBlock(IRNode):
    """
    Compiled parallel dispatch — branches run via asyncio.gather.

    At compile time, the IRGenerator verifies no data dependencies
    between branches. At runtime, the executor fires them concurrently
    and collects results into `context[branch.step_name]`.
    """
    node_type: str = "parallel_block"
    branches: tuple[IRNode, ...] = ()           # independent step subtrees
    consolidation: str = ""                     # optional consolidation strategy


@dataclass(frozen=True)
class IRHibernate(IRNode):
    """
    Compiled hibernate checkpoint — CPS serialization point.

    The continuation_id is compiler-generated (hash of flow_name + step_index)
    so that resume() is deterministic. The executor serializes the full
    ExecutionState and halts; resume() deserializes and continues.
    """
    node_type: str = "hibernate"
    event_name: str = ""                        # event to wait for
    timeout: str = ""                           # optional duration
    continuation_id: str = ""                   # compiler-generated unique ID


@dataclass(frozen=True)
class IRDeliberate(IRNode):
    """
    Compiled deliberate block — compute budget envelope.

    Maps from AST DeliberateBlock. Wraps inner IR steps with
    a computational budget that controls reasoning effort,
    token allocation, and iteration depth.

    The strategy field maps to LLM parameter sets:
      quick      → reasoning_effort=low,    budget_factor=0.25
      balanced   → reasoning_effort=medium, budget_factor=0.5
      thorough   → reasoning_effort=high,   budget_factor=1.0
      exhaustive → reasoning_effort=max,    budget_factor=1.0
    """
    node_type: str = "deliberate"
    budget: int = 0                              # max tokens for reasoning
    depth: int = 1                               # max reasoning iterations
    strategy: str = "balanced"                   # quick|balanced|thorough|exhaustive
    children: tuple[IRNode, ...] = ()            # compiled inner steps


@dataclass(frozen=True)
class IRConsensus(IRNode):
    """
    Compiled consensus block — Best-of-N selection.

    Maps from AST ConsensusBlock. Runs inner steps N times under
    speculative mode (high temperature) and selects the best result
    via the referenced reward anchor.

    Fields:
      n_branches:     number of parallel evaluation runs (>= 2)
      reward_anchor:  name of the anchor used as reward function
      selection:      "best" (highest score) or "majority" (most common)
    """
    node_type: str = "consensus"
    n_branches: int = 3                          # parallel evaluation count
    reward_anchor: str = ""                      # reward function anchor name
    selection: str = "best"                      # best | majority
    children: tuple[IRNode, ...] = ()            # compiled inner steps


@dataclass(frozen=True)
class IRForge(IRNode):
    """
    Compiled forge block — directed creative synthesis.

    Maps from AST ForgeBlock. Orchestrates the full Poincaré pipeline:
      1. Preparation:  expand seed with context probing
      2. Incubation:   speculative divergence with novelty control
      3. Illumination:  Best-of-N consensus selection
      4. Verification:  adversarial doubt + anchor validation

    Boden modes map to internal parameters:
      combinatory      → recombination of existing elements (interpolation)
      exploratory      → search within rules of conceptual space
      transformational → restructuring the rules of the space itself
    """
    node_type: str = "forge"
    name: str = ""
    seed: str = ""
    output_type: str = ""
    mode: str = "combinatory"           # combinatory|exploratory|transformational
    novelty: float = 0.7                # novelty-utility tradeoff [0.0, 1.0]
    constraints: str = ""               # reward anchor for quality/beauty
    depth: int = 3                      # incubation iterations (Poincaré phase 2)
    branches: int = 5                   # Best-of-N for illumination (phase 3)
    children: tuple[IRNode, ...] = ()   # compiled inner steps


@dataclass(frozen=True)
class IROtsDefinition(IRNode):
    """
    Compiled OTS definition - a synthesized continual capability.
    """
    node_type: str = "ots"
    name: str = ""
    types: tuple[str, ...] = ()
    teleology: str = ""
    homotopy_search: str = "shallow"
    linear_constraints: tuple[tuple[str, str], ...] = ()
    loss_function: str = ""
    children: tuple[IRNode, ...] = ()


@dataclass(frozen=True)
class IROtsApply(IRNode):
    """
    Compiled OTS application point.
    """
    node_type: str = "ots_apply"
    ots_name: str = ""
    target: str = ""
    output_type: str = ""
    output_type: str = ""

# ═══════════════════════════════════════════════════════════════════
#  AGENT IR NODE — compiled BDI autonomous agent
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IRAgent(IRNode):
    """
    Compiled agent block — BDI autonomous agent.

    Maps from AST AgentDefinition. Orchestrates the full BDI
    deliberation cycle:
      1. Observe   — gather beliefs from inputs + memory + tool results
      2. Deliberate — evaluate goal satisfaction (epistemic assessment)
      3. Plan      — select next action from plan library (body steps)
      4. Act       — execute step or tool call (parallel if independent)
      5. Reflect   — update beliefs, advance epistemic state

    ╔══════════════════════════════════════════════════════════════╗
    ║  FORMAL SEMANTICS                                            ║
    ╠══════════════════════════════════════════════════════════════╣
    ║                                                              ║
    ║  Coalgebraic transition system:                              ║
    ║    Agent = (S, O, step: S × Action → S, obs: S → O)         ║
    ║    where S = cognitive state (beliefs, goals, plans)         ║
    ║          O = observations (tool outputs, LLM responses)      ║
    ║                                                              ║
    ║  Convergence (Tarski fixed-point):                           ║
    ║    T(σ*) = σ* on epistemic lattice                           ║
    ║    doubt ⊏ speculate ⊏ believe ⊏ know                       ║
    ║    Agent terminates when σ reaches 'believe' or 'know' for   ║
    ║    the goal, OR when budget is exhausted.                    ║
    ║                                                              ║
    ║  Concurrency (π-calculus):                                   ║
    ║    Agent ≡ goal.( ν ch )( tool₁⟨ch⟩ | tool₂⟨ch⟩ | … )     ║
    ║    Independent tools execute in parallel via channels.       ║
    ║                                                              ║
    ║  Resource management (linear logic):                         ║
    ║    Each iteration consumes: tokens ⊗ time ⊗ cost             ║
    ║    Budget guards ensure ∀i: Σ(cost_i) ≤ max_cost            ║
    ║                                                              ║
    ║  Recovery (STIT logic):                                      ║
    ║    When ¬◇φ (no option achieves goal), on_stuck fires:       ║
    ║    forge → creative synthesis, hibernate → suspend,           ║
    ║    escalate → human operator, retry → modified params.       ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝

    Strategies:
      react             — Thought → Action → Observation loop
      reflexion         — ReAct + self-critique after each cycle
      plan_and_execute  — full plan generation before execution
      custom            — user-defined via body steps only
    """
    node_type: str = "agent"
    name: str = ""
    goal: str = ""                              # Davidson's pro-attitude
    tools: tuple[str, ...] = ()                 # available tool references
    max_iterations: int = 10                    # budget: iteration cap
    max_tokens: int = 0                         # budget: token cap (0=unlimited)
    max_time: str = ""                          # budget: time cap (duration)
    max_cost: float = 0.0                       # budget: cost cap (0.0=unlimited)
    memory_ref: str = ""                        # reference to declared memory
    strategy: str = "react"                     # deliberation strategy
    on_stuck: str = "escalate"                  # STIT recovery policy
    return_type: str = ""                       # expected output type name
    shield_ref: str = ""                        # reference to declared shield
    children: tuple[IRNode, ...] = ()           # compiled plan library steps


# ═══════════════════════════════════════════════════════════════════
#  SHIELD IR NODES — compiler-level LLM security boundaries
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IRShield(IRNode):
    """
    Compiled shield declaration — a security boundary in the
    Denning Lattice Model for information flow control.

    Represents the compile-time verified, runtime-enforced security
    policy. The type checker ensures all data paths from untrusted
    sources pass through a shield before reaching trusted sinks.

    Trust Lattice:
      Untrusted → Quarantined → Sanitized → Validated → Trusted

    Shield levels:
      1. Input shields  — scan/sanitize before LLM context
      2. Output shields — validate LLM responses
      3. Capability shields — restrict tool access (WASI/OCM)
    """
    node_type: str = "shield"
    name: str = ""
    scan: tuple[str, ...] = ()                  # threat categories
    strategy: str = "pattern"                   # detection mechanism
    on_breach: str = "halt"                     # breach handler
    severity: str = "critical"                  # severity level
    quarantine: str = ""                        # quarantine label
    max_retries: int = 0                        # for sanitize_and_retry
    confidence_threshold: float = 0.0           # min confidence
    allow_tools: tuple[str, ...] = ()           # capability allow list
    deny_tools: tuple[str, ...] = ()            # capability deny list
    sandbox: bool = False                       # sandbox tool execution
    redact: tuple[str, ...] = ()                # PII fields to redact
    log: str = ""                               # logging directive
    deflect_message: str = ""                   # canned deflection


@dataclass(frozen=True)
class IRShieldApply(IRNode):
    """
    Compiled shield application point — the taint analysis insertion.

    Transforms data from Untrusted to Sanitized in the trust lattice.
    The compiler verifies this node exists on every path from
    untrusted sources to trusted sinks.
    """
    node_type: str = "shield_apply"
    shield_name: str = ""                       # reference to declared shield
    target: str = ""                            # expression being shielded
    output_type: str = ""                       # result type after shielding


# ═══════════════════════════════════════════════════════════════════
#  DATA SCIENCE IR NODES — associative engine operations
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IRDataSpace(IRNode):
    """
    Compiled dataspace declaration — creates an in-memory associative space.
    """
    node_type: str = "dataspace"
    name: str = ""
    body: tuple[IRNode, ...] = ()


@dataclass(frozen=True)
class IRIngest(IRNode):
    """
    Compiled ingest command — loads external data into a DataSpace.
    """
    node_type: str = "ingest"
    source: str = ""           # file path or identifier
    target: str = ""           # target DataSpace name


@dataclass(frozen=True)
class IRFocus(IRNode):
    """
    Compiled focus command — sets selection filter on the associative engine.
    """
    node_type: str = "focus"
    expression: str = ""


@dataclass(frozen=True)
class IRAssociate(IRNode):
    """
    Compiled associate command — links two tables/dataspaces.
    """
    node_type: str = "associate"
    left: str = ""
    right: str = ""
    using_field: str = ""


@dataclass(frozen=True)
class IRAggregate(IRNode):
    """
    Compiled aggregate command — performs summary reduction.
    """
    node_type: str = "aggregate"
    target: str = ""
    group_by: tuple[str, ...] = ()
    alias: str = ""


@dataclass(frozen=True)
class IRExplore(IRNode):
    """
    Compiled explore command — interactive data display.
    """
    node_type: str = "explore"
    target: str = ""
    limit: int | None = None


# ═══════════════════════════════════════════════════════════════════
#  EXECUTION IR NODE — the complete wiring
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IRRun(IRNode):
    """
    Compiled run statement — the complete execution binding.

    Maps from AST RunStatement. This is the top-level entry point
    that wires together flow + persona + context + anchors into
    a single executable unit.

    The Anchor Enforcer attaches resolved anchor references here.
    The Tool Resolver ensures all tools referenced in the flow exist.
    """
    node_type: str = "run"
    flow_name: str = ""
    arguments: tuple[str, ...] = ()
    persona_name: str = ""
    context_name: str = ""
    anchor_names: tuple[str, ...] = ()
    on_failure: str = ""
    on_failure_params: tuple[tuple[str, str], ...] = ()
    output_to: str = ""
    effort: str = ""

    # Resolved references (populated by IRGenerator)
    resolved_flow: IRFlow | None = None
    resolved_persona: IRPersona | None = None
    resolved_context: IRContext | None = None
    resolved_anchors: tuple[IRAnchor, ...] = ()


# ═══════════════════════════════════════════════════════════════════
#  STREAMING & EFFECT IR NODES — Convergence Theorems 1 & 2
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IREffectRow(IRNode):
    """
    Compiled algebraic effect row — Koka-style effect annotation.

    Theoretical basis — Convergence Theorem 2:
      effect ToolCall[E: EpistemicLevel] where
        invoke : (tool: ToolSpec, args: Dict) →[E] ToolResult<E>

    The effect row declares side-effect categories and epistemic
    classification for a tool or step. The type checker uses this
    to verify epistemic compatibility at tool-use sites.

    Examples:
      <pure, epistemic:know>         — deterministic, no I/O
      <io, network, epistemic:speculate> — network I/O, unverified
    """
    node_type: str = "effect_row"
    effects: tuple[str, ...] = ()          # ("io", "network", "pure")
    epistemic_level: str = ""              # "know" | "believe" | "speculate" | "doubt"


@dataclass(frozen=True)
class IRStreamSpec(IRNode):
    """
    Compiled stream specification — coinductive semantic stream.

    Theoretical basis — Convergence Theorem 1:
      Stream(τ) = νX. (StreamChunk × EpistemicState × X)

    Maps from AST StreamDefinition. Embeds the epistemic gradient
    and shield reference for co-inductive evaluation at runtime.

    The gradient is a monotonic path on the epistemic lattice:
      ⊥ ⊑ doubt ⊑ speculate ⊑ believe ⊑ know

    Transition from believe→know requires:
      1. Stream convergence (complete response)
      2. Anchor validation against ground truth
      3. All contracts satisfied
    """
    node_type: str = "stream_spec"
    name: str = ""                                  # stream element type name
    element_type: str = ""                          # resolved type name
    element_type_generic: str = ""                  # generic parameter if any
    initial_gradient: str = "doubt"                 # starting epistemic level
    epistemic_gradient: tuple[str, ...] = ()        # ("doubt", "speculate", "believe", "know")
    on_chunk_handler: str = ""                      # serialized handler reference
    on_complete_handler: str = ""                   # serialized handler reference
    on_chunk_body: tuple = ()                       # compiled on_chunk handler IR nodes
    on_complete_body: tuple = ()                    # compiled on_complete handler IR nodes
    shield_ref: str = ""                            # shield for co-inductive eval


# ═══════════════════════════════════════════════════════════════════
#  PIX IR NODES — Structured Cognitive Retrieval
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IRPixSpec(IRNode):
    """
    Compiled PIX index specification — structured document tree retrieval.

    Theoretical basis — PIX Retrieval Theorem:
      PIX(D, q) = argmax_{n ∈ N} P(relevant(n, q) | path(root, n))

    Maps from AST PixDefinition. Encodes the bounded search parameters
    and source reference for tree-based navigation at runtime.
    """
    node_type: str = "pix_spec"
    name: str = ""                                  # PIX index name
    source: str = ""                                # document source reference
    max_depth: int = 4                              # tree search depth bound
    max_branching: int = 3                          # branching factor limit
    model: str = ""                                 # LLM model for scoring
    effect_row: IREffectRow | None = None           # effect annotations


@dataclass(frozen=True)
class IRNavigate(IRNode):
    """
    Compiled navigate operation — PIX tree traversal with LLM scoring.

    At runtime, performs bounded BFS/DFS on the document tree with
    heuristic pruning based on the LLM's information scent scoring.

    The epistemic level of the result is always 'believe' (external I/O),
    matching the formal specification:
      navigate : (PIX, Query) →[believe] NavigationResult
    """
    node_type: str = "navigate"
    pix_ref: str = ""                               # reference to a PIX spec
    corpus_ref: str = ""                             # MDN: reference to a corpus spec
    query: str = ""                                  # search query text
    trail_enabled: bool = True                       # whether to capture reasoning path
    output_name: str = ""                            # optional binding name
    budget_depth: int | None = None                  # MDN: override max_depth
    budget_nodes: int | None = None                  # MDN: override max_nodes
    edge_filter: tuple[str, ...] = ()                # MDN: relation type filter


@dataclass(frozen=True)
class IRDrill(IRNode):
    """
    Compiled drill operation — subtree descent within a PIX tree.

    Focuses navigation on a specific subtree path, enabling targeted
    information retrieval within a previously navigated region.

    Formal semantics:
      drill : (PIX, Path, Query) →[believe] NavigationResult
    """
    node_type: str = "drill"
    pix_ref: str = ""                               # reference to a PIX spec
    subtree_path: str = ""                          # dot-separated path to subtree root
    query: str = ""                                  # search query text
    output_name: str = ""                            # optional binding name


@dataclass(frozen=True)
class IRTrail(IRNode):
    """
    Compiled trail access — retrieves the reasoning path from a navigate/drill.

    The trail is a sequence of NavigationStep records documenting
    which nodes the LLM scored, why, and what it selected—providing
    full explainability of the retrieval process.
    """
    node_type: str = "trail"
    navigate_ref: str = ""                          # reference to a navigate/drill result


# ═══════════════════════════════════════════════════════════════════
#  MDN IR NODES — Multi-Document Navigation (§5.3)
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IRCorpusDocSpec(IRNode):
    """Compiled document entry in a corpus spec."""
    node_type: str = "corpus_doc_spec"
    pix_ref: str = ""                               # PIX index reference
    doc_type: str = ""                              # document classification
    role: str = ""                                  # optional role


@dataclass(frozen=True)
class IRCorpusEdgeSpec(IRNode):
    """Compiled edge entry in a corpus spec."""
    node_type: str = "corpus_edge_spec"
    source_ref: str = ""                            # source document ID
    target_ref: str = ""                            # target document ID
    relation_type: str = ""                         # edge label


@dataclass(frozen=True)
class IRCorpusSpec(IRNode):
    """
    Compiled corpus specification — multi-document knowledge graph.

    Formal basis — Definition 1 (§2.1):
      C = (D, R, τ, ω, σ)
      D = finite set of documents
      R ⊆ D × D × L = typed, directed edges
      τ : R → L = edge type assignment
      ω : R → (0, 1] = edge weight function
      σ : D → R^m = summary embedding

    Maps from AST CorpusDefinition. Invariants G1–G4 are enforced
    at type-check time; this node is the compiled output.
    """
    node_type: str = "corpus_spec"
    name: str = ""                                  # corpus name
    documents: tuple[IRCorpusDocSpec, ...] = ()      # compiled document list
    edges: tuple[IRCorpusEdgeSpec, ...] = ()          # compiled edge list
    weights: tuple[tuple[str, float], ...] = ()      # compiled weight map


@dataclass(frozen=True)
class IRCorroborate(IRNode):
    """
    Compiled corroboration operation — cross-path verification.

    Formal basis — Proposition 6 (§4.1):
      C(D₀, φ, π) = ∏ᵢ ω(rᵢ) · EPR(D_last)

    At runtime, checks independent provenance paths for claim
    confirmation, implementing the Principle of Epistemic
    Corroboration from §4.2.
    """
    node_type: str = "corroborate"
    navigate_ref: str = ""                          # reference to a navigate result
    output_name: str = ""                           # binding name for corroborated claims


# ═══════════════════════════════════════════════════════════════════
#  PSYCHE IR NODES — Psychological-Epistemic Modeling (§PEM)
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IRPsycheSpec(IRNode):
    """
    Compiled psyche specification — psychological-epistemic model config.

    Models mental states as epistemological objects with structured
    uncertainty, grounded in 4 mathematical pillars:

      §1  Riemannian Manifold — state dynamics with inertia
      §2  Density Operators — quantum cognitive probability
      §3  Active Inference — free energy minimization
      §4  Dependent Types — NonDiagnostic safety constraint

    Formal basis:
      ψ ∈ M  (cognitive state on manifold M)
      dψ_t = -∇U(ψ_t, I_t)dt + σ·dW_t
      P(D|ψ) = Tr(Π_D · ρ_ψ · Π_D)
      G(π,τ) = E_q[DKL[q||p] - ln p(o_τ|s_τ)]

    Safety invariant (compile-time enforced):
      ∀ output ∈ Results(q') : ¬IsClinicalDiagnosis(output)
    """
    node_type: str = "psyche_spec"
    name: str = ""
    dimensions: tuple[str, ...] = ()                # cognitive dimension names
    manifold_curvature: tuple[tuple[str, float], ...] = ()  # per-dim curvature
    manifold_noise: float = 0.05                    # σ — stochastic perturbation
    manifold_momentum: float = 0.7                  # β — momentum decay
    safety_constraints: tuple[str, ...] = ()        # e.g. ("non_diagnostic", "non_prescriptive")
    quantum_enabled: bool = False                   # density matrix mode
    inference_mode: str = ""                        # "active" | "passive"


# ═══════════════════════════════════════════════════════════════════
#  MANDATE IR NODES — Cybernetic Refinement Calculus (§CRC)
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IRMandate(IRNode):
    """
    Compiled mandate specification — deterministic LLM control.

    Operationalizes the Cybernetic Refinement Calculus (CRC):

      Vía C (Static): Refinement type T_M = { x ∈ Σ* | M(x) ⊢ ⊤ }
      Vía A (Dynamic): PID control u(t) = Kp·e + Ki·∫e·dτ + Kd·de/dt
      Vía B (Empirical): Logit bias ΔL_t collapses violating tokens

    Convergence guarantee (Theorem 1):
      V(e) = ½e²  →  V̇(e) ≈ -λe² < 0  ∀ e ≠ 0
      ⟹ asymptotic stability to mandate setpoint.
    """
    node_type: str = "mandate"
    name: str = ""
    constraint: str = ""                            # M(x) semantic predicate
    kp: float = 10.0                                # proportional gain
    ki: float = 0.1                                 # integral gain
    kd: float = 0.05                                # derivative gain
    tolerance: float = 0.01                         # convergence threshold ε
    max_steps: int = 50                             # PID iteration budget N
    on_violation: str = "coerce"                    # coerce | halt | retry


@dataclass(frozen=True)
class IRMandateApply(IRNode):
    """
    Compiled mandate application point — PID enforcement insertion.

    At runtime, the executor instantiates MandatePIDController
    with the referenced mandate's gains and runs the closed-loop
    control until convergence or budget exhaustion.
    """
    node_type: str = "mandate_apply"
    mandate_name: str = ""                          # reference to declared mandate
    target: str = ""                                # expression being mandated
    output_type: str = ""                           # result type after mandate


# ═══════════════════════════════════════════════════════════════════
#  LAMBDA DATA IR NODES — Epistemic State Vectors (§ΛD)
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IRLambdaData(IRNode):
    """
    Compiled ΛD specification — an Epistemic State Vector.

    Operationalizes the ΛD formalism from paper_lambda_data.md:

      ψ = ⟨T, V, E⟩  where  E = ⟨c, τ, ρ, δ⟩

    Invariants (compile-time enforced):
      1. Ontological Rigidity:  T ∈ O ∧ T ≠ ⊥
      4. Epistemic Bounding:   c ∈ [0,1], δ ∈ {axiomatic, observed, inferred, mutated}

    Theorem 5.1 (Epistemic Degradation):
      c_out ≤ min(c_in₁, …, c_inₙ)
      Compile-time enforcement for statically composed ΛD chains.

    JSON projection (lossy):
      π_JSON(ψ) = V  (discards T, E → information entropy increases)
    """
    node_type: str = "lambda_data"
    name: str = ""
    ontology: str = ""                              # T — ontological type
    certainty: float = 1.0                          # c ∈ [0,1]
    temporal_frame_start: str = ""                  # τ_start
    temporal_frame_end: str = ""                    # τ_end
    provenance: str = ""                            # ρ — EntityRef origin
    derivation: str = "observed"                    # δ ∈ Δ


@dataclass(frozen=True)
class IRLambdaDataApply(IRNode):
    """
    Compiled ΛD application point — epistemic binding insertion.

    At runtime, the executor binds the referenced ΛD's epistemic
    tensor to the target expression, propagating certainty through
    the pipeline per Theorem 5.1 (Epistemic Degradation).

    The projection mode determines fidelity:
      - Full ΛD:  ψ = ⟨T, V, E⟩  (lossless)
      - JSON:     π_JSON(ψ) = V   (lossy, information entropy ΔH > 0)
    """
    node_type: str = "lambda_data_apply"
    lambda_data_name: str = ""                      # reference to declared ΛD
    target: str = ""                                # expression being bound
    output_type: str = ""                           # result type after binding
