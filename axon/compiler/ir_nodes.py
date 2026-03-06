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


# ═══════════════════════════════════════════════════════════════════
#  DECLARATION IR NODES — resolved identities and configurations
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IRImport(IRNode):
    """
    A resolved import declaration.

    Example: import axon.anchors.{NoHallucination, NoBias}
    → module_path=("axon", "anchors"), names=("NoHallucination", "NoBias")
    """
    node_type: str = "import"
    module_path: tuple[str, ...] = ()
    names: tuple[str, ...] = ()


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
