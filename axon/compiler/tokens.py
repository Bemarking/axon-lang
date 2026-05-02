"""
AXON Compiler — Token Definitions
===================================
Every token the lexer can produce. Derived directly from the AXON EBNF grammar.

Categories:
  - KEYWORDS: 82 cognitive keywords (persona, context, flow, anchor, agent, shield, psyche, mandate, lambda, dataspace, …)
  - LITERALS: STRING, INTEGER, FLOAT, BOOL, DURATION, IDENTIFIER
  - SYMBOLS:  braces, parens, brackets, colon, comma, arrow, range, etc.
  - COMPARISON: <, >, <=, >=, ==, !=
  - SPECIAL:  EOF, NEWLINE, COMMENT
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto


class TokenType(Enum):
    """All token types in the AXON language."""

    # ── KEYWORDS (cognitive primitives & language constructs) ──────
    PERSONA = auto()
    CONTEXT = auto()
    INTENT = auto()
    FLOW = auto()
    REASON = auto()
    ANCHOR = auto()
    VALIDATE = auto()
    REFINE = auto()
    MEMORY = auto()
    TOOL = auto()
    PROBE = auto()
    WEAVE = auto()
    STEP = auto()
    TYPE = auto()
    IMPORT = auto()
    RUN = auto()
    IF = auto()
    ELSE = auto()
    USE = auto()
    REMEMBER = auto()
    RECALL = auto()

    # ── EPISTEMIC KEYWORDS (cognitive scope modifiers) ─────────────
    KNOW = auto()
    BELIEVE = auto()
    SPECULATE = auto()
    DOUBT = auto()

    # ── PARALLEL & YIELDING KEYWORDS ──────────────────────────────
    PAR = auto()
    CONSOLIDATE = auto()
    HIBERNATE = auto()
    DELIBERATE = auto()
    CONSENSUS = auto()

    # ── CREATIVE SYNTHESIS KEYWORDS ──────────────────────────────
    FORGE = auto()

    # ── OTS KEYWORDS (Ontological Tool Synthesis) ────────────────
    OTS = auto()
    TELEOLOGY = auto()
    HOMOTOPY_SEARCH = auto()
    LINEAR_CONSTRAINTS = auto()
    LOSS_FUNCTION = auto()

    # ── STREAMING & EFFECT KEYWORDS (Convergence Theorems 1 & 2) ─
    STREAM = auto()           # stream<τ> semantic streaming
    ON_CHUNK = auto()         # on_chunk handler (co-inductive eval)
    ON_COMPLETE = auto()      # on_complete handler (epistemic promotion)
    EFFECTS = auto()          # effects: <io, network, epistemic:E>
    PURE = auto()             # pure effect (no side effects)
    NETWORK = auto()          # network effect row element

    # ── AGENT KEYWORDS (BDI autonomous agent primitive) ──────────
    AGENT = auto()
    GOAL = auto()
    TOOLS = auto()
    BUDGET = auto()
    STRATEGY = auto()
    ON_STUCK = auto()

    # ── SHIELD KEYWORDS (security primitive) ─────────────────────
    SHIELD = auto()
    SCAN = auto()
    ON_BREACH = auto()
    SEVERITY = auto()
    ALLOW = auto()
    DENY = auto()
    SANDBOX = auto()
    QUARANTINE = auto()
    REDACT = auto()

    # ── PIX KEYWORDS (structured cognitive retrieval) ─────────────
    PIX = auto()              # pix declaration
    NAVIGATE = auto()         # navigate pix_name with query: Q
    DRILL = auto()            # drill into subtree
    TRAIL = auto()            # reasoning path access

    # ── PSYCHE KEYWORDS (psychological-epistemic modeling §PEM) ────
    PSYCHE = auto()           # psyche definition
    DIMENSIONS = auto()       # dimensions: [...]
    MANIFOLD = auto()         # manifold: { ... }
    QUANTUM = auto()          # quantum: enabled
    INFERENCE = auto()        # inference: active

    # ── MDN KEYWORDS (multi-document navigation §5.3) ─────────────
    CORPUS = auto()           # corpus definition
    CORROBORATE = auto()      # corroborate operation (§4.2)
    EDGE_FILTER = auto()      # edge_filter budget parameter

    # ── DATA SCIENCE KEYWORDS ────────────────────────────────────
    DATASPACE = auto()
    INGEST = auto()
    FOCUS = auto()
    ASSOCIATE = auto()
    AGGREGATE = auto()
    EXPLORE = auto()

    # ── EMCP KEYWORDS (Epistemic MCP §6) ─────────────────────────
    MCP = auto()              # mcp("server", "resource")
    TAINT = auto()            # taint: untrusted

    # ── MANDATE KEYWORDS (Cybernetic Refinement Calculus §CRC) ────
    MANDATE = auto()          # mandate definition / apply
    CONSTRAINT = auto()       # constraint: "..."
    KP = auto()               # kp: 10.0  (proportional gain)
    KI = auto()               # ki: 0.1   (integral gain)
    KD = auto()               # kd: 0.05  (derivative gain)
    TOLERANCE = auto()        # tolerance: 0.01
    MAX_STEPS = auto()        # max_steps: 50
    ON_VIOLATION = auto()     # on_violation: halt|retry|coerce

    # ── DAEMON KEYWORDS (AxonServer — π-calculus reactive primitive) ─
    DAEMON = auto()           # daemon definition (νX co-algebraic)
    LISTEN = auto()           # listen block inside daemon
    BUDGET_PER_EVENT = auto() # budget_per_event: N (linear logic ⊗)

    # ── COMPUTE KEYWORDS (Deterministic Muscle Primitive §CM) ─────
    COMPUTE = auto()          # compute definition / apply
    LOGIC = auto()            # logic block inside compute

    # ── LAMBDA DATA KEYWORDS (ΛD — Epistemic State Vectors §ΛD) ──
    LAMBDA = auto()           # lambda definition / apply
    ONTOLOGY = auto()         # ontology: Measure | Chronon | Quantity | ...
    CERTAINTY = auto()        # certainty: 0.95 (c ∈ [0,1])
    TEMPORAL_FRAME = auto()   # temporal_frame: ["2024-01-01", "2024-12-31"]
    PROVENANCE = auto()       # provenance: "sensor_x" | "llm_y" (EntityRef ρ)
    DERIVATION = auto()       # derivation: axiomatic | observed | inferred | mutated (δ ∈ Δ)

    # ── AXONSTORE KEYWORDS (HoTT Transactional Persistence §AS) ──
    AXONSTORE = auto()        # axonstore definition (HoTT transducer)
    SCHEMA = auto()           # schema block inside axonstore
    PERSIST = auto()          # persist into Store (linear write token ⊗)
    RETRIEVE = auto()         # retrieve from Store (query projection π)
    MUTATE = auto()           # mutate Store where (atomic update Δ)
    PURGE = auto()            # purge from Store where (controlled deletion)
    TRANSACT = auto()         # transact { ... } (linear logic block A ⊸ B)

    # ── AXONENDPOINT KEYWORDS (Reactive Boundary Primitive §AE) ──
    AXONENDPOINT = auto()     # axonendpoint declaration

    # ── I/O COGNITIVO PRIMITIVES (§λ-L-E — Cálculo Lambda Lineal Epistémico) ──
    RESOURCE = auto()         # resource Name { kind, endpoint, lifetime: linear|affine|persistent, ... }
    FABRIC = auto()           # fabric Name { provider, region, zones, ephemeral, ... }
    MANIFEST = auto()         # manifest Name { resources: [...], fabric, compliance: [...], ... }
    OBSERVE = auto()          # observe Name from Manifest { sources, quorum, timeout, on_partition, ... }

    # ── CONTROL COGNITIVO PRIMITIVES (§λ-L-E Fase 3 — Active-Inference control) ──
    RECONCILE = auto()        # reconcile Name { observe, threshold, tolerance, on_drift, shield, mandate, max_retries }
    LEASE = auto()            # lease Name { resource, duration, acquire, on_expire }
    ENSEMBLE = auto()         # ensemble Name { observations: [...], quorum, aggregation, certainty_mode }

    # ── TOPOLOGY & SESSION PRIMITIVES (§λ-L-E Fase 4 — π-calculus / session types) ──
    TOPOLOGY = auto()         # topology Name { nodes: [...], edges: [A -> B : Sess, ...] }
    SESSION = auto()          # session Name { role1: [send T, receive U, ...], role2: [...] }
    SEND = auto()             # send T (session step)
    RECEIVE = auto()          # receive T (session step)
    LOOP = auto()             # loop (session step — repeat from start)
    END = auto()              # end (session step — terminate)

    # ── IMMUNE SYSTEM PRIMITIVES (§λ-L-E Fase 5 — Cognitive Immune System, per paper_inmune.md) ──
    IMMUNE = auto()           # immune Name { watch: [...], sensitivity, baseline, scope, tau, decay }
    REFLEX = auto()           # reflex Name { trigger, on_level, action, scope, sla }
    HEAL = auto()             # heal Name { source, on_level, mode, scope, review_sla, shield, max_patches }

    # ── UI COGNITIVA DECLARATIVA (§λ-L-E Fase 9 — 100% .axon applications) ──
    COMPONENT = auto()        # component Name { renders, via_shield, on_interact, render_hint }
    VIEW = auto()             # view Name { title, components: [...] }

    # ── MOBILE TYPED CHANNELS (§λ-L-E Fase 13 — π-calc mobility, paper_mobile_channels.md) ──
    CHANNEL = auto()          # channel Name { message: T, qos: X, lifetime: ℓ, persistence: π }
    EMIT = auto()             # emit Name(value)  — (Chan-Output) / (Chan-Mobility)
    PUBLISH = auto()          # publish Name within Shield  — (Publish-Ext) capability extrusion
    DISCOVER = auto()         # discover Cap as alias  — dual of publish, dynamic import

    # ── MODIFIERS (run statement modifiers) ───────────────────────
    AS = auto()
    WITHIN = auto()
    CONSTRAINED_BY = auto()
    ON_FAILURE = auto()
    OUTPUT_TO = auto()
    EFFORT = auto()

    # ── CONTEXTUAL KEYWORDS ──────────────────────────────────────
    FOR = auto()
    IN = auto()        # for X in Y
    INTO = auto()
    AGAINST = auto()
    ABOUT = auto()
    FROM = auto()
    WHERE = auto()
    LET = auto()       # let X = V (SSA immutable binding)
    RETURN = auto()    # return expr (Early Exit Sink)
    OR = auto()        # or (boolean connective)

    # ── FIELD KEYWORDS (inside blocks) ───────────────────────────
    GIVEN = auto()
    ASK = auto()
    OUTPUT = auto()

    # ── LITERALS ─────────────────────────────────────────────────
    STRING = auto()
    INTEGER = auto()
    FLOAT = auto()
    BOOL = auto()
    DURATION = auto()
    IDENTIFIER = auto()

    # ── SYMBOLS ──────────────────────────────────────────────────
    LBRACE = auto()       # {
    RBRACE = auto()       # }
    LPAREN = auto()       # (
    RPAREN = auto()       # )
    LBRACKET = auto()     # [
    RBRACKET = auto()     # ]
    COLON = auto()        # :
    COMMA = auto()        # ,
    DOT = auto()          # .
    ARROW = auto()        # ->
    DOTDOT = auto()       # ..
    QUESTION = auto()     # ?
    AT = auto()           # @

    # ── COMPARISON & ASSIGNMENT ───────────────────────────────────
    LT = auto()           # <
    GT = auto()           # >
    LTE = auto()          # <=
    GTE = auto()          # >=
    EQ = auto()           # ==
    NEQ = auto()          # !=
    ASSIGN = auto()       # = (SSA binding operator)

    # ── ARITHMETIC (Compute primitive §CM) ────────────────────────
    PLUS = auto()         # +
    MINUS = auto()        # -
    STAR = auto()         # *
    SLASH = auto()        # /

    # ── SPECIAL ──────────────────────────────────────────────────
    EOF = auto()
    NEWLINE = auto()
    COMMENT = auto()  # legacy — kept for backward compat; new code uses
                      # the four discriminated comment kinds below.

    # ── TRIVIA (Fase 14.a — Lossless lexing) ─────────────────────
    # Comment tokens emitted by the lexer instead of being silently
    # stripped. The parser ignores these for AST shape but materialises
    # them into ``Trivia`` objects attached to AST nodes (leading +
    # trailing) per the Roslyn convention. This is what enables LSP
    # hover with docstrings, ``axon fmt`` round-trip preservation,
    # rustdoc-style doc generation, and `// SECURITY:`-style audit
    # annotations to be reachable downstream.
    #
    # Doc-comment distinction (Rust convention):
    #   //   regular line comment
    #   ///  doc line comment  (outer doc — documents the next item)
    #   /*   regular block comment
    #   /**  doc block comment (outer doc — documents the next item)
    # `////` (4+ slashes) and `/**/` (empty block) are regular, not doc.
    LINE_COMMENT = auto()       # //  regular line comment
    BLOCK_COMMENT = auto()      # /* */ regular block comment
    DOC_LINE_COMMENT = auto()   # ///  doc line comment
    DOC_BLOCK_COMMENT = auto()  # /** */ doc block comment


# ── KEYWORD LOOKUP TABLE ──────────────────────────────────────────
# Maps raw text → TokenType for keyword discrimination
KEYWORDS: dict[str, TokenType] = {
    "persona": TokenType.PERSONA,
    "context": TokenType.CONTEXT,
    "intent": TokenType.INTENT,
    "flow": TokenType.FLOW,
    "reason": TokenType.REASON,
    "anchor": TokenType.ANCHOR,
    "validate": TokenType.VALIDATE,
    "refine": TokenType.REFINE,
    "memory": TokenType.MEMORY,
    "tool": TokenType.TOOL,
    "probe": TokenType.PROBE,
    "weave": TokenType.WEAVE,
    "step": TokenType.STEP,
    "type": TokenType.TYPE,
    "import": TokenType.IMPORT,
    "run": TokenType.RUN,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "use": TokenType.USE,
    "remember": TokenType.REMEMBER,
    "recall": TokenType.RECALL,
    # Epistemic scope modifiers
    "know": TokenType.KNOW,
    "believe": TokenType.BELIEVE,
    "speculate": TokenType.SPECULATE,
    "doubt": TokenType.DOUBT,
    # Parallel & yielding
    "par": TokenType.PAR,
    "consolidate": TokenType.CONSOLIDATE,
    "hibernate": TokenType.HIBERNATE,
    # Compute budget & consensus
    "deliberate": TokenType.DELIBERATE,
    "consensus": TokenType.CONSENSUS,
    # Creative synthesis
    "forge": TokenType.FORGE,
    # OTS (Ontological Tool Synthesis)
    "ots": TokenType.OTS,
    "teleology": TokenType.TELEOLOGY,
    "homotopy_search": TokenType.HOMOTOPY_SEARCH,
    "linear_constraints": TokenType.LINEAR_CONSTRAINTS,
    "loss_function": TokenType.LOSS_FUNCTION,
    # Streaming & effects (Convergence Theorems 1 & 2)
    "stream": TokenType.STREAM,
    "on_chunk": TokenType.ON_CHUNK,
    "on_complete": TokenType.ON_COMPLETE,
    "effects": TokenType.EFFECTS,
    "pure": TokenType.PURE,
    "network": TokenType.NETWORK,
    # Agent primitive
    "agent": TokenType.AGENT,
    "goal": TokenType.GOAL,
    "tools": TokenType.TOOLS,
    "budget": TokenType.BUDGET,
    "strategy": TokenType.STRATEGY,
    "on_stuck": TokenType.ON_STUCK,
    "as": TokenType.AS,
    "within": TokenType.WITHIN,
    "constrained_by": TokenType.CONSTRAINED_BY,
    "on_failure": TokenType.ON_FAILURE,
    "output_to": TokenType.OUTPUT_TO,
    "effort": TokenType.EFFORT,
    "for": TokenType.FOR,
    "in": TokenType.IN,
    "let": TokenType.LET,
    "return": TokenType.RETURN,
    "or": TokenType.OR,
    "into": TokenType.INTO,
    "against": TokenType.AGAINST,
    "about": TokenType.ABOUT,
    "from": TokenType.FROM,
    "where": TokenType.WHERE,
    "given": TokenType.GIVEN,
    "ask": TokenType.ASK,
    "output": TokenType.OUTPUT,
    "true": TokenType.BOOL,
    "false": TokenType.BOOL,
    # Shield primitive
    "shield": TokenType.SHIELD,
    "scan": TokenType.SCAN,
    "on_breach": TokenType.ON_BREACH,
    "severity": TokenType.SEVERITY,
    "allow": TokenType.ALLOW,
    "deny": TokenType.DENY,
    "sandbox": TokenType.SANDBOX,
    "quarantine": TokenType.QUARANTINE,
    "redact": TokenType.REDACT,
    # PIX (structured cognitive retrieval)
    "pix": TokenType.PIX,
    "navigate": TokenType.NAVIGATE,
    "drill": TokenType.DRILL,
    "trail": TokenType.TRAIL,
    # Psyche (psychological-epistemic modeling §PEM)
    "psyche": TokenType.PSYCHE,
    "dimensions": TokenType.DIMENSIONS,
    "manifold": TokenType.MANIFOLD,
    "quantum": TokenType.QUANTUM,
    "inference": TokenType.INFERENCE,
    # MDN (multi-document navigation §5.3)
    "corpus": TokenType.CORPUS,
    "corroborate": TokenType.CORROBORATE,
    "edge_filter": TokenType.EDGE_FILTER,
    # Data Science
    "dataspace": TokenType.DATASPACE,
    "ingest": TokenType.INGEST,
    "focus": TokenType.FOCUS,
    "associate": TokenType.ASSOCIATE,
    "aggregate": TokenType.AGGREGATE,
    "explore": TokenType.EXPLORE,
    # EMCP (Epistemic MCP §6)
    "mcp": TokenType.MCP,
    "taint": TokenType.TAINT,
    # Daemon (AxonServer — π-calculus reactive primitive)
    "daemon": TokenType.DAEMON,
    "listen": TokenType.LISTEN,
    "budget_per_event": TokenType.BUDGET_PER_EVENT,
    # Compute (Deterministic Muscle Primitive §CM)
    "compute": TokenType.COMPUTE,
    "logic": TokenType.LOGIC,
    # Mandate (Cybernetic Refinement Calculus §CRC)
    "mandate": TokenType.MANDATE,
    "constraint": TokenType.CONSTRAINT,
    "kp": TokenType.KP,
    "ki": TokenType.KI,
    "kd": TokenType.KD,
    "tolerance": TokenType.TOLERANCE,
    "max_steps": TokenType.MAX_STEPS,
    "on_violation": TokenType.ON_VIOLATION,
    # Lambda Data (ΛD — Epistemic State Vectors §ΛD)
    "lambda": TokenType.LAMBDA,
    "ontology": TokenType.ONTOLOGY,
    "certainty": TokenType.CERTAINTY,
    "temporal_frame": TokenType.TEMPORAL_FRAME,
    "provenance": TokenType.PROVENANCE,
    "derivation": TokenType.DERIVATION,
    # AxonStore (HoTT Transactional Persistence §AS)
    "axonstore": TokenType.AXONSTORE,
    "schema": TokenType.SCHEMA,
    "persist": TokenType.PERSIST,
    "retrieve": TokenType.RETRIEVE,
    "mutate": TokenType.MUTATE,
    "purge": TokenType.PURGE,
    "transact": TokenType.TRANSACT,
    # AxonEndpoint (Reactive Boundary Primitive §AE)
    "axonendpoint": TokenType.AXONENDPOINT,
    "axpoint": TokenType.AXONENDPOINT,
    # I/O Cognitivo (§λ-L-E — Cálculo Lambda Lineal Epistémico)
    "resource": TokenType.RESOURCE,
    "fabric": TokenType.FABRIC,
    "manifest": TokenType.MANIFEST,
    "observe": TokenType.OBSERVE,
    # Control Cognitivo (§λ-L-E Fase 3)
    "reconcile": TokenType.RECONCILE,
    "lease": TokenType.LEASE,
    "ensemble": TokenType.ENSEMBLE,
    # Topology & Session (§λ-L-E Fase 4)
    "topology": TokenType.TOPOLOGY,
    "session": TokenType.SESSION,
    "send": TokenType.SEND,
    "receive": TokenType.RECEIVE,
    "loop": TokenType.LOOP,
    "end": TokenType.END,
    # Immune System (§λ-L-E Fase 5)
    "immune": TokenType.IMMUNE,
    "reflex": TokenType.REFLEX,
    "heal": TokenType.HEAL,
    # UI Cognitiva (§λ-L-E Fase 9)
    "component": TokenType.COMPONENT,
    "view":      TokenType.VIEW,
    # Mobile Typed Channels (§λ-L-E Fase 13)
    "channel":  TokenType.CHANNEL,
    "emit":     TokenType.EMIT,
    "publish":  TokenType.PUBLISH,
    "discover": TokenType.DISCOVER,
}

# Duration suffixes recognized by the lexer
DURATION_SUFFIXES = {"s", "ms", "m", "h", "d"}


@dataclass(frozen=True, slots=True)
class Token:
    """A single token produced by the AXON lexer."""
    type: TokenType
    value: str
    line: int
    column: int

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, L{self.line}:C{self.column})"
