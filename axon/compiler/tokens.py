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

    # ── LAMBDA DATA KEYWORDS (ΛD — Epistemic State Vectors §ΛD) ──
    LAMBDA = auto()           # lambda definition / apply
    ONTOLOGY = auto()         # ontology: Measure | Chronon | Quantity | ...
    CERTAINTY = auto()        # certainty: 0.95 (c ∈ [0,1])
    TEMPORAL_FRAME = auto()   # temporal_frame: ["2024-01-01", "2024-12-31"]
    PROVENANCE = auto()       # provenance: "sensor_x" | "llm_y" (EntityRef ρ)
    DERIVATION = auto()       # derivation: axiomatic | observed | inferred | mutated (δ ∈ Δ)

    # ── MODIFIERS (run statement modifiers) ───────────────────────
    AS = auto()
    WITHIN = auto()
    CONSTRAINED_BY = auto()
    ON_FAILURE = auto()
    OUTPUT_TO = auto()
    EFFORT = auto()

    # ── CONTEXTUAL KEYWORDS ──────────────────────────────────────
    FOR = auto()
    INTO = auto()
    AGAINST = auto()
    ABOUT = auto()
    FROM = auto()
    WHERE = auto()

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

    # ── COMPARISON ───────────────────────────────────────────────
    LT = auto()           # <
    GT = auto()           # >
    LTE = auto()          # <=
    GTE = auto()          # >=
    EQ = auto()           # ==
    NEQ = auto()          # !=

    # ── SPECIAL ──────────────────────────────────────────────────
    EOF = auto()
    NEWLINE = auto()
    COMMENT = auto()


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
