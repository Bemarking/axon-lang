"""
AXON Compiler — Token Definitions
===================================
Every token the lexer can produce. Derived directly from the AXON EBNF grammar.

Categories:
  - KEYWORDS: 54 cognitive keywords (persona, context, flow, anchor, agent, dataspace, …)
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

    # ── AGENT KEYWORDS (BDI autonomous agent primitive) ──────────
    AGENT = auto()
    GOAL = auto()
    TOOLS = auto()
    BUDGET = auto()
    STRATEGY = auto()
    ON_STUCK = auto()

    # ── DATA SCIENCE KEYWORDS ────────────────────────────────────
    DATASPACE = auto()
    INGEST = auto()
    FOCUS = auto()
    ASSOCIATE = auto()
    AGGREGATE = auto()
    EXPLORE = auto()

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
    # Data Science
    "dataspace": TokenType.DATASPACE,
    "ingest": TokenType.INGEST,
    "focus": TokenType.FOCUS,
    "associate": TokenType.ASSOCIATE,
    "aggregate": TokenType.AGGREGATE,
    "explore": TokenType.EXPLORE,
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
