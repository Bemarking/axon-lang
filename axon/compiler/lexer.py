"""
AXON Compiler — Lexer
======================
Hand-written, single-pass character scanner.

Source (.axon text) → list[Token]

Features:
  - Keyword vs identifier discrimination via lookup table
  - String literals with escape sequences
  - Integer / Float / Duration literals
  - Arrow (->) and range (..) as single tokens
  - Lossless comment lexing (Fase 14.a) — comments are emitted as
    discriminated ``LINE_COMMENT`` / ``BLOCK_COMMENT`` /
    ``DOC_LINE_COMMENT`` / ``DOC_BLOCK_COMMENT`` tokens preserving
    full text + position. The parser materialises them into ``Trivia``
    attached to AST nodes (leading + trailing). Pre-14.a behaviour
    (comment stripping) is reachable via ``Lexer.tokenize(strip_comments=True)``
    so callers that want the legacy IR-equivalent token stream still
    get it without filtering.
  - Line/column tracking for error messages
"""

from __future__ import annotations

from .errors import AxonLexerError
from .tokens import KEYWORDS, Token, TokenType


class Lexer:
    """Tokenizes AXON source code into a stream of Token objects."""

    def __init__(self, source: str, filename: str = "<stdin>"):
        self._source = source
        self._filename = filename
        self._pos = 0
        self._line = 1
        self._column = 1
        self._tokens: list[Token] = []

    # ── public API ────────────────────────────────────────────────

    def tokenize(self, *, strip_comments: bool = False) -> list[Token]:
        """Scan the entire source and return all tokens.

        Args:
            strip_comments: when ``True``, comment tokens are not
                emitted (legacy pre-14.a behaviour). Default ``False``
                preserves comments as discriminated tokens (Fase 14.a)
                so the parser can materialise them into ``Trivia`` on
                AST nodes. The parser itself always tolerates either
                shape — ``strip_comments=True`` is for downstream
                tooling that treats comments as pure whitespace.
        """
        self._strip_comments = strip_comments
        while not self._at_end():
            self._consume_trivia()
            if self._at_end():
                break
            self._scan_token()
        self._tokens.append(Token(TokenType.EOF, "", self._line, self._column))
        return self._tokens

    # ── character helpers ─────────────────────────────────────────

    def _at_end(self) -> bool:
        return self._pos >= len(self._source)

    def _peek(self) -> str:
        if self._at_end():
            return "\0"
        return self._source[self._pos]

    def _peek_next(self) -> str:
        if self._pos + 1 >= len(self._source):
            return "\0"
        return self._source[self._pos + 1]

    def _advance(self) -> str:
        ch = self._source[self._pos]
        self._pos += 1
        if ch == "\n":
            self._line += 1
            self._column = 1
        else:
            self._column += 1
        return ch

    def _match(self, expected: str) -> bool:
        """Advance if the current char matches expected."""
        if self._at_end() or self._source[self._pos] != expected:
            return False
        self._advance()
        return True

    # ── whitespace & comments (Fase 14.a — lossless) ──────────────

    def _consume_trivia(self) -> None:
        """Consume whitespace + emit comment tokens until next non-trivia.

        Pre-14.a this routine was named ``_skip_whitespace`` and silently
        discarded comments. Now it advances past pure whitespace but
        for comments delegates to ``_consume_*_comment`` which emit
        discriminated tokens. ``strip_comments=True`` on ``tokenize``
        suppresses the emission while preserving the cursor advance.
        """
        while not self._at_end():
            ch = self._peek()
            if ch in (" ", "\t", "\r", "\n"):
                self._advance()
            elif ch == "/" and self._peek_next() == "/":
                self._consume_line_comment()
            elif ch == "/" and self._peek_next() == "*":
                self._consume_block_comment()
            else:
                break

    def _consume_line_comment(self) -> None:
        """Lex a ``// …`` or ``/// …`` line comment.

        Doc-comment heuristic: a line is a doc comment iff it starts
        with EXACTLY three slashes (``///`` followed by a non-``/``).
        ``////`` (4+ slashes) is a regular line comment by Rust
        convention — keeps the discriminator stable when the user
        writes a banner like ``//// section ////``.
        """
        line = self._line
        col = self._column
        # consume //
        self._advance()
        self._advance()
        is_doc = self._peek() == "/" and self._peek_next() != "/"
        if is_doc:
            self._advance()  # consume the third /

        body_start = self._pos
        while not self._at_end() and self._peek() != "\n":
            self._advance()
        body = self._source[body_start:self._pos]

        if is_doc:
            full_text = "///" + body
            kind = TokenType.DOC_LINE_COMMENT
        else:
            full_text = "//" + body
            kind = TokenType.LINE_COMMENT

        if not getattr(self, "_strip_comments", False):
            self._emit(kind, full_text, line, col)

    def _consume_block_comment(self) -> None:
        """Lex a ``/* … */`` or ``/** … */`` block comment.

        Doc-comment heuristic: a block is a doc comment iff it starts
        with exactly ``/**`` followed by a non-``/`` character. ``/**/``
        (empty block) and ``/***`` (which would be ``/* ** /`` parsed as
        a regular block whose body opens with two stars) are regular.
        """
        line = self._line
        col = self._column
        # consume /*
        self._advance()
        self._advance()
        is_doc = (
            self._peek() == "*"
            and self._peek_next() != "/"  # /**/ is empty regular, not doc
        )
        if is_doc:
            self._advance()  # consume the second *

        body_start = self._pos
        while not self._at_end():
            if self._peek() == "*" and self._peek_next() == "/":
                body = self._source[body_start:self._pos]
                self._advance()  # *
                self._advance()  # /
                if is_doc:
                    full_text = "/**" + body + "*/"
                    kind = TokenType.DOC_BLOCK_COMMENT
                else:
                    full_text = "/*" + body + "*/"
                    kind = TokenType.BLOCK_COMMENT
                if not getattr(self, "_strip_comments", False):
                    self._emit(kind, full_text, line, col)
                return
            self._advance()
        raise AxonLexerError(
            "Unterminated block comment",
            line=line,
            column=col,
        )

    # ── main scanner dispatch ─────────────────────────────────────

    def _scan_token(self) -> None:
        line = self._line
        col = self._column
        ch = self._advance()

        match ch:
            # single-character symbols
            case "{":
                self._emit(TokenType.LBRACE, "{", line, col)
            case "}":
                self._emit(TokenType.RBRACE, "}", line, col)
            case "(":
                self._emit(TokenType.LPAREN, "(", line, col)
            case ")":
                self._emit(TokenType.RPAREN, ")", line, col)
            case "[":
                self._emit(TokenType.LBRACKET, "[", line, col)
            case "]":
                self._emit(TokenType.RBRACKET, "]", line, col)
            case ":":
                self._emit(TokenType.COLON, ":", line, col)
            case ",":
                self._emit(TokenType.COMMA, ",", line, col)
            case "?":
                self._emit(TokenType.QUESTION, "?", line, col)

            # dot or dotdot (..)
            case ".":
                if self._match("."):
                    self._emit(TokenType.DOTDOT, "..", line, col)
                else:
                    self._emit(TokenType.DOT, ".", line, col)

            # arrow (->) or minus
            case "-":
                if self._match(">"):
                    self._emit(TokenType.ARROW, "->", line, col)
                else:
                    # standalone minus — treat as part of a number if next is digit
                    if not self._at_end() and self._peek().isdigit():
                        self._scan_number(line, col, negative=True)
                    else:
                        self._emit(TokenType.MINUS, "-", line, col)

            # arithmetic operators (Compute primitive §CM)
            case "+":
                self._emit(TokenType.PLUS, "+", line, col)
            case "*":
                self._emit(TokenType.STAR, "*", line, col)
            case "/":
                self._emit(TokenType.SLASH, "/", line, col)

            # comparison operators
            case "<":
                if self._match("="):
                    self._emit(TokenType.LTE, "<=", line, col)
                else:
                    self._emit(TokenType.LT, "<", line, col)
            case ">":
                if self._match("="):
                    self._emit(TokenType.GTE, ">=", line, col)
                else:
                    self._emit(TokenType.GT, ">", line, col)
            case "=":
                if self._match("="):
                    self._emit(TokenType.EQ, "==", line, col)
                else:
                    self._emit(TokenType.ASSIGN, "=", line, col)
            case "!":
                if self._match("="):
                    self._emit(TokenType.NEQ, "!=", line, col)
                else:
                    raise AxonLexerError(
                        "Unexpected '!'. Did you mean '!='?",
                        line=line,
                        column=col,
                    )

            # string literal
            case '"':
                self._scan_string(line, col)

            # @ scope operator (topological functor for EMS imports)
            case "@":
                self._emit(TokenType.AT, "@", line, col)

            case _:
                # numbers
                if ch.isdigit():
                    self._scan_number(line, col, first_char=ch)
                # identifiers & keywords
                elif ch.isalpha() or ch == "_":
                    self._scan_identifier(line, col, first_char=ch)
                else:
                    raise AxonLexerError(
                        f"Unexpected character {ch!r}",
                        line=line,
                        column=col,
                    )

    # ── literal scanners ──────────────────────────────────────────

    def _scan_string(self, start_line: int, start_col: int) -> None:
        """Scan a double-quoted string literal with escape support."""
        chars: list[str] = []
        while not self._at_end() and self._peek() != '"':
            if self._peek() == "\n":
                chars.append(self._advance())
                continue
            if self._peek() == "\\":
                self._advance()  # consume backslash
                if self._at_end():
                    raise AxonLexerError(
                        "Unterminated escape sequence",
                        line=self._line,
                        column=self._column,
                    )
                esc = self._advance()
                match esc:
                    case "n":
                        chars.append("\n")
                    case "t":
                        chars.append("\t")
                    case "\\":
                        chars.append("\\")
                    case '"':
                        chars.append('"')
                    case _:
                        chars.append(esc)
            else:
                chars.append(self._advance())

        if self._at_end():
            raise AxonLexerError(
                "Unterminated string",
                line=start_line,
                column=start_col,
            )
        self._advance()  # consume closing "
        self._emit(TokenType.STRING, "".join(chars), start_line, start_col)

    def _scan_number(
        self,
        start_line: int,
        start_col: int,
        first_char: str = "",
        negative: bool = False,
    ) -> None:
        """Scan an integer, float, or duration literal."""
        digits: list[str] = []
        if negative:
            digits.append("-")
        if first_char:
            digits.append(first_char)

        # consume integer part
        while not self._at_end() and self._peek().isdigit():
            digits.append(self._advance())

        is_float = False

        # check for decimal point (but not range operator ..)
        if (
            not self._at_end()
            and self._peek() == "."
            and self._peek_next() != "."
        ):
            is_float = True
            digits.append(self._advance())  # consume '.'
            if self._at_end() or not self._peek().isdigit():
                raise AxonLexerError(
                    "Expected digit after decimal point",
                    line=self._line,
                    column=self._column,
                )
            while not self._at_end() and self._peek().isdigit():
                digits.append(self._advance())

        raw = "".join(digits)

        # check for duration suffix
        if not self._at_end() and self._peek().isalpha():
            suffix_start = self._pos
            suffix = ""
            while not self._at_end() and self._peek().isalpha():
                suffix += self._advance()

            if suffix in ("s", "ms", "m", "h", "d"):
                self._emit(
                    TokenType.DURATION, raw + suffix, start_line, start_col
                )
                return
            else:
                # not a duration — rewind
                self._pos = suffix_start
                self._column -= len(suffix)

        if is_float:
            self._emit(TokenType.FLOAT, raw, start_line, start_col)
        else:
            self._emit(TokenType.INTEGER, raw, start_line, start_col)

    def _scan_identifier(
        self, start_line: int, start_col: int, first_char: str = ""
    ) -> None:
        """Scan an identifier or keyword."""
        chars: list[str] = [first_char]

        while not self._at_end() and (
            self._peek().isalnum() or self._peek() == "_"
        ):
            chars.append(self._advance())

        word = "".join(chars)

        # keyword lookup
        token_type = KEYWORDS.get(word, TokenType.IDENTIFIER)
        self._emit(token_type, word, start_line, start_col)

    # ── emit helper ───────────────────────────────────────────────

    def _emit(
        self, token_type: TokenType, value: str, line: int, col: int
    ) -> None:
        self._tokens.append(Token(token_type, value, line, col))
