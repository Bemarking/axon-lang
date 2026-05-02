"""
Fase 14.a — Lossless lexing + trivia channel tests
====================================================
Closes the gap reported by adopters reading axon-frontend 0.2.0:
the lexer was silently stripping comments at lex-time so the AST had
no trivia channel. Pre-14.a this blocked LSP hover with docstrings,
``axon fmt`` round-trip preservation, rustdoc-style doc generators,
and ``// SECURITY:``-style audit annotations.

14.a wires the four layers:
  1. Lexer emits four discriminated comment kinds
     (LINE_COMMENT, BLOCK_COMMENT, DOC_LINE_COMMENT, DOC_BLOCK_COMMENT)
  2. ``Trivia`` dataclass (kind/text/line/column) carries comments
     up to the parser
  3. ``ASTNode`` gains ``leading_trivia`` and ``trailing_trivia``
     tuples (default empty — backward-compat with all existing code)
  4. ``Parser.__init__`` auto-decorates every ``_parse_*`` method so
     trivia attach happens transparently across the ~50 grammar rules
"""

from __future__ import annotations

import pytest

from axon.compiler.ast_nodes import ASTNode, Trivia
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.tokens import TokenType


# ═══════════════════════════════════════════════════════════════════
#  14.a.1 — Lexer emits discriminated comment kinds
# ═══════════════════════════════════════════════════════════════════


class TestLexerEmitsCommentTokens:
    def test_regular_line_comment(self):
        toks = [t for t in Lexer("// hi").tokenize() if t.type != TokenType.EOF]
        assert len(toks) == 1
        assert toks[0].type == TokenType.LINE_COMMENT
        assert toks[0].value == "// hi"

    def test_doc_line_comment(self):
        toks = [t for t in Lexer("/// docs").tokenize() if t.type != TokenType.EOF]
        assert len(toks) == 1
        assert toks[0].type == TokenType.DOC_LINE_COMMENT
        assert toks[0].value == "/// docs"

    def test_four_slash_banner_is_regular_not_doc(self):
        # `////` (4+ slashes) is a regular line comment by Rust convention.
        # Keeps the discriminator stable when users write `//// section ////`.
        toks = [t for t in Lexer("//// banner").tokenize() if t.type != TokenType.EOF]
        assert toks[0].type == TokenType.LINE_COMMENT
        assert toks[0].value == "//// banner"

    def test_regular_block_comment(self):
        toks = [t for t in Lexer("/* body */").tokenize() if t.type != TokenType.EOF]
        assert toks[0].type == TokenType.BLOCK_COMMENT
        assert toks[0].value == "/* body */"

    def test_doc_block_comment(self):
        toks = [t for t in Lexer("/** docs */").tokenize() if t.type != TokenType.EOF]
        assert toks[0].type == TokenType.DOC_BLOCK_COMMENT
        assert toks[0].value == "/** docs */"

    def test_empty_block_is_regular_not_doc(self):
        # `/**/` is empty regular block, NOT a doc comment.
        # The doc-comment heuristic requires `/**` followed by a non-`/`.
        toks = [t for t in Lexer("/**/").tokenize() if t.type != TokenType.EOF]
        assert toks[0].type == TokenType.BLOCK_COMMENT
        assert toks[0].value == "/**/"

    def test_block_comment_preserves_inner_newlines(self):
        toks = [t for t in Lexer("/* line1\nline2 */").tokenize() if t.type != TokenType.EOF]
        assert toks[0].value == "/* line1\nline2 */"

    def test_unterminated_block_still_raises(self):
        from axon.compiler.errors import AxonLexerError
        with pytest.raises(AxonLexerError, match="Unterminated"):
            Lexer("/* never closes").tokenize()

    def test_loc_preserved(self):
        # Lex three comments on three different lines and verify line
        # tracking is correct after the comment-emission rewrite.
        toks = [
            t for t in Lexer("// a\n/// b\n/* c */").tokenize()
            if t.type != TokenType.EOF
        ]
        assert toks[0].line == 1 and toks[0].column == 1
        assert toks[1].line == 2 and toks[1].column == 1
        assert toks[2].line == 3 and toks[2].column == 1

    def test_strip_comments_opt_in(self):
        # Legacy callers that want pre-14.a token streams (no comments)
        # opt in via tokenize(strip_comments=True).
        src = "// drop me\nflow F() -> Out { }"
        toks = Lexer(src).tokenize(strip_comments=True)
        comment_kinds = {
            TokenType.LINE_COMMENT, TokenType.BLOCK_COMMENT,
            TokenType.DOC_LINE_COMMENT, TokenType.DOC_BLOCK_COMMENT,
        }
        assert all(t.type not in comment_kinds for t in toks)


# ═══════════════════════════════════════════════════════════════════
#  14.a.2 — Trivia dataclass behaviour
# ═══════════════════════════════════════════════════════════════════


class TestTriviaHelpers:
    def test_is_doc_predicate(self):
        assert Trivia("doc_line", "/// x", 1, 1).is_doc
        assert Trivia("doc_block", "/** x */", 1, 1).is_doc
        assert not Trivia("line", "// x", 1, 1).is_doc
        assert not Trivia("block", "/* x */", 1, 1).is_doc

    def test_stripped_text_line(self):
        assert Trivia("line", "// hello", 1, 1).stripped_text() == " hello"
        assert Trivia("doc_line", "/// hello", 1, 1).stripped_text() == " hello"

    def test_stripped_text_block(self):
        assert Trivia("block", "/* body */", 1, 1).stripped_text() == " body "
        assert Trivia("doc_block", "/** body */", 1, 1).stripped_text() == " body "

    def test_trivia_is_frozen(self):
        t = Trivia("line", "// x", 1, 1)
        with pytest.raises((AttributeError, Exception)):
            t.text = "// y"  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════
#  14.a.3 — ASTNode gains leading/trailing channels (default empty)
# ═══════════════════════════════════════════════════════════════════


class TestASTNodeTriviaChannels:
    def test_default_empty_tuples(self):
        # Backward-compat guard: existing code that constructs AST
        # nodes without trivia must continue to work.
        from axon.compiler.ast_nodes import ProgramNode
        p = ProgramNode()
        assert p.leading_trivia == ()
        assert p.trailing_trivia == ()

    def test_explicit_trivia_construction(self):
        from axon.compiler.ast_nodes import ProgramNode
        leading = (Trivia("doc_line", "/// header", 1, 1),)
        p = ProgramNode(leading_trivia=leading)
        assert p.leading_trivia == leading


# ═══════════════════════════════════════════════════════════════════
#  14.a.4 — Parser auto-attaches leading + trailing trivia
# ═══════════════════════════════════════════════════════════════════


def _parse(src: str):
    return Parser(Lexer(src).tokenize()).parse()


class TestParserAttachesLeadingTrivia:
    def test_doc_comment_before_flow_attaches_to_flow(self):
        src = """/// Documents FlowA
flow FlowA() -> Out {
}"""
        prog = _parse(src)
        flow = prog.declarations[0]
        assert len(flow.leading_trivia) == 1
        assert flow.leading_trivia[0].is_doc
        assert flow.leading_trivia[0].text == "/// Documents FlowA"

    def test_regular_comment_before_flow_attaches(self):
        src = """// header
flow FlowA() -> Out {
}"""
        flow = _parse(src).declarations[0]
        assert len(flow.leading_trivia) == 1
        assert flow.leading_trivia[0].kind == "line"
        assert not flow.leading_trivia[0].is_doc

    def test_block_doc_comment_before_flow_attaches(self):
        src = """/** Doc block */
flow FlowA() -> Out {
}"""
        flow = _parse(src).declarations[0]
        assert flow.leading_trivia[0].kind == "doc_block"
        assert flow.leading_trivia[0].is_doc

    def test_multiple_comments_all_collected(self):
        # Two doc-line comments preceding a flow are both collected as
        # leading trivia in source order.
        src = """/// First doc line
/// Second doc line
flow FlowA() -> Out {
}"""
        flow = _parse(src).declarations[0]
        assert len(flow.leading_trivia) == 2
        assert all(t.is_doc for t in flow.leading_trivia)
        assert flow.leading_trivia[0].text == "/// First doc line"
        assert flow.leading_trivia[1].text == "/// Second doc line"

    def test_three_flows_each_get_their_leading(self):
        # Per Roslyn convention, each flow gets the leading trivia
        # immediately preceding it. Comments separated by a flow do
        # not bleed across.
        src = """/// for A
flow A() -> Out { }
/// for B
flow B() -> Out { }
/// for C
flow C() -> Out { }"""
        prog = _parse(src)
        assert len(prog.declarations) == 3
        for i, name in enumerate(("A", "B", "C")):
            decl = prog.declarations[i]
            assert decl.name == name
            assert len(decl.leading_trivia) == 1
            assert decl.leading_trivia[0].text == f"/// for {name}"

    def test_no_trivia_when_no_comments(self):
        src = "flow FlowA() -> Out { }"
        flow = _parse(src).declarations[0]
        assert flow.leading_trivia == ()
        assert flow.trailing_trivia == ()


class TestParserAttachesTrailingTrivia:
    def test_trailing_comment_after_program_attaches_to_last_node(self):
        # A comment on the same line as the last effective token of a
        # node attaches as that token's trailing trivia. For a top-level
        # node whose last token is `}` and the comment follows on the
        # same line, the trailing channel of the AST node captures it.
        src = "flow A() -> Out { } // trailing on A's closing brace"
        flow = _parse(src).declarations[0]
        assert len(flow.trailing_trivia) == 1
        assert flow.trailing_trivia[0].text == "// trailing on A's closing brace"


class TestParserSeparation:
    def test_doc_then_regular_then_doc(self):
        src = """/// doc for A
flow A() -> Out { }

// header comment, separated by blank line
/// doc for B
flow B() -> Out { }"""
        prog = _parse(src)
        a, b = prog.declarations
        assert len(a.leading_trivia) == 1
        assert a.leading_trivia[0].text == "/// doc for A"
        # B's leading is the comments between A and B: header + doc.
        assert len(b.leading_trivia) == 2
        assert b.leading_trivia[0].text == "// header comment, separated by blank line"
        assert b.leading_trivia[1].text == "/// doc for B"


# ═══════════════════════════════════════════════════════════════════
#  14.a.5 — Backward-compat: existing test suites unaffected
# ═══════════════════════════════════════════════════════════════════


class TestBackwardCompat:
    def test_parsing_without_comments_unchanged(self):
        # The exact same source produces an AST whose top-level shape
        # matches the pre-14.a behaviour. Trivia tuples are empty and
        # AST nodes carry the same fields/values they always did.
        src = """persona Researcher {
    domain: ["physics"]
}
flow Investigate(topic: String) -> FactualClaim {
}"""
        prog = _parse(src)
        assert len(prog.declarations) == 2
        persona = prog.declarations[0]
        flow = prog.declarations[1]
        assert persona.name == "Researcher"
        assert flow.name == "Investigate"
        # No comments → all trivia empty.
        assert persona.leading_trivia == ()
        assert flow.leading_trivia == ()

    def test_pipeline_runs_with_interleaved_comments(self):
        # The trivia channel is an AST-level feature; downstream stages
        # walk AST without seeing trivia. This test checks the full
        # pipeline (lex → parse) completes on a non-trivial program
        # with comments interleaved at top-level.
        src = """/// Heart of the system
persona Auditor {
    domain: ["compliance"]
}
// Inline comment between declarations
flow Audit(report: String) -> FactualClaim {
}"""
        prog = _parse(src)
        # Trivia attached to the right top-level nodes.
        persona = prog.declarations[0]
        flow = prog.declarations[1]
        assert persona.name == "Auditor"
        assert flow.name == "Audit"
        # Persona's leading trivia: the doc-line preceding it.
        assert len(persona.leading_trivia) == 1
        assert persona.leading_trivia[0].is_doc
        # Flow's leading trivia: the regular line comment between them.
        assert len(flow.leading_trivia) == 1
        assert not flow.leading_trivia[0].is_doc
