"""
AXON Compiler — Source Formatter (Fase 14.d MVP)
==================================================

A token-level formatter that consumes the lossless lexing channel
introduced in Fase 14.a (and extended in 14.b/14.c) to round-trip
AXON source code with comments and layout preserved.

This is the MVP scope:

  * Round-trip preservation — every comment kind (regular, outer doc,
    inner doc; line and block) survives format → reparse → format
    byte-identically (modulo the whitespace canonicalisations below).
  * Minimal cosmetic normalisation — each line is right-trimmed of
    trailing whitespace and the file ends with exactly one ``\\n``.
  * Idempotence — :func:`format_source` is a fixed point: applying it
    twice yields the same output as applying it once.

Out of scope (deferred to future sub-phases):

  * Layout canonicalisation (consistent indent width, brace style,
    keyword alignment). The MVP intentionally preserves the author's
    existing layout. A later phase can layer canonical reformatting
    on top of this same trivia channel without re-architecting.
  * AST-driven pretty-printing. The 50+ grammar productions would
    each need an emitter; the token-level approach reaches a usable
    formatter without that engineering surface.

Why a token-level formatter rather than AST pretty-printer?

  The Trivia channel from 14.a already records every comment with its
  exact line/column. Combined with the effective tokens (which carry
  the same positional metadata) the *source byte stream* can be
  reconstructed deterministically. That is enough to call ``axon fmt
  --check`` a lossless contract: if the formatter changes nothing
  beyond the documented cosmetics, the file is canonical.
"""

from __future__ import annotations

from axon.compiler.lexer import Lexer
from axon.compiler.tokens import TokenType


__all__ = ["format_source"]


def format_source(src: str) -> str:
    """Format an AXON source string.

    Walks every token (effective + comment) emitted by the lexer in
    source order, re-emitting each at its original ``(line, column)``
    position. Comments survive verbatim — including ``//`` regular,
    ``///`` outer doc, ``//!`` inner doc, and the three block variants.

    The returned string is canonicalised so that:

    * every line has no trailing whitespace, and
    * the file terminates with exactly one ``\\n``.

    Beyond those two normalisations, the output is byte-identical to
    the input. This guarantees idempotence: ``format_source(format_source(x))
    == format_source(x)`` holds for every input.
    """
    tokens = [t for t in Lexer(src).tokenize() if t.type != TokenType.EOF]

    pieces: list[str] = []
    cur_line = 1
    cur_col = 1

    for tok in tokens:
        if tok.line > cur_line:
            pieces.append("\n" * (tok.line - cur_line))
            cur_line = tok.line
            cur_col = 1
        if tok.column > cur_col:
            pieces.append(" " * (tok.column - cur_col))
            cur_col = tok.column

        pieces.append(tok.value)
        # Block comments (and only block comments, in current grammar)
        # can contain newlines. Update the cursor accordingly so the
        # next token is positioned correctly.
        if "\n" in tok.value:
            parts = tok.value.split("\n")
            cur_line += len(parts) - 1
            cur_col = len(parts[-1]) + 1
        else:
            cur_col += len(tok.value)

    raw = "".join(pieces)
    # Right-trim every line; collapse trailing blank lines to a single
    # final ``\n``. These two normalisations are the only cosmetic
    # changes the MVP applies — everything else is preserved verbatim.
    trimmed = "\n".join(line.rstrip() for line in raw.split("\n"))
    return trimmed.rstrip("\n") + "\n"
