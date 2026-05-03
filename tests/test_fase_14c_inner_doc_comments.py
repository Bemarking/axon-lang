"""
Fase 14.c — Inner doc comments (//! and /*!)
===========================================
Adds the Rust-style inner-doc convention to the lossless lexing
channel introduced in 14.a:

  ``//`` regular line comment
  ``///`` outer doc line comment   (documents the next item — 14.a)
  ``//!`` inner doc line comment   (documents the *enclosing* item — 14.c)
  ``/*`` regular block comment
  ``/**`` outer doc block comment  (documents the next item — 14.a)
  ``/*!`` inner doc block comment  (documents the *enclosing* item — 14.c)

Inner doc comments target file/module-level documentation: an
``axon doc`` generator surfaces them as the documentation of the file
they live in rather than of the next-following declaration. The
runtime semantics of the trivia channel itself are unchanged — inner
doc trivia rides through the same `leading_trivia` / `trailing_trivia`
arrays. Consumers discriminate via :pyattr:`Trivia.is_inner_doc`.
"""

from __future__ import annotations

from axon.compiler.ast_nodes import Trivia
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.tokens import TokenType


# ═══════════════════════════════════════════════════════════════════
#  14.c.1 — Lexer emits inner-doc comment tokens
# ═══════════════════════════════════════════════════════════════════


class TestLexerEmitsInnerDocTokens:
    def test_inner_doc_line_comment_emitted(self) -> None:
        toks = [t for t in Lexer("//! module docs").tokenize() if t.type != TokenType.EOF]
        assert len(toks) == 1
        assert toks[0].type == TokenType.INNER_DOC_LINE_COMMENT
        assert toks[0].value == "//! module docs"

    def test_inner_doc_block_comment_emitted(self) -> None:
        toks = [t for t in Lexer("/*! module docs */").tokenize() if t.type != TokenType.EOF]
        assert len(toks) == 1
        assert toks[0].type == TokenType.INNER_DOC_BLOCK_COMMENT
        assert toks[0].value == "/*! module docs */"

    def test_outer_inner_and_regular_distinguished(self) -> None:
        # `///` outer, `//!` inner, `//` regular — three distinct kinds.
        toks = [
            t
            for t in Lexer("/// outer\n//! inner\n// plain").tokenize()
            if t.type != TokenType.EOF
        ]
        assert len(toks) == 3
        assert toks[0].type == TokenType.DOC_LINE_COMMENT
        assert toks[1].type == TokenType.INNER_DOC_LINE_COMMENT
        assert toks[2].type == TokenType.LINE_COMMENT

    def test_block_outer_inner_and_regular_distinguished(self) -> None:
        toks = [
            t
            for t in Lexer("/** outer */\n/*! inner */\n/* plain */").tokenize()
            if t.type != TokenType.EOF
        ]
        assert len(toks) == 3
        assert toks[0].type == TokenType.DOC_BLOCK_COMMENT
        assert toks[1].type == TokenType.INNER_DOC_BLOCK_COMMENT
        assert toks[2].type == TokenType.BLOCK_COMMENT

    def test_strip_comments_drops_inner_doc_too(self) -> None:
        # Legacy callers opting out of trivia must see neither outer nor
        # inner doc comments in their token stream.
        toks = Lexer("//! dropped\nflow F() -> Out { }").tokenize(strip_comments=True)
        for t in toks:
            assert t.type not in {
                TokenType.LINE_COMMENT,
                TokenType.BLOCK_COMMENT,
                TokenType.DOC_LINE_COMMENT,
                TokenType.DOC_BLOCK_COMMENT,
                TokenType.INNER_DOC_LINE_COMMENT,
                TokenType.INNER_DOC_BLOCK_COMMENT,
            }


# ═══════════════════════════════════════════════════════════════════
#  14.c.2 — Trivia helpers recognise inner doc comments
# ═══════════════════════════════════════════════════════════════════


class TestTriviaHelpers:
    def test_inner_doc_line_is_doc_and_inner_doc(self) -> None:
        triv = Trivia(kind="inner_doc_line", text="//! hi", line=1, column=1)
        assert triv.is_doc is True
        assert triv.is_inner_doc is True

    def test_inner_doc_block_is_doc_and_inner_doc(self) -> None:
        triv = Trivia(kind="inner_doc_block", text="/*! hi */", line=1, column=1)
        assert triv.is_doc is True
        assert triv.is_inner_doc is True

    def test_outer_doc_line_is_not_inner_doc(self) -> None:
        triv = Trivia(kind="doc_line", text="/// hi", line=1, column=1)
        assert triv.is_doc is True
        assert triv.is_inner_doc is False

    def test_regular_line_is_neither(self) -> None:
        triv = Trivia(kind="line", text="// hi", line=1, column=1)
        assert triv.is_doc is False
        assert triv.is_inner_doc is False

    def test_inner_doc_line_stripped_text(self) -> None:
        triv = Trivia(kind="inner_doc_line", text="//! the body", line=1, column=1)
        assert triv.stripped_text() == " the body"

    def test_inner_doc_block_stripped_text(self) -> None:
        triv = Trivia(kind="inner_doc_block", text="/*! body */", line=1, column=1)
        assert triv.stripped_text() == " body "


# ═══════════════════════════════════════════════════════════════════
#  14.c.3 — Parser end-to-end: inner doc trivia attach to AST nodes
# ═══════════════════════════════════════════════════════════════════


def _parse(src: str):
    tokens = Lexer(src).tokenize()
    return Parser(tokens).parse()


class TestParserAttachesInnerDocTrivia:
    def test_inner_doc_line_attaches_as_leading(self) -> None:
        prog = _parse("//! file-level docs\nflow F() -> Out { }")
        assert len(prog.declarations) == 1
        decl = prog.declarations[0]
        assert len(decl.leading_trivia) == 1
        triv = decl.leading_trivia[0]
        assert triv.kind == "inner_doc_line"
        assert triv.is_inner_doc is True
        assert triv.text == "//! file-level docs"

    def test_inner_doc_block_attaches_as_leading(self) -> None:
        prog = _parse("/*! file-level docs */\nflow F() -> Out { }")
        decl = prog.declarations[0]
        assert len(decl.leading_trivia) == 1
        triv = decl.leading_trivia[0]
        assert triv.kind == "inner_doc_block"
        assert triv.is_inner_doc is True

    def test_outer_and_inner_doc_can_coexist(self) -> None:
        # File-level inner doc on top, outer doc for the declaration.
        # Both reach the trivia channel, distinguishable via is_inner_doc.
        src = "//! file docs\n/// docs F\nflow F() -> Out { }"
        prog = _parse(src)
        decl = prog.declarations[0]
        assert len(decl.leading_trivia) == 2
        assert decl.leading_trivia[0].is_inner_doc is True
        assert decl.leading_trivia[1].is_doc is True
        assert decl.leading_trivia[1].is_inner_doc is False

    def test_inner_doc_trivia_does_not_break_parsing(self) -> None:
        # Regression guard: inner doc comments interleaved between
        # legal tokens must not change the AST shape.
        src = (
            "//! header\n"
            "flow F() -> Out {\n"
            "  //! body header (legal but unusual)\n"
            "}\n"
        )
        prog = _parse(src)
        assert len(prog.declarations) == 1
        assert prog.declarations[0].name == "F"
