"""
AXON Lexer — Unit Tests
========================
Verifies tokenization of all AXON language constructs.
"""

import pytest

from axon.compiler.lexer import Lexer
from axon.compiler.tokens import TokenType
from axon.compiler.errors import AxonLexerError


class TestKeywords:
    """Lexer correctly recognizes all 35 AXON keywords."""

    def test_cognitive_primitives(self):
        source = "persona context intent flow reason anchor validate refine memory tool probe weave"
        tokens = Lexer(source).tokenize()
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert types == [
            TokenType.PERSONA, TokenType.CONTEXT, TokenType.INTENT,
            TokenType.FLOW, TokenType.REASON, TokenType.ANCHOR,
            TokenType.VALIDATE, TokenType.REFINE, TokenType.MEMORY,
            TokenType.TOOL, TokenType.PROBE, TokenType.WEAVE,
        ]

    def test_flow_keywords(self):
        source = "step use given ask output"
        tokens = Lexer(source).tokenize()
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert types == [
            TokenType.STEP, TokenType.USE, TokenType.GIVEN,
            TokenType.ASK, TokenType.OUTPUT,
        ]

    def test_run_modifiers(self):
        source = "run as within constrained_by on_failure output_to effort"
        tokens = Lexer(source).tokenize()
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert types == [
            TokenType.RUN, TokenType.AS, TokenType.WITHIN,
            TokenType.CONSTRAINED_BY, TokenType.ON_FAILURE,
            TokenType.OUTPUT_TO, TokenType.EFFORT,
        ]

    def test_guard_keywords(self):
        source = "if else for against about into from where"
        tokens = Lexer(source).tokenize()
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert types == [
            TokenType.IF, TokenType.ELSE, TokenType.FOR,
            TokenType.AGAINST, TokenType.ABOUT, TokenType.INTO,
            TokenType.FROM, TokenType.WHERE,
        ]


class TestLiterals:
    """Lexer handles all literal types."""

    def test_string_simple(self):
        tokens = Lexer('"hello world"').tokenize()
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == "hello world"

    def test_string_with_escapes(self):
        tokens = Lexer(r'"line1\nline2\ttab"').tokenize()
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == "line1\nline2\ttab"

    def test_string_with_escaped_quote(self):
        tokens = Lexer(r'"say \"hello\""').tokenize()
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == 'say "hello"'

    def test_integer(self):
        tokens = Lexer("42").tokenize()
        assert tokens[0].type == TokenType.INTEGER
        assert tokens[0].value == "42"

    def test_float(self):
        tokens = Lexer("3.14").tokenize()
        assert tokens[0].type == TokenType.FLOAT
        assert tokens[0].value == "3.14"

    def test_float_leading_dot(self):
        """0.85 is a float."""
        tokens = Lexer("0.85").tokenize()
        assert tokens[0].type == TokenType.FLOAT
        assert tokens[0].value == "0.85"

    def test_duration(self):
        tokens = Lexer("10s 30m 2h 7d").tokenize()
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        values = [t.value for t in tokens if t.type != TokenType.EOF]
        assert types == [TokenType.DURATION] * 4
        assert values == ["10s", "30m", "2h", "7d"]

    def test_boolean(self):
        tokens = Lexer("true false").tokenize()
        assert tokens[0].type == TokenType.BOOL
        assert tokens[0].value == "true"
        assert tokens[1].type == TokenType.BOOL
        assert tokens[1].value == "false"


class TestSymbols:
    """Lexer recognizes all symbol tokens."""

    def test_braces_and_parens(self):
        tokens = Lexer("{ } ( ) [ ]").tokenize()
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert types == [
            TokenType.LBRACE, TokenType.RBRACE,
            TokenType.LPAREN, TokenType.RPAREN,
            TokenType.LBRACKET, TokenType.RBRACKET,
        ]

    def test_delimiters(self):
        tokens = Lexer(": , .").tokenize()
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert types == [TokenType.COLON, TokenType.COMMA, TokenType.DOT]

    def test_arrow(self):
        tokens = Lexer("->").tokenize()
        assert tokens[0].type == TokenType.ARROW

    def test_dotdot(self):
        tokens = Lexer("..").tokenize()
        assert tokens[0].type == TokenType.DOTDOT

    def test_comparison_operators(self):
        tokens = Lexer("< > <= >= == !=").tokenize()
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert types == [
            TokenType.LT, TokenType.GT, TokenType.LTE,
            TokenType.GTE, TokenType.EQ, TokenType.NEQ,
        ]

    def test_question_mark(self):
        tokens = Lexer("?").tokenize()
        assert tokens[0].type == TokenType.QUESTION

    def test_generics(self):
        tokens = Lexer("List<Party>").tokenize()
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert types == [
            TokenType.IDENTIFIER, TokenType.LT,
            TokenType.IDENTIFIER, TokenType.GT,
        ]


class TestIdentifiers:
    """Lexer handles identifiers vs keywords."""

    def test_simple_identifier(self):
        tokens = Lexer("LegalExpert").tokenize()
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "LegalExpert"

    def test_underscore_identifier(self):
        tokens = Lexer("source_citation").tokenize()
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "source_citation"

    def test_keyword_beats_identifier(self):
        """Keywords take priority over identifiers."""
        tokens = Lexer("persona").tokenize()
        assert tokens[0].type == TokenType.PERSONA


class TestComments:
    """Lexer emits comment tokens (Fase 14.a — was lossless-stripping pre-14.a).

    The four discriminated kinds are LINE_COMMENT / BLOCK_COMMENT /
    DOC_LINE_COMMENT / DOC_BLOCK_COMMENT. Callers that want the
    pre-14.a behaviour use ``Lexer.tokenize(strip_comments=True)``.
    """

    def test_single_line_comment(self):
        # Default behaviour (Fase 14.a): the comment is emitted as
        # LINE_COMMENT between PERSONA and IDENTIFIER.
        tokens = Lexer("persona // this is a comment\nLegalExpert").tokenize()
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert types == [TokenType.PERSONA, TokenType.LINE_COMMENT, TokenType.IDENTIFIER]

    def test_strip_comments_legacy_behaviour(self):
        # Opt-in pre-14.a behaviour: comment tokens are not emitted.
        tokens = Lexer("persona // dropped\nLegalExpert").tokenize(strip_comments=True)
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert types == [TokenType.PERSONA, TokenType.IDENTIFIER]


class TestLineColumn:
    """Lexer tracks line and column accurately."""

    def test_first_token_position(self):
        tokens = Lexer("persona").tokenize()
        assert tokens[0].line == 1
        assert tokens[0].column == 1

    def test_multi_line_positions(self):
        source = "persona\nflow"
        tokens = Lexer(source).tokenize()
        assert tokens[0].line == 1
        assert tokens[1].line == 2

    def test_eof_token(self):
        tokens = Lexer("").tokenize()
        assert tokens[-1].type == TokenType.EOF


class TestErrors:
    """Lexer raises clear errors for invalid input."""

    def test_unterminated_string(self):
        with pytest.raises(AxonLexerError, match="Unterminated string"):
            Lexer('"hello').tokenize()

    def test_unknown_character(self):
        with pytest.raises(AxonLexerError):
            Lexer("~").tokenize()


class TestComplexInput:
    """Lexer handles realistic AXON snippets."""

    def test_persona_block(self):
        source = '''persona LegalExpert {
  domain: ["contract law", "IP"]
  tone: precise
  confidence_threshold: 0.85
}'''
        tokens = Lexer(source).tokenize()
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert TokenType.PERSONA in types
        assert TokenType.LBRACE in types
        assert TokenType.RBRACE in types
        assert TokenType.STRING in types
        assert TokenType.FLOAT in types

    def test_flow_signature(self):
        source = "flow AnalyzeContract(doc: Document) -> ContractAnalysis {"
        tokens = Lexer(source).tokenize()
        assert tokens[0].type == TokenType.FLOW
        assert tokens[1].type == TokenType.IDENTIFIER
        assert tokens[2].type == TokenType.LPAREN
        # arrow
        arrow_tokens = [t for t in tokens if t.type == TokenType.ARROW]
        assert len(arrow_tokens) == 1

    def test_import_statement(self):
        source = "import axon.anchors.{NoHallucination, NoBias}"
        tokens = Lexer(source).tokenize()
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert types[0] == TokenType.IMPORT


class TestMultilineStrings:
    """Lexer handles multiline string literals (v0.24.2)."""

    def test_string_multiline(self):
        """Strings with embedded newlines are valid tokens."""
        source = '"line1\nline2\nline3"'
        tokens = Lexer(source).tokenize()
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == "line1\nline2\nline3"

    def test_string_multiline_tracks_lines(self):
        """Line counter advances correctly after multiline string."""
        source = '"first\nsecond"\npersona'
        tokens = Lexer(source).tokenize()
        # String starts at L1, spans to L2
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].line == 1
        # "persona" is on L3 (after the string's newline + the real newline)
        assert tokens[1].type == TokenType.PERSONA
        assert tokens[1].line == 3

    def test_string_multiline_with_escapes(self):
        """Multiline strings can contain escape sequences."""
        source = '"line1\\n still line1\nreal line2"'
        tokens = Lexer(source).tokenize()
        assert tokens[0].type == TokenType.STRING
        # \\n becomes literal \n, \n is real newline
        assert "\n" in tokens[0].value


class TestAtSymbol:
    """Lexer handles @ as AT token (v0.24.2)."""

    def test_at_produces_token(self):
        """@ character emits AT token."""
        tokens = Lexer("@").tokenize()
        assert tokens[0].type == TokenType.AT
        assert tokens[0].value == "@"

    def test_at_before_identifier(self):
        """@ followed by identifier produces two tokens."""
        tokens = Lexer("@axon").tokenize()
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert types == [TokenType.AT, TokenType.IDENTIFIER]

    def test_at_in_import_context(self):
        """@ in import context produces correct token sequence."""
        source = "import @axon.anchors.{NoHallucination}"
        tokens = Lexer(source).tokenize()
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert types[0] == TokenType.IMPORT
        assert types[1] == TokenType.AT
        assert types[2] == TokenType.IDENTIFIER  # axon
