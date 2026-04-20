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
    AxonEndpointDefinition,
    AxonStoreDefinition,
    ConditionalNode,
    ConsensusBlock,
    ContextDefinition,
    CorpusDefinition,
    CorroborateNode,
    DaemonDefinition,
    DataSpaceDefinition,
    DeliberateBlock,
    DrillNode,
    EffectRowNode,
    EpistemicBlock,
    EnsembleDefinition,
    ExploreNode,
    FabricDefinition,
    FlowDefinition,
    FocusNode,
    ForInStatement,
    ForgeBlock,
    ComponentDefinition,
    HealDefinition,
    HibernateNode,
    ImmuneDefinition,
    ImportNode,
    IngestNode,
    IntentNode,
    LambdaDataApplyNode,
    LambdaDataDefinition,
    LeaseDefinition,
    LetStatement,
    MandateApplyNode,
    MandateDefinition,
    ManifestDefinition,
    MemoryDefinition,
    MutateNode,
    NavigateNode,
    ObserveDefinition,
    OtsApplyNode,
    OtsDefinition,
    ParallelBlock,
    PersistNode,
    PersonaDefinition,
    PixDefinition,
    ProbeDirective,
    ProgramNode,
    PsycheDefinition,
    PurgeNode,
    ReasonChain,
    RecallNode,
    ReconcileDefinition,
    ReflexDefinition,
    RefineBlock,
    RememberNode,
    ResourceDefinition,
    RetrieveNode,
    SessionDefinition,
    SessionStep,
    ReturnStatement,
    RunStatement,
    ShieldApplyNode,
    ShieldDefinition,
    StepNode,
    StreamDefinition,
    ToolDefinition,
    TopologyDefinition,
    TopologyEdge,
    TrailNode,
    TransactNode,
    TypeDefinition,
    ValidateGate,
    ViewDefinition,
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
VALID_APX_POLICY_KEYS = frozenset({
    "min_epr",
    "on_low_rank",
    "trust_floor",
    "ffi_mode",
    "require_pcc",
    "allow_scopes",
})
VALID_APX_ON_LOW_RANK = frozenset({"warn", "quarantine", "block"})
VALID_APX_TRUST_FLOOR = frozenset({
    "uncertainty",
    "speculation",
    "opinion",
    "factual_claim",
    "cited_fact",
    "corroborated_fact",
})
VALID_APX_FFI_MODE = frozenset({"taint", "sanitize", "strict"})


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
    """Registry of all declared names in an AXON program.

    Supports lexical scoping via enter_scope/exit_scope for
    if-block bodies.  SSA bindings inside a scope do not leak.
    """
    symbols: dict[str, Symbol] = field(default_factory=dict)
    _scope_stack: list[dict[str, Symbol]] = field(default_factory=list)

    def enter_scope(self) -> None:
        """Push a new lexical scope (for if { } blocks)."""
        self._scope_stack.append({})

    def exit_scope(self) -> None:
        """Pop the current scope, discarding its bindings."""
        if self._scope_stack:
            self._scope_stack.pop()

    def declare(self, name: str, kind: str, node: ASTNode, type_name: str = "") -> str | None:
        """Register a name. Returns an error message if duplicate."""
        # Check current scope first, then global
        target = self._scope_stack[-1] if self._scope_stack else self.symbols
        if name in target:
            existing = target[name]
            return (
                f"Duplicate declaration: '{name}' already defined as {existing.kind} "
                f"(first defined at line {existing.node.line})"
            )
        # Also check parent scope for SSA
        if name in self.symbols:
            existing = self.symbols[name]
            return (
                f"Duplicate declaration: '{name}' already defined as {existing.kind} "
                f"(first defined at line {existing.node.line})"
            )
        target[name] = Symbol(name=name, kind=kind, node=node, type_name=type_name)
        return None

    def lookup(self, name: str) -> Symbol | None:
        # Check scopes from innermost to outermost
        for scope in reversed(self._scope_stack):
            if name in scope:
                return scope[name]
        return self.symbols.get(name)

    def lookup_kind(self, name: str, kind: str) -> Symbol | None:
        sym = self.lookup(name)
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
        # I/O Cognitivo Phase 1 — Linear Logic tracker (λ-L-E)
        # Maps: resource_name → list of (manifest_name, node_referencing) tuples.
        # Used to enforce Separation Logic disjointness across manifests:
        # a `linear` or `affine` resource can belong to at most one manifest.
        self._resource_usage: dict[str, list[tuple[str, ASTNode]]] = {}

    def check(self) -> list[AxonTypeError]:
        """Full type-check pass. Returns all semantic errors found."""
        self._errors = []
        self._resource_usage = {}

        # Phase 1: Register all declarations in the symbol table
        self._register_declarations()

        # Phase 2: Validate each declaration's body
        for decl in self._program.declarations:
            self._check_declaration(decl)

        # Phase 3: Cross-declaration linearity (Linear + Separation Logic)
        self._check_resource_linearity()

        # Phase 4: Regulatory coverage (ESK Fase 6.1 — Compile-time Compliance)
        self._check_regulatory_compliance()

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
                # ── v0.24.3 FIX: PsycheDefinition was missing from Phase 1 ──
                # Without this registration, psyche names never entered the
                # SymbolTable, causing _check_psyche to use an ad-hoc
                # self._symbol_table dict that was never initialized.
                # Now psyche follows the same SymbolTable pattern as all
                # other 15+ primitives (persona, anchor, flow, agent, etc.)
                case PsycheDefinition(name=name):
                    self._register(name, "psyche", decl)
                case IngestNode():
                    pass  # ingest is a command, not a declaration
                case FocusNode() | AssociateNode() | AggregateNode() | ExploreNode():
                    pass  # flow-level commands, not declarations
                case OtsDefinition(name=name):
                    self._register(name, "ots", decl)
                case OtsApplyNode():
                    pass
                case MandateDefinition(name=name):
                    self._register(name, "mandate", decl)
                case MandateApplyNode():
                    pass  # mandate apply is a flow-level command
                case LambdaDataDefinition(name=name):
                    self._register(name, "lambda_data", decl)
                case LambdaDataApplyNode():
                    pass  # lambda apply is a flow-level command
                case NavigateNode() | DrillNode() | TrailNode():
                    pass  # PIX flow-level commands, not declarations
                case AxonStoreDefinition(name=name):
                    self._register(name, "axonstore", decl)
                case DaemonDefinition(name=name):
                    self._register(name, "daemon", decl)
                case AxonEndpointDefinition(name=name):
                    self._register(name, "axonendpoint", decl)
                case ResourceDefinition(name=name):
                    self._register(name, "resource", decl)
                case FabricDefinition(name=name):
                    self._register(name, "fabric", decl)
                case ManifestDefinition(name=name):
                    self._register(name, "manifest", decl)
                case ObserveDefinition(name=name):
                    self._register(name, "observe", decl)
                case ReconcileDefinition(name=name):
                    self._register(name, "reconcile", decl)
                case LeaseDefinition(name=name):
                    self._register(name, "lease", decl)
                case EnsembleDefinition(name=name):
                    self._register(name, "ensemble", decl)
                case SessionDefinition(name=name):
                    self._register(name, "session", decl)
                case TopologyDefinition(name=name):
                    self._register(name, "topology", decl)
                case ImmuneDefinition(name=name):
                    self._register(name, "immune", decl)
                case ReflexDefinition(name=name):
                    self._register(name, "reflex", decl)
                case HealDefinition(name=name):
                    self._register(name, "heal", decl)
                case ComponentDefinition(name=name):
                    self._register(name, "component", decl)
                case ViewDefinition(name=name):
                    self._register(name, "view", decl)
                case PersistNode() | RetrieveNode() | MutateNode() | PurgeNode() | TransactNode():
                    pass  # axonstore CRUD ops validated at Phase 2

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
                self._check_import(decl)
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
            case MandateDefinition():
                self._check_mandate(decl)
            case MandateApplyNode():
                self._check_mandate_apply(decl)
            case LambdaDataDefinition():
                self._check_lambda_data(decl)
            case LambdaDataApplyNode():
                self._check_lambda_data_apply(decl)
            case IngestNode():
                pass  # validated at runtime
            case FocusNode() | AssociateNode() | AggregateNode() | ExploreNode():
                pass  # validated at runtime
            case NavigateNode() | DrillNode() | TrailNode() | CorroborateNode():
                pass  # PIX/MDN flow commands validated in flow step context
            case AxonStoreDefinition():
                self._check_axonstore(decl)
            case AxonEndpointDefinition():
                self._check_axonendpoint(decl)
            case ResourceDefinition():
                self._check_resource(decl)
            case FabricDefinition():
                self._check_fabric(decl)
            case ManifestDefinition():
                self._check_manifest(decl)
            case ObserveDefinition():
                self._check_observe(decl)
            case ReconcileDefinition():
                self._check_reconcile(decl)
            case LeaseDefinition():
                self._check_lease(decl)
            case EnsembleDefinition():
                self._check_ensemble(decl)
            case SessionDefinition():
                self._check_session(decl)
            case TopologyDefinition():
                self._check_topology(decl)
            case ImmuneDefinition():
                self._check_immune(decl)
            case ReflexDefinition():
                self._check_reflex(decl)
            case HealDefinition():
                self._check_heal(decl)
            case ComponentDefinition():
                self._check_component(decl)
            case ViewDefinition():
                self._check_view(decl)
            case PersistNode() | RetrieveNode() | MutateNode() | PurgeNode() | TransactNode():
                self._check_store_crud(decl)
            case LetStatement():
                self._check_let(decl)

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
            case MandateApplyNode():
                self._check_mandate_apply(step)
            case LambdaDataApplyNode():
                self._check_lambda_data_apply(step)
            case ForInStatement():
                self._check_for_in(step, step_names, flow_name)
            case LetStatement():
                self._check_let(step)
            case ReturnStatement():
                self._check_return(step, flow_name)

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
        # v0.25.4 — Block-style if { body }: scoped validation
        if node.then_body:
            self._symbols.enter_scope()
            for child in node.then_body:
                self._check_flow_step(child, step_names, flow_name)
            self._symbols.exit_scope()
        if node.else_body:
            self._symbols.enter_scope()
            for child in node.else_body:
                self._check_flow_step(child, step_names, flow_name)
            self._symbols.exit_scope()

    def _check_return(self, node: ReturnStatement, flow_name: str) -> None:
        """Semantic cortafuegos: return only valid inside a flow subgraph."""
        if not flow_name:
            self._emit(
                "return statement is only valid inside a flow body",
                node,
            )

    def _check_for_in(self, node: ForInStatement, step_names: set[str], flow_name: str) -> None:
        """Validate for-in iteration: variable binding and body steps."""
        if not node.variable:
            self._emit("for-in loop requires a variable binding", node)
        if not node.iterable:
            self._emit("for-in loop requires an iterable expression", node)
        for step in node.body:
            self._check_flow_step(step, step_names, flow_name)

    def _check_let(self, node: LetStatement) -> None:
        """Validate let binding — SSA immutability enforced via SymbolTable.

        The SymbolTable.declare() method rejects duplicate names, which
        provides compile-time Single Static Assignment enforcement:
        any attempt to rebind an existing name produces a fatal
        AxonTypeError ("ImmutableBindingError").
        """
        if not node.identifier:
            self._emit("let binding requires an identifier", node)
            return

        # SSA enforcement: SymbolTable.declare() returns error if name exists
        err = self._symbols.declare(node.identifier, "let", node)
        if err:
            self._emit(
                f"ImmutableBindingError: Cannot rebind '{node.identifier}'. "
                f"SSA axiom violated — {err}",
                node,
            )

        if node.value_expr is None:
            self._emit(
                f"let binding '{node.identifier}' requires a value expression",
                node,
            )

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

    # ── AXONSTORE validation ──────────────────────────────────────

    _VALID_STORE_BACKENDS = frozenset({"sqlite", "postgresql", "mysql"})
    _VALID_STORE_ISOLATION = frozenset({
        "read_committed", "repeatable_read", "serializable",
    })
    _VALID_STORE_ON_BREACH = frozenset({"rollback", "raise", "log"})
    _VALID_COLUMN_TYPES = frozenset({
        "integer", "text", "real", "decimal", "timestamp",
        "boolean", "float", "string",
    })
    _VALID_ENDPOINT_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})

    def _check_axonstore(self, node: AxonStoreDefinition) -> None:
        if not node.name:
            self._emit("axonstore requires a name", node)
        if node.backend and node.backend not in self._VALID_STORE_BACKENDS:
            self._emit(
                f"Unknown backend '{node.backend}' in axonstore '{node.name}'. "
                f"Valid: {', '.join(sorted(self._VALID_STORE_BACKENDS))}",
                node,
            )
        if node.isolation and node.isolation not in self._VALID_STORE_ISOLATION:
            self._emit(
                f"Unknown isolation level '{node.isolation}' in axonstore '{node.name}'. "
                f"Valid: {', '.join(sorted(self._VALID_STORE_ISOLATION))}",
                node,
            )
        if node.on_breach and node.on_breach not in self._VALID_STORE_ON_BREACH:
            self._emit(
                f"Unknown on_breach policy '{node.on_breach}' in axonstore '{node.name}'. "
                f"Valid: {', '.join(sorted(self._VALID_STORE_ON_BREACH))}",
                node,
            )
        if node.schema:
            if not node.schema.columns:
                self._emit(
                    f"axonstore '{node.name}' schema must have at least one column",
                    node,
                )
            else:
                # Check for duplicate column names
                seen_cols: set[str] = set()
                for col in node.schema.columns:
                    if col.col_name in seen_cols:
                        self._emit(
                            f"Duplicate column '{col.col_name}' in "
                            f"axonstore '{node.name}' schema",
                            node,
                        )
                    seen_cols.add(col.col_name)
                    # Validate column type
                    if col.col_type and col.col_type not in self._VALID_COLUMN_TYPES:
                        self._emit(
                            f"Unknown column type '{col.col_type}' for "
                            f"'{col.col_name}' in axonstore '{node.name}'. "
                            f"Valid: {', '.join(sorted(self._VALID_COLUMN_TYPES))}",
                            node,
                        )
        self._check_range(node.confidence_floor, 0.0, 1.0,
                          "confidence_floor", node)

    def _check_store_crud(self, node: ASTNode) -> None:
        """Validate CRUD operations cross-reference declared stores."""
        store_name = ""
        op_name = ""
        match node:
            case PersistNode(store_name=sn):
                store_name, op_name = sn, "persist"
            case RetrieveNode(store_name=sn):
                store_name, op_name = sn, "retrieve"
            case MutateNode(store_name=sn):
                store_name, op_name = sn, "mutate"
            case PurgeNode(store_name=sn):
                store_name, op_name = sn, "purge"
            case TransactNode():
                for child in node.body:
                    self._check_store_crud(child)
                return
            case _:
                return

        if store_name:
            sym = self._symbols.lookup(store_name)
            if sym is None:
                self._emit(
                    f"{op_name} references undeclared store '{store_name}'. "
                    f"Declare it with: axonstore {store_name} {{ ... }}",
                    node,
                )
            elif sym.kind != "axonstore":
                self._emit(
                    f"'{store_name}' is a {sym.kind}, not an axonstore",
                    node,
                )

    def _check_axonendpoint(self, node: AxonEndpointDefinition) -> None:
        if not node.name:
            self._emit("axonendpoint requires a name", node)

        if node.method and node.method.upper() not in self._VALID_ENDPOINT_METHODS:
            self._emit(
                f"Unknown HTTP method '{node.method}' in axonendpoint '{node.name}'. "
                f"Valid: {', '.join(sorted(self._VALID_ENDPOINT_METHODS))}",
                node,
            )

        if not node.path or not node.path.startswith("/"):
            self._emit(
                f"axonendpoint '{node.name}' path must start with '/': got '{node.path}'",
                node,
            )

        if node.execute_flow:
            sym = self._symbols.lookup(node.execute_flow)
            if sym is None:
                self._emit(
                    f"axonendpoint '{node.name}' references undefined flow '{node.execute_flow}'",
                    node,
                )
            elif sym.kind != "flow":
                self._emit(
                    f"'{node.execute_flow}' is a {sym.kind}, not a flow",
                    node,
                )
        else:
            self._emit(
                f"axonendpoint '{node.name}' requires 'execute: <FlowName>'",
                node,
            )

        if node.body_type:
            self._check_type_reference(node.body_type, node)

        if node.output_type:
            self._check_type_reference(node.output_type, node)

        if node.shield_ref:
            sym = self._symbols.lookup(node.shield_ref)
            if sym is None:
                self._emit(
                    f"axonendpoint '{node.name}' references undefined shield '{node.shield_ref}'",
                    node,
                )
            elif sym.kind != "shield":
                self._emit(
                    f"'{node.shield_ref}' is a {sym.kind}, not a shield",
                    node,
                )

        if node.retries < 0:
            self._emit(
                f"axonendpoint '{node.name}' retries must be >= 0, got {node.retries}",
                node,
            )

    # ═══════════════════════════════════════════════════════════════
    #  I/O COGNITIVO — Cálculo Lambda Lineal Epistémico (λ-L-E) · Fase 1
    #
    #  Validates the four infrastructure primitives against:
    #    • Linear Logic (Girard 1987)     — affine/linear resource usage
    #    • Separation Logic (O'Hearn)     — resource disjointness (*)
    #    • Epistemic Lattice (Fagin et al) — c, quorum, partition semantics
    # ═══════════════════════════════════════════════════════════════

    _VALID_RESOURCE_LIFETIMES = frozenset({"linear", "affine", "persistent"})
    _VALID_PARTITION_POLICIES = frozenset({"fail", "shield_quarantine"})
    _VALID_PROVIDERS = frozenset({
        "aws", "gcp", "azure", "kubernetes", "bare_metal", "custom",
    })

    def _check_resource(self, node: ResourceDefinition) -> None:
        if not node.name:
            self._emit("resource requires a name", node)

        if not node.kind:
            self._emit(f"resource '{node.name}' requires 'kind: <provider-kind>'", node)

        if node.lifetime not in self._VALID_RESOURCE_LIFETIMES:
            self._emit(
                f"resource '{node.name}' has invalid lifetime '{node.lifetime}'. "
                f"Valid: linear | affine | persistent",
                node,
            )

        if node.certainty_floor is not None:
            if not 0.0 <= node.certainty_floor <= 1.0:
                self._emit(
                    f"resource '{node.name}' certainty_floor must be in [0.0, 1.0], "
                    f"got {node.certainty_floor}",
                    node,
                )

        if node.capacity is not None and node.capacity < 0:
            self._emit(
                f"resource '{node.name}' capacity must be >= 0, got {node.capacity}",
                node,
            )

        if node.shield_ref:
            sym = self._symbols.lookup(node.shield_ref)
            if sym is None:
                self._emit(
                    f"resource '{node.name}' references undefined shield "
                    f"'{node.shield_ref}'",
                    node,
                )
            elif sym.kind != "shield":
                self._emit(
                    f"resource '{node.name}' shield ref '{node.shield_ref}' "
                    f"is a {sym.kind}, not a shield",
                    node,
                )

    def _check_fabric(self, node: FabricDefinition) -> None:
        if not node.name:
            self._emit("fabric requires a name", node)

        if node.provider and node.provider not in self._VALID_PROVIDERS:
            self._emit(
                f"fabric '{node.name}' has unknown provider '{node.provider}'. "
                f"Valid: {', '.join(sorted(self._VALID_PROVIDERS))}",
                node,
            )

        if node.zones is not None and node.zones < 1:
            self._emit(
                f"fabric '{node.name}' zones must be >= 1, got {node.zones}",
                node,
            )

        if node.shield_ref:
            sym = self._symbols.lookup(node.shield_ref)
            if sym is None:
                self._emit(
                    f"fabric '{node.name}' references undefined shield "
                    f"'{node.shield_ref}'",
                    node,
                )
            elif sym.kind != "shield":
                self._emit(
                    f"fabric '{node.name}' shield ref '{node.shield_ref}' "
                    f"is a {sym.kind}, not a shield",
                    node,
                )

    def _check_manifest(self, node: ManifestDefinition) -> None:
        if not node.name:
            self._emit("manifest requires a name", node)

        # Separation Logic (*): resources listed in a single manifest must be
        # pairwise disjoint — no name may appear twice.
        seen: set[str] = set()
        for res_name in node.resources:
            if res_name in seen:
                self._emit(
                    f"manifest '{node.name}' lists resource '{res_name}' "
                    f"more than once (Separation Logic disjointness violation)",
                    node,
                )
                continue
            seen.add(res_name)

            sym = self._symbols.lookup(res_name)
            if sym is None:
                self._emit(
                    f"manifest '{node.name}' references undefined resource "
                    f"'{res_name}'",
                    node,
                )
                continue
            if sym.kind != "resource":
                self._emit(
                    f"manifest '{node.name}' reference '{res_name}' is a "
                    f"{sym.kind}, not a resource",
                    node,
                )
                continue

            # Register usage for Phase 3 cross-manifest linearity check.
            self._resource_usage.setdefault(res_name, []).append(
                (node.name, node)
            )

        if node.fabric_ref:
            sym = self._symbols.lookup(node.fabric_ref)
            if sym is None:
                self._emit(
                    f"manifest '{node.name}' references undefined fabric "
                    f"'{node.fabric_ref}'",
                    node,
                )
            elif sym.kind != "fabric":
                self._emit(
                    f"manifest '{node.name}' fabric ref '{node.fabric_ref}' "
                    f"is a {sym.kind}, not a fabric",
                    node,
                )

        if node.zones is not None and node.zones < 1:
            self._emit(
                f"manifest '{node.name}' zones must be >= 1, got {node.zones}",
                node,
            )

        # compliance κ values are free-form identifiers (HIPAA, PCI_DSS, GDPR,
        # SOX, FINRA, ISO27001, ...). Validation is deferred to Fase 6.1
        # where the regulatory type lattice is formalized.

    def _check_observe(self, node: ObserveDefinition) -> None:
        if not node.name:
            self._emit("observe requires a name", node)

        if not node.target:
            self._emit(
                f"observe '{node.name}' requires 'from <ManifestName>'",
                node,
            )
        else:
            sym = self._symbols.lookup(node.target)
            if sym is None:
                self._emit(
                    f"observe '{node.name}' references undefined manifest "
                    f"'{node.target}'",
                    node,
                )
            elif sym.kind != "manifest":
                self._emit(
                    f"observe '{node.name}' target '{node.target}' is a "
                    f"{sym.kind}, not a manifest",
                    node,
                )

        if not node.sources:
            self._emit(
                f"observe '{node.name}' requires at least one source "
                f"(sources: [prometheus, ...])",
                node,
            )

        if node.quorum is not None:
            if node.quorum < 1:
                self._emit(
                    f"observe '{node.name}' quorum must be >= 1, got {node.quorum}",
                    node,
                )
            elif node.sources and node.quorum > len(node.sources):
                self._emit(
                    f"observe '{node.name}' quorum ({node.quorum}) exceeds "
                    f"number of sources ({len(node.sources)})",
                    node,
                )

        if node.on_partition not in self._VALID_PARTITION_POLICIES:
            # Decision D4 (plan_io_cognitivo.md): partition = ⊥ void = CT-3.
            # `fail` raises a structural Network Error; `shield_quarantine`
            # isolates the observation without aborting the program.
            self._emit(
                f"observe '{node.name}' has invalid on_partition "
                f"'{node.on_partition}'. Valid: fail | shield_quarantine",
                node,
            )

        if node.certainty_floor is not None:
            if not 0.0 <= node.certainty_floor <= 1.0:
                self._emit(
                    f"observe '{node.name}' certainty_floor must be in "
                    f"[0.0, 1.0], got {node.certainty_floor}",
                    node,
                )

    # ═══════════════════════════════════════════════════════════════
    #  CONTROL COGNITIVO — Fase 3 (reconcile / lease / ensemble)
    # ═══════════════════════════════════════════════════════════════

    _VALID_ON_DRIFT = frozenset({"provision", "alert", "refine"})
    _VALID_LEASE_ACQUIRE = frozenset({"on_start", "on_demand"})
    _VALID_LEASE_ON_EXPIRE = frozenset({"anchor_breach", "release", "extend"})
    _VALID_AGGREGATION = frozenset({"majority", "weighted", "byzantine"})
    _VALID_CERTAINTY_MODE = frozenset({"min", "weighted", "harmonic"})

    def _check_reconcile(self, node: ReconcileDefinition) -> None:
        if not node.name:
            self._emit("reconcile requires a name", node)

        if not node.observe_ref:
            self._emit(
                f"reconcile '{node.name}' requires 'observe: <ObserveName>'",
                node,
            )
        else:
            sym = self._symbols.lookup(node.observe_ref)
            if sym is None:
                self._emit(
                    f"reconcile '{node.name}' references undefined observe "
                    f"'{node.observe_ref}'",
                    node,
                )
            elif sym.kind != "observe":
                self._emit(
                    f"reconcile '{node.name}' observe ref '{node.observe_ref}' "
                    f"is a {sym.kind}, not an observe",
                    node,
                )

        if node.threshold is not None and not 0.0 <= node.threshold <= 1.0:
            self._emit(
                f"reconcile '{node.name}' threshold must be in [0.0, 1.0], "
                f"got {node.threshold}",
                node,
            )

        if node.tolerance is not None and not 0.0 <= node.tolerance <= 1.0:
            self._emit(
                f"reconcile '{node.name}' tolerance must be in [0.0, 1.0], "
                f"got {node.tolerance}",
                node,
            )

        if node.on_drift not in self._VALID_ON_DRIFT:
            self._emit(
                f"reconcile '{node.name}' has invalid on_drift "
                f"'{node.on_drift}'. Valid: provision | alert | refine",
                node,
            )

        if node.shield_ref:
            sym = self._symbols.lookup(node.shield_ref)
            if sym is None:
                self._emit(
                    f"reconcile '{node.name}' references undefined shield "
                    f"'{node.shield_ref}'",
                    node,
                )
            elif sym.kind != "shield":
                self._emit(
                    f"reconcile '{node.name}' shield ref '{node.shield_ref}' "
                    f"is a {sym.kind}, not a shield",
                    node,
                )

        if node.mandate_ref:
            sym = self._symbols.lookup(node.mandate_ref)
            if sym is None:
                self._emit(
                    f"reconcile '{node.name}' references undefined mandate "
                    f"'{node.mandate_ref}'",
                    node,
                )
            elif sym.kind != "mandate":
                self._emit(
                    f"reconcile '{node.name}' mandate ref '{node.mandate_ref}' "
                    f"is a {sym.kind}, not a mandate",
                    node,
                )

        if node.max_retries < 0:
            self._emit(
                f"reconcile '{node.name}' max_retries must be >= 0, got "
                f"{node.max_retries}",
                node,
            )

    def _check_lease(self, node: LeaseDefinition) -> None:
        if not node.name:
            self._emit("lease requires a name", node)

        if not node.resource_ref:
            self._emit(
                f"lease '{node.name}' requires 'resource: <ResourceName>'",
                node,
            )
        else:
            sym = self._symbols.lookup(node.resource_ref)
            if sym is None:
                self._emit(
                    f"lease '{node.name}' references undefined resource "
                    f"'{node.resource_ref}'",
                    node,
                )
            elif sym.kind != "resource":
                self._emit(
                    f"lease '{node.name}' resource ref '{node.resource_ref}' "
                    f"is a {sym.kind}, not a resource",
                    node,
                )
            else:
                # Decision D2: a `persistent` resource is the exponential `!A`,
                # which does NOT need leasing — its τ is infinite.  Emit an
                # error to stop the operator from making a meaningless lease.
                resource_node = sym.node
                if isinstance(resource_node, ResourceDefinition):
                    if resource_node.lifetime == "persistent":
                        self._emit(
                            f"lease '{node.name}' targets resource "
                            f"'{node.resource_ref}' with lifetime 'persistent' "
                            f"— persistent (!A) resources do not require "
                            f"leasing; use 'linear' or 'affine' lifetime",
                            node,
                        )

        if not node.duration:
            self._emit(
                f"lease '{node.name}' requires a 'duration' (e.g. 30s, 5m, 2h)",
                node,
            )

        if node.acquire not in self._VALID_LEASE_ACQUIRE:
            self._emit(
                f"lease '{node.name}' has invalid acquire '{node.acquire}'. "
                f"Valid: on_start | on_demand",
                node,
            )

        if node.on_expire not in self._VALID_LEASE_ON_EXPIRE:
            self._emit(
                f"lease '{node.name}' has invalid on_expire "
                f"'{node.on_expire}'. Valid: anchor_breach | release | extend",
                node,
            )

    def _check_ensemble(self, node: EnsembleDefinition) -> None:
        if not node.name:
            self._emit("ensemble requires a name", node)

        if len(node.observations) < 2:
            self._emit(
                f"ensemble '{node.name}' requires at least 2 observations "
                f"for a meaningful Byzantine quorum (got {len(node.observations)})",
                node,
            )

        # Separation Logic: observations in an ensemble must be pairwise
        # distinct — aggregating the same observation N times is a fake
        # quorum.
        seen: set[str] = set()
        for obs_ref in node.observations:
            if obs_ref in seen:
                self._emit(
                    f"ensemble '{node.name}' lists observation '{obs_ref}' "
                    f"more than once (disjointness violation)",
                    node,
                )
                continue
            seen.add(obs_ref)

            sym = self._symbols.lookup(obs_ref)
            if sym is None:
                self._emit(
                    f"ensemble '{node.name}' references undefined observe "
                    f"'{obs_ref}'",
                    node,
                )
                continue
            if sym.kind != "observe":
                self._emit(
                    f"ensemble '{node.name}' member '{obs_ref}' is a "
                    f"{sym.kind}, not an observe",
                    node,
                )

        if node.quorum is not None:
            if node.quorum < 1:
                self._emit(
                    f"ensemble '{node.name}' quorum must be >= 1, got "
                    f"{node.quorum}",
                    node,
                )
            elif node.observations and node.quorum > len(node.observations):
                self._emit(
                    f"ensemble '{node.name}' quorum ({node.quorum}) exceeds "
                    f"number of observations ({len(node.observations)})",
                    node,
                )

        if node.aggregation not in self._VALID_AGGREGATION:
            self._emit(
                f"ensemble '{node.name}' has invalid aggregation "
                f"'{node.aggregation}'. Valid: majority | weighted | byzantine",
                node,
            )

        if node.certainty_mode not in self._VALID_CERTAINTY_MODE:
            self._emit(
                f"ensemble '{node.name}' has invalid certainty_mode "
                f"'{node.certainty_mode}'. Valid: min | weighted | harmonic",
                node,
            )

    # ═══════════════════════════════════════════════════════════════
    #  TOPOLOGY & SESSION TYPES — Fase 4 (π-calculus binary sessions)
    #
    #  Compile-time guarantees enforced here:
    #    1. Duality   — exactly two roles per session, dual pairwise.
    #    2. Closure   — nodes/sessions/types referenced are declared.
    #    3. Liveness  — directed cycles whose every edge is `receive`-
    #                   first are flagged as static deadlocks.
    # ═══════════════════════════════════════════════════════════════

    _NODE_KINDS = frozenset({
        "resource", "fabric", "manifest", "observe", "axonendpoint",
        "axonstore", "daemon", "agent", "shield",
    })

    def _check_session(self, node: SessionDefinition) -> None:
        if not node.name:
            self._emit("session requires a name", node)

        # Binary sessions only — exactly two roles.
        if len(node.roles) != 2:
            self._emit(
                f"session '{node.name}' must declare exactly 2 roles "
                f"(binary session); got {len(node.roles)}",
                node,
            )
            # Cannot duality-check without two roles, but continue with
            # per-role validation.
        else:
            # Role names must be distinct.
            r1, r2 = node.roles[0], node.roles[1]
            if r1.name == r2.name:
                self._emit(
                    f"session '{node.name}' has duplicate role name "
                    f"'{r1.name}'",
                    node,
                )

        # Per-role: validate every step's op + message_type reference.
        for role in node.roles:
            self._check_session_role(node.name, role)

        # Duality is a property of the pair.
        if len(node.roles) == 2:
            self._check_session_duality(node)

    def _check_session_role(self, session_name: str, role) -> None:
        for idx, step in enumerate(role.steps):
            if step.op not in {"send", "receive", "loop", "end"}:
                self._emit(
                    f"session '{session_name}' role '{role.name}' step "
                    f"#{idx} has invalid op '{step.op}'",
                    step,
                )
                continue
            if step.op in ("send", "receive") and not step.message_type:
                self._emit(
                    f"session '{session_name}' role '{role.name}' step "
                    f"#{idx} '{step.op}' requires a message type",
                    step,
                )

    def _check_session_duality(self, node: SessionDefinition) -> None:
        r1, r2 = node.roles[0], node.roles[1]
        if len(r1.steps) != len(r2.steps):
            self._emit(
                f"session '{node.name}' duality violation: roles "
                f"'{r1.name}' ({len(r1.steps)} steps) and '{r2.name}' "
                f"({len(r2.steps)} steps) have different lengths",
                node,
            )
            return
        for i, (s1, s2) in enumerate(zip(r1.steps, r2.steps)):
            if not self._steps_dual(s1, s2):
                self._emit(
                    f"session '{node.name}' duality violation at step #{i}: "
                    f"'{r1.name}' has '{self._format_step(s1)}' but "
                    f"'{r2.name}' has '{self._format_step(s2)}' "
                    f"(expected the dual)",
                    node,
                )

    @staticmethod
    def _steps_dual(s1: SessionStep, s2: SessionStep) -> bool:
        """Honda-Vasconcelos duality: send T ↔ receive T; loop ↔ loop; end ↔ end."""
        if s1.op == "send" and s2.op == "receive":
            return s1.message_type == s2.message_type
        if s1.op == "receive" and s2.op == "send":
            return s1.message_type == s2.message_type
        if s1.op == "loop" and s2.op == "loop":
            return True
        if s1.op == "end" and s2.op == "end":
            return True
        return False

    @staticmethod
    def _format_step(step: SessionStep) -> str:
        if step.op in ("send", "receive"):
            return f"{step.op} {step.message_type}"
        return step.op

    def _check_topology(self, node: TopologyDefinition) -> None:
        if not node.name:
            self._emit("topology requires a name", node)

        seen_nodes: set[str] = set()
        for n in node.nodes:
            if n in seen_nodes:
                self._emit(
                    f"topology '{node.name}' lists node '{n}' more than once",
                    node,
                )
                continue
            seen_nodes.add(n)

            sym = self._symbols.lookup(n)
            if sym is None:
                self._emit(
                    f"topology '{node.name}' references undefined node '{n}'",
                    node,
                )
                continue
            if sym.kind not in self._NODE_KINDS:
                self._emit(
                    f"topology '{node.name}' node '{n}' is a {sym.kind} — "
                    f"not a valid topology entity. Valid kinds: "
                    f"{', '.join(sorted(self._NODE_KINDS))}",
                    node,
                )

        # Edges
        for edge in node.edges:
            self._check_topology_edge(node.name, edge, seen_nodes)

        # Liveness: detect deadlock-prone cycles.
        self._check_topology_liveness(node)

    def _check_topology_edge(
        self, topology_name: str, edge: TopologyEdge, declared_nodes: set[str]
    ) -> None:
        if edge.source not in declared_nodes:
            self._emit(
                f"topology '{topology_name}' edge source '{edge.source}' is "
                f"not in the topology's nodes list",
                edge,
            )
        if edge.target not in declared_nodes:
            self._emit(
                f"topology '{topology_name}' edge target '{edge.target}' is "
                f"not in the topology's nodes list",
                edge,
            )
        if edge.source == edge.target:
            self._emit(
                f"topology '{topology_name}' has self-loop edge on "
                f"'{edge.source}' — π-calculus binary sessions require "
                f"two distinct endpoints",
                edge,
            )

        if not edge.session_ref:
            self._emit(
                f"topology '{topology_name}' edge {edge.source}->{edge.target} "
                f"has no session reference",
                edge,
            )
            return
        sym = self._symbols.lookup(edge.session_ref)
        if sym is None:
            self._emit(
                f"topology '{topology_name}' edge {edge.source}->{edge.target} "
                f"references undefined session '{edge.session_ref}'",
                edge,
            )
        elif sym.kind != "session":
            self._emit(
                f"topology '{topology_name}' edge {edge.source}->{edge.target} "
                f"session ref '{edge.session_ref}' is a {sym.kind}, not a session",
                edge,
            )

    def _check_topology_liveness(self, node: TopologyDefinition) -> None:
        """Detect cycles whose every edge starts with `receive` on the source.

        A directed cycle in the topology graph is a *static deadlock* if
        every node in the cycle is waiting (receive-first) before doing
        anything else.  A cycle that contains at least one `send`-first
        edge has progress and is liveness-preserving.
        """
        adjacency: dict[str, list[TopologyEdge]] = {}
        for edge in node.edges:
            if edge.source and edge.target:
                adjacency.setdefault(edge.source, []).append(edge)

        cycles = self._find_cycles(adjacency)
        if not cycles:
            return

        for cycle in cycles:
            cycle_edges = self._cycle_to_edges(cycle, node.edges)
            if all(self._edge_is_receive_first(e) for e in cycle_edges):
                cycle_str = " -> ".join(cycle + [cycle[0]])
                self._emit(
                    f"topology '{node.name}' has a static deadlock: cycle "
                    f"[{cycle_str}] where every edge waits on receive — "
                    f"no progress is possible (Honda liveness violation)",
                    node,
                )

    def _find_cycles(
        self, adjacency: dict[str, list[TopologyEdge]]
    ) -> list[list[str]]:
        """Tarjan-flavoured DFS that yields one representative per strongly
        connected component containing at least one back-edge."""
        color: dict[str, str] = {}
        stack: list[str] = []
        cycles: list[list[str]] = []

        def visit(n: str) -> None:
            color[n] = "gray"
            stack.append(n)
            for edge in adjacency.get(n, []):
                tgt = edge.target
                if color.get(tgt) == "gray":
                    if tgt in stack:
                        idx = stack.index(tgt)
                        cycles.append(stack[idx:])
                elif color.get(tgt) is None:
                    visit(tgt)
            stack.pop()
            color[n] = "black"

        for src in list(adjacency.keys()):
            if color.get(src) is None:
                visit(src)
        return cycles

    @staticmethod
    def _cycle_to_edges(
        cycle: list[str], edges: list[TopologyEdge]
    ) -> list[TopologyEdge]:
        result: list[TopologyEdge] = []
        n = len(cycle)
        for i in range(n):
            src = cycle[i]
            tgt = cycle[(i + 1) % n]
            for e in edges:
                if e.source == src and e.target == tgt:
                    result.append(e)
                    break
        return result

    def _edge_is_receive_first(self, edge: TopologyEdge) -> bool:
        """Return True if the source role's first step is `receive`.

        Convention (per AST docstring): the source plays the FIRST role
        of the session; the target plays the SECOND.  An edge is
        receive-first when the source's role starts by waiting.
        """
        sym = self._symbols.lookup(edge.session_ref)
        if sym is None or not isinstance(sym.node, SessionDefinition):
            return False  # cannot decide — defer to other checks
        session = sym.node
        if not session.roles:
            return False
        first_role_steps = session.roles[0].steps
        if not first_role_steps:
            return False
        return first_role_steps[0].op == "receive"

    # ═══════════════════════════════════════════════════════════════
    #  COGNITIVE IMMUNE SYSTEM — Fase 5 (immune / reflex / heal)
    #  Per docs/paper_inmune.md §4, §7, §8.  Key regulatory invariants:
    #    • `scope` is MANDATORY (paper §8.2 — no implicit blast radius).
    #    • `immune` references must resolve to kind=immune.
    #    • `reflex.trigger` must be an immune (one-way dependency).
    #    • `heal.source` must be an immune; mode defaults to
    #      human_in_loop (compliance, paper §7.2).
    # ═══════════════════════════════════════════════════════════════

    _VALID_EPISTEMIC_LEVELS = frozenset({"know", "believe", "speculate", "doubt"})
    _VALID_REFLEX_ACTIONS = frozenset({
        "drop", "revoke", "emit", "redact", "quarantine", "terminate", "alert",
    })
    _VALID_HEAL_MODES = frozenset({"audit_only", "human_in_loop", "adversarial"})
    _VALID_IMMUNE_SCOPES = frozenset({"tenant", "flow", "global"})
    _VALID_DECAY = frozenset({"exponential", "linear", "none"})

    def _check_immune(self, node: ImmuneDefinition) -> None:
        if not node.name:
            self._emit("immune requires a name", node)

        # Paper §8.2 — scope is mandatory, no implicit global default.
        if not node.scope:
            self._emit(
                f"immune '{node.name}' requires an explicit 'scope' "
                f"(tenant | flow | global). No implicit default exists — "
                f"blast radius must be declared (paper §8.2)",
                node,
            )
        elif node.scope not in self._VALID_IMMUNE_SCOPES:
            self._emit(
                f"immune '{node.name}' has invalid scope '{node.scope}'. "
                f"Valid: {', '.join(sorted(self._VALID_IMMUNE_SCOPES))}",
                node,
            )

        if not node.watch:
            self._emit(
                f"immune '{node.name}' requires a non-empty 'watch' list "
                f"(observables to monitor)",
                node,
            )

        if node.sensitivity is not None:
            if not 0.0 <= node.sensitivity <= 1.0:
                self._emit(
                    f"immune '{node.name}' sensitivity must be in [0.0, 1.0], "
                    f"got {node.sensitivity}",
                    node,
                )

        if node.window < 1:
            self._emit(
                f"immune '{node.name}' window must be >= 1, got {node.window}",
                node,
            )

        if node.decay not in self._VALID_DECAY:
            self._emit(
                f"immune '{node.name}' has invalid decay '{node.decay}'. "
                f"Valid: exponential | linear | none",
                node,
            )

    def _check_reflex(self, node: ReflexDefinition) -> None:
        if not node.name:
            self._emit("reflex requires a name", node)

        if not node.scope:
            self._emit(
                f"reflex '{node.name}' requires an explicit 'scope' "
                f"(tenant | flow | global) — paper §8.2",
                node,
            )
        elif node.scope not in self._VALID_IMMUNE_SCOPES:
            self._emit(
                f"reflex '{node.name}' has invalid scope '{node.scope}'",
                node,
            )

        if not node.trigger:
            self._emit(
                f"reflex '{node.name}' requires a 'trigger: <ImmuneName>'",
                node,
            )
        else:
            sym = self._symbols.lookup(node.trigger)
            if sym is None:
                self._emit(
                    f"reflex '{node.name}' references undefined trigger "
                    f"'{node.trigger}' (expected an immune)",
                    node,
                )
            elif sym.kind != "immune":
                self._emit(
                    f"reflex '{node.name}' trigger '{node.trigger}' is a "
                    f"{sym.kind}, not an immune",
                    node,
                )

        if node.on_level not in self._VALID_EPISTEMIC_LEVELS:
            self._emit(
                f"reflex '{node.name}' invalid on_level '{node.on_level}'. "
                f"Valid: know | believe | speculate | doubt",
                node,
            )

        if not node.action:
            self._emit(
                f"reflex '{node.name}' requires an 'action' "
                f"(drop | revoke | emit | redact | quarantine | terminate | alert)",
                node,
            )
        elif node.action not in self._VALID_REFLEX_ACTIONS:
            self._emit(
                f"reflex '{node.name}' invalid action '{node.action}'",
                node,
            )

    def _check_heal(self, node: HealDefinition) -> None:
        if not node.name:
            self._emit("heal requires a name", node)

        if not node.scope:
            self._emit(
                f"heal '{node.name}' requires an explicit 'scope' "
                f"(tenant | flow | global) — paper §8.2",
                node,
            )
        elif node.scope not in self._VALID_IMMUNE_SCOPES:
            self._emit(
                f"heal '{node.name}' has invalid scope '{node.scope}'",
                node,
            )

        if not node.source:
            self._emit(
                f"heal '{node.name}' requires a 'source: <ImmuneName>'",
                node,
            )
        else:
            sym = self._symbols.lookup(node.source)
            if sym is None:
                self._emit(
                    f"heal '{node.name}' references undefined source "
                    f"'{node.source}' (expected an immune)",
                    node,
                )
            elif sym.kind != "immune":
                self._emit(
                    f"heal '{node.name}' source '{node.source}' is a "
                    f"{sym.kind}, not an immune",
                    node,
                )

        if node.on_level not in self._VALID_EPISTEMIC_LEVELS:
            self._emit(
                f"heal '{node.name}' invalid on_level '{node.on_level}'",
                node,
            )

        if node.mode not in self._VALID_HEAL_MODES:
            self._emit(
                f"heal '{node.name}' invalid mode '{node.mode}'. "
                f"Valid: audit_only | human_in_loop | adversarial (paper §7)",
                node,
            )

        # Paper §7.3 — `adversarial` mode is opt-in and requires explicit
        # opt-in.  We flag it here as a warning-style error for the operator
        # to confirm the Risk Acceptance Statement is in place.  For Fase 5
        # we only require the shield gate; a future phase can wire the RAS
        # attestation directly.
        if node.mode == "adversarial" and not node.shield_ref:
            self._emit(
                f"heal '{node.name}' mode='adversarial' requires a 'shield' "
                f"gate (no LLM-generated patch ships without review). "
                f"Paper §7.3: adversarial mode needs explicit Risk Acceptance",
                node,
            )

        if node.shield_ref:
            sym = self._symbols.lookup(node.shield_ref)
            if sym is None:
                self._emit(
                    f"heal '{node.name}' references undefined shield "
                    f"'{node.shield_ref}'",
                    node,
                )
            elif sym.kind != "shield":
                self._emit(
                    f"heal '{node.name}' shield ref '{node.shield_ref}' "
                    f"is a {sym.kind}, not a shield",
                    node,
                )

        if node.max_patches < 1:
            self._emit(
                f"heal '{node.name}' max_patches must be >= 1, got "
                f"{node.max_patches}",
                node,
            )

    # ═══════════════════════════════════════════════════════════════
    #  UI COGNITIVA — Fase 9 (component / view)
    #
    #  Invariants enforced at compile time:
    #    1. `renders` references a declared `type`.
    #    2. `on_interact` (if present) references a declared `flow` whose
    #       first parameter type matches `renders`.
    #    3. If `renders` carries κ (regulatory class), `via_shield` is
    #       MANDATORY and its `compliance` set must cover every κ of
    #       the rendered type. Missing classes are compile errors.
    #    4. `via_shield` (if present) must name a declared `shield`.
    #    5. Every component listed in a `view.components` must be a
    #       declared `component`.
    # ═══════════════════════════════════════════════════════════════

    def _check_component(self, node: ComponentDefinition) -> None:
        # (1) renders must resolve to a type
        rendered_type = None
        if not node.renders:
            self._emit(
                f"component '{node.name}' requires 'renders: <TypeName>'",
                node,
            )
        else:
            sym = self._symbols.lookup(node.renders)
            if sym is None:
                self._emit(
                    f"component '{node.name}' references undefined type "
                    f"'{node.renders}'",
                    node,
                )
            elif sym.kind != "type":
                self._emit(
                    f"component '{node.name}' renders '{node.renders}' which is "
                    f"a {sym.kind}, not a type",
                    node,
                )
            else:
                rendered_type = sym.node

        # (4) shield ref kind
        shield_node = None
        if node.via_shield:
            sym = self._symbols.lookup(node.via_shield)
            if sym is None:
                self._emit(
                    f"component '{node.name}' references undefined shield "
                    f"'{node.via_shield}'",
                    node,
                )
            elif sym.kind != "shield":
                self._emit(
                    f"component '{node.name}' via_shield '{node.via_shield}' is "
                    f"a {sym.kind}, not a shield",
                    node,
                )
            else:
                shield_node = sym.node

        # (3) regulated-render rule — Fase 9.5 compile-time contract
        if rendered_type is not None:
            type_kappa = set(getattr(rendered_type, "compliance", ()) or ())
            if type_kappa:
                if not shield_node:
                    self._emit(
                        f"component '{node.name}' renders regulated type "
                        f"'{node.renders}' (κ = {{{', '.join(sorted(type_kappa))}}}) "
                        f"but declares no 'via_shield'. Regulated renders require "
                        f"a shield that covers the type's κ — Fase 9.5.",
                        node,
                    )
                else:
                    shield_kappa = set(getattr(shield_node, "compliance", ()) or ())
                    missing = type_kappa - shield_kappa
                    if missing:
                        self._emit(
                            f"component '{node.name}' via_shield "
                            f"'{node.via_shield}' does not cover κ = "
                            f"{{{', '.join(sorted(missing))}}} of type "
                            f"'{node.renders}'. Add these classes to the "
                            f"shield's 'compliance' list or pick a shield "
                            f"that already covers them.",
                            node,
                        )

        # (2) on_interact must resolve to a flow with compatible signature
        if node.on_interact:
            sym = self._symbols.lookup(node.on_interact)
            if sym is None:
                self._emit(
                    f"component '{node.name}' references undefined flow "
                    f"'{node.on_interact}'",
                    node,
                )
            elif sym.kind != "flow":
                self._emit(
                    f"component '{node.name}' on_interact '{node.on_interact}' "
                    f"is a {sym.kind}, not a flow",
                    node,
                )
            elif rendered_type is not None:
                # The flow's first parameter must accept the rendered type.
                flow_node = sym.node
                params = list(getattr(flow_node, "parameters", []) or [])
                if params:
                    first_param = params[0]
                    param_type = getattr(first_param, "type_name", "") \
                        or getattr(first_param, "type_expr", None)
                    if hasattr(param_type, "name"):
                        param_type = param_type.name
                    if param_type and param_type != node.renders:
                        self._emit(
                            f"component '{node.name}' on_interact flow "
                            f"'{node.on_interact}' expects first parameter of "
                            f"type '{param_type}', but component renders "
                            f"'{node.renders}'. Signatures must match — "
                            f"Fase 9.2 rule 2.",
                            node,
                        )

    def _check_view(self, node: ViewDefinition) -> None:
        if not node.components:
            self._emit(
                f"view '{node.name}' has empty components list — a view must "
                f"compose at least one component",
                node,
            )
            return
        seen: set[str] = set()
        for comp_name in node.components:
            if comp_name in seen:
                self._emit(
                    f"view '{node.name}' lists component '{comp_name}' more "
                    f"than once",
                    node,
                )
                continue
            seen.add(comp_name)
            sym = self._symbols.lookup(comp_name)
            if sym is None:
                self._emit(
                    f"view '{node.name}' references undefined component "
                    f"'{comp_name}'",
                    node,
                )
            elif sym.kind != "component":
                self._emit(
                    f"view '{node.name}' component ref '{comp_name}' is a "
                    f"{sym.kind}, not a component",
                    node,
                )

    # ═══════════════════════════════════════════════════════════════
    #  EPISTEMIC SECURITY KERNEL — Fase 6.1 (Compile-time Compliance)
    #
    #  Regulatory Type Theory: a type carrying κ = {HIPAA, PCI_DSS, ...}
    #  may only cross a boundary gated by a shield whose compliance set
    #  covers κ.  Programs that violate coverage are rejected at
    #  compile time — reducing external audit work from months of review
    #  to zero, because the compiler itself is the auditor.
    #
    #  Coverage rules (per plan_io_cognitivo.md §6.1 "Compliance-as-a-Type"):
    #    1. axonendpoint.body_type / output_type with κ ≠ ∅ must be
    #       gated by a shield whose compliance ⊇ κ.
    #    2. axonendpoint.compliance declares the boundary's own class;
    #       the shield must cover it too.
    #    3. A program may have types with κ that never appear in an
    #       endpoint (internal use) — those do not trigger the check.
    # ═══════════════════════════════════════════════════════════════

    # Regulatory class registry.  Expanded in §6.x; the symbol table
    # only accepts declared classes to catch typos at compile time
    # ("GDRP" instead of "GDPR").
    _REGULATORY_CLASSES = frozenset({
        "HIPAA", "PCI_DSS", "GDPR", "SOX", "FINRA", "ISO27001",
        "SOC2", "FISMA", "GxP", "CCPA", "NIST_800_53",
    })

    def _check_regulatory_compliance(self) -> None:
        """Phase 4 post-pass: verify shield coverage for every type
        carrying a regulatory class.  Each violation is reported with
        the offending type, endpoint, and missing κ entries so the
        operator can remediate without re-reading the whole program.
        """
        # 1. Validate every compliance label is a known regulatory class.
        for decl in self._program.declarations:
            self._validate_compliance_labels(decl)

        # 2. For every axonendpoint, compute required κ = union of
        #    (endpoint.compliance, body_type.compliance, output_type.compliance).
        #    The shield's compliance must be ⊇ this union.
        for decl in self._program.declarations:
            if isinstance(decl, AxonEndpointDefinition):
                self._check_endpoint_compliance_coverage(decl)

    def _validate_compliance_labels(self, decl: ASTNode) -> None:
        labels = getattr(decl, "compliance", None)
        if not labels:
            return
        # Manifests already allow any label — compliance there is
        # forward-looking (Fase 6.1 ESK dossier), not enforced coverage.
        for label in labels:
            if label not in self._REGULATORY_CLASSES:
                name = getattr(decl, "name", "<unknown>")
                self._emit(
                    f"'{name}' declares unknown regulatory class '{label}'. "
                    f"Known classes: {', '.join(sorted(self._REGULATORY_CLASSES))}. "
                    f"Typos are compile-time errors per ESK Fase 6.1.",
                    decl,
                )

    def _check_endpoint_compliance_coverage(
        self, node: AxonEndpointDefinition
    ) -> None:
        required: set[str] = set(node.compliance)

        # Inherit compliance from body_type and output_type if they are
        # declared TypeDefinitions with κ ≠ ∅.
        body_compliance = self._type_compliance(node.body_type)
        output_compliance = self._type_compliance(node.output_type)
        required |= body_compliance | output_compliance

        if not required:
            return  # No regulatory obligation — no check needed.

        if not node.shield_ref:
            self._emit(
                f"axonendpoint '{node.name}' handles regulated data "
                f"(compliance: {sorted(required)}) but declares no shield. "
                f"ESK Fase 6.1 requires a shield whose compliance ⊇ "
                f"{sorted(required)} — this is a compile-time block, not a "
                f"runtime warning.",
                node,
            )
            return

        sym = self._symbols.lookup(node.shield_ref)
        if sym is None or sym.kind != "shield":
            # Already reported by _check_axonendpoint — don't double-flag.
            return

        shield_node = sym.node
        provided: set[str] = set(getattr(shield_node, "compliance", []) or [])
        missing = required - provided
        if missing:
            self._emit(
                f"axonendpoint '{node.name}' shield '{node.shield_ref}' does "
                f"not cover regulatory class(es) {sorted(missing)}. "
                f"Required κ: {sorted(required)}; shield provides: "
                f"{sorted(provided) or '∅'}. "
                f"Add '{sorted(missing)}' to the shield's compliance list, "
                f"or remove the regulatory annotation from the source type "
                f"(ESK Fase 6.1 — Compile-time Compliance).",
                node,
            )

    def _type_compliance(self, type_name: str) -> set[str]:
        if not type_name:
            return set()
        sym = self._symbols.lookup(type_name)
        if sym is None or sym.kind != "type":
            return set()
        type_node = sym.node
        if not isinstance(type_node, TypeDefinition):
            return set()
        return set(type_node.compliance or [])

    def _check_resource_linearity(self) -> None:
        """
        Phase 3 post-pass: enforce Linear/Affine cross-manifest constraint.

        Under Girard's Linear Logic:
          • A `linear`   resource must be consumed exactly once (treated here as
            "referenced from exactly one manifest" for Fase 1 scope).
          • An `affine`  resource may be referenced at most once across manifests.
          • A `persistent` resource (!A) may be referenced freely.

        Aliasing a non-persistent resource across manifests is a Separation
        Logic violation (heap regions must be disjoint — the `*` connector).
        """
        for res_name, usages in self._resource_usage.items():
            if len(usages) <= 1:
                continue
            sym = self._symbols.lookup(res_name)
            if sym is None or sym.kind != "resource":
                continue
            resource_node = sym.node
            if not isinstance(resource_node, ResourceDefinition):
                continue
            lifetime = resource_node.lifetime
            if lifetime == "persistent":
                continue  # !A — unrestricted exponential, no violation.
            manifests = ", ".join(f"'{m}'" for m, _ in usages)
            for _manifest_name, referencing_node in usages:
                self._emit(
                    f"resource '{res_name}' (lifetime: {lifetime}) is aliased "
                    f"across multiple manifests [{manifests}]. Linear/affine "
                    f"resources must be disjoint across manifests. Declare it "
                    f"as 'lifetime: persistent' to allow sharing.",
                    referencing_node,
                )

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
        # ── v0.24.3 FIX ──────────────────────────────────────────
        # REMOVED: ad-hoc self._symbol_table duplicate check.
        # Previously, _check_psyche used self._symbol_table (a plain
        # dict that was NEVER initialized in __init__), causing:
        #   AttributeError: 'TypeChecker' object has no attribute '_symbol_table'
        # This crashed compilation of any deliberate{} block containing psyche.
        #
        # Duplicate detection is now handled by self._symbols.declare()
        # in _register_declarations Phase 1, consistent with all other
        # AXON primitives (persona, anchor, mandate, lambda, etc.).
        # ─────────────────────────────────────────────────────────────

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

    # ── MANDATE validation ─────────────────────────────────────────────────

    # Valid on_violation policies for mandates (CRC Vía B)
    _VALID_MANDATE_POLICIES = frozenset({"coerce", "halt", "retry"})

    def _check_mandate(self, node: MandateDefinition) -> None:
        """
        Validate mandate definition — Cybernetic Refinement Calculus.

        Enforces formal constraints from the CRC paper:
          Vía C — constraint predicate M(x) is required
          Vía A — PID gains must be positive: Kp, Ki, Kd > 0
          Vía A — tolerance ε must be in (0, 1]
          Vía A — max_steps N must be ≥ 1
          Vía B — on_violation must be a valid policy
        """
        # Vía C — constraint is mandatory
        if not node.constraint:
            self._emit(
                f"mandate '{node.name}' requires a 'constraint' field "
                f"(Vía C: refinement type T_M = {{ x ∈ Σ* | M(x) ⊢ ⊤ }})",
                node,
            )

        # Vía A — PID gains must be positive
        if node.kp <= 0.0:
            self._emit(
                f"PID proportional gain Kp must be > 0, got {node.kp} "
                f"(mandate '{node.name}', Vía A: control law)",
                node,
            )
        if node.ki < 0.0:
            self._emit(
                f"PID integral gain Ki must be ≥ 0, got {node.ki} "
                f"(mandate '{node.name}', Vía A: accumulated error)",
                node,
            )
        if node.kd < 0.0:
            self._emit(
                f"PID derivative gain Kd must be ≥ 0, got {node.kd} "
                f"(mandate '{node.name}', Vía A: error rate damping)",
                node,
            )

        # Vía A — tolerance must be in (0, 1]
        if node.tolerance <= 0.0 or node.tolerance > 1.0:
            self._emit(
                f"Tolerance ε must be in (0, 1], got {node.tolerance} "
                f"(mandate '{node.name}', convergence threshold)",
                node,
            )

        # Vía A — max_steps must be ≥ 1
        if node.max_steps < 1:
            self._emit(
                f"max_steps N must be ≥ 1, got {node.max_steps} "
                f"(mandate '{node.name}', PID iteration budget)",
                node,
            )

        # Vía B — on_violation policy
        if node.on_violation and node.on_violation not in self._VALID_MANDATE_POLICIES:
            self._emit(
                f"Unknown on_violation policy '{node.on_violation}' for "
                f"mandate '{node.name}'. "
                f"Valid: {', '.join(sorted(self._VALID_MANDATE_POLICIES))}",
                node,
            )

    def _check_mandate_apply(self, node: MandateApplyNode) -> None:
        """
        Validate mandate application in a flow step.

        Ensures the referenced mandate is declared.
        """
        sym = self._symbols.lookup(node.mandate_name)
        if sym is not None and sym.kind != "mandate":
            self._emit(
                f"'{node.mandate_name}' in mandate apply is a {sym.kind}, "
                "not a mandate",
                node,
            )

    # ── LAMBDA DATA (ΛD) validation ──────────────────────────────────

    # Valid derivation categories for ΛD
    _VALID_DERIVATIONS = frozenset({
        "raw", "derived", "inferred", "aggregated", "transformed",
    })

    def _check_lambda_data(self, node: LambdaDataDefinition) -> None:
        """
        Validate Lambda Data definition — Epistemic Data Primitive.

        Enforces formal constraints from the ΛD formalism:
          1. Ontological Rigidity  — ontology field is required
          2. Epistemic Bounding    — certainty c ∈ [0, 1]
          3. Derivation validity   — derivation ∈ {raw, derived, inferred, aggregated, transformed}
          4. Epistemic Degradation Theorem (compile-time enforcement):
             For static compositions ΛD₁ ∘ ΛD₂, the composed certainty
             must satisfy: c_composed ≤ min(c₁, c₂)
             This is a structural invariant — we validate that individual
             certainty values are well-formed so the runtime composition
             operator can guarantee monotonic degradation.
        """
        # 1. Ontological Rigidity — ontology tag is mandatory
        if not node.ontology:
            self._emit(
                f"lambda '{node.name}' requires an 'ontology' field "
                f"(Ontological Rigidity: O must classify the data domain)",
                node,
            )

        # 2. Epistemic Bounding — certainty ∈ [0, 1]
        if node.certainty < 0.0 or node.certainty > 1.0:
            self._emit(
                f"certainty coefficient must be in [0, 1], got {node.certainty} "
                f"(lambda '{node.name}', Epistemic Bounding)",
                node,
            )

        # 3. Derivation validity
        if node.derivation and node.derivation not in self._VALID_DERIVATIONS:
            self._emit(
                f"Unknown derivation '{node.derivation}' for lambda '{node.name}'. "
                f"Valid: {', '.join(sorted(self._VALID_DERIVATIONS))}",
                node,
            )

        # 4. Epistemic Degradation Theorem — compile-time structural check
        #    For each ΛD definition, ensure certainty is strictly representable
        #    in the degradation lattice. A certainty of exactly 1.0 would mean
        #    "absolute truth" — which violates the theorem's premise that all
        #    derived data must degrade. Only 'raw' data with direct provenance
        #    may carry c = 1.0; all other derivations must have c < 1.0.
        if node.certainty == 1.0 and node.derivation and node.derivation != "raw":
            self._emit(
                f"Epistemic Degradation Theorem violation: lambda '{node.name}' "
                f"has certainty=1.0 with derivation='{node.derivation}'. "
                f"Only 'raw' data may carry absolute certainty (c=1.0). "
                f"Derived/inferred/aggregated data must have c < 1.0 "
                f"(∀ΛD₁∘ΛD₂: c_composed ≤ min(c₁, c₂))",
                node,
            )

    def _check_lambda_data_apply(self, node: LambdaDataApplyNode) -> None:
        """
        Validate Lambda Data application in a flow step.

        Ensures the referenced lambda data specification is declared.
        """
        sym = self._symbols.lookup(node.lambda_data_name)
        if sym is not None and sym.kind != "lambda_data":
            self._emit(
                f"'{node.lambda_data_name}' in lambda apply is a {sym.kind}, "
                "not a lambda data specification",
                node,
            )

    def _check_import(self, node: ImportNode) -> None:
        """Validate import declaration and optional APX policy metadata."""
        if not node.module_path:
            self._emit("Import must contain a module path", node)

        if node.apx_policy and not node.apx_enabled:
            self._emit("APX policy provided but APX mode is not enabled", node)

        if not node.apx_enabled:
            return

        for key in node.apx_policy.keys():
            if key not in VALID_APX_POLICY_KEYS:
                self._emit(
                    f"Unknown APX policy key '{key}'. "
                    f"Valid keys: {', '.join(sorted(VALID_APX_POLICY_KEYS))}",
                    node,
                )

        min_epr = node.apx_policy.get("min_epr")
        if min_epr is not None and not isinstance(min_epr, (int, float)):
            self._emit("APX min_epr must be numeric", node)
        elif isinstance(min_epr, (int, float)) and (min_epr < 0.0 or min_epr > 1.0):
            self._emit("APX min_epr must be between 0.0 and 1.0", node)

        on_low_rank = node.apx_policy.get("on_low_rank")
        if on_low_rank is not None and str(on_low_rank) not in VALID_APX_ON_LOW_RANK:
            self._emit(
                f"APX on_low_rank must be one of: {', '.join(sorted(VALID_APX_ON_LOW_RANK))}",
                node,
            )

        trust_floor = node.apx_policy.get("trust_floor")
        if trust_floor is not None and str(trust_floor) not in VALID_APX_TRUST_FLOOR:
            self._emit(
                f"APX trust_floor must be one of: {', '.join(sorted(VALID_APX_TRUST_FLOOR))}",
                node,
            )

        ffi_mode = node.apx_policy.get("ffi_mode")
        if ffi_mode is not None and str(ffi_mode) not in VALID_APX_FFI_MODE:
            self._emit(
                f"APX ffi_mode must be one of: {', '.join(sorted(VALID_APX_FFI_MODE))}",
                node,
            )

        require_pcc = node.apx_policy.get("require_pcc")
        if require_pcc is not None and not isinstance(require_pcc, bool):
            self._emit("APX require_pcc must be boolean", node)

        allow_scopes = node.apx_policy.get("allow_scopes")
        if allow_scopes is not None and not isinstance(allow_scopes, list):
            self._emit("APX allow_scopes must be a list", node)

    # ── HELPERS ─────────────────────────────────────────────────────────

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
