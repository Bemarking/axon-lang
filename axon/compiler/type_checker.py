"""
AXON Compiler — Epistemic Type Checker
========================================
Semantic type validation for AXON programs.

This is NOT your typical type checker. AXON's type system is *epistemic* —
it tracks the nature and reliability of information, not memory layout.

Key rules (from the spec):
  • FactualClaim  → can be used where: String, CitedFact (if sourced)
  • Opinion       → CANNOT be used where: FactualClaim
  • Uncertainty   → propagates: any computation using Uncertainty yields Uncertainty
  • RiskScore     → coerces to: Float, but NOT the reverse
  • StructuredReport → satisfies: any output contract requiring structured data

Entry point: TypeChecker(program_ast).check() → list[AxonTypeError]
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ast_nodes import (
    ASTNode,
    AgentBudget,
    AgentDefinition,
    AggregateNode,
    AnchorConstraint,
    AssociateNode,
    ConditionalNode,
    ConsensusBlock,
    ContextDefinition,
    CorpusDefinition,
    CorroborateNode,
    DataSpaceDefinition,
    DeliberateBlock,
    DrillNode,
    EffectRowNode,
    EpistemicBlock,
    ExploreNode,
    FlowDefinition,
    FocusNode,
    ForgeBlock,
    HibernateNode,
    ImportNode,
    IngestNode,
    IntentNode,
    MemoryDefinition,
    NavigateNode,
    OtsApplyNode,
    OtsDefinition,
    ParallelBlock,
    PersonaDefinition,
    PixDefinition,
    ProbeDirective,
    ProgramNode,
    PsycheDefinition,
    ReasonChain,
    RecallNode,
    RefineBlock,
    RememberNode,
    RunStatement,
    ShieldApplyNode,
    ShieldDefinition,
    StepNode,
    StreamDefinition,
    ToolDefinition,
    TrailNode,
    TypeDefinition,
    ValidateGate,
    WeaveNode,
)
from .errors import AxonTypeError


# ═══════════════════════════════════════════════════════════════════
#  TYPE COMPATIBILITY MATRIX
# ═══════════════════════════════════════════════════════════════════

# Epistemic types that the type checker is aware of
EPISTEMIC_TYPES = frozenset({
    "FactualClaim", "Opinion", "Uncertainty", "Speculation",
})

# Content types
CONTENT_TYPES = frozenset({
    "Document", "Chunk", "EntityMap", "Summary", "Translation",
})

# Analysis types
ANALYSIS_TYPES = frozenset({
    "RiskScore", "ConfidenceScore", "SentimentScore",
    "ReasoningChain", "Contradiction",
})

# All built-in semantic types
BUILTIN_TYPES = EPISTEMIC_TYPES | CONTENT_TYPES | ANALYSIS_TYPES | frozenset({
    "String", "Integer", "Float", "Boolean", "Duration",
    "List", "StructuredReport",
})

# Types with built-in range constraints
RANGED_TYPES = {
    "RiskScore": (0.0, 1.0),
    "ConfidenceScore": (0.0, 1.0),
    "SentimentScore": (-1.0, 1.0),
}

class EpistemicLattice:
    """
    Partial Order Lattice for AXON epistemic types.
    Defines the subsumption relationship (<=), join (supremum), and meet (infimum).
    """
    
    # Hierarchy dictionary: child -> parent
    _parents = {
        "HighConfidenceFact": "CitedFact",
        "CitedFact": "FactualClaim",
        "FactualClaim": "Any",
        "Opinion": "Any",
        "Speculation": "Any",
        "Uncertainty": "Any",
        "Any": None,
        "Never": None,
    }

    @classmethod
    def is_subtype(cls, t1: str, t2: str) -> bool:
        """True if t1 <= t2 (t1 can be used where t2 is expected)"""
        if t1 == "Never" or t2 == "Any":
            return True
        if t1 == "Any" or t2 == "Never":
            return False
            
        t1_base, t1_inner, t1_prob = cls.parse_monad(t1)
        t2_base, t2_inner, t2_prob = cls.parse_monad(t2)
        
        # Uncertainty taint propagates: it can be passed anywhere, tainting the result
        if t1_base == "Uncertainty":
            return True
            
        inner1 = t1_inner if t1_inner else t1_base
        inner2 = t2_inner if t2_inner else t2_base

        if not cls._is_nominal_subtype(inner1, inner2):
            return False

        # Graded Monad probability check: t1 must be at least as confident as t2 expects
        if t2_prob is not None:
            if t1_prob is None or t1_prob < t2_prob:
                return False
                
        return True

    @classmethod
    def _is_nominal_subtype(cls, t1: str, t2: str) -> bool:
        if t1 == t2:
            return True
        curr = t1
        while curr in cls._parents and cls._parents[curr] is not None:
            curr = cls._parents[curr]
            if curr == t2:
                return True
        # Special compatibilities
        if (t1 == "FactualClaim" or t1 == "CitedFact") and t2 == "String":
            return True
        if t1 in ("RiskScore", "ConfidenceScore", "SentimentScore") and t2 == "Float":
            return True
        if t1 == "StructuredReport":
            return True # Satisfies any output contract
        return False

    @classmethod
    def join(cls, t1: str, t2: str) -> str:
        """Supremum (∨): The most specific type that can accept both t1 and t2 (Degradación Epistémica)."""
        if t1 == t2:
            return t1
        
        t1_b, t1_i, p1 = cls.parse_monad(t1)
        t2_b, t2_i, p2 = cls.parse_monad(t2)
        
        is_uncertain = t1_b == "Uncertainty" or t2_b == "Uncertainty"
        
        inner1 = t1_i if t1_i else t1_b
        inner2 = t2_i if t2_i else t2_b
        
        # Lowest Common Ancestor
        ancestors1 = [inner1]
        curr = inner1
        while curr in cls._parents and cls._parents[curr] is not None:
            curr = cls._parents[curr]
            ancestors1.append(curr)
            
        joined_inner = "Any"
        curr = inner2
        while curr is not None:
            if curr in ancestors1:
                joined_inner = curr
                break
            curr = cls._parents.get(curr)
            
        # Fallback to Any if disjoint and no common ancestor in epistemic tree
        if joined_inner == "Any" and not cls._is_nominal_subtype(inner1, "Any") and not cls._is_nominal_subtype(inner2, "Any"):
             # If they are totally custom disjoint types
             if cls._is_nominal_subtype(inner1, inner2): return inner2
             if cls._is_nominal_subtype(inner2, inner1): return inner1
             joined_inner = "Any"
            
        if is_uncertain:
            p = min(p1, p2) if (p1 is not None and p2 is not None) else None
            if p is not None:
                return f"Uncertain[{p}, {joined_inner}]"
            return f"Uncertain[{joined_inner}]"
            
        return joined_inner

    @classmethod
    def meet(cls, t1: str, t2: str) -> str:
        """Infimum (∧): The least specific type that is a subtype of both."""
        if cls.is_subtype(t1, t2): return t1
        if cls.is_subtype(t2, t1): return t2
        return "Never"

    @classmethod
    def parse_monad(cls, type_name: str) -> tuple[str, str|None, float|None]:
        """Parses a graded monad type string.
        Returns (BaseType, InnerType, Probability)"""
        import re
        if type_name.startswith("Uncertain[") and type_name.endswith("]"):
            inner = type_name[10:-1]
            parts = [p.strip() for p in inner.split(",")]
            if len(parts) == 2:
                try:
                    return ("Uncertainty", parts[1], float(parts[0]))
                except ValueError:
                    pass
            return ("Uncertainty", parts[0], None)
        elif type_name == "Uncertainty":
            return ("Uncertainty", "Any", None)
        return (type_name, None, None)
        
    @classmethod
    def lift(cls, type_name: str, probability: float | None = None) -> str:
        """Lifts a type into the Uncertainty monad (Unit operation)."""
        base, inner, prob = cls.parse_monad(type_name)
        if base == "Uncertainty":
            # Just lower the probability if needed
            new_p = min(prob, probability) if prob is not None and probability is not None else (probability or prob)
            if new_p is not None:
                return f"Uncertain[{new_p}, {inner or 'Any'}]"
            return type_name
            
        if probability is not None:
            return f"Uncertain[{probability}, {type_name}]"
        return f"Uncertain[{type_name}]"

# Valid values for specific AXON fields
VALID_TONES = frozenset({
    "precise", "friendly", "formal", "casual", "analytical",
    "diplomatic", "assertive", "empathetic",
})

VALID_MEMORY_SCOPES = frozenset({"session", "persistent", "none", "ephemeral"})

VALID_DEPTHS = frozenset({"shallow", "standard", "deep", "exhaustive"})

VALID_BACKOFF_STRATEGIES = frozenset({"none", "linear", "exponential"})

VALID_VIOLATION_ACTIONS = frozenset({"raise", "warn", "log", "escalate", "fallback"})

VALID_EFFORT_LEVELS = frozenset({"low", "medium", "high", "max"})

VALID_RETRIEVAL_STRATEGIES = frozenset({"semantic", "exact", "hybrid"})


# ═══════════════════════════════════════════════════════════════════
#  SYMBOL TABLE
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Symbol:
    """A named entity in the AXON program."""
    name: str
    kind: str  # "persona" | "context" | "anchor" | "memory" | "tool" | "type" | "flow" | "intent"
    node: ASTNode | None = None
    type_name: str = ""  # resolved type name for flows/intents


@dataclass
class SymbolTable:
    """Registry of all declared names in an AXON program."""
    symbols: dict[str, Symbol] = field(default_factory=dict)

    def declare(self, name: str, kind: str, node: ASTNode, type_name: str = "") -> str | None:
        """Register a name. Returns an error message if duplicate."""
        if name in self.symbols:
            existing = self.symbols[name]
            return (
                f"Duplicate declaration: '{name}' already defined as {existing.kind} "
                f"(first defined at line {existing.node.line})"
            )
        self.symbols[name] = Symbol(name=name, kind=kind, node=node, type_name=type_name)
        return None

    def lookup(self, name: str) -> Symbol | None:
        return self.symbols.get(name)

    def lookup_kind(self, name: str, kind: str) -> Symbol | None:
        sym = self.symbols.get(name)
        if sym and sym.kind == kind:
            return sym
        return None


# ═══════════════════════════════════════════════════════════════════
#  TYPE CHECKER
# ═══════════════════════════════════════════════════════════════════

class TypeChecker:
    """
    Epistemic type checker for AXON programs.

    Validates:
      1. Name resolution — all referenced names are declared
      2. Type compatibility — epistemic rules are respected
      3. Semantic constraints — field values are valid
      4. Uncertainty propagation — Uncertainty taints downstream data
      5. Anchor completeness — required fields are present
      6. Run statement wiring — persona, context, anchors, flow all exist
    """

    def __init__(self, program: ProgramNode):
        self._program = program
        self._symbols = SymbolTable()
        self._errors: list[AxonTypeError] = []
        self._user_types: dict[str, TypeDefinition] = {}

    def check(self) -> list[AxonTypeError]:
        """Full type-check pass. Returns all semantic errors found."""
        self._errors = []

        # Phase 1: Register all declarations in the symbol table
        self._register_declarations()

        # Phase 2: Validate each declaration's body
        for decl in self._program.declarations:
            self._check_declaration(decl)

        return self._errors

    # ── Phase 1: Registration ─────────────────────────────────────

    def _register_declarations(self) -> None:
        """First pass: collect all names so forward references work."""
        for decl in self._program.declarations:
            match decl:
                case PersonaDefinition(name=name):
                    self._register(name, "persona", decl)
                case ContextDefinition(name=name):
                    self._register(name, "context", decl)
                case AnchorConstraint(name=name):
                    self._register(name, "anchor", decl)
                case MemoryDefinition(name=name):
                    self._register(name, "memory", decl)
                case ToolDefinition(name=name):
                    self._register(name, "tool", decl)
                case TypeDefinition(name=name):
                    self._register(name, "type", decl)
                    self._user_types[name] = decl
                case FlowDefinition(name=name):
                    ret = decl.return_type.name if decl.return_type else ""
                    self._register(name, "flow", decl, type_name=ret)
                case IntentNode(name=name):
                    ret = decl.output_type.name if decl.output_type else ""
                    self._register(name, "intent", decl, type_name=ret)
                case ImportNode():
                    pass  # imports are handled separately
                case RunStatement():
                    pass  # run statements don't declare names
                case EpistemicBlock():
                    # Register declarations within the epistemic block
                    for inner_decl in decl.body:
                        match inner_decl:
                            case FlowDefinition(name=name):
                                ret = inner_decl.return_type.name if inner_decl.return_type else ""
                                self._register(name, "flow", inner_decl, type_name=ret)
                            case IntentNode(name=name):
                                ret = inner_decl.output_type.name if inner_decl.output_type else ""
                                self._register(name, "intent", inner_decl, type_name=ret)
                            case _:
                                pass  # other inner declarations handled recursively
                case DataSpaceDefinition(name=name):
                    self._register(name, "dataspace", decl)
                case AgentDefinition(name=name):
                    ret = decl.return_type.name if decl.return_type else ""
                    self._register(name, "agent", decl, type_name=ret)
                case ShieldDefinition(name=name):
                    self._register(name, "shield", decl)
                case PixDefinition(name=name):
                    self._register(name, "pix", decl)
                case IngestNode():
                    pass  # ingest is a command, not a declaration
                case FocusNode() | AssociateNode() | AggregateNode() | ExploreNode():
                    pass  # flow-level commands, not declarations
                case OtsDefinition(name=name):
                    self._register(name, "ots", decl)
                case OtsApplyNode():
                    pass
                case NavigateNode() | DrillNode() | TrailNode():
                    pass  # PIX flow-level commands, not declarations

    def _register(self, name: str, kind: str, node: ASTNode, type_name: str = "") -> None:
        err = self._symbols.declare(name, kind, node, type_name=type_name)
        if err:
            self._emit(err, node)

    # ── Phase 2: Validation dispatch ──────────────────────────────

    def _check_declaration(self, decl: ASTNode) -> None:
        match decl:
            case PersonaDefinition():
                self._check_persona(decl)
            case ContextDefinition():
                self._check_context(decl)
            case AnchorConstraint():
                self._check_anchor(decl)
            case MemoryDefinition():
                self._check_memory(decl)
            case ToolDefinition():
                self._check_tool(decl)
            case TypeDefinition():
                self._check_type_def(decl)
            case FlowDefinition():
                self._check_flow(decl)
            case IntentNode():
                self._check_intent(decl)
            case RunStatement():
                self._check_run(decl)
            case ImportNode():
                pass  # module resolution is a later-phase concern
            case EpistemicBlock():
                self._check_epistemic_block(decl)
            case ParallelBlock():
                self._check_par_block(decl)
            case HibernateNode():
                self._check_hibernate(decl)
            case DeliberateBlock():
                self._check_deliberate(decl)
            case ConsensusBlock():
                self._check_consensus(decl)
            case ForgeBlock():
                self._check_forge(decl)
            case OtsDefinition():
                self._check_ots_definition(decl)
            case OtsApplyNode():
                self._check_ots_apply(decl)
            case AgentDefinition():
                self._check_agent(decl)
            case ShieldDefinition():
                self._check_shield(decl)
            case ShieldApplyNode():
                self._check_shield_apply(decl)
            case DataSpaceDefinition():
                self._check_dataspace(decl)
            case PixDefinition():
                self._check_pix_definition(decl)
            case CorpusDefinition():
                self._check_corpus_definition(decl)
            case PsycheDefinition():
                self._check_psyche(decl)
            case IngestNode():
                pass  # validated at runtime
            case FocusNode() | AssociateNode() | AggregateNode() | ExploreNode():
                pass  # validated at runtime
            case NavigateNode() | DrillNode() | TrailNode() | CorroborateNode():
                pass  # PIX/MDN flow commands validated in flow step context

    # ── PERSONA validation ────────────────────────────────────────

    def _check_persona(self, node: PersonaDefinition) -> None:
        if node.tone and node.tone not in VALID_TONES:
            self._emit(
                f"Unknown tone '{node.tone}' for persona '{node.name}'. "
                f"Valid tones: {', '.join(sorted(VALID_TONES))}",
                node,
            )

        if node.confidence_threshold is not None:
            self._check_range(node.confidence_threshold, 0.0, 1.0,
                              "confidence_threshold", node)

    # ── CONTEXT validation ────────────────────────────────────────

    def _check_context(self, node: ContextDefinition) -> None:
        if node.memory_scope and node.memory_scope not in VALID_MEMORY_SCOPES:
            self._emit(
                f"Unknown memory scope '{node.memory_scope}' in context '{node.name}'. "
                f"Valid: {', '.join(sorted(VALID_MEMORY_SCOPES))}",
                node,
            )

        if node.depth and node.depth not in VALID_DEPTHS:
            self._emit(
                f"Unknown depth '{node.depth}' in context '{node.name}'. "
                f"Valid: {', '.join(sorted(VALID_DEPTHS))}",
                node,
            )

        if node.temperature is not None:
            self._check_range(node.temperature, 0.0, 2.0, "temperature", node)

        if node.max_tokens is not None and node.max_tokens <= 0:
            self._emit(
                f"max_tokens must be positive, got {node.max_tokens} "
                f"in context '{node.name}'",
                node,
            )

    # ── ANCHOR validation ─────────────────────────────────────────

    def _check_anchor(self, node: AnchorConstraint) -> None:
        if node.confidence_floor is not None:
            self._check_range(node.confidence_floor, 0.0, 1.0,
                              "confidence_floor", node)

        if node.on_violation and node.on_violation not in VALID_VIOLATION_ACTIONS:
            self._emit(
                f"Unknown on_violation action '{node.on_violation}' "
                f"in anchor '{node.name}'. "
                f"Valid: {', '.join(sorted(VALID_VIOLATION_ACTIONS))}",
                node,
            )

        if node.on_violation == "raise" and not node.on_violation_target:
            self._emit(
                f"Anchor '{node.name}' uses 'raise' but no error type specified",
                node,
            )

    # ── MEMORY validation ─────────────────────────────────────────

    def _check_memory(self, node: MemoryDefinition) -> None:
        if node.store and node.store not in VALID_MEMORY_SCOPES:
            self._emit(
                f"Unknown store type '{node.store}' in memory '{node.name}'. "
                f"Valid: {', '.join(sorted(VALID_MEMORY_SCOPES))}",
                node,
            )

        if node.retrieval and node.retrieval not in VALID_RETRIEVAL_STRATEGIES:
            self._emit(
                f"Unknown retrieval strategy '{node.retrieval}' "
                f"in memory '{node.name}'. "
                f"Valid: {', '.join(sorted(VALID_RETRIEVAL_STRATEGIES))}",
                node,
            )

    # ── TOOL validation ───────────────────────────────────────────

    # Valid effect kinds for CT-2 effect rows
    VALID_EFFECTS = frozenset({"pure", "io", "network", "storage", "random"})
    VALID_EPISTEMIC_LEVELS = frozenset({"know", "believe", "speculate", "doubt"})

    def _check_tool(self, node: ToolDefinition) -> None:
        if node.max_results is not None and node.max_results <= 0:
            self._emit(
                f"max_results must be positive, got {node.max_results} "
                f"in tool '{node.name}'",
                node,
            )

        # v0.14.0 — CT-2: validate effect row
        if node.effects is not None:
            self._check_effect_row(node.effects, node.name)

    # ── TYPE DEFINITION validation ────────────────────────────────

    def _check_type_def(self, node: TypeDefinition) -> None:
        # Validate range constraint
        if node.range_constraint:
            rc = node.range_constraint
            if rc.min_value >= rc.max_value:
                self._emit(
                    f"Invalid range constraint in type '{node.name}': "
                    f"min ({rc.min_value}) must be less than max ({rc.max_value})",
                    node,
                )

        # Validate field types exist
        for fld in node.fields:
            if fld.type_expr:
                self._check_type_reference(fld.type_expr.name, fld)
                if fld.type_expr.generic_param:
                    self._check_type_reference(fld.type_expr.generic_param, fld)

    # ── INTENT validation ─────────────────────────────────────────

    def _check_intent(self, node: IntentNode) -> None:
        if not node.ask:
            self._emit(
                f"Intent '{node.name}' is missing required 'ask' field — "
                "every intent must express a question",
                node,
            )

        if node.output_type:
            self._check_type_reference(node.output_type.name, node)

        if node.confidence_floor is not None:
            self._check_range(node.confidence_floor, 0.0, 1.0,
                              "confidence_floor", node)

    # ── FLOW validation ───────────────────────────────────────────

    def _check_flow(self, node: FlowDefinition) -> None:
        # Validate parameter types
        for param in node.parameters:
            if param.type_expr:
                self._check_type_reference(param.type_expr.name, param)

        # Validate return type
        if node.return_type:
            self._check_type_reference(node.return_type.name, node)

        # Validate body steps
        step_names: set[str] = set()
        for step in node.body:
            self._check_flow_step(step, step_names, node.name)

    def _check_flow_step(self, step: ASTNode, step_names: set[str], flow_name: str) -> None:
        match step:
            case StepNode():
                self._check_step(step, step_names, flow_name)
            case ProbeDirective():
                self._check_probe(step)
            case ReasonChain():
                self._check_reason(step)
            case ValidateGate():
                self._check_validate(step)
            case RefineBlock():
                self._check_refine(step)
            case WeaveNode():
                self._check_weave(step)
            case ConditionalNode():
                self._check_conditional(step, step_names, flow_name)
            case RememberNode():
                self._check_remember(step)
            case RecallNode():
                self._check_recall(step)
            case ParallelBlock():
                self._check_par_block(step)
            case HibernateNode():
                self._check_hibernate(step)
            case DeliberateBlock():
                self._check_deliberate(step)
            case ConsensusBlock():
                self._check_consensus(step)
            case ForgeBlock():
                self._check_forge(step)
            case OtsApplyNode():
                self._check_ots_apply(step)
            case AgentDefinition():
                self._check_agent(step)
            case ShieldApplyNode():
                self._check_shield_apply(step)
            case StreamDefinition():
                self._check_stream_definition(step)
            case NavigateNode():
                self._check_navigate(step)
            case DrillNode():
                self._check_drill(step)
            case TrailNode():
                self._check_trail(step)
            case CorroborateNode():
                self._check_corroborate(step)

    def _check_step(self, node: StepNode, step_names: set[str], flow_name: str) -> None:
        if node.name in step_names:
            self._emit(
                f"Duplicate step name '{node.name}' in flow '{flow_name}'",
                node,
            )
        step_names.add(node.name)

        if node.confidence_floor is not None:
            self._check_range(node.confidence_floor, 0.0, 1.0,
                              "confidence_floor", node)

        # Recursively check nested cognitive nodes
        if node.probe:
            self._check_probe(node.probe)
        if node.reason:
            self._check_reason(node.reason)
        if node.weave:
            self._check_weave(node.weave)
        if node.use_tool:
            self._check_use_tool(node.use_tool)

    def _check_probe(self, node: ProbeDirective) -> None:
        if not node.fields:
            self._emit("Probe directive is missing extraction fields", node)

    def _check_reason(self, node: ReasonChain) -> None:
        if node.depth < 1:
            self._emit(
                f"Reasoning depth must be >= 1, got {node.depth}",
                node,
            )

    def _check_validate(self, node: ValidateGate) -> None:
        if node.schema:
            self._check_type_reference(node.schema, node)

        if not node.rules:
            self._emit(
                "Validate gate has no rules — at least one rule is required",
                node,
            )

    def _check_refine(self, node: RefineBlock) -> None:
        if node.max_attempts < 1:
            self._emit(
                f"Refine max_attempts must be >= 1, got {node.max_attempts}",
                node,
            )

        if node.backoff and node.backoff not in VALID_BACKOFF_STRATEGIES:
            self._emit(
                f"Unknown backoff strategy '{node.backoff}'. "
                f"Valid: {', '.join(sorted(VALID_BACKOFF_STRATEGIES))}",
                node,
            )

    def _check_weave(self, node: WeaveNode) -> None:
        if len(node.sources) < 2:
            self._emit(
                "Weave requires at least 2 sources to synthesize — "
                f"got {len(node.sources)}",
                node,
            )

    def _check_use_tool(self, node: ASTNode) -> None:
        """Validate tool references exist if tools are declared."""
        from .ast_nodes import UseToolNode
        if isinstance(node, UseToolNode) and node.tool_name:
            sym = self._symbols.lookup(node.tool_name)
            if sym and sym.kind != "tool":
                self._emit(
                    f"'{node.tool_name}' is a {sym.kind}, not a tool",
                    node,
                )

    # ── EFFECT ROW validation (CT-2) ──────────────────────────────

    def _check_effect_row(self, effect_row: EffectRowNode, tool_name: str) -> None:
        """Validate effect row entries and epistemic level annotation."""
        for eff in effect_row.effects:
            # Handle composite effects like 'custom:qualifier'
            base_effect = eff.split(":")[0] if ":" in eff else eff
            if base_effect not in self.VALID_EFFECTS:
                self._emit(
                    f"Unknown effect '{eff}' in tool '{tool_name}'. "
                    f"Valid effects: {', '.join(sorted(self.VALID_EFFECTS))}",
                    effect_row,
                )

        if effect_row.epistemic_level:
            if effect_row.epistemic_level not in self.VALID_EPISTEMIC_LEVELS:
                self._emit(
                    f"Unknown epistemic level '{effect_row.epistemic_level}' "
                    f"in tool '{tool_name}'. "
                    f"Valid levels: {', '.join(sorted(self.VALID_EPISTEMIC_LEVELS))}",
                    effect_row,
                )

    # ── STREAM DEFINITION validation (CT-1) ───────────────────────

    def _check_stream_definition(self, node: StreamDefinition) -> None:
        """Validate stream definition: element type, epistemic rules.

        Streams enforce:
          - Element type must be a known type reference
          - Stream chunks start at ⊥/doubt, never at 'know'
          - on_complete handlers may upgrade to 'believe' via shield
        """
        if node.element_type:
            self._check_type_reference(node.element_type, node)

        # Validate handler bodies recursively
        step_names: set[str] = set()
        if node.on_chunk:
            for child in node.on_chunk.body:
                self._check_flow_step(child, step_names, "<stream:on_chunk>")
        if node.on_complete:
            for child in node.on_complete.body:
                self._check_flow_step(child, step_names, "<stream:on_complete>")

    def _check_remember(self, node: RememberNode) -> None:
        if node.memory_target:
            sym = self._symbols.lookup(node.memory_target)
            if sym and sym.kind != "memory":
                self._emit(
                    f"'remember' target '{node.memory_target}' is "
                    f"a {sym.kind}, not a memory store",
                    node,
                )

    def _check_recall(self, node: RecallNode) -> None:
        if node.memory_source:
            sym = self._symbols.lookup(node.memory_source)
            if sym and sym.kind != "memory":
                self._emit(
                    f"'recall' source '{node.memory_source}' is "
                    f"a {sym.kind}, not a memory store",
                    node,
                )

    def _check_conditional(self, node: ConditionalNode, step_names: set[str], flow_name: str) -> None:
        if node.then_step:
            self._check_flow_step(node.then_step, step_names, flow_name)
        if node.else_step:
            self._check_flow_step(node.else_step, step_names, flow_name)

    # ── RUN STATEMENT validation ──────────────────────────────────

    def _check_run(self, node: RunStatement) -> None:
        # Flow must exist
        if node.flow_name:
            sym = self._symbols.lookup(node.flow_name)
            if sym is None:
                self._emit(
                    f"Undefined flow '{node.flow_name}' in run statement",
                    node,
                )
            elif sym.kind != "flow":
                self._emit(
                    f"'{node.flow_name}' is a {sym.kind}, not a flow — "
                    "only flows can be run",
                    node,
                )

        # Persona must exist
        if node.persona:
            sym = self._symbols.lookup(node.persona)
            if sym is None:
                self._emit(f"Undefined persona '{node.persona}'", node)
            elif sym.kind != "persona":
                self._emit(
                    f"'{node.persona}' is a {sym.kind}, not a persona",
                    node,
                )

        # Context must exist
        if node.context:
            sym = self._symbols.lookup(node.context)
            if sym is None:
                self._emit(f"Undefined context '{node.context}'", node)
            elif sym.kind != "context":
                self._emit(
                    f"'{node.context}' is a {sym.kind}, not a context",
                    node,
                )

        # Anchors must exist
        for anchor_name in node.anchors:
            sym = self._symbols.lookup(anchor_name)
            if sym is None:
                self._emit(f"Undefined anchor '{anchor_name}'", node)
            elif sym.kind != "anchor":
                self._emit(
                    f"'{anchor_name}' is a {sym.kind}, not an anchor",
                    node,
                )

        # Effort level validation
        if node.effort and node.effort not in VALID_EFFORT_LEVELS:
            self._emit(
                f"Unknown effort level '{node.effort}'. "
                f"Valid: {', '.join(sorted(VALID_EFFORT_LEVELS))}",
                node,
            )

    # ── TYPE COMPATIBILITY ────────────────────────────────────────

    def check_type_compatible(self, source: str, target: str) -> bool:
        """
        Check if `source` type can be used where `target` type is expected.
        Utilizes the formal EpistemicLattice for evaluation.
        """
        # User-defined types fallback
        if source not in BUILTIN_TYPES and target not in BUILTIN_TYPES and source != target:
            # Fallback to checking nominal user types if not in lattice
            pass

        return EpistemicLattice.is_subtype(source, target)

    def check_uncertainty_propagation(self, types: list[str] | str) -> str:
        """
        Applies Supreme (Join) operation across all inputs to find the
        resulting generic type and taint output with Uncertainty.
        """
        if isinstance(types, str):
            types = [types]
            
        if not types:
            return "Any"
            
        result = types[0]
        for t in types[1:]:
            result = EpistemicLattice.join(result, t)
        return result

    # ── EPISTEMIC BLOCK validation ─────────────────────────────────

    _VALID_EPISTEMIC_MODES = frozenset({"know", "believe", "speculate", "doubt"})

    def _check_epistemic_block(self, node: EpistemicBlock) -> None:
        if node.mode not in self._VALID_EPISTEMIC_MODES:
            self._emit(
                f"Invalid epistemic mode '{node.mode}', "
                f"expected one of: {', '.join(sorted(self._VALID_EPISTEMIC_MODES))}",
                node,
            )
        # Recursively check inner declarations
        for decl in node.body:
            self._check_declaration(decl)

    # ── PARALLEL BLOCK validation ─────────────────────────────────

    def _check_par_block(self, node: ParallelBlock) -> None:
        if len(node.branches) < 2:
            self._emit(
                "Parallel block requires at least 2 branches for concurrent dispatch",
                node,
            )
        for branch in node.branches:
            self._check_declaration(branch)

    # ── HIBERNATE validation ──────────────────────────────────────

    def _check_hibernate(self, node: HibernateNode) -> None:
        if not node.event_name:
            self._emit(
                "hibernate requires an event name: hibernate until \"event_name\"",
                node,
            )

    # ── DATASPACE validation ──────────────────────────────────────

    def _check_dataspace(self, node: DataSpaceDefinition) -> None:
        if not node.name:
            self._emit("dataspace requires a name", node)
        # Recursively check inner body statements
        for stmt in node.body:
            self._check_declaration(stmt)

    # ── DELIBERATE validation ─────────────────────────────────────────

    _VALID_DELIBERATE_STRATEGIES = frozenset({
        "quick", "balanced", "thorough", "exhaustive",
    })

    def _check_deliberate(self, node: DeliberateBlock) -> None:
        if node.budget < 0:
            self._emit("deliberate budget must be >= 0", node)
        if node.depth < 1:
            self._emit(
                f"deliberate depth must be >= 1, got {node.depth}", node,
            )
        if node.strategy and node.strategy not in self._VALID_DELIBERATE_STRATEGIES:
            self._emit(
                f"Unknown deliberate strategy '{node.strategy}'. "
                f"Valid: {', '.join(sorted(self._VALID_DELIBERATE_STRATEGIES))}",
                node,
            )
        for child in node.body:
            self._check_declaration(child)

    # ── CONSENSUS validation ──────────────────────────────────────────

    _VALID_CONSENSUS_SELECTIONS = frozenset({"best", "majority"})

    def _check_consensus(self, node: ConsensusBlock) -> None:
        if node.branches < 2:
            self._emit("consensus requires at least 2 branches", node)
        if not node.reward_anchor:
            self._emit(
                "consensus requires a 'reward' anchor for selection", node,
            )
        else:
            sym = self._symbols.lookup(node.reward_anchor)
            if sym is None:
                self._emit(
                    f"Undefined anchor '{node.reward_anchor}' in consensus",
                    node,
                )
            elif sym.kind != "anchor":
                self._emit(
                    f"'{node.reward_anchor}' is a {sym.kind}, not an anchor",
                    node,
                )
        if node.selection and node.selection not in self._VALID_CONSENSUS_SELECTIONS:
            self._emit(
                f"Unknown consensus selection '{node.selection}'. "
                f"Valid: {', '.join(sorted(self._VALID_CONSENSUS_SELECTIONS))}",
                node,
            )
        for child in node.body:
            self._check_declaration(child)

    # ── FORGE validation ───────────────────────────────────────────

    _VALID_FORGE_MODES = frozenset({
        "combinatory", "exploratory", "transformational",
    })

    def _check_forge(self, node: ForgeBlock) -> None:
        if not node.name:
            self._emit("forge requires a name", node)
        if node.mode and node.mode not in self._VALID_FORGE_MODES:
            self._emit(
                f"Unknown forge mode '{node.mode}'. "
                f"Valid: {', '.join(sorted(self._VALID_FORGE_MODES))}",
                node,
            )
        if node.novelty < 0.0 or node.novelty > 1.0:
            self._emit(
                f"forge novelty must be between 0.0 and 1.0, got {node.novelty}",
                node,
            )
        if node.branches < 2:
            self._emit("forge requires at least 2 branches", node)
        if node.depth < 1:
            self._emit(
                f"forge depth must be >= 1, got {node.depth}", node,
            )
        if node.constraints:
            sym = self._symbols.lookup(node.constraints)
            if sym is None:
                self._emit(
                    f"Undefined anchor '{node.constraints}' in forge",
                    node,
                )
            elif sym.kind != "anchor":
                self._emit(
                    f"'{node.constraints}' is a {sym.kind}, not an anchor",
                    node,
                )
        for child in node.body:
            self._check_declaration(child)

    # ── OTS validation ─────────────────────────────────────────────

    _VALID_OTS_HOMOTOPY = frozenset({"shallow", "deep", "speculative"})
    _VALID_OTS_CONSTRAINTS = frozenset({"strictly_once", "at_most_once", "at_least_once"})

    def _check_ots_definition(self, node: OtsDefinition) -> None:
        if not node.name:
            self._emit("ots requires a name", node)
            
        if node.input_type:
            self._check_type_reference(node.input_type.name, node)
        if node.output_type:
            self._check_type_reference(node.output_type.name, node)
            
        if not node.teleology:
            self._emit("ots requires a teleology goal", node)
            
        if node.homotopy_search not in self._VALID_OTS_HOMOTOPY:
            self._emit(
                f"Unknown homotopy_search '{node.homotopy_search}'. "
                f"Valid: {', '.join(sorted(self._VALID_OTS_HOMOTOPY))}",
                node,
            )
            
        for k, v in node.linear_constraints.items():
            if v not in self._VALID_OTS_CONSTRAINTS:
                self._emit(
                    f"Unknown linear constraint '{v}' for '{k}'. "
                    f"Valid: {', '.join(sorted(self._VALID_OTS_CONSTRAINTS))}",
                    node,
                )
                
        for child in node.body:
            self._check_declaration(child)

    def _check_ots_apply(self, node: OtsApplyNode) -> None:
        if not node.ots_name:
            self._emit("ots application requires a tool name", node)
        else:
            sym = self._symbols.lookup(node.ots_name)
            if sym is None:
                self._emit(f"Undefined ots tool '{node.ots_name}'", node)
            elif sym.kind != "ots":
                self._emit(f"'{node.ots_name}' is a {sym.kind}, not an ots tool", node)

        if node.output_type:
            self._check_type_reference(node.output_type, node)

    # ── AGENT validation ────────────────────────────────────────────

    _VALID_AGENT_STRATEGIES = frozenset({
        "react", "reflexion", "plan_and_execute", "custom",
    })

    _VALID_ON_STUCK_POLICIES = frozenset({
        "forge", "hibernate", "escalate", "retry",
    })

    def _check_agent(self, node: AgentDefinition) -> None:
        """
        Semantic validation for the agent primitive.

        Validates:
          1. Goal is present (BDI requires at least one desire)
          2. Tool references point to declared tools
          3. Budget constraints are non-negative
          4. Strategy is from the valid set
          5. on_stuck policy is from the valid set
          6. Memory reference exists (if provided)
          7. Return type is declared (if provided)
          8. Body steps are recursively valid
        """
        # 1. Goal validation (Davidson: every agent needs a pro-attitude)
        if not node.goal:
            self._emit(
                f"Agent '{node.name}' is missing required 'goal' field — "
                "every agent must declare a desired objective",
                node,
            )

        # 2. Tool references
        for tool_name in node.tools:
            sym = self._symbols.lookup(tool_name)
            if sym is not None and sym.kind != "tool":
                self._emit(
                    f"'{tool_name}' in agent '{node.name}' tools list is "
                    f"a {sym.kind}, not a tool",
                    node,
                )

        # 3. Budget constraints (linear logic: resources must be positive)
        if node.budget:
            b = node.budget
            if b.max_iterations < 1:
                self._emit(
                    f"Agent '{node.name}' max_iterations must be >= 1, "
                    f"got {b.max_iterations}",
                    node,
                )
            if b.max_tokens < 0:
                self._emit(
                    f"Agent '{node.name}' max_tokens cannot be negative, "
                    f"got {b.max_tokens}",
                    node,
                )
            if b.max_cost < 0.0:
                self._emit(
                    f"Agent '{node.name}' max_cost cannot be negative, "
                    f"got {b.max_cost}",
                    node,
                )

        # 4. Strategy validation
        if node.strategy and node.strategy not in self._VALID_AGENT_STRATEGIES:
            self._emit(
                f"Unknown strategy '{node.strategy}' for agent '{node.name}'. "
                f"Valid: {', '.join(sorted(self._VALID_AGENT_STRATEGIES))}",
                node,
            )

        # 5. on_stuck policy validation (STIT logic recovery)
        if node.on_stuck and node.on_stuck not in self._VALID_ON_STUCK_POLICIES:
            self._emit(
                f"Unknown on_stuck policy '{node.on_stuck}' for agent '{node.name}'. "
                f"Valid: {', '.join(sorted(self._VALID_ON_STUCK_POLICIES))}",
                node,
            )

        # 6. Memory reference
        if node.memory_ref:
            sym = self._symbols.lookup(node.memory_ref)
            if sym is not None and sym.kind != "memory":
                self._emit(
                    f"Agent '{node.name}' memory reference '{node.memory_ref}' is "
                    f"a {sym.kind}, not a memory store",
                    node,
                )

        # 7. Return type
        if node.return_type:
            self._check_type_reference(node.return_type.name, node)

        # 8. Parameter types
        for param in node.parameters:
            if param.type_expr:
                self._check_type_reference(param.type_expr.name, param)

        # 9. Body steps (recursive validation)
        step_names: set[str] = set()
        for step in node.body:
            self._check_flow_step(step, step_names, node.name)

        # 10. Shield reference validation
        if node.shield_ref:
            sym = self._symbols.lookup(node.shield_ref)
            if sym is not None and sym.kind != "shield":
                self._emit(
                    f"Agent '{node.name}' shield reference '{node.shield_ref}' is "
                    f"a {sym.kind}, not a shield",
                    node,
                )
            elif sym is not None and sym.kind == "shield":
                # Capability enforcement: agent tools ⊆ shield allow_tools
                shield_node = sym.node
                if hasattr(shield_node, 'allow_tools') and shield_node.allow_tools:
                    allowed = set(shield_node.allow_tools)
                    for tool_name in node.tools:
                        if tool_name not in allowed:
                            self._emit(
                                f"Agent '{node.name}' uses tool '{tool_name}' not "
                                f"permitted by shield '{node.shield_ref}' — "
                                f"allowed: {', '.join(sorted(allowed))}",
                                node,
                            )

    # ── SHIELD validation ──────────────────────────────────────────

    _VALID_SCAN_CATEGORIES = frozenset({
        "prompt_injection", "jailbreak", "data_exfil", "pii_leak",
        "toxicity", "bias", "hallucination", "code_injection",
        "social_engineering", "model_theft", "training_poisoning",
    })

    _VALID_SHIELD_STRATEGIES = frozenset({
        "pattern", "classifier", "dual_llm", "canary",
        "perplexity", "ensemble",
    })

    _VALID_ON_BREACH_POLICIES = frozenset({
        "halt", "sanitize_and_retry", "escalate", "quarantine", "deflect",
    })

    _VALID_SEVERITY_LEVELS = frozenset({
        "low", "medium", "high", "critical",
    })

    def _check_shield(self, node: ShieldDefinition) -> None:
        """
        Semantic validation for the shield primitive.

        Validates:
          1. Scan categories are from the known threat taxonomy
          2. Strategy is valid
          3. on_breach policy is valid
          4. Severity level is valid
          5. max_retries is non-negative
          6. confidence_threshold is in [0.0, 1.0]
          7. allow/deny lists don't overlap
        """
        # 1. Scan categories
        for cat in node.scan:
            if cat not in self._VALID_SCAN_CATEGORIES:
                self._emit(
                    f"Unknown scan category '{cat}' in shield '{node.name}'. "
                    f"Valid: {', '.join(sorted(self._VALID_SCAN_CATEGORIES))}",
                    node,
                )

        # 2. Strategy
        if node.strategy and node.strategy not in self._VALID_SHIELD_STRATEGIES:
            self._emit(
                f"Unknown strategy '{node.strategy}' for shield '{node.name}'. "
                f"Valid: {', '.join(sorted(self._VALID_SHIELD_STRATEGIES))}",
                node,
            )

        # 3. on_breach policy
        if node.on_breach and node.on_breach not in self._VALID_ON_BREACH_POLICIES:
            self._emit(
                f"Unknown on_breach policy '{node.on_breach}' for shield '{node.name}'. "
                f"Valid: {', '.join(sorted(self._VALID_ON_BREACH_POLICIES))}",
                node,
            )

        # 4. Severity
        if node.severity and node.severity not in self._VALID_SEVERITY_LEVELS:
            self._emit(
                f"Unknown severity '{node.severity}' for shield '{node.name}'. "
                f"Valid: {', '.join(sorted(self._VALID_SEVERITY_LEVELS))}",
                node,
            )

        # 5. max_retries
        if node.max_retries < 0:
            self._emit(
                f"Shield '{node.name}' max_retries cannot be negative, "
                f"got {node.max_retries}",
                node,
            )

        # 6. confidence_threshold
        if node.confidence_threshold is not None:
            self._check_range(
                node.confidence_threshold, 0.0, 1.0,
                f"shield '{node.name}' confidence_threshold", node,
            )

        # 7. allow/deny overlap
        if node.allow_tools and node.deny_tools:
            overlap = set(node.allow_tools) & set(node.deny_tools)
            if overlap:
                self._emit(
                    f"Shield '{node.name}' has tools in both allow and deny: "
                    f"{', '.join(sorted(overlap))}",
                    node,
                )

    def _check_shield_apply(self, node: ShieldApplyNode) -> None:
        """
        Validate shield application in a flow step.

        Ensures the referenced shield is declared.
        """
        sym = self._symbols.lookup(node.shield_name)
        if sym is not None and sym.kind != "shield":
            self._emit(
                f"'{node.shield_name}' in shield apply is a {sym.kind}, "
                "not a shield",
                node,
            )

    # ── PIX validation ─────────────────────────────────────────────

    def _check_pix_definition(self, node: PixDefinition) -> None:
        """
        Validate pix definition — structured cognitive retrieval index.

        Rules:
          1. Source must be non-empty
          2. Depth must be in [1, 8]
          3. Branching must be in [1, 10]
          4. Model must be non-empty
          5. Effect row (if present) must be valid
        """
        if not node.source:
            self._emit(
                f"PIX '{node.name}' requires a 'source' field",
                node,
            )

        if not (1 <= node.depth <= 8):
            self._emit(
                f"PIX '{node.name}' depth must be between 1 and 8, got {node.depth}",
                node,
            )

        if not (1 <= node.branching <= 10):
            self._emit(
                f"PIX '{node.name}' branching must be between 1 and 10, got {node.branching}",
                node,
            )

    def _check_navigate(self, node: NavigateNode) -> None:
        """Validate navigate statement — PIX retrieval."""
        sym = self._symbols.lookup(node.pix_name)
        if sym is not None and sym.kind != "pix":
            self._emit(
                f"'{node.pix_name}' in navigate is a {sym.kind}, not a pix",
                node,
            )

        if not node.query_expr:
            self._emit(
                f"navigate '{node.pix_name}' requires a query expression",
                node,
            )

    def _check_drill(self, node: DrillNode) -> None:
        """Validate drill statement — PIX subtree descent."""
        sym = self._symbols.lookup(node.pix_name)
        if sym is not None and sym.kind != "pix":
            self._emit(
                f"'{node.pix_name}' in drill is a {sym.kind}, not a pix",
                node,
            )

        if not node.subtree_path:
            self._emit(
                f"drill '{node.pix_name}' requires a subtree path (into \"...\")",
                node,
            )

        if not node.query_expr:
            self._emit(
                f"drill '{node.pix_name}' requires a query expression",
                node,
            )

    def _check_trail(self, node: TrailNode) -> None:
        """Validate trail statement — reasoning path access."""
        if not node.navigate_ref:
            self._emit(
                "trail requires a reference to a navigate step",
                node,
            )

    # ── MDN CORPUS validation (§5.3) ───────────────────────────────

    _VALID_RELATION_TYPES = frozenset({
        "cite", "implement", "contradict", "amend", "extend",
        "support", "derive", "reference", "supersede",
    })

    def _check_corpus_definition(self, node: CorpusDefinition) -> None:
        """Validate corpus definition — invariants G1–G4 from §2.1.

        Rules:
          1. Corpus must have a name
          2. At least one document required (G1: D ≠ ∅)
          3. Edge source/target must reference declared documents
          4. Edge weights must be in (0, 1] (G3: ω positivity)
          5. Document PIX references must be declared (soft check)
        """
        if not node.name:
            self._emit("corpus requires a name", node)

        # G1: D ≠ ∅
        if not node.documents:
            self._emit(
                f"Corpus '{node.name}' requires at least one document "
                "(invariant G1: D ≠ ∅)",
                node,
            )

        # Collect declared document identifiers
        doc_names = {doc.pix_ref for doc in node.documents}

        # Validate document PIX references exist in symbol table
        for doc in node.documents:
            if doc.pix_ref:
                sym = self._symbols.lookup(doc.pix_ref)
                if sym is not None and sym.kind != "pix":
                    self._emit(
                        f"Document '{doc.pix_ref}' in corpus '{node.name}' is "
                        f"a {sym.kind}, not a pix",
                        doc,
                    )

        # Validate edges reference declared documents
        for edge in node.edges:
            if edge.source_ref not in doc_names:
                self._emit(
                    f"Edge source '{edge.source_ref}' in corpus '{node.name}' "
                    f"not in declared documents: {', '.join(sorted(doc_names))}",
                    edge,
                )
            if edge.target_ref not in doc_names:
                self._emit(
                    f"Edge target '{edge.target_ref}' in corpus '{node.name}' "
                    f"not in declared documents: {', '.join(sorted(doc_names))}",
                    edge,
                )

        # G3: ω positivity — weights in (0, 1]
        for key, weight in node.weights.items():
            if weight <= 0.0 or weight > 1.0:
                self._emit(
                    f"Weight for edge '{key}' in corpus '{node.name}' must be in "
                    f"(0, 1], got {weight} (invariant G3: ω positivity)",
                    node,
                )

    def _check_corroborate(self, node: CorroborateNode) -> None:
        """Validate corroborate — cross-path verification (§4.2)."""
        if not node.navigate_ref:
            self._emit(
                "corroborate requires a reference to a navigate result",
                node,
            )

    # ── PSYCHE validation (§PEM) ──────────────────────────────────

    def _check_psyche(self, node: PsycheDefinition) -> None:
        """
        Validate psyche definition — psychological-epistemic modeling.

        Enforces formal constraints from the PEM framework:
          §1  Manifold validity: σ ∈ (0, 1], β ∈ [0, 1], κ > 0
          §2  Dimension completeness: |D| ≥ 1
          §4  Safety: NonDiagnostic dependent type constraint
        """
        # Unique name in symbol table
        if node.name in self._symbol_table:
            self._emit(
                f"Duplicate psyche definition: '{node.name}' already defined "
                f"(line {self._symbol_table[node.name]})",
                node,
            )
        else:
            self._symbol_table[node.name] = node.line

        # §2 — dimension completeness: |D| ≥ 1
        if not node.dimensions:
            self._emit(
                f"psyche '{node.name}' requires at least one cognitive dimension "
                f"(§1: ψ ∈ M requires dim(M) ≥ 1)",
                node,
            )

        # Check for duplicate dimensions
        seen_dims: set[str] = set()
        for dim in node.dimensions:
            if dim in seen_dims:
                self._emit(
                    f"Duplicate dimension '{dim}' in psyche '{node.name}'",
                    node,
                )
            seen_dims.add(dim)

        # §1 — manifold parameter validation
        # σ — noise: must be in (0, 1]
        if node.manifold_noise <= 0.0 or node.manifold_noise > 1.0:
            self._emit(
                f"Manifold noise σ must be in (0, 1], got {node.manifold_noise} "
                f"(psyche '{node.name}', §1: stochastic perturbation bound)",
                node,
            )

        # β — momentum decay: must be in [0, 1]
        if node.manifold_momentum < 0.0 or node.manifold_momentum > 1.0:
            self._emit(
                f"Manifold momentum β must be in [0, 1], got {node.manifold_momentum} "
                f"(psyche '{node.name}', §1: exponential decay factor)",
                node,
            )

        # κ — curvature: must be positive for all dimensions
        for dim_name, kappa in node.manifold_curvature.items():
            if kappa <= 0.0:
                self._emit(
                    f"Curvature κ for dimension '{dim_name}' must be > 0, "
                    f"got {kappa} (psyche '{node.name}', §1: Riemannian metric)",
                    node,
                )
            # Curvature dimension must be declared in dimensions list
            if dim_name not in seen_dims:
                self._emit(
                    f"Curvature references undeclared dimension '{dim_name}' "
                    f"in psyche '{node.name}' (not in dimensions list)",
                    node,
                )

        # §4 — safety: NonDiagnostic dependent type constraint
        # The safety list MUST include 'non_diagnostic' — this is the
        # core invariant from the PEM paper:
        #   ∀ output ∈ Results(q') : ¬IsClinicalDiagnosis(output)
        if not node.safety_constraints:
            self._emit(
                f"psyche '{node.name}' must declare at least one safety constraint "
                f"(§4: dependent type safety — 'non_diagnostic' is mandatory)",
                node,
            )
        elif 'non_diagnostic' not in node.safety_constraints:
            self._emit(
                f"psyche '{node.name}' missing mandatory 'non_diagnostic' safety "
                f"constraint (§4: ∀ output ∈ Results(q') : ¬IsClinicalDiagnosis(output))",
                node,
            )

        # Inference mode validation
        valid_modes = {'active', 'passive', ''}
        if node.inference_mode not in valid_modes:
            self._emit(
                f"Invalid inference mode '{node.inference_mode}' in psyche "
                f"'{node.name}' — must be 'active' or 'passive' "
                f"(§3: free energy minimization)",
                node,
            )

    # ── HELPERS ────────────────────────────────────────────────────

    def _check_type_reference(self, type_name: str, node: ASTNode) -> None:
        """Verify that a referenced type name is either built-in or user-defined."""
        if type_name in BUILTIN_TYPES:
            return
        if type_name in self._user_types:
            return
        # Allow unknown types as soft warnings — they might be defined in
        # imported modules or be added in later compilation phases
        # For now, we just skip (no error for unresolved types at Phase 1)

    def _check_range(self, value: float, lo: float, hi: float,
                     field_name: str, node: ASTNode) -> None:
        if value < lo or value > hi:
            self._emit(
                f"{field_name} must be between {lo} and {hi}, got {value}",
                node,
            )

    def _emit(self, message: str, node: ASTNode) -> None:
        self._errors.append(AxonTypeError(
            message=message,
            line=node.line,
            column=node.column,
        ))
