"""Stable frontend facade for AXON source analysis and compilation.

This module provides the narrow boundary that CLI adapters consume during
Phase B. It centralizes the current Python frontend pipeline so a future
native implementation can replace it behind the same interface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Protocol

from .ast_nodes import ProgramNode
from .errors import AxonError, AxonLexerError, AxonTypeError
from .ir_generator import IRGenerator
from .ir_nodes import IRAnchor, IRAxonStore, IRCompute, IRContext, IRDataSpace, IREndpoint, IRFlow, IRImport, IRIntent, IRMemory, IRParameter, IRPersona, IRProgram, IRRun, IRShield, IRStep, IRToolSpec, IRType, IRTypeField
from .lexer import Lexer
from .parser import Parser
from .tokens import KEYWORDS, Token, TokenType
from .type_checker import (
    TypeChecker,
    VALID_DEPTHS,
    VALID_MEMORY_SCOPES,
    VALID_RETRIEVAL_STRATEGIES,
    VALID_TONES,
    VALID_VIOLATION_ACTIONS,
)


@dataclass(frozen=True)
class FrontendDiagnostic:
    """Structured diagnostic exposed by the frontend boundary."""

    stage: str
    message: str
    line: int = 0
    column: int = 0


@dataclass(frozen=True)
class FrontendCheckResult:
    """Result of running the frontend through type checking."""

    token_count: int
    declaration_count: int
    diagnostics: tuple[FrontendDiagnostic, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.diagnostics


@dataclass(frozen=True)
class FrontendCompileResult:
    """Result of compiling AXON source through IR generation."""

    token_count: int
    declaration_count: int
    diagnostics: tuple[FrontendDiagnostic, ...] = ()
    ir_program: IRProgram | None = None

    @property
    def ok(self) -> bool:
        return self.ir_program is not None and not self.diagnostics


@dataclass(frozen=True)
class _AnalysisResult:
    token_count: int
    declaration_count: int
    diagnostics: tuple[FrontendDiagnostic, ...] = ()
    ast: ProgramNode | None = None


class FrontendImplementation(Protocol):
    """Backend contract for frontend implementations.

    This is the replacement seam for the current Python pipeline and any
    future native frontend.
    """

    def check_source(self, source: str, filename: str) -> FrontendCheckResult:
        """Run source through the frontend check pipeline."""

    def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
        """Run source through the full frontend compilation pipeline."""


class PythonFrontendImplementation:
    """Default Python-backed implementation of the frontend contract."""

    def check_source(self, source: str, filename: str) -> FrontendCheckResult:
        analysis = self._analyze_source(source, filename)
        return FrontendCheckResult(
            token_count=analysis.token_count,
            declaration_count=analysis.declaration_count,
            diagnostics=analysis.diagnostics,
        )

    def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
        analysis = self._analyze_source(source, filename)
        if analysis.diagnostics or analysis.ast is None:
            return FrontendCompileResult(
                token_count=analysis.token_count,
                declaration_count=analysis.declaration_count,
                diagnostics=analysis.diagnostics,
                ir_program=None,
            )

        try:
            ir_program = IRGenerator().generate(analysis.ast)
        except Exception as exc:
            return FrontendCompileResult(
                token_count=analysis.token_count,
                declaration_count=analysis.declaration_count,
                diagnostics=(
                    FrontendDiagnostic(
                        stage="ir_generator",
                        message=str(exc),
                    ),
                ),
                ir_program=None,
            )

        return FrontendCompileResult(
            token_count=analysis.token_count,
            declaration_count=analysis.declaration_count,
            diagnostics=(),
            ir_program=ir_program,
        )

    def _analyze_source(self, source: str, filename: str) -> _AnalysisResult:
        try:
            tokens = Lexer(source, filename=filename).tokenize()
        except AxonLexerError as exc:
            return _AnalysisResult(
                token_count=0,
                declaration_count=0,
                diagnostics=(self._diagnostic_from_error("lexer", exc),),
            )

        token_count = len(tokens)

        try:
            ast = Parser(tokens).parse()
        except AxonError as exc:
            return _AnalysisResult(
                token_count=token_count,
                declaration_count=0,
                diagnostics=(self._diagnostic_from_error("parser", exc),),
            )

        declaration_count = len(ast.declarations) if hasattr(ast, "declarations") else 0
        type_errors = TypeChecker(ast).check()

        if type_errors:
            return _AnalysisResult(
                token_count=token_count,
                declaration_count=declaration_count,
                diagnostics=tuple(
                    FrontendDiagnostic(
                        stage="type_checker",
                        message=error.message,
                        line=error.line,
                        column=error.column,
                    )
                    for error in type_errors
                ),
                ast=ast,
            )

        return _AnalysisResult(
            token_count=token_count,
            declaration_count=declaration_count,
            diagnostics=(),
            ast=ast,
        )

    @staticmethod
    def _diagnostic_from_error(stage: str, error: AxonError) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage=stage,
            message=error.message,
            line=error.line,
            column=error.column,
        )


class NativeFrontendPlaceholder:
    """Placeholder implementation reserved for the future native frontend."""

    def check_source(self, source: str, filename: str) -> FrontendCheckResult:
        del source, filename
        return FrontendCheckResult(
            token_count=0,
            declaration_count=0,
            diagnostics=(
                FrontendDiagnostic(
                    stage="parser",
                    message=(
                        "Native frontend placeholder is not implemented yet. "
                        "Select 'python' or provide a native implementation backend."
                    ),
                ),
            ),
        )

    def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
        del source, filename
        return FrontendCompileResult(
            token_count=0,
            declaration_count=0,
            diagnostics=(
                FrontendDiagnostic(
                    stage="ir_generator",
                    message=(
                        "Native frontend placeholder is not implemented yet. "
                        "Select 'python' or provide a native implementation backend."
                    ),
                ),
            ),
            ir_program=None,
        )


class _NativeDevelopmentPrefixLexer:
    """Small native-dev lexer slice used to scan the first significant token."""

    _SINGLE_CHAR_TOKENS = {
        "{": TokenType.LBRACE,
        "}": TokenType.RBRACE,
        "(": TokenType.LPAREN,
        ")": TokenType.RPAREN,
        "[": TokenType.LBRACKET,
        "]": TokenType.RBRACKET,
        ":": TokenType.COLON,
        ",": TokenType.COMMA,
        "?": TokenType.QUESTION,
        "+": TokenType.PLUS,
        "*": TokenType.STAR,
        "/": TokenType.SLASH,
        "@": TokenType.AT,
    }

    def __init__(self, source: str) -> None:
        self._source = source
        self._pos = 0
        self._line = 1
        self._column = 1

    def scan_token_window(self, limit: int) -> tuple[Token, ...]:
        tokens: list[Token] = []
        while len(tokens) < limit:
            self._skip_whitespace()
            if self._at_end():
                break
            tokens.append(self._scan_token())
        return tuple(tokens)

    def scan_all_tokens(self) -> tuple[Token, ...]:
        tokens: list[Token] = []
        while True:
            self._skip_whitespace()
            if self._at_end():
                break
            tokens.append(self._scan_token())
        return tuple(tokens)

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
        if self._at_end() or self._source[self._pos] != expected:
            return False
        self._advance()
        return True

    def _skip_whitespace(self) -> None:
        while not self._at_end():
            ch = self._peek()
            if ch in (" ", "\t", "\r", "\n"):
                self._advance()
            elif ch == "/" and self._peek_next() == "/":
                self._skip_line_comment()
            elif ch == "/" and self._peek_next() == "*":
                self._skip_block_comment()
            else:
                return

    def _skip_line_comment(self) -> None:
        self._advance()
        self._advance()
        while not self._at_end() and self._peek() != "\n":
            self._advance()

    def _skip_block_comment(self) -> None:
        start_line = self._line
        start_col = self._column
        self._advance()
        self._advance()
        while not self._at_end():
            if self._peek() == "*" and self._peek_next() == "/":
                self._advance()
                self._advance()
                return
            self._advance()
        raise AxonLexerError(
            "Unterminated block comment",
            line=start_line,
            column=start_col,
        )

    def _scan_token(self) -> Token:
        line = self._line
        col = self._column
        ch = self._advance()

        token_type = self._SINGLE_CHAR_TOKENS.get(ch)
        if token_type is not None:
            return Token(token_type, ch, line, col)

        match ch:
            case ".":
                return self._scan_dot_token(line, col)
            case "-":
                return self._scan_minus_token(line, col)
            case "<":
                return self._scan_comparison_token("=", TokenType.LTE, TokenType.LT, "<", line, col)
            case ">":
                return self._scan_comparison_token("=", TokenType.GTE, TokenType.GT, ">", line, col)
            case "=":
                return self._scan_comparison_token("=", TokenType.EQ, TokenType.ASSIGN, "=", line, col)
            case "!":
                return self._scan_bang_token(line, col)
            case '"':
                return self._scan_string(line, col)
            case _:
                return self._scan_dynamic_token(ch, line, col)

    def _scan_dot_token(self, line: int, col: int) -> Token:
        if self._match("."):
            return Token(TokenType.DOTDOT, "..", line, col)
        return Token(TokenType.DOT, ".", line, col)

    def _scan_minus_token(self, line: int, col: int) -> Token:
        if self._match(">"):
            return Token(TokenType.ARROW, "->", line, col)
        if not self._at_end() and self._peek().isdigit():
            return self._scan_number(line, col, negative=True)
        return Token(TokenType.MINUS, "-", line, col)

    def _scan_comparison_token(
        self,
        expected: str,
        matched_type: TokenType,
        fallback_type: TokenType,
        fallback_value: str,
        line: int,
        col: int,
    ) -> Token:
        if self._match(expected):
            return Token(matched_type, fallback_value + expected, line, col)
        return Token(fallback_type, fallback_value, line, col)

    def _scan_bang_token(self, line: int, col: int) -> Token:
        if self._match("="):
            return Token(TokenType.NEQ, "!=", line, col)
        raise AxonLexerError(
            "Unexpected '!'. Did you mean '!='?",
            line=line,
            column=col,
        )

    def _scan_dynamic_token(self, ch: str, line: int, col: int) -> Token:
        if ch.isdigit():
            return self._scan_number(line, col, first_char=ch)
        if ch.isalpha() or ch == "_":
            return self._scan_identifier(line, col, first_char=ch)
        raise AxonLexerError(
            f"Unexpected character {ch!r}",
            line=line,
            column=col,
        )

    def _scan_string(self, start_line: int, start_col: int) -> Token:
        chars: list[str] = []
        while not self._at_end() and self._peek() != '"':
            if self._peek() == "\n":
                chars.append(self._advance())
                continue
            if self._peek() == "\\":
                self._advance()
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

        self._advance()
        return Token(TokenType.STRING, "".join(chars), start_line, start_col)

    def _scan_number(
        self,
        start_line: int,
        start_col: int,
        first_char: str = "",
        negative: bool = False,
    ) -> Token:
        raw = self._scan_integer_portion(first_char=first_char, negative=negative)
        raw, is_float = self._scan_fractional_portion(raw)

        duration_token = self._scan_duration_suffix(raw, start_line, start_col)
        if duration_token is not None:
            return duration_token

        if is_float:
            return Token(TokenType.FLOAT, raw, start_line, start_col)
        return Token(TokenType.INTEGER, raw, start_line, start_col)

    def _scan_integer_portion(self, first_char: str = "", negative: bool = False) -> str:
        digits: list[str] = []
        if negative:
            digits.append("-")
        if first_char:
            digits.append(first_char)
        digits.append(self._consume_digits())
        return "".join(digits)

    def _consume_digits(self) -> str:
        digits: list[str] = []
        while not self._at_end() and self._peek().isdigit():
            digits.append(self._advance())
        return "".join(digits)

    def _scan_fractional_portion(self, raw: str) -> tuple[str, bool]:
        if self._at_end() or self._peek() != "." or self._peek_next() == ".":
            return raw, False

        fractional = self._advance()
        if self._at_end() or not self._peek().isdigit():
            raise AxonLexerError(
                "Expected digit after decimal point",
                line=self._line,
                column=self._column,
            )

        fractional += self._consume_digits()
        return raw + fractional, True

    def _scan_duration_suffix(self, raw: str, start_line: int, start_col: int) -> Token | None:
        if self._at_end() or not self._peek().isalpha():
            return None

        suffix_start = self._pos
        suffix_column = self._column
        suffix = ""
        while not self._at_end() and self._peek().isalpha():
            suffix += self._advance()

        if suffix in ("s", "ms", "m", "h", "d"):
            return Token(TokenType.DURATION, raw + suffix, start_line, start_col)

        self._pos = suffix_start
        self._column = suffix_column
        return None

    def _scan_identifier(self, start_line: int, start_col: int, first_char: str = "") -> Token:
        chars: list[str] = [first_char]

        while not self._at_end() and (self._peek().isalnum() or self._peek() == "_"):
            chars.append(self._advance())

        word = "".join(chars)
        return Token(KEYWORDS.get(word, TokenType.IDENTIFIER), word, start_line, start_col)


class NativeDevelopmentFrontendImplementation:
    """Development-native selector path backed by the Python frontend.

    This implementation is intentionally not a real native compiler yet.
    It exists to exercise the selection, bootstrap, and compatibility path
    for a future native frontend while preserving the frozen frontend contract.
    """

    _ALLOWED_TOP_LEVEL_STARTS = frozenset({
        "import",
        "persona",
        "context",
        "anchor",
        "memory",
        "tool",
        "type",
        "flow",
        "intent",
        "run",
        "know",
        "believe",
        "speculate",
        "doubt",
        "dataspace",
        "ingest",
        "agent",
        "shield",
        "pix",
        "corpus",
        "psyche",
        "ots",
        "mandate",
        "compute",
        "lambda",
        "daemon",
        "axonstore",
        "axonendpoint",
        "persist",
        "retrieve",
        "mutate",
        "purge",
        "transact",
        "let",
    })
    _EXPECTED_DECLARATION = (
        "declaration (persona, context, anchor, flow, agent, shield, psyche, "
        "pix, ots, mandate, lambda, daemon, axonstore, run, know, speculate, ...)"
    )
    _SIGNATURE_WINDOW_RULES = {
        "persona": TokenType.LBRACE,
        "context": TokenType.LBRACE,
        "anchor": TokenType.LBRACE,
        "memory": TokenType.LBRACE,
        "tool": TokenType.LBRACE,
        "intent": TokenType.LBRACE,
        "flow": TokenType.LPAREN,
        "run": TokenType.LPAREN,
        "agent": TokenType.LBRACE,
        "shield": TokenType.LBRACE,
        "pix": TokenType.LBRACE,
        "corpus": TokenType.LBRACE,
        "psyche": TokenType.LBRACE,
        "ots": TokenType.LBRACE,
        "mandate": TokenType.LBRACE,
        "compute": TokenType.LBRACE,
        "lambda": TokenType.LBRACE,
        "daemon": TokenType.LBRACE,
        "dataspace": TokenType.LBRACE,
        "axonstore": TokenType.LBRACE,
        "axonendpoint": TokenType.LBRACE,
    }
    _BLOCK_FIELD_HEADER_RULES = frozenset({
        "persona",
        "context",
        "anchor",
        "memory",
        "tool",
        "intent",
        "agent",
        "shield",
        "pix",
        "corpus",
        "psyche",
        "ots",
        "mandate",
        "compute",
        "lambda",
        "daemon",
        "axonstore",
        "axonendpoint",
    })
    _IDENTIFIER_LIKE_FIRST_FIELDS = frozenset({
        "tone",
        "memory",
        "depth",
        "require",
        "enforce",
        "store",
        "backend",
        "retrieval",
        "provider",
        "runtime",
        "method",
    })
    _BOOL_FIRST_FIELDS = frozenset({
        "cite_sources",
        "sandbox",
        "quantum",
        "inference",
    })
    _AXONENDPOINT_FIELD_TO_IR_ATTR = {
        "method": "method",
        "path": "path",
        "execute": "execute_flow",
        "body": "body_type",
        "output": "output_type",
        "shield": "shield_ref",
        "timeout": "timeout",
        "retries": "retries",
    }
    _AXONENDPOINT_SUPPORTED_FIELD_SETS = (
        frozenset({"method", "path", "execute"}),
        frozenset({"method", "path", "execute", "output"}),
        frozenset({"method", "path", "execute", "body", "shield"}),
        frozenset({"method", "path", "execute", "body", "shield", "timeout"}),
        frozenset({"method", "path", "execute", "body", "shield", "retries"}),
        frozenset({"method", "path", "execute", "output", "shield", "timeout"}),
        frozenset({"method", "path", "execute", "output", "shield", "retries"}),
        frozenset({"method", "path", "execute", "output", "retries", "timeout"}),
        frozenset({"method", "path", "execute", "body", "retries", "timeout"}),
        frozenset({"method", "path", "execute", "body", "output", "timeout"}),
        frozenset({"method", "path", "execute", "body", "output", "retries"}),
        frozenset({"method", "path", "execute", "body", "output", "shield"}),
        frozenset({"method", "path", "execute", "body", "output"}),
        frozenset({"method", "path", "execute", "body", "timeout"}),
        frozenset({"method", "path", "execute", "body", "retries"}),
        frozenset({"method", "path", "execute", "output", "retries"}),
        frozenset({"method", "path", "execute", "shield", "retries"}),
        frozenset({"method", "path", "execute", "output", "timeout"}),
        frozenset({"method", "path", "execute", "shield", "timeout"}),
        frozenset({"method", "path", "execute", "output", "shield"}),
        frozenset({"method", "path", "execute", "retries", "timeout"}),
        frozenset({"method", "path", "execute", "timeout"}),
        frozenset({"method", "path", "execute", "retries"}),
        frozenset({"method", "path", "execute", "body"}),
        frozenset({"method", "path", "execute", "shield"}),
    )
    _AXONENDPOINT_SUPPORTED_FIELDS = frozenset().union(*_AXONENDPOINT_SUPPORTED_FIELD_SETS)

    _SHIELD_SUPPORTED_FIELDS = frozenset({
        "strategy", "on_breach", "severity", "quarantine", "log",
        "max_retries", "sandbox", "confidence_threshold",
    })
    _SHIELD_FIELD_TO_IR_ATTR: dict[str, str] = {
        "strategy": "strategy",
        "on_breach": "on_breach",
        "severity": "severity",
        "quarantine": "quarantine",
        "log": "log",
        "max_retries": "max_retries",
        "sandbox": "sandbox",
        "confidence_threshold": "confidence_threshold",
    }

    _COMPUTE_SUPPORTED_FIELDS = frozenset({
        "output", "shield", "verified",
    })
    _COMPUTE_FIELD_TO_IR_ATTR: dict[str, str] = {
        "output": "output_type",
        "shield": "shield_ref",
        "verified": "verified",
    }

    _AXONSTORE_SUPPORTED_FIELDS = frozenset({
        "backend", "connection", "confidence_floor", "isolation", "on_breach",
    })
    _AXONSTORE_FIELD_TO_IR_ATTR: dict[str, str] = {
        "backend": "backend",
        "connection": "connection",
        "confidence_floor": "confidence_floor",
        "isolation": "isolation",
        "on_breach": "on_breach",
    }

    def __init__(self, delegate: PythonFrontendImplementation | None = None) -> None:
        self._delegate = delegate or PythonFrontendImplementation()

    def check_source(self, source: str, filename: str) -> FrontendCheckResult:
        native_success_result = self._check_native_success_subset(source)
        if native_success_result is not None:
            return native_success_result
        native_type_duplicate_result = self._check_native_type_duplicate_subset(source)
        if native_type_duplicate_result is not None:
            return native_type_duplicate_result
        native_type_validation_result = self._check_native_type_validation_subset(source)
        if native_type_validation_result is not None:
            return native_type_validation_result
        native_duplicate_declaration_result = self._check_structural_duplicate_declaration_subset(source)
        if native_duplicate_declaration_result is not None:
            return native_duplicate_declaration_result
        native_validation_result = self._check_structural_validation_subset(source)
        if native_validation_result is not None:
            return native_validation_result
        native_run_result = self._check_isolated_run_subset(source)
        if native_run_result is not None:
            return native_run_result
        diagnostic = self._preparse_top_level(source)
        if diagnostic is not None:
            return FrontendCheckResult(
                token_count=0,
                declaration_count=0,
                diagnostics=(diagnostic,),
            )
        return self._delegate.check_source(source, filename)

    def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
        native_success_result = self._compile_native_success_subset(source)
        if native_success_result is not None:
            return native_success_result
        native_type_duplicate_result = self._compile_native_type_duplicate_subset(source)
        if native_type_duplicate_result is not None:
            return native_type_duplicate_result
        native_type_validation_result = self._compile_native_type_validation_subset(source)
        if native_type_validation_result is not None:
            return native_type_validation_result
        native_duplicate_declaration_result = self._compile_structural_duplicate_declaration_subset(source)
        if native_duplicate_declaration_result is not None:
            return native_duplicate_declaration_result
        native_validation_result = self._compile_structural_validation_subset(source)
        if native_validation_result is not None:
            return native_validation_result
        native_run_result = self._compile_isolated_run_subset(source)
        if native_run_result is not None:
            return native_run_result
        diagnostic = self._preparse_top_level(source)
        if diagnostic is not None:
            return FrontendCompileResult(
                token_count=0,
                declaration_count=0,
                diagnostics=(diagnostic,),
                ir_program=None,
            )
        return self._delegate.compile_source(source, filename)

    @classmethod
    def _check_native_success_subset(cls, source: str) -> FrontendCheckResult | None:
        match = cls._match_native_success_program(source)
        if match is None:
            return None
        _, token_count, declaration_count = match
        return FrontendCheckResult(
            token_count=token_count,
            declaration_count=declaration_count,
            diagnostics=(),
        )

    @classmethod
    def _compile_native_success_subset(cls, source: str) -> FrontendCompileResult | None:
        match = cls._match_native_success_program(source)
        if match is None:
            return None
        ir_program, token_count, declaration_count = match
        return FrontendCompileResult(
            token_count=token_count,
            declaration_count=declaration_count,
            diagnostics=(),
            ir_program=ir_program,
        )

    @classmethod
    def _check_native_type_duplicate_subset(cls, source: str) -> FrontendCheckResult | None:
        match = cls._match_native_type_duplicate_program(source)
        if match is None:
            return None
        diagnostics, token_count, declaration_count = match
        return FrontendCheckResult(
            token_count=token_count,
            declaration_count=declaration_count,
            diagnostics=diagnostics,
        )

    @classmethod
    def _compile_native_type_duplicate_subset(cls, source: str) -> FrontendCompileResult | None:
        match = cls._match_native_type_duplicate_program(source)
        if match is None:
            return None
        diagnostics, token_count, declaration_count = match
        return FrontendCompileResult(
            token_count=token_count,
            declaration_count=declaration_count,
            diagnostics=diagnostics,
            ir_program=None,
        )

    @classmethod
    def _check_native_type_validation_subset(cls, source: str) -> FrontendCheckResult | None:
        match = cls._match_native_type_validation_program(source)
        if match is None:
            return None
        diagnostics, token_count, declaration_count = match
        return FrontendCheckResult(
            token_count=token_count,
            declaration_count=declaration_count,
            diagnostics=diagnostics,
        )

    @classmethod
    def _compile_native_type_validation_subset(cls, source: str) -> FrontendCompileResult | None:
        match = cls._match_native_type_validation_program(source)
        if match is None:
            return None
        diagnostics, token_count, declaration_count = match
        return FrontendCompileResult(
            token_count=token_count,
            declaration_count=declaration_count,
            diagnostics=diagnostics,
            ir_program=None,
        )

    @classmethod
    def _check_isolated_run_subset(cls, source: str) -> FrontendCheckResult | None:
        match = cls._match_native_run_subset(source)
        if match is None:
            return None
        run_name, token_count, declaration_count = match
        return FrontendCheckResult(
            token_count=token_count,
            declaration_count=declaration_count,
            diagnostics=(
                FrontendDiagnostic(
                    stage="type_checker",
                    message=f"Undefined flow '{run_name}' in run statement",
                ),
            ),
        )

    @classmethod
    def _compile_isolated_run_subset(cls, source: str) -> FrontendCompileResult | None:
        match = cls._match_native_run_subset(source)
        if match is None:
            return None
        run_name, token_count, declaration_count = match
        return FrontendCompileResult(
            token_count=token_count,
            declaration_count=declaration_count,
            diagnostics=(
                FrontendDiagnostic(
                    stage="type_checker",
                    message=f"Undefined flow '{run_name}' in run statement",
                ),
            ),
            ir_program=None,
        )

    @classmethod
    def _check_structural_duplicate_declaration_subset(cls, source: str) -> FrontendCheckResult | None:
        match = cls._match_structural_duplicate_declaration_program(source)
        if match is None:
            return None
        diagnostics, token_count, declaration_count = match
        return FrontendCheckResult(
            token_count=token_count,
            declaration_count=declaration_count,
            diagnostics=diagnostics,
        )

    @classmethod
    def _compile_structural_duplicate_declaration_subset(cls, source: str) -> FrontendCompileResult | None:
        match = cls._match_structural_duplicate_declaration_program(source)
        if match is None:
            return None
        diagnostics, token_count, declaration_count = match
        return FrontendCompileResult(
            token_count=token_count,
            declaration_count=declaration_count,
            diagnostics=diagnostics,
            ir_program=None,
        )

    @classmethod
    def _check_structural_validation_subset(cls, source: str) -> FrontendCheckResult | None:
        match = cls._match_structural_validation_program(source)
        if match is None:
            return None
        diagnostics, token_count, declaration_count = match
        return FrontendCheckResult(
            token_count=token_count,
            declaration_count=declaration_count,
            diagnostics=diagnostics,
        )

    @classmethod
    def _compile_structural_validation_subset(cls, source: str) -> FrontendCompileResult | None:
        match = cls._match_structural_validation_program(source)
        if match is None:
            return None
        diagnostics, token_count, declaration_count = match
        return FrontendCompileResult(
            token_count=token_count,
            declaration_count=declaration_count,
            diagnostics=diagnostics,
            ir_program=None,
        )

    @classmethod
    def _match_structural_duplicate_declaration_program(
        cls,
        source: str,
    ) -> tuple[tuple[FrontendDiagnostic, ...], int, int] | None:
        try:
            tokens = _NativeDevelopmentPrefixLexer(source).scan_all_tokens()
        except AxonLexerError:
            return None

        match = cls._match_structural_duplicate_declaration_program_tokens(tokens)
        if match is not None:
            return match

        return cls._match_native_type_structural_duplicate_declaration_program_tokens(tokens)

    @classmethod
    def _match_structural_validation_program(
        cls,
        source: str,
    ) -> tuple[tuple[FrontendDiagnostic, ...], int, int] | None:
        try:
            tokens = _NativeDevelopmentPrefixLexer(source).scan_all_tokens()
        except AxonLexerError:
            return None

        match = cls._match_structural_validation_program_tokens(tokens)
        if match is not None:
            return match

        return cls._match_native_type_structural_validation_program_tokens(tokens)

    @classmethod
    def _match_native_type_duplicate_program(
        cls,
        source: str,
    ) -> tuple[tuple[FrontendDiagnostic, ...], int, int] | None:
        try:
            tokens = _NativeDevelopmentPrefixLexer(source).scan_all_tokens()
        except AxonLexerError:
            return None

        return cls._match_native_type_duplicate_program_tokens(tokens)

    @classmethod
    def _match_native_type_validation_program(
        cls,
        source: str,
    ) -> tuple[tuple[FrontendDiagnostic, ...], int, int] | None:
        try:
            tokens = _NativeDevelopmentPrefixLexer(source).scan_all_tokens()
        except AxonLexerError:
            return None

        return cls._match_native_type_validation_program_tokens(tokens)

    @classmethod
    def _match_native_success_program(cls, source: str) -> tuple[IRProgram, int, int] | None:
        try:
            tokens = _NativeDevelopmentPrefixLexer(source).scan_all_tokens()
        except AxonLexerError:
            return None

        type_flow_run_match = cls._match_native_type_flow_run_program(tokens)
        if type_flow_run_match is not None:
            return type_flow_run_match

        type_match = cls._match_native_type_program(tokens)
        if type_match is not None:
            return type_match

        import_flow_run_match = cls._match_native_import_flow_run_program(tokens)
        if import_flow_run_match is not None:
            return import_flow_run_match

        import_match = cls._match_native_import_program(tokens)
        if import_match is not None:
            return import_match

        return cls._match_native_non_type_success_program(tokens)

    @classmethod
    def _match_native_non_type_success_program(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[IRProgram, int, int] | None:
        prefixed_match = cls._match_structural_prefixed_native_success_program(tokens)
        if prefixed_match is not None:
            return prefixed_match
        prefixed_match = cls._match_persona_context_anchor_prefixed_native_success_program(tokens)
        if prefixed_match is not None:
            return prefixed_match
        prefixed_match = cls._match_context_anchor_prefixed_native_success_program(tokens)
        if prefixed_match is not None:
            return prefixed_match
        prefixed_match = cls._match_persona_anchor_prefixed_native_success_program(tokens)
        if prefixed_match is not None:
            return prefixed_match
        prefixed_match = cls._match_persona_context_prefixed_native_success_program(tokens)
        if prefixed_match is not None:
            return prefixed_match
        prefixed_match = cls._match_persona_prefixed_native_success_program(tokens)
        if prefixed_match is not None:
            return prefixed_match
        prefixed_match = cls._match_context_prefixed_native_success_program(tokens)
        if prefixed_match is not None:
            return prefixed_match
        prefixed_match = cls._match_anchor_prefixed_native_success_program(tokens)
        if prefixed_match is not None:
            return prefixed_match

        multi_flow_match = cls._match_native_multi_flow_run_program(tokens)
        if multi_flow_match is not None:
            return multi_flow_match

        param_flow_match = cls._match_native_parameterized_flow_run_program(tokens)
        if param_flow_match is not None:
            return param_flow_match

        run_config = cls._match_minimal_success_flow_run_tokens(tokens)
        if run_config is None:
            return None

        flow_token = tokens[0]
        flow_name = tokens[1].value
        run_token = tokens[6]
        flow = IRFlow(
            source_line=flow_token.line,
            source_column=flow_token.column,
            name=flow_name,
        )
        run = IRRun(
            source_line=run_token.line,
            source_column=run_token.column,
            flow_name=flow_name,
            on_failure=run_config["on_failure"],
            on_failure_params=run_config["on_failure_params"],
            output_to=run_config["output_to"],
            effort=run_config["effort"],
            resolved_flow=flow,
        )
        return (
            IRProgram(
                source_line=flow_token.line,
                source_column=flow_token.column,
                flows=(flow,),
                runs=(run,),
            ),
            len(tokens) + 1,
            2,
        )

    @classmethod
    def _parse_native_flow_body(
        cls,
        tokens: tuple[Token, ...],
        idx: int,
    ) -> tuple[tuple[IRStep, ...], tuple[tuple[str, ...], ...], int] | None:
        if idx >= len(tokens) or tokens[idx].type != TokenType.LBRACE:
            return None
        idx += 1
        steps: list[IRStep] = []
        while idx < len(tokens) and tokens[idx].type != TokenType.RBRACE:
            if tokens[idx].type != TokenType.STEP:
                return None
            step_token = tokens[idx]
            idx += 1
            if idx >= len(tokens) or tokens[idx].type != TokenType.IDENTIFIER:
                return None
            step_name = tokens[idx].value
            idx += 1
            if idx + 1 >= len(tokens) or tokens[idx].type != TokenType.LBRACE or tokens[idx + 1].type != TokenType.RBRACE:
                return None
            idx += 2
            steps.append(IRStep(
                source_line=step_token.line,
                source_column=step_token.column,
                name=step_name,
            ))
        if idx >= len(tokens) or tokens[idx].type != TokenType.RBRACE:
            return None
        idx += 1
        if steps:
            execution_levels: tuple[tuple[str, ...], ...] = (tuple(s.name for s in steps),)
        else:
            execution_levels = ()
        return (tuple(steps), execution_levels, idx)

    @classmethod
    def _match_native_multi_flow_run_program(
        cls,
        tokens: tuple[Token, ...],
        *,
        available_personas: set[str] | None = None,
        available_contexts: set[str] | None = None,
        available_anchors: set[str] | None = None,
    ) -> tuple[IRProgram, int, int] | None:
        flows: list[IRFlow] = []
        flow_map: dict[str, IRFlow] = {}
        idx = 0
        while idx + 5 < len(tokens):
            if (
                tokens[idx].type != TokenType.FLOW
                or tokens[idx + 1].type != TokenType.IDENTIFIER
                or tokens[idx + 2].type != TokenType.LPAREN
            ):
                break
            flow_token = tokens[idx]
            flow_name = tokens[idx + 1].value
            idx += 3

            params: list[IRParameter] = []
            if idx < len(tokens) and tokens[idx].type != TokenType.RPAREN:
                while idx < len(tokens) and tokens[idx].type != TokenType.RPAREN:
                    if params:
                        if idx >= len(tokens) or tokens[idx].type != TokenType.COMMA:
                            return None
                        idx += 1
                    if idx >= len(tokens) or tokens[idx].type != TokenType.IDENTIFIER:
                        return None
                    param_token = tokens[idx]
                    param_name = tokens[idx].value
                    idx += 1
                    if idx >= len(tokens) or tokens[idx].type != TokenType.COLON:
                        return None
                    idx += 1
                    type_result = cls._parse_structural_type_expr(tokens, idx)
                    if type_result is None:
                        return None
                    type_name, generic_param, optional, idx = type_result
                    params.append(IRParameter(
                        source_line=param_token.line,
                        source_column=param_token.column,
                        name=param_name,
                        type_name=type_name,
                        generic_param=generic_param,
                        optional=optional,
                    ))

            if idx >= len(tokens) or tokens[idx].type != TokenType.RPAREN:
                return None
            idx += 1

            body_result = cls._parse_native_flow_body(tokens, idx)
            if body_result is None:
                break
            body_steps, body_levels, idx = body_result

            flow = IRFlow(
                source_line=flow_token.line,
                source_column=flow_token.column,
                name=flow_name,
                parameters=tuple(params),
                steps=body_steps,
                execution_levels=body_levels,
            )
            flows.append(flow)
            flow_map[flow_name] = flow

        if len(flows) < 2:
            return None

        runs: list[IRRun] = []
        while idx + 3 < len(tokens):
            if (
                tokens[idx].type != TokenType.RUN
                or tokens[idx + 1].type != TokenType.IDENTIFIER
                or tokens[idx + 2].type != TokenType.LPAREN
                or tokens[idx + 3].type != TokenType.RPAREN
            ):
                break
            run_name = tokens[idx + 1].value
            resolved = flow_map.get(run_name)
            if resolved is None:
                return None
            run_token = tokens[idx]

            next_run_idx = idx + 4
            while next_run_idx < len(tokens) and tokens[next_run_idx].type != TokenType.RUN:
                next_run_idx += 1

            modifier_tokens = tokens[idx + 3:next_run_idx]

            if len(modifier_tokens) == 1:
                run_config = cls._default_native_success_run_config()
            elif cls._is_as_run_modifier_tokens(modifier_tokens, available_personas=available_personas):
                run_config = cls._native_success_run_config(persona_name=modifier_tokens[2].value)
            elif cls._is_within_run_modifier_tokens(modifier_tokens, available_contexts=available_contexts):
                run_config = cls._native_success_run_config(context_name=modifier_tokens[2].value)
            elif cls._match_constrained_by_run_modifier_tokens(modifier_tokens, available_anchors=available_anchors) is not None:
                run_config = cls._native_success_run_config(
                    anchor_names=cls._extract_constrained_by_anchor_names(modifier_tokens[3:-1]),
                )
            elif cls._is_output_to_run_modifier_tokens(modifier_tokens):
                run_config = cls._native_success_run_config(output_to=modifier_tokens[3].value)
            elif cls._is_effort_run_modifier_tokens(modifier_tokens):
                run_config = cls._native_success_run_config(effort=modifier_tokens[3].value)
            elif cls._is_simple_on_failure_run_modifier_tokens(modifier_tokens):
                run_config = cls._native_success_run_config(on_failure=modifier_tokens[3].value)
            elif cls._is_raise_on_failure_run_modifier_tokens(modifier_tokens):
                run_config = cls._native_success_run_config(
                    on_failure="raise",
                    on_failure_params=(("target", modifier_tokens[4].value),),
                )
            elif cls._matches_retry_on_failure_shape(modifier_tokens):
                run_config = cls._native_success_run_config(
                    on_failure="retry",
                    on_failure_params=cls._extract_retry_on_failure_parameter_pairs(modifier_tokens[5:-1]),
                )
            else:
                return None

            runs.append(
                IRRun(
                    source_line=run_token.line,
                    source_column=run_token.column,
                    flow_name=run_name,
                    persona_name=run_config["persona_name"],
                    context_name=run_config["context_name"],
                    anchor_names=run_config["anchor_names"],
                    on_failure=run_config["on_failure"],
                    on_failure_params=run_config["on_failure_params"],
                    output_to=run_config["output_to"],
                    effort=run_config["effort"],
                    resolved_flow=resolved,
                )
            )
            idx = next_run_idx

        if not runs:
            return None
        if idx != len(tokens):
            return None

        return (
            IRProgram(
                source_line=flows[0].source_line,
                source_column=flows[0].source_column,
                flows=tuple(flows),
                runs=tuple(runs),
            ),
            len(tokens) + 1,
            len(flows) + len(runs),
        )

    @classmethod
    def _match_native_parameterized_flow_run_program(
        cls,
        tokens: tuple[Token, ...],
        *,
        available_personas: set[str] | None = None,
        available_contexts: set[str] | None = None,
        available_anchors: set[str] | None = None,
    ) -> tuple[IRProgram, int, int] | None:
        if len(tokens) < 13:
            return None
        if (
            tokens[0].type != TokenType.FLOW
            or tokens[1].type != TokenType.IDENTIFIER
            or tokens[2].type != TokenType.LPAREN
        ):
            return None

        flow_name = tokens[1].value
        flow_token = tokens[0]
        idx = 3
        params: list[IRParameter] = []
        while idx < len(tokens) and tokens[idx].type != TokenType.RPAREN:
            if params:
                if idx >= len(tokens) or tokens[idx].type != TokenType.COMMA:
                    return None
                idx += 1
            if idx >= len(tokens) or tokens[idx].type != TokenType.IDENTIFIER:
                return None
            param_token = tokens[idx]
            param_name = tokens[idx].value
            idx += 1
            if idx >= len(tokens) or tokens[idx].type != TokenType.COLON:
                return None
            idx += 1
            type_result = cls._parse_structural_type_expr(tokens, idx)
            if type_result is None:
                return None
            type_name, generic_param, optional, idx = type_result
            params.append(IRParameter(
                source_line=param_token.line,
                source_column=param_token.column,
                name=param_name,
                type_name=type_name,
                generic_param=generic_param,
                optional=optional,
            ))

        if idx >= len(tokens) or tokens[idx].type != TokenType.RPAREN:
            return None
        idx += 1

        body_result = cls._parse_native_flow_body(tokens, idx)
        if body_result is None:
            return None
        body_steps, body_levels, idx = body_result

        if idx + 3 >= len(tokens):
            return None
        if (
            tokens[idx].type != TokenType.RUN
            or tokens[idx + 1].type != TokenType.IDENTIFIER
            or tokens[idx + 2].type != TokenType.LPAREN
            or tokens[idx + 3].type != TokenType.RPAREN
        ):
            return None
        run_name = tokens[idx + 1].value
        run_token = tokens[idx]
        idx += 4

        if run_name != flow_name:
            return None

        if idx == len(tokens):
            run_config = cls._default_native_success_run_config()
        else:
            modifier_tokens = tokens[idx - 1:]
            if cls._is_as_run_modifier_tokens(modifier_tokens, available_personas=available_personas):
                run_config = cls._native_success_run_config(persona_name=modifier_tokens[2].value)
            elif cls._is_within_run_modifier_tokens(modifier_tokens, available_contexts=available_contexts):
                run_config = cls._native_success_run_config(context_name=modifier_tokens[2].value)
            elif cls._match_constrained_by_run_modifier_tokens(modifier_tokens, available_anchors=available_anchors) is not None:
                run_config = cls._native_success_run_config(
                    anchor_names=cls._extract_constrained_by_anchor_names(modifier_tokens[3:-1]),
                )
            elif cls._is_output_to_run_modifier_tokens(modifier_tokens):
                run_config = cls._native_success_run_config(output_to=modifier_tokens[3].value)
            elif cls._is_effort_run_modifier_tokens(modifier_tokens):
                run_config = cls._native_success_run_config(effort=modifier_tokens[3].value)
            elif cls._is_simple_on_failure_run_modifier_tokens(modifier_tokens):
                run_config = cls._native_success_run_config(on_failure=modifier_tokens[3].value)
            elif cls._is_raise_on_failure_run_modifier_tokens(modifier_tokens):
                run_config = cls._native_success_run_config(
                    on_failure="raise",
                    on_failure_params=(("target", modifier_tokens[4].value),),
                )
            elif cls._matches_retry_on_failure_shape(modifier_tokens):
                run_config = cls._native_success_run_config(
                    on_failure="retry",
                    on_failure_params=cls._extract_retry_on_failure_parameter_pairs(modifier_tokens[5:-1]),
                )
            else:
                return None

        flow = IRFlow(
            source_line=flow_token.line,
            source_column=flow_token.column,
            name=flow_name,
            parameters=tuple(params),
            steps=body_steps,
            execution_levels=body_levels,
        )
        run = IRRun(
            source_line=run_token.line,
            source_column=run_token.column,
            flow_name=run_name,
            persona_name=run_config["persona_name"],
            context_name=run_config["context_name"],
            anchor_names=run_config["anchor_names"],
            on_failure=run_config["on_failure"],
            on_failure_params=run_config["on_failure_params"],
            output_to=run_config["output_to"],
            effort=run_config["effort"],
            resolved_flow=flow,
        )
        return (
            IRProgram(
                source_line=flow_token.line,
                source_column=flow_token.column,
                flows=(flow,),
                runs=(run,),
            ),
            len(tokens) + 1,
            2,
        )

    @classmethod
    def _match_native_type_program(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[IRProgram, int, int] | None:
        parsed_types = cls._parse_native_type_prefix(
            tokens, allow_where_clause=True, allow_terminal_end=True
        )
        if parsed_types is None:
            return None

        ir_types, next_index = parsed_types
        if cls._collect_native_type_validation_diagnostics(ir_types):
            return None

        remaining_tokens = tokens[next_index:]

        if remaining_tokens:
            import_match = cls._match_native_import_program(remaining_tokens)
            if import_match is not None:
                import_program, _, import_decl_count = import_match
                merged_program = cls._merge_type_prefix_into_program(
                    ir_types, import_program
                )
                return (
                    merged_program,
                    len(tokens) + 1,
                    len(ir_types) + import_decl_count,
                )
            return None

        first_type = ir_types[0]
        return (
            IRProgram(
                source_line=first_type.source_line,
                source_column=first_type.source_column,
                types=tuple(ir_types),
            ),
            len(tokens) + 1,
            len(ir_types),
        )

    @classmethod
    def _parse_native_single_import(
        cls,
        tokens: tuple[Token, ...],
        start_index: int,
    ) -> tuple[IRImport, int] | None:
        idx = start_index
        if idx >= len(tokens) or tokens[idx].type != TokenType.IMPORT:
            return None
        if idx + 1 >= len(tokens) or tokens[idx + 1].type != TokenType.IDENTIFIER:
            return None

        import_token = tokens[idx]
        path_parts: list[str] = [tokens[idx + 1].value]
        idx = start_index + 2

        while idx + 1 < len(tokens) and tokens[idx].type == TokenType.DOT and tokens[idx + 1].type == TokenType.IDENTIFIER:
            path_parts.append(tokens[idx + 1].value)
            idx += 2

        named: list[str] = []
        if idx < len(tokens) and tokens[idx].type == TokenType.LBRACE:
            idx += 1
            if idx >= len(tokens) or tokens[idx].type != TokenType.IDENTIFIER:
                return None
            named.append(tokens[idx].value)
            idx += 1
            while idx + 1 < len(tokens) and tokens[idx].type == TokenType.COMMA and tokens[idx + 1].type == TokenType.IDENTIFIER:
                named.append(tokens[idx + 1].value)
                idx += 2
            if idx >= len(tokens) or tokens[idx].type != TokenType.RBRACE:
                return None
            idx += 1

        ir_import = IRImport(
            source_line=import_token.line,
            source_column=import_token.column,
            module_path=tuple(path_parts),
            names=tuple(named),
        )
        return ir_import, idx

    @classmethod
    def _parse_native_import_prefix(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[list[IRImport], int] | None:
        if not tokens or tokens[0].type != TokenType.IMPORT:
            return None

        ir_imports: list[IRImport] = []
        index = 0

        while index < len(tokens) and tokens[index].type == TokenType.IMPORT:
            parsed = cls._parse_native_single_import(tokens, index)
            if parsed is None:
                return None
            ir_import, index = parsed
            ir_imports.append(ir_import)

        if not ir_imports:
            return None
        if index >= len(tokens):
            return None
        return ir_imports, index

    @classmethod
    def _match_native_import_program(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[IRProgram, int, int] | None:
        if len(tokens) < 2:
            return None
        if tokens[0].type != TokenType.IMPORT:
            return None

        ir_imports: list[IRImport] = []
        idx = 0

        while idx < len(tokens) and tokens[idx].type == TokenType.IMPORT:
            parsed = cls._parse_native_single_import(tokens, idx)
            if parsed is None:
                return None
            ir_import, idx = parsed
            ir_imports.append(ir_import)

        if not ir_imports:
            return None

        remaining_tokens = tokens[idx:]

        if remaining_tokens:
            type_match = cls._match_native_type_program(remaining_tokens)
            if type_match is not None:
                type_program, _, type_decl_count = type_match
                merged_program = cls._merge_import_prefix_into_program(
                    ir_imports, type_program
                )
                return (
                    merged_program,
                    len(tokens) + 1,
                    len(ir_imports) + type_decl_count,
                )
            return None

        first = ir_imports[0]
        return (
            IRProgram(
                source_line=first.source_line,
                source_column=first.source_column,
                imports=tuple(ir_imports),
            ),
            len(tokens) + 1,
            len(ir_imports),
        )

    @classmethod
    def _match_native_import_flow_run_program(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[IRProgram, int, int] | None:
        parsed_imports = cls._parse_native_import_prefix(tokens)
        if parsed_imports is None:
            return None

        ir_imports, next_index = parsed_imports
        remaining_tokens = tokens[next_index:]

        type_flow_run_match = cls._match_native_type_flow_run_program(remaining_tokens)
        if type_flow_run_match is not None:
            type_program, _, type_decl_count = type_flow_run_match
            merged_program = cls._merge_import_prefix_into_program(ir_imports, type_program)
            return (
                merged_program,
                len(tokens) + 1,
                len(ir_imports) + type_decl_count,
            )

        non_type_match = cls._match_native_non_type_success_program(remaining_tokens)
        if non_type_match is None:
            return None

        non_type_program, _, non_type_declaration_count = non_type_match
        merged_program = cls._merge_import_prefix_into_program(ir_imports, non_type_program)
        return (
            merged_program,
            len(tokens) + 1,
            len(ir_imports) + non_type_declaration_count,
        )

    @staticmethod
    def _merge_import_prefix_into_program(
        ir_imports: list[IRImport],
        program: IRProgram,
    ) -> IRProgram:
        first_import = ir_imports[0]
        return IRProgram(
            source_line=first_import.source_line,
            source_column=first_import.source_column,
            personas=program.personas,
            contexts=program.contexts,
            anchors=program.anchors,
            tools=program.tools,
            memories=program.memories,
            types=program.types,
            flows=program.flows,
            runs=program.runs,
            imports=tuple(ir_imports) + program.imports,
            agents=program.agents,
            shields=program.shields,
            daemons=program.daemons,
            ots_specs=program.ots_specs,
            pix_specs=program.pix_specs,
            corpus_specs=program.corpus_specs,
            psyche_specs=program.psyche_specs,
            mandate_specs=program.mandate_specs,
            lambda_data_specs=program.lambda_data_specs,
            compute_specs=program.compute_specs,
            axonstore_specs=program.axonstore_specs,
            endpoints=program.endpoints,
        )

    @classmethod
    def _match_native_type_flow_run_program(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[IRProgram, int, int] | None:
        parsed_types = cls._parse_native_type_prefix(tokens, allow_where_clause=True)
        if parsed_types is None:
            return None

        ir_types, next_index = parsed_types
        if cls._collect_native_type_validation_diagnostics(ir_types):
            return None
        remaining_tokens = tokens[next_index:]

        import_flow_run_match = cls._match_native_import_flow_run_program(remaining_tokens)
        if import_flow_run_match is not None:
            import_program, _, import_decl_count = import_flow_run_match
            merged_program = cls._merge_type_prefix_into_program(ir_types, import_program)
            return (
                merged_program,
                len(tokens) + 1,
                len(ir_types) + import_decl_count,
            )

        non_type_match = cls._match_native_non_type_success_program(remaining_tokens)
        if non_type_match is None:
            return None

        non_type_program, _, non_type_declaration_count = non_type_match
        merged_program = cls._merge_type_prefix_into_program(ir_types, non_type_program)
        return (
            merged_program,
            len(tokens) + 1,
            len(ir_types) + non_type_declaration_count,
        )

    @classmethod
    def _parse_native_type_prefix(
        cls,
        tokens: tuple[Token, ...],
        *,
        allow_where_clause: bool = False,
        allow_terminal_end: bool = False,
    ) -> tuple[list[IRType], int] | None:
        if not tokens or tokens[0].type != TokenType.TYPE:
            return None

        ir_types: list[IRType] = []
        seen_type_names: set[str] = set()
        index = 0

        while index < len(tokens) and tokens[index].type == TokenType.TYPE:
            parsed_type = cls._parse_native_type_definition(
                tokens,
                start_index=index,
                allow_where_clause=allow_where_clause,
            )
            if parsed_type is None:
                return None
            ir_type, index = parsed_type
            if ir_type.name in seen_type_names:
                return None
            seen_type_names.add(ir_type.name)
            ir_types.append(ir_type)

        if not ir_types:
            return None
        if index >= len(tokens):
            if allow_terminal_end:
                return ir_types, index
            return None
        return ir_types, index

    @staticmethod
    def _merge_type_prefix_into_program(
        ir_types: list[IRType],
        program: IRProgram,
    ) -> IRProgram:
        first_type = ir_types[0]
        return IRProgram(
            source_line=first_type.source_line,
            source_column=first_type.source_column,
            personas=program.personas,
            contexts=program.contexts,
            anchors=program.anchors,
            tools=program.tools,
            memories=program.memories,
            types=tuple(ir_types) + program.types,
            flows=program.flows,
            runs=program.runs,
            imports=program.imports,
            agents=program.agents,
            shields=program.shields,
            daemons=program.daemons,
            ots_specs=program.ots_specs,
            pix_specs=program.pix_specs,
            corpus_specs=program.corpus_specs,
            psyche_specs=program.psyche_specs,
            mandate_specs=program.mandate_specs,
            lambda_data_specs=program.lambda_data_specs,
            compute_specs=program.compute_specs,
            axonstore_specs=program.axonstore_specs,
            endpoints=program.endpoints,
        )

    @classmethod
    def _match_native_type_validation_program_tokens(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[tuple[FrontendDiagnostic, ...], int, int] | None:
        parsed_types = cls._parse_native_type_prefix(
            tokens,
            allow_where_clause=True,
            allow_terminal_end=True,
        )
        if parsed_types is None:
            return None

        ir_types, next_index = parsed_types
        validation_diagnostics = cls._collect_native_type_validation_diagnostics(ir_types)
        if not validation_diagnostics:
            return None

        remaining_tokens = tokens[next_index:]
        if not remaining_tokens:
            return validation_diagnostics, len(tokens) + 1, len(ir_types)

        non_type_success_match = cls._match_native_non_type_success_program(remaining_tokens)
        if non_type_success_match is not None:
            _, _, declaration_count = non_type_success_match
            return (
                validation_diagnostics,
                len(tokens) + 1,
                len(ir_types) + declaration_count,
            )

        non_type_duplicate_match = cls._match_structural_duplicate_declaration_program_tokens(
            remaining_tokens
        )
        if non_type_duplicate_match is not None:
            diagnostics, _, declaration_count = non_type_duplicate_match
            return (
                (*validation_diagnostics, *diagnostics),
                len(tokens) + 1,
                len(ir_types) + declaration_count,
            )

        non_type_validation_match = cls._match_structural_validation_program_tokens(
            remaining_tokens
        )
        if non_type_validation_match is not None:
            diagnostics, _, declaration_count = non_type_validation_match
            return (
                (*validation_diagnostics, *diagnostics),
                len(tokens) + 1,
                len(ir_types) + declaration_count,
            )

        run_match = cls._match_native_run_subset_tokens(remaining_tokens)
        if run_match is None:
            return None

        run_name, _, declaration_count = run_match
        return (
            (
                *validation_diagnostics,
                FrontendDiagnostic(
                    stage="type_checker",
                    message=f"Undefined flow '{run_name}' in run statement",
                ),
            ),
            len(tokens) + 1,
            len(ir_types) + declaration_count,
        )

    @classmethod
    def _match_native_type_structural_duplicate_declaration_program_tokens(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[tuple[FrontendDiagnostic, ...], int, int] | None:
        parsed_types = cls._parse_native_type_prefix(tokens, allow_where_clause=True)
        if parsed_types is None:
            return None

        ir_types, next_index = parsed_types
        duplicate_match = cls._match_structural_duplicate_declaration_program_tokens(
            tokens[next_index:]
        )
        if duplicate_match is None:
            return None

        diagnostics, _, declaration_count = duplicate_match
        return diagnostics, len(tokens) + 1, len(ir_types) + declaration_count

    @classmethod
    def _match_native_type_structural_validation_program_tokens(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[tuple[FrontendDiagnostic, ...], int, int] | None:
        parsed_types = cls._parse_native_type_prefix(tokens, allow_where_clause=True)
        if parsed_types is None:
            return None

        ir_types, next_index = parsed_types
        validation_match = cls._match_structural_validation_program_tokens(tokens[next_index:])
        if validation_match is None:
            return None

        diagnostics, _, declaration_count = validation_match
        return diagnostics, len(tokens) + 1, len(ir_types) + declaration_count

    @classmethod
    def _match_native_type_duplicate_program_tokens(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[tuple[FrontendDiagnostic, ...], int, int] | None:
        scanned_prefix = cls._scan_native_type_prefix_with_duplicates(tokens)
        if scanned_prefix is None:
            return None

        next_index, type_declaration_count, duplicate_diagnostics, validation_diagnostics = scanned_prefix
        if not duplicate_diagnostics:
            return None

        remaining_tokens = tokens[next_index:]
        if not remaining_tokens:
            return (
                (*duplicate_diagnostics, *validation_diagnostics),
                len(tokens) + 1,
                type_declaration_count,
            )

        non_type_success_match = cls._match_native_non_type_success_program(remaining_tokens)
        if non_type_success_match is not None:
            _, _, declaration_count = non_type_success_match
            return (
                (*duplicate_diagnostics, *validation_diagnostics),
                len(tokens) + 1,
                type_declaration_count + declaration_count,
            )

        non_type_duplicate_match = cls._match_structural_duplicate_declaration_program_tokens(
            remaining_tokens
        )
        if non_type_duplicate_match is not None:
            diagnostics, _, declaration_count = non_type_duplicate_match
            return (
                (*duplicate_diagnostics, *validation_diagnostics, *diagnostics),
                len(tokens) + 1,
                type_declaration_count + declaration_count,
            )

        non_type_validation_match = cls._match_structural_validation_program_tokens(
            remaining_tokens
        )
        if non_type_validation_match is not None:
            diagnostics, _, declaration_count = non_type_validation_match
            return (
                (*duplicate_diagnostics, *validation_diagnostics, *diagnostics),
                len(tokens) + 1,
                type_declaration_count + declaration_count,
            )

        run_match = cls._match_native_run_subset_tokens(remaining_tokens)
        if run_match is None:
            return None

        run_name, _, declaration_count = run_match
        return (
            (
                *duplicate_diagnostics,
                *validation_diagnostics,
                FrontendDiagnostic(
                    stage="type_checker",
                    message=f"Undefined flow '{run_name}' in run statement",
                ),
            ),
            len(tokens) + 1,
            type_declaration_count + declaration_count,
        )

    @classmethod
    def _scan_native_type_prefix_with_duplicates(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[int, int, tuple[FrontendDiagnostic, ...], tuple[FrontendDiagnostic, ...]] | None:
        if not tokens or tokens[0].type != TokenType.TYPE:
            return None

        index = 0
        declaration_count = 0
        first_lines_by_name: dict[str, int] = {}
        duplicate_diagnostics: list[FrontendDiagnostic] = []
        validation_diagnostics: list[FrontendDiagnostic] = []

        while index < len(tokens) and tokens[index].type == TokenType.TYPE:
            parsed_type = cls._parse_native_type_definition(
                tokens,
                start_index=index,
                allow_where_clause=True,
            )
            if parsed_type is None:
                return None
            ir_type, index = parsed_type
            declaration_count += 1
            validation_diagnostics.extend(cls._type_range_validation_diagnostics(ir_type))
            first_line = first_lines_by_name.get(ir_type.name)
            if first_line is None:
                first_lines_by_name[ir_type.name] = ir_type.source_line
                continue
            duplicate_diagnostics.append(
                cls._structural_duplicate_declaration_diagnostic(
                    kind="type",
                    name=ir_type.name,
                    line=ir_type.source_line,
                    column=ir_type.source_column,
                    first_line=first_line,
                )
            )

        if declaration_count == 0:
            return None
        return (
            index,
            declaration_count,
            tuple(duplicate_diagnostics),
            tuple(validation_diagnostics),
        )

    @classmethod
    def _collect_native_type_validation_diagnostics(
        cls,
        ir_types: list[IRType],
    ) -> tuple[FrontendDiagnostic, ...]:
        diagnostics: list[FrontendDiagnostic] = []
        for ir_type in ir_types:
            diagnostics.extend(cls._type_range_validation_diagnostics(ir_type))
        return tuple(diagnostics)

    @staticmethod
    def _type_range_validation_diagnostics(ir_type: IRType) -> tuple[FrontendDiagnostic, ...]:
        if ir_type.range_min is None or ir_type.range_max is None:
            return ()
        if ir_type.range_min < ir_type.range_max:
            return ()
        return (
            FrontendDiagnostic(
                stage="type_checker",
                message=(
                    f"Invalid range constraint in type '{ir_type.name}': "
                    f"min ({ir_type.range_min}) must be less than max ({ir_type.range_max})"
                ),
                line=ir_type.source_line,
                column=ir_type.source_column,
            ),
        )

    @classmethod
    def _parse_native_type_definition(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        allow_where_clause: bool = False,
    ) -> tuple[IRType, int] | None:
        if len(tokens) - start_index < 2:
            return None
        if tokens[start_index].type != TokenType.TYPE:
            return None
        if tokens[start_index + 1].type != TokenType.IDENTIFIER:
            return None

        type_token = tokens[start_index]
        name_token = tokens[start_index + 1]
        index = start_index + 2
        range_min: float | None = None
        range_max: float | None = None
        fields: list[IRTypeField] = []
        where_expression = ""
        has_where_clause = False

        if index < len(tokens) and tokens[index].type == TokenType.LPAREN:
            parsed_range = cls._parse_native_type_range_constraint(tokens, start_index=index)
            if parsed_range is None:
                return None
            range_min, range_max, index = parsed_range

        if index < len(tokens) and tokens[index].type == TokenType.WHERE:
            if not allow_where_clause:
                return None
            parsed_where = cls._parse_native_type_where_clause(tokens, start_index=index)
            if parsed_where is None:
                return None
            where_expression, index = parsed_where
            has_where_clause = True

        if index < len(tokens) and tokens[index].type == TokenType.LBRACE:
            parsed_fields = cls._parse_native_type_fields(tokens, start_index=index)
            if parsed_fields is None:
                return None
            fields, index = parsed_fields

        if range_min is None and not fields and not has_where_clause:
            return None

        return (
            IRType(
                source_line=type_token.line,
                source_column=type_token.column,
                name=name_token.value,
                fields=tuple(fields),
                range_min=range_min,
                range_max=range_max,
                where_expression=where_expression,
            ),
            index,
        )

    @classmethod
    def _parse_native_type_where_clause(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
    ) -> tuple[str, int] | None:
        if start_index >= len(tokens) or tokens[start_index].type != TokenType.WHERE:
            return None

        expression_parts: list[str] = []
        index = start_index + 1
        while index < len(tokens):
            token = tokens[index]
            if token.type in (TokenType.LBRACE, TokenType.TYPE, TokenType.FLOW, TokenType.RUN):
                break
            if (
                cls._starts_supported_prefixed_block(tokens, start_index=index)
                and tokens[index].value.lower() in {"persona", "context", "anchor"}
            ):
                break
            expression_parts.append(token.value)
            index += 1

        return " ".join(expression_parts), index

    @classmethod
    def _parse_native_type_range_constraint(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
    ) -> tuple[float, float, int] | None:
        if len(tokens) - start_index < 5:
            return None
        if tokens[start_index].type != TokenType.LPAREN:
            return None

        min_token = tokens[start_index + 1]
        dotdot_token = tokens[start_index + 2]
        max_token = tokens[start_index + 3]
        close_token = tokens[start_index + 4]
        if min_token.type not in (TokenType.INTEGER, TokenType.FLOAT):
            return None
        if dotdot_token.type != TokenType.DOTDOT:
            return None
        if max_token.type not in (TokenType.INTEGER, TokenType.FLOAT):
            return None
        if close_token.type != TokenType.RPAREN:
            return None

        return float(min_token.value), float(max_token.value), start_index + 5

    @classmethod
    def _parse_native_type_fields(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
    ) -> tuple[list[IRTypeField], int] | None:
        if start_index >= len(tokens) or tokens[start_index].type != TokenType.LBRACE:
            return None

        fields: list[IRTypeField] = []
        index = start_index + 1

        while index < len(tokens) and tokens[index].type != TokenType.RBRACE:
            parsed_field = cls._parse_native_type_field(tokens, start_index=index)
            if parsed_field is None:
                return None
            field, index = parsed_field
            fields.append(field)

            if index < len(tokens) and tokens[index].type == TokenType.COMMA:
                index += 1

        if index >= len(tokens) or tokens[index].type != TokenType.RBRACE:
            return None
        return fields, index + 1

    @classmethod
    def _parse_native_type_field(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
    ) -> tuple[IRTypeField, int] | None:
        if start_index + 1 >= len(tokens):
            return None
        if tokens[start_index].type != TokenType.IDENTIFIER:
            return None
        if tokens[start_index + 1].type != TokenType.COLON:
            return None

        field_token = tokens[start_index]
        parsed_type_expr = cls._parse_structural_type_expr(tokens, start_index + 2)
        if parsed_type_expr is None:
            return None

        type_name, generic_param, optional, next_index = parsed_type_expr
        return (
            IRTypeField(
                source_line=field_token.line,
                source_column=field_token.column,
                name=field_token.value,
                type_name=type_name,
                generic_param=generic_param,
                optional=optional,
            ),
            next_index,
        )

    @classmethod
    def _match_structural_duplicate_declaration_program_tokens(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[tuple[FrontendDiagnostic, ...], int, int] | None:
        scanned_prefix = cls._scan_structural_duplicate_declaration_prefix(tokens)
        if scanned_prefix is None:
            return None

        (
            personas,
            contexts,
            anchors,
            _,
            memories,
            _,
            endpoints,
            shields,
            next_index,
            declaration_count,
            duplicate_diagnostics,
            validation_diagnostics,
        ) = scanned_prefix
        if not duplicate_diagnostics:
            return None

        run_tokens = tokens[next_index:]
        if len(run_tokens) < 10:
            return None

        run_config = cls._match_minimal_success_flow_run_tokens(
            run_tokens,
            available_personas={persona.name for persona in personas},
            available_contexts={context.name for context in contexts},
            available_anchors={anchor.name for anchor in anchors},
        )
        if run_config is None:
            return None

        available_declarations = cls._collect_structural_available_declarations(
            personas=personas,
            contexts=contexts,
            anchors=anchors,
            memories=memories,
            endpoints=endpoints,
            shields=shields,
            flows={run_tokens[1].value},
        )
        validation_diagnostics = [
            *validation_diagnostics,
            *cls._collect_structural_endpoint_flow_reference_diagnostics(
                endpoints,
                available_flows={run_tokens[1].value},
                available_declarations=available_declarations,
            ),
        ]

        return (
            (*duplicate_diagnostics, *validation_diagnostics),
            len(tokens) + 1,
            declaration_count + 2,
        )

    @classmethod
    def _match_structural_validation_program_tokens(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[tuple[FrontendDiagnostic, ...], int, int] | None:
        scanned_prefix = cls._scan_structural_validation_prefix(tokens)
        if scanned_prefix is None:
            return None

        personas, contexts, anchors, intents, memories, _, endpoints, shields, next_index, declaration_count, validation_diagnostics = scanned_prefix

        available_declarations = cls._collect_structural_available_declarations(
            personas=personas,
            contexts=contexts,
            anchors=anchors,
            intents=intents,
            memories=memories,
            endpoints=endpoints,
            shields=shields,
        )

        run_tokens = tokens[next_index:]
        if len(run_tokens) >= 10:
            run_config = cls._match_minimal_success_flow_run_tokens(
                run_tokens,
                available_personas={persona.name for persona in personas},
                available_contexts={context.name for context in contexts},
                available_anchors={anchor.name for anchor in anchors},
            )
            if run_config is not None and cls._supports_structural_prefixed_run_config(run_config):
                available_declarations = {
                    **available_declarations,
                    run_tokens[1].value: "flow",
                }
                validation_diagnostics = [
                    *validation_diagnostics,
                    *cls._collect_structural_endpoint_flow_reference_diagnostics(
                        endpoints,
                        available_flows={run_tokens[1].value},
                        available_declarations=available_declarations,
                    ),
                ]
                if not validation_diagnostics:
                    return None
                return (
                    tuple(validation_diagnostics),
                    len(tokens) + 1,
                    declaration_count + 2,
                )

        prefixed_run = cls._match_prefixed_run_tokens(
            run_tokens,
            available_personas={persona.name for persona in personas},
            available_contexts={context.name for context in contexts},
            available_anchors={anchor.name for anchor in anchors},
            total_token_count=len(tokens) + 1,
            declaration_count=declaration_count + 1,
        )
        if prefixed_run is None:
            return None

        run_name, token_count, prefixed_declaration_count = prefixed_run
        validation_diagnostics = [
            *validation_diagnostics,
            *cls._collect_structural_endpoint_flow_reference_diagnostics(
                endpoints,
                available_flows=set(),
                available_declarations=available_declarations,
            ),
        ]
        if not validation_diagnostics:
            return None
        return (
            (
                *validation_diagnostics,
                FrontendDiagnostic(
                    stage="type_checker",
                    message=f"Undefined flow '{run_name}' in run statement",
                ),
            ),
            token_count,
            prefixed_declaration_count,
        )

    @classmethod
    def _scan_structural_duplicate_declaration_prefix(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[
        list[IRPersona],
        list[IRContext],
        list[IRAnchor],
        list[IRIntent],
        list[IRMemory],
        list[IRToolSpec],
        list[IREndpoint],
        list[IRShield],
        int,
        int,
        list[FrontendDiagnostic],
        list[FrontendDiagnostic],
    ] | None:
        personas: list[IRPersona] = []
        contexts: list[IRContext] = []
        anchors: list[IRAnchor] = []
        intents: list[IRIntent] = []
        memories: list[IRMemory] = []
        tools: list[IRToolSpec] = []
        endpoints: list[IREndpoint] = []
        shields: list[IRShield] = []
        seen_singleton_kinds: set[str] = set()
        singleton_first_declarations: dict[str, tuple[str, int]] = {}
        declaration_first_lines = {
            "anchor": {},
            "intent": {},
            "memory": {},
            "tool": {},
            "axonendpoint": {},
            "shield": {},
        }
        duplicate_diagnostics: list[FrontendDiagnostic] = []
        validation_diagnostics: list[FrontendDiagnostic] = []
        declaration_count = 0
        next_index = 0

        while next_index < len(tokens):
            parsed_block = cls._parse_structural_success_prefixed_block(tokens, start_index=next_index)
            if parsed_block is None:
                break

            block_kind, declaration, next_index = parsed_block
            declaration_count += 1
            append_result = cls._append_structural_duplicate_declaration(
                block_kind,
                declaration,
                personas=personas,
                contexts=contexts,
                anchors=anchors,
                intents=intents,
                memories=memories,
                tools=tools,
                endpoints=endpoints,
                shields=shields,
                seen_singleton_kinds=seen_singleton_kinds,
                singleton_first_declarations=singleton_first_declarations,
                declaration_first_lines=declaration_first_lines,
                duplicate_diagnostics=duplicate_diagnostics,
                validation_diagnostics=validation_diagnostics,
            )
            if append_result is False:
                return None

        return (
            personas,
            contexts,
            anchors,
            intents,
            memories,
            tools,
            endpoints,
            shields,
            next_index,
            declaration_count,
            duplicate_diagnostics,
            validation_diagnostics,
        )

    @classmethod
    def _scan_structural_validation_prefix(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[
        list[IRPersona],
        list[IRContext],
        list[IRAnchor],
        list[IRIntent],
        list[IRMemory],
        list[IRToolSpec],
        list[IREndpoint],
        list[IRShield],
        int,
        int,
        list[FrontendDiagnostic],
    ] | None:
        personas: list[IRPersona] = []
        contexts: list[IRContext] = []
        anchors: list[IRAnchor] = []
        intents: list[IRIntent] = []
        memories: list[IRMemory] = []
        tools: list[IRToolSpec] = []
        endpoints: list[IREndpoint] = []
        shields: list[IRShield] = []
        seen_singleton_kinds: set[str] = set()
        seen_anchor_names: set[str] = set()
        seen_intent_names: set[str] = set()
        seen_memory_names: set[str] = set()
        seen_tool_names: set[str] = set()
        seen_endpoint_names: set[str] = set()
        seen_shield_names: set[str] = set()
        validation_diagnostics: list[FrontendDiagnostic] = []
        declaration_count = 0
        next_index = 0

        while next_index < len(tokens):
            parsed_block = cls._parse_structural_success_prefixed_block(tokens, start_index=next_index)
            if parsed_block is None:
                break

            block_kind, declaration, next_index = parsed_block
            declaration_count += 1
            if block_kind == "intent":
                if declaration.name in seen_intent_names:
                    return None
                seen_intent_names.add(declaration.name)
                NativeDevelopmentFrontendImplementation._append_structural_intent_validation_diagnostics(
                    declaration,
                    validation_diagnostics,
                )
                continue
            if not cls._append_structural_validation_declaration(
                block_kind,
                declaration,
                personas=personas,
                contexts=contexts,
                anchors=anchors,
                intents=intents,
                memories=memories,
                tools=tools,
                endpoints=endpoints,
                shields=shields,
                seen_singleton_kinds=seen_singleton_kinds,
                seen_anchor_names=seen_anchor_names,
                seen_memory_names=seen_memory_names,
                seen_tool_names=seen_tool_names,
                seen_endpoint_names=seen_endpoint_names,
                seen_intent_names=seen_intent_names,
                seen_shield_names=seen_shield_names,
                validation_diagnostics=validation_diagnostics,
            ):
                return None

        if (
            not seen_singleton_kinds
            and not seen_anchor_names
            and not seen_intent_names
            and not seen_memory_names
            and not seen_tool_names
            and not seen_endpoint_names
            and not seen_shield_names
        ):
            return None
        return personas, contexts, anchors, intents, memories, tools, endpoints, shields, next_index, declaration_count, validation_diagnostics

    @staticmethod
    def _append_structural_validation_declaration(
        block_kind: str,
        declaration: IRPersona | IRContext | IRAnchor | IRIntent | IRMemory | IRToolSpec | IREndpoint | IRShield,
        *,
        personas: list[IRPersona],
        contexts: list[IRContext],
        anchors: list[IRAnchor],
        intents: list[IRIntent],
        memories: list[IRMemory],
        tools: list[IRToolSpec],
        endpoints: list[IREndpoint],
        shields: list[IRShield],
        seen_singleton_kinds: set[str],
        seen_anchor_names: set[str],
        seen_intent_names: set[str],
        seen_memory_names: set[str],
        seen_tool_names: set[str],
        seen_endpoint_names: set[str],
        seen_shield_names: set[str],
        validation_diagnostics: list[FrontendDiagnostic],
    ) -> bool:
        if block_kind == "persona":
            if block_kind in seen_singleton_kinds:
                return False
            seen_singleton_kinds.add(block_kind)
            personas.append(declaration)
            NativeDevelopmentFrontendImplementation._append_structural_persona_validation_diagnostics(
                declaration,
                validation_diagnostics,
            )
            return True

        if block_kind == "context":
            if block_kind in seen_singleton_kinds:
                return False
            seen_singleton_kinds.add(block_kind)
            contexts.append(declaration)
            NativeDevelopmentFrontendImplementation._append_structural_context_validation_diagnostics(
                declaration,
                validation_diagnostics,
            )
            return True

        if block_kind == "intent":
            if declaration.name in seen_intent_names:
                return False
            seen_intent_names.add(declaration.name)
            intents.append(declaration)
            NativeDevelopmentFrontendImplementation._append_structural_intent_validation_diagnostics(
                declaration,
                validation_diagnostics,
            )
            return True

        if block_kind == "memory":
            if declaration.name in seen_memory_names:
                return False
            seen_memory_names.add(declaration.name)
            memories.append(declaration)
            NativeDevelopmentFrontendImplementation._append_structural_memory_validation_diagnostics(
                declaration,
                validation_diagnostics,
            )
            return True

        if block_kind == "tool":
            if declaration.name in seen_tool_names:
                return False
            seen_tool_names.add(declaration.name)
            tools.append(declaration)
            NativeDevelopmentFrontendImplementation._append_structural_tool_validation_diagnostics(
                declaration,
                validation_diagnostics,
            )
            return True

        if block_kind == "axonendpoint":
            if declaration.name in seen_endpoint_names:
                return False
            seen_endpoint_names.add(declaration.name)
            endpoints.append(declaration)
            NativeDevelopmentFrontendImplementation._append_structural_endpoint_validation_diagnostics(
                declaration,
                validation_diagnostics,
                available_flows=None,
            )
            return True

        if block_kind == "shield":
            if declaration.name in seen_shield_names:
                return False
            seen_shield_names.add(declaration.name)
            shields.append(declaration)
            return True

        if block_kind == "compute":
            return True

        if block_kind in ("dataspace", "axonstore"):
            return True

        if declaration.name in seen_anchor_names:
            return False
        seen_anchor_names.add(declaration.name)
        anchors.append(declaration)
        NativeDevelopmentFrontendImplementation._append_structural_anchor_validation_diagnostics(
            declaration,
            validation_diagnostics,
        )
        return True

    @staticmethod
    def _append_structural_duplicate_declaration(
        block_kind: str,
        declaration: IRPersona | IRContext | IRAnchor | IRIntent | IRMemory | IRToolSpec | IREndpoint | IRShield,
        *,
        personas: list[IRPersona],
        contexts: list[IRContext],
        anchors: list[IRAnchor],
        intents: list[IRIntent],
        memories: list[IRMemory],
        tools: list[IRToolSpec],
        endpoints: list[IREndpoint],
        shields: list[IRShield],
        seen_singleton_kinds: set[str],
        singleton_first_declarations: dict[str, tuple[str, int]],
        declaration_first_lines: dict[str, dict[str, int]],
        duplicate_diagnostics: list[FrontendDiagnostic],
        validation_diagnostics: list[FrontendDiagnostic],
    ) -> bool:
        if block_kind == "persona":
            return NativeDevelopmentFrontendImplementation._append_structural_duplicate_persona_declaration(
                declaration,
                seen_singleton_kinds=seen_singleton_kinds,
                singleton_first_declarations=singleton_first_declarations,
                personas=personas,
                duplicate_diagnostics=duplicate_diagnostics,
                validation_diagnostics=validation_diagnostics,
            )

        if block_kind == "context":
            return NativeDevelopmentFrontendImplementation._append_structural_duplicate_context_declaration(
                declaration,
                seen_singleton_kinds=seen_singleton_kinds,
                singleton_first_declarations=singleton_first_declarations,
                contexts=contexts,
                duplicate_diagnostics=duplicate_diagnostics,
                validation_diagnostics=validation_diagnostics,
            )

        if block_kind == "memory":
            NativeDevelopmentFrontendImplementation._append_structural_memory_validation_diagnostics(
                declaration,
                validation_diagnostics,
            )
            first_line = declaration_first_lines["memory"].get(declaration.name)
            if first_line is not None:
                duplicate_diagnostics.append(
                    NativeDevelopmentFrontendImplementation._structural_duplicate_declaration_diagnostic(
                        kind=block_kind,
                        name=declaration.name,
                        line=declaration.source_line,
                        column=declaration.source_column,
                        first_line=first_line,
                    )
                )
                return True

            declaration_first_lines["memory"][declaration.name] = declaration.source_line
            memories.append(declaration)
            return True

        if block_kind == "intent":
            NativeDevelopmentFrontendImplementation._append_structural_intent_validation_diagnostics(
                declaration,
                validation_diagnostics,
            )
            first_line = declaration_first_lines["intent"].get(declaration.name)
            if first_line is not None:
                duplicate_diagnostics.append(
                    NativeDevelopmentFrontendImplementation._structural_duplicate_declaration_diagnostic(
                        kind=block_kind,
                        name=declaration.name,
                        line=declaration.source_line,
                        column=declaration.source_column,
                        first_line=first_line,
                    )
                )
                return True

            declaration_first_lines["intent"][declaration.name] = declaration.source_line
            intents.append(declaration)
            return True

        if block_kind == "tool":
            NativeDevelopmentFrontendImplementation._append_structural_tool_validation_diagnostics(
                declaration,
                validation_diagnostics,
            )
            first_line = declaration_first_lines["tool"].get(declaration.name)
            if first_line is not None:
                duplicate_diagnostics.append(
                    NativeDevelopmentFrontendImplementation._structural_duplicate_declaration_diagnostic(
                        kind=block_kind,
                        name=declaration.name,
                        line=declaration.source_line,
                        column=declaration.source_column,
                        first_line=first_line,
                    )
                )
                return True

            declaration_first_lines["tool"][declaration.name] = declaration.source_line
            tools.append(declaration)
            return True

        if block_kind == "axonendpoint":
            NativeDevelopmentFrontendImplementation._append_structural_endpoint_validation_diagnostics(
                declaration,
                validation_diagnostics,
                available_flows=None,
            )
            first_line = declaration_first_lines["axonendpoint"].get(declaration.name)
            if first_line is not None:
                duplicate_diagnostics.append(
                    NativeDevelopmentFrontendImplementation._structural_duplicate_declaration_diagnostic(
                        kind=block_kind,
                        name=declaration.name,
                        line=declaration.source_line,
                        column=declaration.source_column,
                        first_line=first_line,
                    )
                )
                return True

            declaration_first_lines["axonendpoint"][declaration.name] = declaration.source_line
            endpoints.append(declaration)
            return True

        if block_kind == "shield":
            first_line = declaration_first_lines["shield"].get(declaration.name)
            if first_line is not None:
                duplicate_diagnostics.append(
                    NativeDevelopmentFrontendImplementation._structural_duplicate_declaration_diagnostic(
                        kind=block_kind,
                        name=declaration.name,
                        line=declaration.source_line,
                        column=declaration.source_column,
                        first_line=first_line,
                    )
                )
                return True

            declaration_first_lines["shield"][declaration.name] = declaration.source_line
            shields.append(declaration)
            return True

        if block_kind == "compute":
            first_line = declaration_first_lines.get("compute", {}).get(declaration.name)
            if first_line is not None:
                duplicate_diagnostics.append(
                    NativeDevelopmentFrontendImplementation._structural_duplicate_declaration_diagnostic(
                        kind=block_kind,
                        name=declaration.name,
                        line=declaration.source_line,
                        column=declaration.source_column,
                        first_line=first_line,
                    )
                )
                return True

            declaration_first_lines.setdefault("compute", {})[declaration.name] = declaration.source_line
            return True

        if block_kind in ("dataspace", "axonstore"):
            return True

        NativeDevelopmentFrontendImplementation._append_structural_anchor_validation_diagnostics(
            declaration,
            validation_diagnostics,
        )
        first_line = declaration_first_lines["anchor"].get(declaration.name)
        if first_line is not None:
            duplicate_diagnostics.append(
                NativeDevelopmentFrontendImplementation._structural_duplicate_declaration_diagnostic(
                    kind=block_kind,
                    name=declaration.name,
                    line=declaration.source_line,
                    column=declaration.source_column,
                    first_line=first_line,
                )
            )
            return True

        declaration_first_lines["anchor"][declaration.name] = declaration.source_line
        anchors.append(declaration)
        return True

    @staticmethod
    def _append_structural_duplicate_persona_declaration(
        declaration: IRPersona,
        *,
        seen_singleton_kinds: set[str],
        singleton_first_declarations: dict[str, tuple[str, int]],
        personas: list[IRPersona],
        duplicate_diagnostics: list[FrontendDiagnostic],
        validation_diagnostics: list[FrontendDiagnostic],
    ) -> bool:
        NativeDevelopmentFrontendImplementation._append_structural_persona_validation_diagnostics(
            declaration,
            validation_diagnostics,
        )

        if "persona" not in seen_singleton_kinds:
            seen_singleton_kinds.add("persona")
            singleton_first_declarations["persona"] = (declaration.name, declaration.source_line)
            personas.append(declaration)
            return True

        first_name, first_line = singleton_first_declarations["persona"]
        if declaration.name != first_name:
            return False
        duplicate_diagnostics.append(
            NativeDevelopmentFrontendImplementation._structural_duplicate_declaration_diagnostic(
                kind="persona",
                name=declaration.name,
                line=declaration.source_line,
                column=declaration.source_column,
                first_line=first_line,
            )
        )
        return True

    @staticmethod
    def _append_structural_duplicate_context_declaration(
        declaration: IRContext,
        *,
        seen_singleton_kinds: set[str],
        singleton_first_declarations: dict[str, tuple[str, int]],
        contexts: list[IRContext],
        duplicate_diagnostics: list[FrontendDiagnostic],
        validation_diagnostics: list[FrontendDiagnostic],
    ) -> bool:
        NativeDevelopmentFrontendImplementation._append_structural_context_validation_diagnostics(
            declaration,
            validation_diagnostics,
        )

        if "context" not in seen_singleton_kinds:
            seen_singleton_kinds.add("context")
            singleton_first_declarations["context"] = (declaration.name, declaration.source_line)
            contexts.append(declaration)
            return True

        first_name, first_line = singleton_first_declarations["context"]
        if declaration.name != first_name:
            return False

        duplicate_diagnostics.append(
            NativeDevelopmentFrontendImplementation._structural_duplicate_declaration_diagnostic(
                kind="context",
                name=declaration.name,
                line=declaration.source_line,
                column=declaration.source_column,
                first_line=first_line,
            )
        )
        return True

    @staticmethod
    def _structural_duplicate_declaration_diagnostic(
        *,
        kind: str,
        name: str,
        line: int,
        column: int,
        first_line: int,
    ) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=f"Duplicate declaration: '{name}' already defined as {kind} (first defined at line {first_line})",
            line=line,
            column=column,
        )

    @staticmethod
    def _structural_invalid_context_memory_scope_diagnostic(context: IRContext) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"Unknown memory scope '{context.memory_scope}' in context '{context.name}'. "
                f"Valid: {', '.join(sorted(VALID_MEMORY_SCOPES))}"
            ),
            line=context.source_line,
            column=context.source_column,
        )

    @staticmethod
    def _structural_invalid_context_depth_diagnostic(context: IRContext) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"Unknown depth '{context.depth}' in context '{context.name}'. "
                f"Valid: {', '.join(sorted(VALID_DEPTHS))}"
            ),
            line=context.source_line,
            column=context.source_column,
        )

    @staticmethod
    def _structural_invalid_context_max_tokens_diagnostic(context: IRContext) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"max_tokens must be positive, got {context.max_tokens} "
                f"in context '{context.name}'"
            ),
            line=context.source_line,
            column=context.source_column,
        )

    @staticmethod
    def _structural_invalid_context_temperature_diagnostic(context: IRContext) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"temperature must be between 0.0 and 2.0, got {context.temperature}"
            ),
            line=context.source_line,
            column=context.source_column,
        )

    @staticmethod
    def _append_structural_context_validation_diagnostics(
        context: IRContext,
        validation_diagnostics: list[FrontendDiagnostic],
    ) -> None:
        if context.memory_scope and context.memory_scope not in VALID_MEMORY_SCOPES:
            validation_diagnostics.append(
                NativeDevelopmentFrontendImplementation._structural_invalid_context_memory_scope_diagnostic(
                    context,
                )
            )
        if context.depth and context.depth not in VALID_DEPTHS:
            validation_diagnostics.append(
                NativeDevelopmentFrontendImplementation._structural_invalid_context_depth_diagnostic(
                    context,
                )
            )
        if context.max_tokens is not None and context.max_tokens <= 0:
            validation_diagnostics.append(
                NativeDevelopmentFrontendImplementation._structural_invalid_context_max_tokens_diagnostic(
                    context,
                )
            )
        if context.temperature is not None and not 0.0 <= context.temperature <= 2.0:
            validation_diagnostics.append(
                NativeDevelopmentFrontendImplementation._structural_invalid_context_temperature_diagnostic(
                    context,
                )
            )

    @staticmethod
    def _structural_invalid_memory_store_diagnostic(memory: IRMemory) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"Unknown store type '{memory.store}' in memory '{memory.name}'. "
                f"Valid: {', '.join(sorted(VALID_MEMORY_SCOPES))}"
            ),
            line=memory.source_line,
            column=memory.source_column,
        )

    @staticmethod
    def _structural_invalid_memory_retrieval_diagnostic(memory: IRMemory) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"Unknown retrieval strategy '{memory.retrieval}' in memory '{memory.name}'. "
                f"Valid: {', '.join(sorted(VALID_RETRIEVAL_STRATEGIES))}"
            ),
            line=memory.source_line,
            column=memory.source_column,
        )

    @staticmethod
    def _append_structural_memory_validation_diagnostics(
        memory: IRMemory,
        validation_diagnostics: list[FrontendDiagnostic],
    ) -> None:
        if memory.store and memory.store not in VALID_MEMORY_SCOPES:
            validation_diagnostics.append(
                NativeDevelopmentFrontendImplementation._structural_invalid_memory_store_diagnostic(
                    memory,
                )
            )
        if memory.retrieval and memory.retrieval not in VALID_RETRIEVAL_STRATEGIES:
            validation_diagnostics.append(
                NativeDevelopmentFrontendImplementation._structural_invalid_memory_retrieval_diagnostic(
                    memory,
                )
            )

    @staticmethod
    def _structural_invalid_tool_max_results_diagnostic(tool: IRToolSpec) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"max_results must be positive, got {tool.max_results} "
                f"in tool '{tool.name}'"
            ),
            line=tool.source_line,
            column=tool.source_column,
        )

    @staticmethod
    def _structural_invalid_tool_effect_diagnostic(tool: IRToolSpec, effect: str) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"Unknown effect '{effect}' in tool '{tool.name}'. "
                f"Valid effects: {', '.join(sorted(TypeChecker.VALID_EFFECTS))}"
            ),
            line=tool.source_line,
            column=tool.source_column,
        )

    @staticmethod
    def _structural_invalid_tool_epistemic_level_diagnostic(
        tool: IRToolSpec,
        level: str,
    ) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"Unknown epistemic level '{level}' in tool '{tool.name}'. "
                f"Valid levels: {', '.join(sorted(TypeChecker.VALID_EPISTEMIC_LEVELS))}"
            ),
            line=tool.source_line,
            column=tool.source_column,
        )

    @staticmethod
    def _append_structural_tool_validation_diagnostics(
        tool: IRToolSpec,
        validation_diagnostics: list[FrontendDiagnostic],
    ) -> None:
        if tool.max_results is not None and tool.max_results <= 0:
            validation_diagnostics.append(
                NativeDevelopmentFrontendImplementation._structural_invalid_tool_max_results_diagnostic(
                    tool,
                )
            )
        if tool.effect_row:
            epistemic_level = ""
            for effect in tool.effect_row:
                if effect.startswith("epistemic:"):
                    epistemic_level = effect.split(":", 1)[1]
                    continue
                base_effect = effect.split(":", 1)[0]
                if base_effect not in TypeChecker.VALID_EFFECTS:
                    validation_diagnostics.append(
                        NativeDevelopmentFrontendImplementation._structural_invalid_tool_effect_diagnostic(
                            tool,
                            effect,
                        )
                    )
            if epistemic_level and epistemic_level not in TypeChecker.VALID_EPISTEMIC_LEVELS:
                validation_diagnostics.append(
                    NativeDevelopmentFrontendImplementation._structural_invalid_tool_epistemic_level_diagnostic(
                        tool,
                        epistemic_level,
                    )
                )

    @staticmethod
    def _append_structural_intent_validation_diagnostics(
        intent: IRIntent,
        validation_diagnostics: list[FrontendDiagnostic],
    ) -> None:
        if intent.confidence_floor is not None and not 0.0 <= intent.confidence_floor <= 1.0:
            validation_diagnostics.append(
                NativeDevelopmentFrontendImplementation._structural_invalid_intent_confidence_floor_diagnostic(
                    intent,
                )
            )

    @staticmethod
    def _structural_invalid_endpoint_retries_diagnostic(endpoint: IREndpoint) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"axonendpoint '{endpoint.name}' retries must be >= 0, got {endpoint.retries}"
            ),
            line=endpoint.source_line,
            column=endpoint.source_column,
        )

    @staticmethod
    def _append_structural_endpoint_validation_diagnostics(
        endpoint: IREndpoint,
        validation_diagnostics: list[FrontendDiagnostic],
        *,
        available_flows: set[str] | None,
        available_declarations: dict[str, str] | None = None,
    ) -> None:
        if endpoint.method and endpoint.method.upper() not in TypeChecker._VALID_ENDPOINT_METHODS:
            validation_diagnostics.append(
                NativeDevelopmentFrontendImplementation._structural_invalid_endpoint_method_diagnostic(
                    endpoint,
                )
            )
        if not endpoint.path or not endpoint.path.startswith("/"):
            validation_diagnostics.append(
                NativeDevelopmentFrontendImplementation._structural_invalid_endpoint_path_diagnostic(
                    endpoint,
                )
            )
        if available_flows is not None and endpoint.execute_flow not in available_flows:
            validation_diagnostics.append(
                NativeDevelopmentFrontendImplementation._structural_undefined_endpoint_flow_diagnostic(
                    endpoint,
                )
            )
        if available_declarations is not None and endpoint.shield_ref:
            declaration_kind = available_declarations.get(endpoint.shield_ref)
            if declaration_kind is None:
                validation_diagnostics.append(
                    NativeDevelopmentFrontendImplementation._structural_undefined_endpoint_shield_diagnostic(
                        endpoint,
                    )
                )
            elif declaration_kind != "shield":
                validation_diagnostics.append(
                    NativeDevelopmentFrontendImplementation._structural_not_a_shield_diagnostic(
                        endpoint,
                        declaration_kind,
                    )
                )
        if available_flows is not None and available_declarations is not None and endpoint.retries < 0:
            validation_diagnostics.append(
                NativeDevelopmentFrontendImplementation._structural_invalid_endpoint_retries_diagnostic(
                    endpoint,
                )
            )

    @classmethod
    def _collect_structural_endpoint_validation_diagnostics(
        cls,
        endpoints: list[IREndpoint],
        *,
        available_flows: set[str],
        available_declarations: dict[str, str] | None = None,
    ) -> tuple[FrontendDiagnostic, ...]:
        diagnostics: list[FrontendDiagnostic] = []
        for endpoint in endpoints:
            cls._append_structural_endpoint_validation_diagnostics(
                endpoint,
                diagnostics,
                available_flows=available_flows,
                available_declarations=available_declarations,
            )
        return tuple(diagnostics)

    @staticmethod
    def _collect_structural_endpoint_flow_reference_diagnostics(
        endpoints: list[IREndpoint],
        *,
        available_flows: set[str],
        available_declarations: dict[str, str] | None = None,
    ) -> tuple[FrontendDiagnostic, ...]:
        diagnostics: list[FrontendDiagnostic] = []
        for endpoint in endpoints:
            if endpoint.execute_flow not in available_flows:
                diagnostics.append(
                    NativeDevelopmentFrontendImplementation._structural_undefined_endpoint_flow_diagnostic(
                        endpoint,
                    )
                )
            if available_declarations is not None and endpoint.shield_ref:
                declaration_kind = available_declarations.get(endpoint.shield_ref)
                if declaration_kind is None:
                    diagnostics.append(
                        NativeDevelopmentFrontendImplementation._structural_undefined_endpoint_shield_diagnostic(
                            endpoint,
                        )
                    )
                elif declaration_kind != "shield":
                    diagnostics.append(
                        NativeDevelopmentFrontendImplementation._structural_not_a_shield_diagnostic(
                            endpoint,
                            declaration_kind,
                        )
                    )
            if endpoint.retries < 0:
                diagnostics.append(
                    NativeDevelopmentFrontendImplementation._structural_invalid_endpoint_retries_diagnostic(
                        endpoint,
                    )
                )
        return tuple(diagnostics)

    @staticmethod
    def _collect_structural_available_declarations(
        *,
        personas: list[IRPersona] = (),
        contexts: list[IRContext] = (),
        anchors: list[IRAnchor] = (),
        intents: list[IRIntent] = (),
        memories: list[IRMemory] = (),
        tools: list[IRToolSpec] = (),
        endpoints: list[IREndpoint] = (),
        shields: list[IRShield] = (),
        compute_specs: list[IRCompute] = (),
        axonstore_specs: list[IRAxonStore] = (),
        flows: set[str] = frozenset(),
    ) -> dict[str, str]:
        available_declarations: dict[str, str] = {}
        for persona in personas:
            available_declarations.setdefault(persona.name, "persona")
        for context in contexts:
            available_declarations.setdefault(context.name, "context")
        for anchor in anchors:
            available_declarations.setdefault(anchor.name, "anchor")
        for intent in intents:
            available_declarations.setdefault(intent.name, "intent")
        for memory in memories:
            available_declarations.setdefault(memory.name, "memory")
        for tool in tools:
            available_declarations.setdefault(tool.name, "tool")
        for endpoint in endpoints:
            available_declarations.setdefault(endpoint.name, "axonendpoint")
        for shield in shields:
            available_declarations.setdefault(shield.name, "shield")
        for compute in compute_specs:
            available_declarations.setdefault(compute.name, "compute")
        for axonstore in axonstore_specs:
            available_declarations.setdefault(axonstore.name, "axonstore")
        for flow_name in flows:
            available_declarations.setdefault(flow_name, "flow")
        return available_declarations

    @classmethod
    def _match_structural_prefixed_native_success_program(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[IRProgram, int, int] | None:
        parsed_blocks = cls._parse_structural_success_prefixed_blocks(tokens)
        if parsed_blocks is None:
            return None

        personas, contexts, anchors, intents, memories, tools, endpoints, shields, compute_specs, dataspaces, axonstore_specs, next_index = parsed_blocks
        run_tokens = tokens[next_index:]

        # Standalone declarations (no flow+run) — prefix-only program
        if len(run_tokens) == 0 or (len(run_tokens) == 1 and run_tokens[0].type == TokenType.EOF):
            all_declarations = personas + contexts + anchors + intents + memories + tools + endpoints + shields + compute_specs + axonstore_specs
            all_with_dataspaces = all_declarations + dataspaces
            if not all_with_dataspaces:
                return None
            first_declaration = min(all_with_dataspaces, key=lambda d: (d.source_line, d.source_column))
            declaration_count = len(all_with_dataspaces)
            return (
                IRProgram(
                    source_line=first_declaration.source_line,
                    source_column=first_declaration.source_column,
                    personas=tuple(personas),
                    contexts=tuple(contexts),
                    anchors=tuple(anchors),
                    memories=tuple(memories),
                    tools=tuple(tools),
                    endpoints=tuple(endpoints),
                    shields=tuple(shields),
                    compute_specs=tuple(compute_specs),
                    axonstore_specs=tuple(axonstore_specs),
                ),
                len(tokens) + 1,
                declaration_count,
            )

        if len(run_tokens) < 10:
            return None

        available_persona_names = {persona.name for persona in personas}
        available_context_names = {context.name for context in contexts}
        available_anchor_names = {anchor.name for anchor in anchors}

        run_config = cls._match_minimal_success_flow_run_tokens(
            run_tokens,
            available_personas=available_persona_names,
            available_contexts=available_context_names,
            available_anchors=available_anchor_names,
        )
        if run_config is not None and cls._supports_structural_prefixed_run_config(run_config):
            # Bare flow+run matched
            flow_token = run_tokens[0]
            flow_name = run_tokens[1].value
            run_token = run_tokens[6]
            run_token_line = run_token.line
            run_token_column = run_token.column
            flow = IRFlow(
                source_line=flow_token.line,
                source_column=flow_token.column,
                name=flow_name,
            )
        else:
            # Try parameterized flow+run
            param_match = cls._match_native_parameterized_flow_run_program(
                run_tokens,
                available_personas=available_persona_names,
                available_contexts=available_context_names,
                available_anchors=available_anchor_names,
            )
            if param_match is not None:
                param_program, _, _ = param_match
                run_config = {
                    "persona_name": param_program.runs[0].persona_name,
                    "context_name": param_program.runs[0].context_name,
                    "anchor_names": param_program.runs[0].anchor_names,
                    "on_failure": param_program.runs[0].on_failure,
                    "on_failure_params": param_program.runs[0].on_failure_params,
                    "output_to": param_program.runs[0].output_to,
                    "effort": param_program.runs[0].effort,
                }
                if not cls._supports_structural_prefixed_run_config(run_config):
                    return None
                flow = param_program.flows[0]
                flow_name = flow.name
                run_token_line = param_program.runs[0].source_line
                run_token_column = param_program.runs[0].source_column
            else:
                # Try multi-flow+run
                multi_match = cls._match_native_multi_flow_run_program(
                    run_tokens,
                    available_personas=available_persona_names,
                    available_contexts=available_context_names,
                    available_anchors=available_anchor_names,
                )
                if multi_match is None:
                    return None
                multi_program, _, _ = multi_match
                multi_flows = list(multi_program.flows)
                multi_runs: list[IRRun] = []
                for mr in multi_program.runs:
                    resolved_persona = cls._resolve_structural_prefixed_persona(personas, mr.persona_name)
                    resolved_context = cls._resolve_structural_prefixed_context(contexts, mr.context_name)
                    resolved_anchors = cls._resolve_structural_prefixed_anchors(anchors, mr.anchor_names)
                    multi_runs.append(
                        IRRun(
                            source_line=mr.source_line,
                            source_column=mr.source_column,
                            flow_name=mr.flow_name,
                            persona_name=mr.persona_name,
                            context_name=mr.context_name,
                            anchor_names=mr.anchor_names,
                            on_failure=mr.on_failure,
                            on_failure_params=mr.on_failure_params,
                            output_to=mr.output_to,
                            effort=mr.effort,
                            resolved_flow=mr.resolved_flow,
                            resolved_persona=resolved_persona,
                            resolved_context=resolved_context,
                            resolved_anchors=resolved_anchors,
                        )
                    )
                multi_flow_names = {f.name for f in multi_flows}

                if endpoints:
                    available_declarations = cls._collect_structural_available_declarations(
                        personas=personas,
                        contexts=contexts,
                        anchors=anchors,
                        intents=intents,
                        memories=memories,
                        tools=tools,
                        endpoints=endpoints,
                        shields=shields,
                        compute_specs=compute_specs,
                        axonstore_specs=axonstore_specs,
                        flows=multi_flow_names,
                    )
                    endpoint_diagnostics = cls._collect_structural_endpoint_validation_diagnostics(
                        endpoints,
                        available_flows=multi_flow_names,
                        available_declarations=available_declarations,
                    )
                    if endpoint_diagnostics:
                        return None

                all_declarations = personas + contexts + anchors + intents + memories + tools + endpoints + shields + compute_specs + axonstore_specs
                if all_declarations:
                    first_declaration = all_declarations[0]
                else:
                    first_declaration = multi_flows[0]
                declaration_count = len(personas) + len(contexts) + len(anchors) + len(intents) + len(memories) + len(tools) + len(endpoints) + len(shields) + len(compute_specs) + len(axonstore_specs) + len(dataspaces) + len(multi_flows) + len(multi_runs)
                return (
                    IRProgram(
                        source_line=first_declaration.source_line,
                        source_column=first_declaration.source_column,
                        personas=tuple(personas),
                        contexts=tuple(contexts),
                        anchors=tuple(anchors),
                        memories=tuple(memories),
                        tools=tuple(tools),
                        endpoints=tuple(endpoints),
                        shields=tuple(shields),
                        compute_specs=tuple(compute_specs),
                        axonstore_specs=tuple(axonstore_specs),
                        flows=tuple(multi_flows),
                        runs=tuple(multi_runs),
                    ),
                    len(tokens) + 1,
                    declaration_count,
                )
        resolved_persona = cls._resolve_structural_prefixed_persona(personas, run_config["persona_name"])
        resolved_context = cls._resolve_structural_prefixed_context(contexts, run_config["context_name"])
        resolved_anchors = cls._resolve_structural_prefixed_anchors(anchors, run_config["anchor_names"])
        run = IRRun(
            source_line=run_token_line,
            source_column=run_token_column,
            flow_name=flow_name,
            persona_name=run_config["persona_name"],
            context_name=run_config["context_name"],
            anchor_names=run_config["anchor_names"],
            on_failure=run_config["on_failure"],
            on_failure_params=run_config["on_failure_params"],
            output_to=run_config["output_to"],
            effort=run_config["effort"],
            resolved_flow=flow,
            resolved_persona=resolved_persona,
            resolved_context=resolved_context,
            resolved_anchors=resolved_anchors,
        )

        if endpoints:
            available_declarations = cls._collect_structural_available_declarations(
                personas=personas,
                contexts=contexts,
                anchors=anchors,
                intents=intents,
                memories=memories,
                tools=tools,
                endpoints=endpoints,
                shields=shields,
                compute_specs=compute_specs,
                axonstore_specs=axonstore_specs,
                flows={flow_name},
            )
            endpoint_diagnostics = cls._collect_structural_endpoint_validation_diagnostics(
                endpoints,
                available_flows={flow_name},
                available_declarations=available_declarations,
            )
            if endpoint_diagnostics:
                return None

        if personas:
            first_declaration = personas[0]
        elif contexts:
            first_declaration = contexts[0]
        elif intents:
            first_declaration = intents[0]
        elif memories:
            first_declaration = memories[0]
        elif tools:
            first_declaration = tools[0]
        elif shields:
            first_declaration = shields[0]
        elif compute_specs:
            first_declaration = compute_specs[0]
        elif axonstore_specs:
            first_declaration = axonstore_specs[0]
        elif endpoints:
            first_declaration = endpoints[0]
        else:
            first_declaration = anchors[0]
        declaration_count = len(personas) + len(contexts) + len(anchors) + len(intents) + len(memories) + len(tools) + len(endpoints) + len(shields) + len(compute_specs) + len(axonstore_specs) + len(dataspaces) + 2
        return (
            IRProgram(
                source_line=first_declaration.source_line,
                source_column=first_declaration.source_column,
                personas=tuple(personas),
                contexts=tuple(contexts),
                anchors=tuple(anchors),
                memories=tuple(memories),
                tools=tuple(tools),
                endpoints=tuple(endpoints),
                shields=tuple(shields),
                compute_specs=tuple(compute_specs),
                axonstore_specs=tuple(axonstore_specs),
                flows=(flow,),
                runs=(run,),
            ),
            len(tokens) + 1,
            declaration_count,
        )

    @classmethod
    def _parse_structural_success_prefixed_blocks(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[list[IRPersona], list[IRContext], list[IRAnchor], list[IRIntent], list[IRMemory], list[IRToolSpec], list[IREndpoint], list[IRShield], list[IRCompute], list[IRDataSpace], list[IRAxonStore], int] | None:
        personas: list[IRPersona] = []
        contexts: list[IRContext] = []
        anchors: list[IRAnchor] = []
        intents: list[IRIntent] = []
        memories: list[IRMemory] = []
        tools: list[IRToolSpec] = []
        endpoints: list[IREndpoint] = []
        shields: list[IRShield] = []
        compute_specs: list[IRCompute] = []
        dataspaces: list[IRDataSpace] = []
        axonstore_specs: list[IRAxonStore] = []
        seen_singleton_kinds: set[str] = set()
        seen_anchor_names: set[str] = set()
        seen_intent_names: set[str] = set()
        seen_memory_names: set[str] = set()
        seen_tool_names: set[str] = set()
        seen_endpoint_names: set[str] = set()
        seen_shield_names: set[str] = set()
        seen_compute_names: set[str] = set()
        seen_dataspace_names: set[str] = set()
        seen_axonstore_names: set[str] = set()
        next_index = 0

        while next_index < len(tokens):
            parsed_block = cls._parse_structural_success_prefixed_block(tokens, start_index=next_index)
            if parsed_block is None:
                break

            block_kind, declaration, next_index = parsed_block
            if not cls._append_structural_success_prefixed_declaration(
                block_kind,
                declaration,
                personas=personas,
                contexts=contexts,
                anchors=anchors,
                intents=intents,
                memories=memories,
                tools=tools,
                endpoints=endpoints,
                shields=shields,
                compute_specs=compute_specs,
                dataspaces=dataspaces,
                axonstore_specs=axonstore_specs,
                seen_singleton_kinds=seen_singleton_kinds,
                seen_anchor_names=seen_anchor_names,
                seen_intent_names=seen_intent_names,
                seen_memory_names=seen_memory_names,
                seen_tool_names=seen_tool_names,
                seen_endpoint_names=seen_endpoint_names,
                seen_shield_names=seen_shield_names,
                seen_compute_names=seen_compute_names,
                seen_dataspace_names=seen_dataspace_names,
                seen_axonstore_names=seen_axonstore_names,
            ):
                return None

        if (
            not seen_singleton_kinds
            and not seen_anchor_names
            and not seen_intent_names
            and not seen_memory_names
            and not seen_tool_names
            and not seen_endpoint_names
            and not seen_shield_names
            and not seen_compute_names
            and not seen_dataspace_names
            and not seen_axonstore_names
        ):
            return None
        return personas, contexts, anchors, intents, memories, tools, endpoints, shields, compute_specs, dataspaces, axonstore_specs, next_index

    @staticmethod
    def _append_structural_success_prefixed_declaration(
        block_kind: str,
        declaration: IRPersona | IRContext | IRAnchor | IRIntent | IRMemory | IRToolSpec | IREndpoint | IRShield | IRCompute | IRDataSpace | IRAxonStore,
        *,
        personas: list[IRPersona],
        contexts: list[IRContext],
        anchors: list[IRAnchor],
        intents: list[IRIntent],
        memories: list[IRMemory],
        tools: list[IRToolSpec],
        endpoints: list[IREndpoint],
        shields: list[IRShield],
        compute_specs: list[IRCompute],
        dataspaces: list[IRDataSpace],
        axonstore_specs: list[IRAxonStore],
        seen_singleton_kinds: set[str],
        seen_anchor_names: set[str],
        seen_intent_names: set[str],
        seen_memory_names: set[str],
        seen_tool_names: set[str],
        seen_endpoint_names: set[str],
        seen_shield_names: set[str],
        seen_compute_names: set[str],
        seen_dataspace_names: set[str],
        seen_axonstore_names: set[str],
    ) -> bool:
        if block_kind == "persona":
            return NativeDevelopmentFrontendImplementation._append_structural_success_persona_declaration(
                declaration,
                personas=personas,
                seen_singleton_kinds=seen_singleton_kinds,
            )

        if block_kind == "context":
            return NativeDevelopmentFrontendImplementation._append_structural_success_context_declaration(
                declaration,
                contexts=contexts,
                seen_singleton_kinds=seen_singleton_kinds,
            )

        if block_kind == "memory":
            return NativeDevelopmentFrontendImplementation._append_structural_success_memory_declaration(
                declaration,
                memories=memories,
                seen_memory_names=seen_memory_names,
            )

        if block_kind == "intent":
            return NativeDevelopmentFrontendImplementation._append_structural_success_intent_declaration(
                declaration,
                intents=intents,
                seen_intent_names=seen_intent_names,
            )

        if block_kind == "tool":
            return NativeDevelopmentFrontendImplementation._append_structural_success_tool_declaration(
                declaration,
                tools=tools,
                seen_tool_names=seen_tool_names,
            )

        if block_kind == "axonendpoint":
            return NativeDevelopmentFrontendImplementation._append_structural_success_endpoint_declaration(
                declaration,
                endpoints=endpoints,
                seen_endpoint_names=seen_endpoint_names,
            )

        if block_kind == "shield":
            return NativeDevelopmentFrontendImplementation._append_structural_success_shield_declaration(
                declaration,
                shields=shields,
                seen_shield_names=seen_shield_names,
            )

        if block_kind == "compute":
            return NativeDevelopmentFrontendImplementation._append_structural_success_compute_declaration(
                declaration,
                compute_specs=compute_specs,
                seen_compute_names=seen_compute_names,
            )

        if block_kind == "dataspace":
            return NativeDevelopmentFrontendImplementation._append_structural_success_dataspace_declaration(
                declaration,
                dataspaces=dataspaces,
                seen_dataspace_names=seen_dataspace_names,
            )

        if block_kind == "axonstore":
            return NativeDevelopmentFrontendImplementation._append_structural_success_axonstore_declaration(
                declaration,
                axonstore_specs=axonstore_specs,
                seen_axonstore_names=seen_axonstore_names,
            )

        return NativeDevelopmentFrontendImplementation._append_structural_success_anchor_declaration(
            declaration,
            anchors=anchors,
            seen_anchor_names=seen_anchor_names,
        )

    @staticmethod
    def _append_structural_success_persona_declaration(
        declaration: IRPersona,
        *,
        personas: list[IRPersona],
        seen_singleton_kinds: set[str],
    ) -> bool:
        if "persona" in seen_singleton_kinds:
            return False
        if declaration.tone and declaration.tone not in VALID_TONES:
            return False
        if declaration.confidence_threshold is not None and not 0.0 <= declaration.confidence_threshold <= 1.0:
            return False
        seen_singleton_kinds.add("persona")
        personas.append(declaration)
        return True

    @staticmethod
    def _append_structural_success_context_declaration(
        declaration: IRContext,
        *,
        contexts: list[IRContext],
        seen_singleton_kinds: set[str],
    ) -> bool:
        if "context" in seen_singleton_kinds:
            return False
        if declaration.memory_scope and declaration.memory_scope not in VALID_MEMORY_SCOPES:
            return False
        if declaration.depth and declaration.depth not in VALID_DEPTHS:
            return False
        if declaration.max_tokens is not None and declaration.max_tokens <= 0:
            return False
        if declaration.temperature is not None and not 0.0 <= declaration.temperature <= 2.0:
            return False
        seen_singleton_kinds.add("context")
        contexts.append(declaration)
        return True

    @staticmethod
    def _append_structural_success_anchor_declaration(
        declaration: IRAnchor,
        *,
        anchors: list[IRAnchor],
        seen_anchor_names: set[str],
    ) -> bool:
        if declaration.name in seen_anchor_names:
            return False
        if declaration.confidence_floor is not None and not 0.0 <= declaration.confidence_floor <= 1.0:
            return False
        if declaration.on_violation and declaration.on_violation not in VALID_VIOLATION_ACTIONS:
            return False
        seen_anchor_names.add(declaration.name)
        anchors.append(declaration)
        return True

    @staticmethod
    def _append_structural_success_memory_declaration(
        declaration: IRMemory,
        *,
        memories: list[IRMemory],
        seen_memory_names: set[str],
    ) -> bool:
        if declaration.name in seen_memory_names:
            return False
        if declaration.store and declaration.store not in VALID_MEMORY_SCOPES:
            return False
        if declaration.retrieval and declaration.retrieval not in VALID_RETRIEVAL_STRATEGIES:
            return False
        seen_memory_names.add(declaration.name)
        memories.append(declaration)
        return True

    @staticmethod
    def _append_structural_success_intent_declaration(
        declaration: IRIntent,
        *,
        intents: list[IRIntent],
        seen_intent_names: set[str],
    ) -> bool:
        if declaration.name in seen_intent_names:
            return False
        if declaration.confidence_floor is not None and not 0.0 <= declaration.confidence_floor <= 1.0:
            return False
        seen_intent_names.add(declaration.name)
        intents.append(declaration)
        return True

    @staticmethod
    def _append_structural_success_tool_declaration(
        declaration: IRToolSpec,
        *,
        tools: list[IRToolSpec],
        seen_tool_names: set[str],
    ) -> bool:
        if declaration.name in seen_tool_names:
            return False
        if declaration.max_results is not None and declaration.max_results <= 0:
            return False
        if declaration.effect_row:
            epistemic_level = ""
            for effect in declaration.effect_row:
                if effect.startswith("epistemic:"):
                    epistemic_level = effect.split(":", 1)[1]
                    continue
                base_effect = effect.split(":", 1)[0]
                if base_effect not in TypeChecker.VALID_EFFECTS:
                    return False
            if epistemic_level and epistemic_level not in TypeChecker.VALID_EPISTEMIC_LEVELS:
                return False
        seen_tool_names.add(declaration.name)
        tools.append(declaration)
        return True

    @staticmethod
    def _append_structural_success_endpoint_declaration(
        declaration: IREndpoint,
        *,
        endpoints: list[IREndpoint],
        seen_endpoint_names: set[str],
    ) -> bool:
        if declaration.name in seen_endpoint_names:
            return False
        if declaration.retries < 0:
            return False
        seen_endpoint_names.add(declaration.name)
        endpoints.append(declaration)
        return True

    @staticmethod
    def _append_structural_success_shield_declaration(
        declaration: IRShield,
        *,
        shields: list[IRShield],
        seen_shield_names: set[str],
    ) -> bool:
        if declaration.name in seen_shield_names:
            return False
        seen_shield_names.add(declaration.name)
        shields.append(declaration)
        return True

    @staticmethod
    def _append_structural_success_compute_declaration(
        declaration: IRCompute,
        *,
        compute_specs: list[IRCompute],
        seen_compute_names: set[str],
    ) -> bool:
        if declaration.name in seen_compute_names:
            return False
        seen_compute_names.add(declaration.name)
        compute_specs.append(declaration)
        return True

    @staticmethod
    def _append_structural_success_dataspace_declaration(
        declaration: IRDataSpace,
        *,
        dataspaces: list[IRDataSpace],
        seen_dataspace_names: set[str],
    ) -> bool:
        if declaration.name in seen_dataspace_names:
            return False
        seen_dataspace_names.add(declaration.name)
        dataspaces.append(declaration)
        return True

    @staticmethod
    def _append_structural_success_axonstore_declaration(
        declaration: IRAxonStore,
        *,
        axonstore_specs: list[IRAxonStore],
        seen_axonstore_names: set[str],
    ) -> bool:
        if declaration.name in seen_axonstore_names:
            return False
        seen_axonstore_names.add(declaration.name)
        axonstore_specs.append(declaration)
        return True

    @classmethod
    def _parse_structural_success_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
    ) -> tuple[str, IRPersona | IRContext | IRAnchor | IRIntent | IRMemory | IRToolSpec | IREndpoint | IRShield | IRCompute | IRDataSpace | IRAxonStore, int] | None:
        if len(tokens) - start_index < 4:
            return None
        kind = tokens[start_index].value.lower()
        if kind not in {"persona", "context", "anchor", "intent", "memory", "tool", "axonendpoint", "shield", "compute", "dataspace", "axonstore"}:
            return None
        if tokens[start_index + 1].type != TokenType.IDENTIFIER or tokens[start_index + 2].type != TokenType.LBRACE:
            return None

        if kind == "shield" and tokens[start_index + 3].type == TokenType.RBRACE:
            return (
                kind,
                IRShield(
                    source_line=tokens[start_index].line,
                    source_column=tokens[start_index].column,
                    name=tokens[start_index + 1].value,
                ),
                start_index + 4,
            )

        if kind == "compute" and tokens[start_index + 3].type == TokenType.RBRACE:
            return (
                kind,
                IRCompute(
                    source_line=tokens[start_index].line,
                    source_column=tokens[start_index].column,
                    name=tokens[start_index + 1].value,
                ),
                start_index + 4,
            )

        if kind == "dataspace" and tokens[start_index + 3].type == TokenType.RBRACE:
            return (
                kind,
                IRDataSpace(
                    source_line=tokens[start_index].line,
                    source_column=tokens[start_index].column,
                    name=tokens[start_index + 1].value,
                ),
                start_index + 4,
            )

        if kind == "axonstore" and tokens[start_index + 3].type == TokenType.RBRACE:
            return (
                kind,
                IRAxonStore(
                    source_line=tokens[start_index].line,
                    source_column=tokens[start_index].column,
                    name=tokens[start_index + 1].value,
                ),
                start_index + 4,
            )

        if len(tokens) - start_index < 7:
            return None

        block_token = tokens[start_index]
        name_token = tokens[start_index + 1]
        field_token = tokens[start_index + 3]
        if not cls._is_identifier_like_value_token(field_token) or tokens[start_index + 4].type != TokenType.COLON:
            return None

        extended_block = cls._parse_structural_extended_prefixed_block(
            tokens,
            start_index=start_index,
            kind=kind,
            block_token=block_token,
            name_token=name_token,
            field_token=field_token,
        )
        if extended_block is not None:
            declaration, next_index = extended_block
            return kind, declaration, next_index

        value_token = tokens[start_index + 5]
        if not cls._is_identifier_like_value_token(value_token) or tokens[start_index + 6].type != TokenType.RBRACE:
            return None

        next_index = start_index + 7
        declaration = cls._parse_structural_simple_prefixed_declaration(
            kind,
            block_token,
            name_token,
            field_token,
            value_token,
        )

        if declaration is None:
            return None
        return kind, declaration, next_index

    @classmethod
    def _parse_structural_simple_prefixed_declaration(
        cls,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
        value_token: Token,
    ) -> IRPersona | IRContext | IRAnchor | IRIntent | IRMemory | IRToolSpec | IREndpoint | IRShield | IRCompute | None:
        if kind == "persona":
            return cls._parse_structural_persona_block(
                block_token,
                name_token,
                field_token,
                value_token,
            )
        if kind == "context":
            return cls._parse_structural_context_block(
                block_token,
                name_token,
                field_token,
                value_token,
            )
        if kind == "memory":
            return cls._parse_structural_memory_block(
                block_token,
                name_token,
                field_token,
                value_token,
            )
        if kind == "intent":
            return cls._parse_structural_intent_block(
                block_token,
                name_token,
                field_token,
                value_token,
            )
        if kind == "tool":
            return cls._parse_structural_tool_block(
                block_token,
                name_token,
                field_token,
                value_token,
            )
        if kind == "axonendpoint":
            return None
        if kind == "shield":
            return cls._parse_structural_shield_simple_block(
                block_token,
                name_token,
                field_token,
                value_token,
            )
        if kind == "compute":
            return cls._parse_structural_compute_simple_block(
                block_token,
                name_token,
                field_token,
                value_token,
            )
        if kind in ("dataspace", "axonstore"):
            if kind == "axonstore":
                return cls._parse_structural_axonstore_simple_block(
                    block_token,
                    name_token,
                    field_token,
                    value_token,
                )
            return None
        return cls._parse_structural_anchor_block(
            block_token,
            name_token,
            field_token,
            value_token,
        )

    @classmethod
    def _parse_structural_extended_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRPersona | IRAnchor | IRIntent | IRMemory | IRToolSpec | IREndpoint | IRShield | IRCompute, int] | None:
        extended_parsers = (
            cls._parse_structural_axonendpoint_prefixed_block,
            cls._parse_structural_intent_given_ask_output_confidence_floor_prefixed_block,
            cls._parse_structural_intent_given_ask_output_prefixed_block,
            cls._parse_structural_intent_output_confidence_floor_prefixed_block,
            cls._parse_structural_intent_output_prefixed_block,
            cls._parse_structural_intent_confidence_floor_prefixed_block,
            cls._parse_structural_intent_given_ask_prefixed_block,
            cls._parse_structural_raise_on_violation_prefixed_block,
            cls._parse_structural_fallback_on_violation_prefixed_block,
            cls._parse_structural_reject_prefixed_block,
            cls._parse_structural_refuse_if_prefixed_block,
            cls._parse_structural_domain_prefixed_block,
            cls._parse_structural_tool_effects_prefixed_block,
            cls._parse_structural_tool_filter_call_prefixed_block,
            cls._parse_structural_tool_timeout_prefixed_block,
            cls._parse_structural_memory_decay_prefixed_block,
            cls._parse_structural_shield_prefixed_block,
            cls._parse_structural_compute_prefixed_block,
            cls._parse_structural_axonstore_prefixed_block,
        )
        for parser in extended_parsers:
            parsed_block = parser(
                tokens,
                start_index=start_index,
                kind=kind,
                block_token=block_token,
                name_token=name_token,
                field_token=field_token,
            )
            if parsed_block is not None:
                return parsed_block
        return None

    @staticmethod
    def _parse_structural_shield_simple_block(
        block_token: Token,
        name_token: Token,
        field_token: Token,
        value_token: Token,
    ) -> IRShield | None:
        field_name = field_token.value
        if field_name in {"strategy", "on_breach", "severity", "quarantine", "log"}:
            if not (value_token.type == TokenType.IDENTIFIER or value_token.value.isalpha()):
                return None
            return IRShield(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                **{field_name: value_token.value},
            )
        if field_name == "max_retries":
            if value_token.type != TokenType.INTEGER:
                return None
            return IRShield(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                max_retries=int(value_token.value),
            )
        if field_name == "confidence_threshold":
            if value_token.type not in (TokenType.FLOAT, TokenType.INTEGER):
                return None
            return IRShield(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                confidence_threshold=float(value_token.value),
            )
        if field_name == "sandbox":
            if value_token.type != TokenType.BOOL:
                return None
            return IRShield(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                sandbox=value_token.value == "true",
            )
        return None

    @staticmethod
    def _parse_structural_compute_simple_block(
        block_token: Token,
        name_token: Token,
        field_token: Token,
        value_token: Token,
    ) -> IRCompute | None:
        field_name = field_token.value
        if field_name == "output":
            if not (value_token.type == TokenType.IDENTIFIER or value_token.value.isalpha()):
                return None
            return IRCompute(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                output_type=value_token.value,
            )
        if field_name == "shield":
            if not (value_token.type == TokenType.IDENTIFIER or value_token.value.isalpha()):
                return None
            return IRCompute(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                shield_ref=value_token.value,
            )
        if field_name == "verified":
            if value_token.type != TokenType.BOOL:
                return None
            return IRCompute(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                verified=value_token.value == "true",
            )
        return None

    @classmethod
    def _parse_structural_shield_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRShield, int] | None:
        if kind != "shield" or field_token.value not in cls._SHIELD_SUPPORTED_FIELDS:
            return None
        parsed_fields = cls._parse_structural_shield_fields(tokens, start_index=start_index)
        if parsed_fields is None:
            return None
        shield_fields, next_index = parsed_fields
        shield_kwargs: dict[str, str | int | float | bool] = {}
        for f_name, value in shield_fields.items():
            shield_kwargs[cls._SHIELD_FIELD_TO_IR_ATTR[f_name]] = value
        return (
            IRShield(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                **shield_kwargs,
            ),
            next_index,
        )

    @classmethod
    def _parse_structural_shield_fields(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
    ) -> tuple[dict[str, str | int | float | bool], int] | None:
        shield_fields: dict[str, str | int | float | bool] = {}
        index = start_index + 3
        while index < len(tokens):
            current_token = tokens[index]
            if current_token.type == TokenType.RBRACE:
                return shield_fields, index + 1
            if not cls._is_identifier_like_value_token(current_token):
                return None
            field_name = current_token.value
            if field_name in shield_fields or field_name not in cls._SHIELD_SUPPORTED_FIELDS:
                return None
            if index + 1 >= len(tokens) or tokens[index + 1].type != TokenType.COLON:
                return None
            value_index = index + 2
            if value_index >= len(tokens):
                return None
            parsed_value = cls._parse_structural_shield_field_value(field_name, tokens[value_index])
            if parsed_value is None:
                return None
            shield_fields[field_name] = parsed_value
            index = value_index + 1
        return None

    @classmethod
    def _parse_structural_shield_field_value(
        cls,
        field_name: str,
        value_token: Token,
    ) -> str | int | float | bool | None:
        if field_name in {"strategy", "on_breach", "severity", "quarantine", "log"}:
            if cls._is_identifier_like_value_token(value_token):
                return value_token.value
            return None
        if field_name == "max_retries":
            if value_token.type == TokenType.INTEGER:
                return int(value_token.value)
            return None
        if field_name == "confidence_threshold":
            if value_token.type in (TokenType.FLOAT, TokenType.INTEGER):
                return float(value_token.value)
            return None
        if field_name == "sandbox":
            if value_token.type == TokenType.BOOL:
                return value_token.value == "true"
            return None
        return None

    @classmethod
    def _parse_structural_compute_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRCompute, int] | None:
        if kind != "compute" or field_token.value not in cls._COMPUTE_SUPPORTED_FIELDS:
            return None
        parsed_fields = cls._parse_structural_compute_fields(tokens, start_index=start_index)
        if parsed_fields is None:
            return None
        compute_fields, next_index = parsed_fields
        compute_kwargs: dict[str, str | bool] = {}
        for f_name, value in compute_fields.items():
            compute_kwargs[cls._COMPUTE_FIELD_TO_IR_ATTR[f_name]] = value
        return (
            IRCompute(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                **compute_kwargs,
            ),
            next_index,
        )

    @classmethod
    def _parse_structural_compute_fields(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
    ) -> tuple[dict[str, str | bool], int] | None:
        compute_fields: dict[str, str | bool] = {}
        index = start_index + 3
        while index < len(tokens):
            current_token = tokens[index]
            if current_token.type == TokenType.RBRACE:
                return compute_fields, index + 1
            if not cls._is_identifier_like_value_token(current_token):
                return None
            field_name = current_token.value
            if field_name in compute_fields or field_name not in cls._COMPUTE_SUPPORTED_FIELDS:
                return None
            if index + 1 >= len(tokens) or tokens[index + 1].type != TokenType.COLON:
                return None
            value_index = index + 2
            if value_index >= len(tokens):
                return None
            parsed_value = cls._parse_structural_compute_field_value(field_name, tokens[value_index])
            if parsed_value is None:
                return None
            compute_fields[field_name] = parsed_value
            index = value_index + 1
        return None

    @classmethod
    def _parse_structural_compute_field_value(
        cls,
        field_name: str,
        value_token: Token,
    ) -> str | bool | None:
        if field_name in {"output", "shield"}:
            if cls._is_identifier_like_value_token(value_token):
                return value_token.value
            return None
        if field_name == "verified":
            if value_token.type == TokenType.BOOL:
                return value_token.value == "true"
            return None
        return None

    @staticmethod
    def _parse_structural_axonstore_simple_block(
        block_token: Token,
        name_token: Token,
        field_token: Token,
        value_token: Token,
    ) -> IRAxonStore | None:
        field_name = field_token.value
        if field_name in {"backend", "isolation", "on_breach"}:
            if not (value_token.type == TokenType.IDENTIFIER or value_token.value.isalpha()):
                return None
            return IRAxonStore(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                **{field_name: value_token.value},
            )
        if field_name == "connection":
            if value_token.type != TokenType.STRING:
                return None
            return IRAxonStore(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                connection=value_token.value,
            )
        if field_name == "confidence_floor":
            if value_token.type not in (TokenType.FLOAT, TokenType.INTEGER):
                return None
            return IRAxonStore(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                confidence_floor=float(value_token.value),
            )
        return None

    @classmethod
    def _parse_structural_axonstore_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRAxonStore, int] | None:
        if kind != "axonstore" or field_token.value not in cls._AXONSTORE_SUPPORTED_FIELDS:
            return None
        parsed_fields = cls._parse_structural_axonstore_fields(tokens, start_index=start_index)
        if parsed_fields is None:
            return None
        store_fields, next_index = parsed_fields
        store_kwargs: dict[str, str | float] = {}
        for f_name, value in store_fields.items():
            store_kwargs[cls._AXONSTORE_FIELD_TO_IR_ATTR[f_name]] = value
        return (
            IRAxonStore(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                **store_kwargs,
            ),
            next_index,
        )

    @classmethod
    def _parse_structural_axonstore_fields(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
    ) -> tuple[dict[str, str | float], int] | None:
        store_fields: dict[str, str | float] = {}
        index = start_index + 3
        while index < len(tokens):
            current_token = tokens[index]
            if current_token.type == TokenType.RBRACE:
                return store_fields, index + 1
            if not cls._is_identifier_like_value_token(current_token):
                return None
            field_name = current_token.value
            if field_name in store_fields or field_name not in cls._AXONSTORE_SUPPORTED_FIELDS:
                return None
            if index + 1 >= len(tokens) or tokens[index + 1].type != TokenType.COLON:
                return None
            value_index = index + 2
            if value_index >= len(tokens):
                return None
            parsed_value = cls._parse_structural_axonstore_field_value(field_name, tokens[value_index])
            if parsed_value is None:
                return None
            store_fields[field_name] = parsed_value
            index = value_index + 1
        return None

    @classmethod
    def _parse_structural_axonstore_field_value(
        cls,
        field_name: str,
        value_token: Token,
    ) -> str | float | None:
        if field_name in {"backend", "isolation", "on_breach"}:
            if cls._is_identifier_like_value_token(value_token):
                return value_token.value
            return None
        if field_name == "connection":
            if value_token.type == TokenType.STRING:
                return value_token.value
            return None
        if field_name == "confidence_floor":
            if value_token.type in (TokenType.FLOAT, TokenType.INTEGER):
                return float(value_token.value)
            return None
        return None

    @classmethod
    def _parse_structural_type_expr(
        cls,
        tokens: tuple[Token, ...],
        start_index: int,
    ) -> tuple[str, str, bool, int] | None:
        if start_index >= len(tokens) or tokens[start_index].type != TokenType.IDENTIFIER:
            return None

        type_name = tokens[start_index].value
        generic_param = ""
        optional = False
        index = start_index + 1

        if index < len(tokens) and tokens[index].type == TokenType.LT:
            index += 1
            if index >= len(tokens) or tokens[index].type != TokenType.IDENTIFIER:
                return None
            generic_param = tokens[index].value
            index += 1
            if index >= len(tokens) or tokens[index].type != TokenType.GT:
                return None
            index += 1

        if index < len(tokens) and tokens[index].type == TokenType.QUESTION:
            optional = True
            index += 1

        return type_name, generic_param, optional, index

    @classmethod
    def _parse_structural_intent_output_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRIntent, int] | None:
        if kind != "intent" or field_token.value not in {"ask", "output"} or len(tokens) - start_index < 10:
            return None

        intent_ask = ""
        output_type_name = ""
        output_type_generic = ""
        output_type_optional = False
        seen_fields: set[str] = set()
        index = start_index + 3

        for _ in range(2):
            if index >= len(tokens):
                return None
            current_field_token = tokens[index]
            if not cls._is_identifier_like_value_token(current_field_token):
                return None

            field_name = current_field_token.value
            if field_name in seen_fields or field_name not in {"ask", "output"}:
                return None
            seen_fields.add(field_name)

            if index + 1 >= len(tokens) or tokens[index + 1].type != TokenType.COLON:
                return None

            value_index = index + 2
            if field_name == "ask":
                if value_index >= len(tokens) or tokens[value_index].type != TokenType.STRING:
                    return None
                intent_ask = tokens[value_index].value
                index = value_index + 1
                continue

            parsed_type_expr = cls._parse_structural_type_expr(tokens, value_index)
            if parsed_type_expr is None:
                return None
            output_type_name, output_type_generic, output_type_optional, index = parsed_type_expr

        if seen_fields != {"ask", "output"} or not intent_ask or not output_type_name:
            return None
        if index >= len(tokens) or tokens[index].type != TokenType.RBRACE:
            return None

        declaration = IRIntent(
            source_line=block_token.line,
            source_column=block_token.column,
            name=name_token.value,
            ask=intent_ask,
            output_type_name=output_type_name,
            output_type_generic=output_type_generic,
            output_type_optional=output_type_optional,
        )
        return declaration, index + 1

    @classmethod
    def _parse_structural_intent_output_confidence_floor_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRIntent, int] | None:
        if kind != "intent" or field_token.value not in {"ask", "output", "confidence_floor"}:
            return None

        intent_ask = ""
        output_type_name = ""
        output_type_generic = ""
        output_type_optional = False
        confidence_floor: float | None = None
        seen_fields: set[str] = set()
        index = start_index + 3

        for _ in range(3):
            if index >= len(tokens):
                return None

            current_field_token = tokens[index]
            if not cls._is_identifier_like_value_token(current_field_token):
                return None

            field_name = current_field_token.value
            if field_name in seen_fields or field_name not in {"ask", "output", "confidence_floor"}:
                return None
            seen_fields.add(field_name)

            if index + 1 >= len(tokens) or tokens[index + 1].type != TokenType.COLON:
                return None

            value_index = index + 2
            if field_name == "ask":
                if value_index >= len(tokens) or tokens[value_index].type != TokenType.STRING:
                    return None
                intent_ask = tokens[value_index].value
                index = value_index + 1
                continue

            if field_name == "output":
                parsed_type_expr = cls._parse_structural_type_expr(tokens, value_index)
                if parsed_type_expr is None:
                    return None
                output_type_name, output_type_generic, output_type_optional, index = parsed_type_expr
                continue

            if value_index >= len(tokens) or tokens[value_index].type != TokenType.FLOAT:
                return None
            confidence_floor = float(tokens[value_index].value)
            index = value_index + 1

        if seen_fields != {"ask", "output", "confidence_floor"}:
            return None
        if not intent_ask or not output_type_name or confidence_floor is None:
            return None
        if index >= len(tokens) or tokens[index].type != TokenType.RBRACE:
            return None

        declaration = IRIntent(
            source_line=block_token.line,
            source_column=block_token.column,
            name=name_token.value,
            ask=intent_ask,
            output_type_name=output_type_name,
            output_type_generic=output_type_generic,
            output_type_optional=output_type_optional,
            confidence_floor=confidence_floor,
        )
        return declaration, index + 1

    @classmethod
    def _parse_structural_intent_given_ask_output_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRIntent, int] | None:
        if kind != "intent" or field_token.value not in {"given", "ask", "output"}:
            return None

        intent_given = ""
        intent_ask = ""
        output_type_name = ""
        output_type_generic = ""
        output_type_optional = False
        seen_fields: set[str] = set()
        index = start_index + 3

        for _ in range(3):
            if index >= len(tokens):
                return None

            current_field_token = tokens[index]
            if not cls._is_identifier_like_value_token(current_field_token):
                return None

            field_name = current_field_token.value
            if field_name in seen_fields or field_name not in {"given", "ask", "output"}:
                return None
            seen_fields.add(field_name)

            if index + 1 >= len(tokens) or tokens[index + 1].type != TokenType.COLON:
                return None

            value_index = index + 2
            if field_name == "given":
                if value_index >= len(tokens) or tokens[value_index].type != TokenType.IDENTIFIER:
                    return None
                intent_given = tokens[value_index].value
                index = value_index + 1
                continue

            if field_name == "ask":
                if value_index >= len(tokens) or tokens[value_index].type != TokenType.STRING:
                    return None
                intent_ask = tokens[value_index].value
                index = value_index + 1
                continue

            parsed_type_expr = cls._parse_structural_type_expr(tokens, value_index)
            if parsed_type_expr is None:
                return None
            output_type_name, output_type_generic, output_type_optional, index = parsed_type_expr

        if seen_fields != {"given", "ask", "output"}:
            return None
        if not intent_given or not intent_ask or not output_type_name:
            return None
        if index >= len(tokens) or tokens[index].type != TokenType.RBRACE:
            return None

        declaration = IRIntent(
            source_line=block_token.line,
            source_column=block_token.column,
            name=name_token.value,
            given=intent_given,
            ask=intent_ask,
            output_type_name=output_type_name,
            output_type_generic=output_type_generic,
            output_type_optional=output_type_optional,
        )
        return declaration, index + 1

    @classmethod
    def _parse_structural_intent_given_ask_output_confidence_floor_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRIntent, int] | None:
        if kind != "intent" or field_token.value not in {"given", "ask", "output", "confidence_floor"}:
            return None

        intent_given = ""
        intent_ask = ""
        output_type_name = ""
        output_type_generic = ""
        output_type_optional = False
        confidence_floor: float | None = None
        seen_fields: set[str] = set()
        index = start_index + 3

        for _ in range(4):
            if index >= len(tokens):
                return None

            current_field_token = tokens[index]
            if not cls._is_identifier_like_value_token(current_field_token):
                return None

            field_name = current_field_token.value
            if field_name in seen_fields or field_name not in {"given", "ask", "output", "confidence_floor"}:
                return None
            seen_fields.add(field_name)

            if index + 1 >= len(tokens) or tokens[index + 1].type != TokenType.COLON:
                return None

            value_index = index + 2
            if field_name == "given":
                if value_index >= len(tokens) or tokens[value_index].type != TokenType.IDENTIFIER:
                    return None
                intent_given = tokens[value_index].value
                index = value_index + 1
                continue

            if field_name == "ask":
                if value_index >= len(tokens) or tokens[value_index].type != TokenType.STRING:
                    return None
                intent_ask = tokens[value_index].value
                index = value_index + 1
                continue

            if field_name == "output":
                parsed_type_expr = cls._parse_structural_type_expr(tokens, value_index)
                if parsed_type_expr is None:
                    return None
                output_type_name, output_type_generic, output_type_optional, index = parsed_type_expr
                continue

            if value_index >= len(tokens) or tokens[value_index].type != TokenType.FLOAT:
                return None
            confidence_floor = float(tokens[value_index].value)
            index = value_index + 1

        if seen_fields != {"given", "ask", "output", "confidence_floor"}:
            return None
        if not intent_given or not intent_ask or not output_type_name or confidence_floor is None:
            return None
        if index >= len(tokens) or tokens[index].type != TokenType.RBRACE:
            return None

        declaration = IRIntent(
            source_line=block_token.line,
            source_column=block_token.column,
            name=name_token.value,
            given=intent_given,
            ask=intent_ask,
            output_type_name=output_type_name,
            output_type_generic=output_type_generic,
            output_type_optional=output_type_optional,
            confidence_floor=confidence_floor,
        )
        return declaration, index + 1

    @classmethod
    def _parse_structural_axonendpoint_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IREndpoint, int] | None:
        if kind != "axonendpoint" or field_token.value not in cls._AXONENDPOINT_SUPPORTED_FIELDS:
            return None

        parsed_fields = cls._parse_structural_axonendpoint_fields(tokens, start_index=start_index)
        if parsed_fields is None:
            return None

        endpoint_fields, next_index = parsed_fields
        if frozenset(endpoint_fields) not in cls._AXONENDPOINT_SUPPORTED_FIELD_SETS:
            return None
        if any(isinstance(value, str) and not value for value in endpoint_fields.values()):
            return None

        endpoint_kwargs: dict[str, str | int] = {
            "method": "",
            "path": "",
            "execute_flow": "",
        }
        for field_name, value in endpoint_fields.items():
            endpoint_kwargs[cls._AXONENDPOINT_FIELD_TO_IR_ATTR[field_name]] = value

        return (
            IREndpoint(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                **endpoint_kwargs,
            ),
            next_index,
        )

    @classmethod
    def _parse_structural_axonendpoint_fields(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
    ) -> tuple[dict[str, str | int], int] | None:
        endpoint_fields: dict[str, str | int] = {}
        index = start_index + 3

        while index < len(tokens):
            current_field_token = tokens[index]
            if current_field_token.type == TokenType.RBRACE:
                return endpoint_fields, index + 1
            if not cls._is_identifier_like_value_token(current_field_token):
                return None

            field_name = current_field_token.value
            if field_name in endpoint_fields or field_name not in cls._AXONENDPOINT_SUPPORTED_FIELDS:
                return None
            if index + 1 >= len(tokens) or tokens[index + 1].type != TokenType.COLON:
                return None

            value_index = index + 2
            if value_index >= len(tokens):
                return None

            parsed_value = cls._parse_structural_axonendpoint_field_value(field_name, tokens[value_index])
            if parsed_value is None:
                return None

            endpoint_fields[field_name] = parsed_value
            index = value_index + 1

        return None

    @classmethod
    def _parse_structural_axonendpoint_field_value(
        cls,
        field_name: str,
        value_token: Token,
    ) -> str | int | None:
        if field_name == "path":
            if value_token.type == TokenType.STRING:
                return value_token.value
            return None
        if field_name == "retries":
            if value_token.type == TokenType.INTEGER:
                return int(value_token.value)
            return None
        if field_name == "timeout":
            if value_token.type == TokenType.DURATION or cls._is_identifier_like_value_token(value_token):
                return value_token.value
            return None
        if field_name == "method":
            if cls._is_identifier_like_value_token(value_token):
                return value_token.value.upper()
            return None
        if field_name in {"execute", "body", "output", "shield"} and cls._is_identifier_like_value_token(value_token):
            return value_token.value
        return None

    @classmethod
    def _parse_structural_intent_confidence_floor_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRIntent, int] | None:
        if kind != "intent" or len(tokens) - start_index < 10:
            return None

        second_field_token = tokens[start_index + 6]
        if (
            not cls._is_identifier_like_value_token(second_field_token)
            or tokens[start_index + 7].type != TokenType.COLON
            or tokens[start_index + 9].type != TokenType.RBRACE
        ):
            return None

        first_value_token = tokens[start_index + 5]
        second_value_token = tokens[start_index + 8]
        intent_ask = ""
        confidence_floor: float | None = None

        field_pairs = (
            (field_token.value, first_value_token),
            (second_field_token.value, second_value_token),
        )
        for field_name, value_token in field_pairs:
            if field_name == "ask" and value_token.type == TokenType.STRING:
                intent_ask = value_token.value
                continue
            if field_name == "confidence_floor" and value_token.type == TokenType.FLOAT:
                confidence_floor = float(value_token.value)
                continue
            return None

        if not intent_ask or confidence_floor is None:
            return None

        declaration = IRIntent(
            source_line=block_token.line,
            source_column=block_token.column,
            name=name_token.value,
            ask=intent_ask,
            confidence_floor=confidence_floor,
        )
        return declaration, start_index + 10

    @classmethod
    def _parse_structural_intent_given_ask_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRIntent, int] | None:
        if kind != "intent" or len(tokens) - start_index < 10:
            return None

        second_field_token = tokens[start_index + 6]
        if (
            not cls._is_identifier_like_value_token(second_field_token)
            or tokens[start_index + 7].type != TokenType.COLON
            or tokens[start_index + 9].type != TokenType.RBRACE
        ):
            return None

        first_value_token = tokens[start_index + 5]
        second_value_token = tokens[start_index + 8]
        intent_given = ""
        intent_ask = ""

        field_pairs = (
            (field_token.value, first_value_token),
            (second_field_token.value, second_value_token),
        )
        for field_name, value_token in field_pairs:
            if field_name == "given" and value_token.type == TokenType.IDENTIFIER:
                intent_given = value_token.value
                continue
            if field_name == "ask" and value_token.type == TokenType.STRING:
                intent_ask = value_token.value
                continue
            return None

        if not intent_given or not intent_ask:
            return None

        declaration = IRIntent(
            source_line=block_token.line,
            source_column=block_token.column,
            name=name_token.value,
            given=intent_given,
            ask=intent_ask,
        )
        return declaration, start_index + 10

    @classmethod
    def _parse_structural_raise_on_violation_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRAnchor, int] | None:
        if kind != "anchor" or field_token.value != "on_violation" or len(tokens) - start_index < 8:
            return None
        value_token = tokens[start_index + 5]
        target_token = tokens[start_index + 6]
        if (
            value_token.type != TokenType.IDENTIFIER
            or value_token.value != "raise"
            or target_token.type != TokenType.IDENTIFIER
            or tokens[start_index + 7].type != TokenType.RBRACE
        ):
            return None
        declaration = cls._parse_structural_anchor_block(
            block_token,
            name_token,
            field_token,
            value_token,
            target_token,
        )
        if declaration is None:
            return None
        return declaration, start_index + 8

    @classmethod
    def _parse_structural_fallback_on_violation_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRAnchor, int] | None:
        if kind != "anchor" or field_token.value != "on_violation" or len(tokens) - start_index < 10:
            return None
        value_token = tokens[start_index + 5]
        target_token = tokens[start_index + 7]
        if (
            value_token.type != TokenType.IDENTIFIER
            or value_token.value != "fallback"
            or tokens[start_index + 6].type != TokenType.LPAREN
            or target_token.type != TokenType.STRING
            or tokens[start_index + 8].type != TokenType.RPAREN
            or tokens[start_index + 9].type != TokenType.RBRACE
        ):
            return None
        declaration = cls._parse_structural_anchor_block(
            block_token,
            name_token,
            field_token,
            value_token,
            target_token,
        )
        if declaration is None:
            return None
        return declaration, start_index + 10

    @classmethod
    def _parse_structural_reject_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRAnchor, int] | None:
        if kind != "anchor" or field_token.value != "reject" or len(tokens) - start_index < 9:
            return None
        if tokens[start_index + 5].type != TokenType.LBRACKET:
            return None
        reject_values = cls._parse_structural_bracketed_identifier_values(tokens, start_index + 6)
        if reject_values is None:
            return None
        values, next_index = reject_values
        if next_index >= len(tokens) or tokens[next_index].type != TokenType.RBRACE:
            return None
        declaration = IRAnchor(
            source_line=block_token.line,
            source_column=block_token.column,
            name=name_token.value,
            reject=values,
        )
        return declaration, next_index + 1

    @classmethod
    def _parse_structural_refuse_if_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRPersona, int] | None:
        if kind != "persona" or field_token.value != "refuse_if" or len(tokens) - start_index < 9:
            return None
        if tokens[start_index + 5].type != TokenType.LBRACKET:
            return None
        refuse_values = cls._parse_structural_bracketed_identifier_values(tokens, start_index + 6)
        if refuse_values is None:
            return None
        values, next_index = refuse_values
        if next_index >= len(tokens) or tokens[next_index].type != TokenType.RBRACE:
            return None
        declaration = IRPersona(
            source_line=block_token.line,
            source_column=block_token.column,
            name=name_token.value,
            refuse_if=values,
        )
        return declaration, next_index + 1

    @classmethod
    def _parse_structural_domain_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRPersona, int] | None:
        if kind != "persona" or field_token.value != "domain" or len(tokens) - start_index < 9:
            return None
        if tokens[start_index + 5].type != TokenType.LBRACKET:
            return None
        domain_values = cls._parse_structural_bracketed_string_values(tokens, start_index + 6)
        if domain_values is None:
            return None
        values, next_index = domain_values
        if next_index >= len(tokens) or tokens[next_index].type != TokenType.RBRACE:
            return None
        declaration = IRPersona(
            source_line=block_token.line,
            source_column=block_token.column,
            name=name_token.value,
            domain=values,
        )
        return declaration, next_index + 1

    @classmethod
    def _parse_structural_memory_decay_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRMemory, int] | None:
        if kind != "memory" or field_token.value != "decay" or len(tokens) - start_index < 7:
            return None
        value_token = tokens[start_index + 5]
        if value_token.type != TokenType.DURATION or tokens[start_index + 6].type != TokenType.RBRACE:
            return None
        declaration = IRMemory(
            source_line=block_token.line,
            source_column=block_token.column,
            name=name_token.value,
            decay=value_token.value,
        )
        return declaration, start_index + 7

    @classmethod
    def _parse_structural_tool_timeout_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRToolSpec, int] | None:
        if kind != "tool" or field_token.value != "timeout" or len(tokens) - start_index < 7:
            return None
        value_token = tokens[start_index + 5]
        if value_token.type != TokenType.DURATION or tokens[start_index + 6].type != TokenType.RBRACE:
            return None
        declaration = IRToolSpec(
            source_line=block_token.line,
            source_column=block_token.column,
            name=name_token.value,
            timeout=value_token.value,
            effect_row=(),
        )
        return declaration, start_index + 7

    @classmethod
    def _parse_structural_tool_effects_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRToolSpec, int] | None:
        if kind != "tool" or field_token.value != "effects" or len(tokens) - start_index < 9:
            return None
        if tokens[start_index + 5].type != TokenType.LT:
            return None

        parsed_effect_row = cls._parse_structural_effect_row(tokens, start_index + 6)
        if parsed_effect_row is None:
            return None
        effect_row, index = parsed_effect_row
        if index >= len(tokens) or tokens[index].type != TokenType.RBRACE:
            return None

        declaration = IRToolSpec(
            source_line=block_token.line,
            source_column=block_token.column,
            name=name_token.value,
            effect_row=effect_row,
        )
        return declaration, index + 1

    @classmethod
    def _parse_structural_effect_row(
        cls,
        tokens: tuple[Token, ...],
        start_index: int,
    ) -> tuple[tuple[str, ...], int] | None:
        entries: list[str] = []
        epistemic_level = ""
        index = start_index

        while index < len(tokens) and tokens[index].type != TokenType.GT:
            parsed_entry = cls._parse_structural_effect_row_entry(tokens, index)
            if parsed_entry is None:
                return None
            effect_value, next_index, entry_is_epistemic = parsed_entry
            if entry_is_epistemic:
                epistemic_level = effect_value
            else:
                entries.append(effect_value)
            index = next_index
            if index < len(tokens) and tokens[index].type == TokenType.COMMA:
                index += 1

        if index >= len(tokens) or tokens[index].type != TokenType.GT:
            return None

        effect_row = tuple(entries)
        if epistemic_level:
            effect_row = effect_row + (f"epistemic:{epistemic_level}",)
        return effect_row, index + 1

    @classmethod
    def _parse_structural_effect_row_entry(
        cls,
        tokens: tuple[Token, ...],
        start_index: int,
    ) -> tuple[str, int, bool] | None:
        if start_index >= len(tokens):
            return None
        name_token = tokens[start_index]
        if not cls._is_identifier_like_value_token(name_token):
            return None
        name = name_token.value
        next_index = start_index + 1

        if next_index < len(tokens) and tokens[next_index].type == TokenType.COLON:
            next_index += 1
            if next_index >= len(tokens) or not cls._is_identifier_like_value_token(tokens[next_index]):
                return None
            qualifier = tokens[next_index].value
            return (qualifier if name == "epistemic" else f"{name}:{qualifier}"), next_index + 1, name == "epistemic"

        return name, next_index, False

    @classmethod
    def _parse_structural_tool_filter_call_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        kind: str,
        block_token: Token,
        name_token: Token,
        field_token: Token,
    ) -> tuple[IRToolSpec, int] | None:
        if kind != "tool" or field_token.value != "filter" or len(tokens) - start_index < 8:
            return None
        value_token = tokens[start_index + 5]
        if not cls._is_identifier_like_value_token(value_token):
            return None
        if tokens[start_index + 6].type != TokenType.LPAREN:
            return None

        index = start_index + 7
        parts = [value_token.value, "("]
        while index < len(tokens) and tokens[index].type != TokenType.RPAREN:
            parts.append(tokens[index].value)
            index += 1
        if index >= len(tokens) or tokens[index].type != TokenType.RPAREN:
            return None
        parts.append(")")
        index += 1
        if index >= len(tokens) or tokens[index].type != TokenType.RBRACE:
            return None

        declaration = IRToolSpec(
            source_line=block_token.line,
            source_column=block_token.column,
            name=name_token.value,
            filter_expr="".join(parts),
            effect_row=(),
        )
        return declaration, index + 1

    @classmethod
    def _parse_structural_bracketed_identifier_values(
        cls,
        tokens: tuple[Token, ...],
        start_index: int,
    ) -> tuple[tuple[str, ...], int] | None:
        values: list[str] = []
        index = start_index

        while index < len(tokens):
            token = tokens[index]
            if token.type == TokenType.RBRACKET:
                if not values:
                    return None
                return tuple(values), index + 1
            if not cls._is_identifier_like_value_token(token):
                return None
            values.append(token.value)
            index += 1
            if index >= len(tokens):
                return None
            separator = tokens[index]
            if separator.type == TokenType.RBRACKET:
                return tuple(values), index + 1
            if separator.type != TokenType.COMMA:
                return None
            index += 1

        return None

    @classmethod
    def _parse_structural_bracketed_string_values(
        cls,
        tokens: tuple[Token, ...],
        start_index: int,
    ) -> tuple[tuple[str, ...], int] | None:
        values: list[str] = []
        index = start_index

        while index < len(tokens):
            token = tokens[index]
            if token.type == TokenType.RBRACKET:
                if not values:
                    return None
                return tuple(values), index + 1
            if token.type != TokenType.STRING:
                return None
            values.append(token.value)
            index += 1
            if index >= len(tokens):
                return None
            separator = tokens[index]
            if separator.type == TokenType.RBRACKET:
                return tuple(values), index + 1
            if separator.type != TokenType.COMMA:
                return None
            index += 1

        return None

    @staticmethod
    def _parse_structural_persona_block(
        block_token: Token,
        name_token: Token,
        field_token: Token,
        value_token: Token,
    ) -> IRPersona | None:
        if field_token.value == "domain":
            return None
        if field_token.value == "tone":
            return IRPersona(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                tone=value_token.value,
            )
        if field_token.value == "language" and value_token.type == TokenType.STRING:
            return IRPersona(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                language=value_token.value,
            )
        if field_token.value == "confidence_threshold" and value_token.type in (TokenType.INTEGER, TokenType.FLOAT):
            return IRPersona(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                confidence_threshold=float(value_token.value),
            )
        if field_token.value == "description" and value_token.type == TokenType.STRING:
            return IRPersona(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                description=value_token.value,
            )
        if field_token.value == "cite_sources" and value_token.type == TokenType.BOOL:
            return IRPersona(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                cite_sources=value_token.value == "true",
            )
        if field_token.value == "refuse_if":
            return None
        return None

    @staticmethod
    def _parse_structural_memory_block(
        block_token: Token,
        name_token: Token,
        field_token: Token,
        value_token: Token,
    ) -> IRMemory | None:
        if field_token.value == "store":
            return IRMemory(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                store=value_token.value,
            )
        if field_token.value == "backend":
            return IRMemory(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                backend=value_token.value,
            )
        if field_token.value == "retrieval":
            return IRMemory(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                retrieval=value_token.value,
            )
        if field_token.value == "decay":
            return IRMemory(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                decay=value_token.value,
            )
        return None

    @staticmethod
    def _parse_structural_intent_block(
        block_token: Token,
        name_token: Token,
        field_token: Token,
        value_token: Token,
    ) -> IRIntent | None:
        if field_token.value == "ask" and value_token.type == TokenType.STRING:
            return IRIntent(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                ask=value_token.value,
            )
        return None

    @staticmethod
    def _parse_structural_tool_block(
        block_token: Token,
        name_token: Token,
        field_token: Token,
        value_token: Token,
    ) -> IRToolSpec | None:
        if field_token.value == "provider":
            return IRToolSpec(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                provider=value_token.value,
                effect_row=(),
            )
        if field_token.value == "filter":
            return IRToolSpec(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                filter_expr=value_token.value,
                effect_row=(),
            )
        if field_token.value == "runtime":
            return IRToolSpec(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                runtime=value_token.value,
                effect_row=(),
            )
        if field_token.value == "sandbox" and value_token.type == TokenType.BOOL:
            return IRToolSpec(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                sandbox=value_token.value == "true",
                effect_row=(),
            )
        if field_token.value == "timeout" and value_token.type == TokenType.DURATION:
            return IRToolSpec(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                timeout=value_token.value,
                effect_row=(),
            )
        if field_token.value == "max_results" and value_token.type == TokenType.INTEGER:
            return IRToolSpec(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                max_results=int(value_token.value),
                effect_row=(),
            )
        return None

    @staticmethod
    def _parse_structural_context_block(
        block_token: Token,
        name_token: Token,
        field_token: Token,
        value_token: Token,
    ) -> IRContext | None:
        if field_token.value == "memory":
            return IRContext(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                memory_scope=value_token.value,
            )
        if field_token.value == "language" and value_token.type == TokenType.STRING:
            return IRContext(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                language=value_token.value,
            )
        if field_token.value == "temperature" and value_token.type in (TokenType.INTEGER, TokenType.FLOAT):
            return IRContext(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                temperature=float(value_token.value),
            )
        if field_token.value == "max_tokens" and value_token.type == TokenType.INTEGER:
            return IRContext(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                max_tokens=int(value_token.value),
            )
        if field_token.value == "depth":
            return IRContext(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                depth=value_token.value,
            )
        if field_token.value == "cite_sources" and value_token.type == TokenType.BOOL:
            return IRContext(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                cite_sources=value_token.value == "true",
            )
        return None

    @staticmethod
    def _parse_structural_anchor_block(
        block_token: Token,
        name_token: Token,
        field_token: Token,
        value_token: Token,
        target_token: Token | None = None,
    ) -> IRAnchor | None:
        if field_token.value == "description" and value_token.type == TokenType.STRING:
            return IRAnchor(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                description=value_token.value,
            )
        if field_token.value == "confidence_floor" and value_token.type in (TokenType.INTEGER, TokenType.FLOAT):
            return IRAnchor(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                confidence_floor=float(value_token.value),
            )
        if field_token.value == "unknown_response" and value_token.type == TokenType.STRING:
            return IRAnchor(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                unknown_response=value_token.value,
            )
        if field_token.value == "reject":
            return None
        if field_token.value == "on_violation" and value_token.type == TokenType.IDENTIFIER:
            return NativeDevelopmentFrontendImplementation._parse_structural_anchor_on_violation_block(
                block_token,
                name_token,
                value_token,
                target_token,
            )
        if field_token.value == "require":
            return IRAnchor(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                require=value_token.value,
            )
        if field_token.value == "enforce":
            return IRAnchor(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                enforce=value_token.value,
            )
        return None

    @staticmethod
    def _parse_structural_anchor_on_violation_block(
        block_token: Token,
        name_token: Token,
        value_token: Token,
        target_token: Token | None,
    ) -> IRAnchor | None:
        if value_token.value == "raise":
            if target_token is None or target_token.type != TokenType.IDENTIFIER:
                return None
            return IRAnchor(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                on_violation=value_token.value,
                on_violation_target=target_token.value,
            )
        if value_token.value == "fallback":
            if target_token is None or target_token.type != TokenType.STRING:
                return None
            return IRAnchor(
                source_line=block_token.line,
                source_column=block_token.column,
                name=name_token.value,
                on_violation=value_token.value,
                on_violation_target=target_token.value,
            )
        return IRAnchor(
            source_line=block_token.line,
            source_column=block_token.column,
            name=name_token.value,
            on_violation=value_token.value,
        )

    @staticmethod
    def _supports_structural_prefixed_run_config(run_config: dict[str, Any]) -> bool:
        return True

    @staticmethod
    def _resolve_structural_prefixed_persona(
        personas: list[IRPersona],
        persona_name: str,
    ) -> IRPersona | None:
        if not persona_name:
            return None
        return next((persona for persona in personas if persona.name == persona_name), None)

    @staticmethod
    def _resolve_structural_prefixed_context(
        contexts: list[IRContext],
        context_name: str,
    ) -> IRContext | None:
        if not context_name:
            return None
        return next((context for context in contexts if context.name == context_name), None)

    @staticmethod
    def _resolve_structural_prefixed_anchors(
        anchors: list[IRAnchor],
        anchor_names: tuple[str, ...],
    ) -> tuple[IRAnchor, ...]:
        if not anchor_names:
            return ()
        anchors_by_name = {anchor.name: anchor for anchor in anchors}
        resolved_anchors = tuple(anchors_by_name[name] for name in anchor_names if name in anchors_by_name)
        if len(resolved_anchors) != len(anchor_names):
            return ()
        return resolved_anchors

    @classmethod
    def _match_persona_context_anchor_prefixed_native_success_program(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[IRProgram, int, int] | None:
        if len(tokens) < 31:
            return None
        if not cls._matches_persona_context_anchor_prefixed_success_prefix(tokens):
            return None

        run_config = cls._match_minimal_success_flow_run_tokens(
            tokens[21:],
            available_personas={tokens[1].value},
            available_contexts={tokens[8].value},
            available_anchors={tokens[15].value},
        )
        if run_config is None:
            return None
        on_failure_params = run_config["on_failure_params"]
        if not cls._supports_persona_context_anchor_prefixed_run_config(run_config):
            return None

        persona_token = tokens[0]
        persona = IRPersona(
            source_line=persona_token.line,
            source_column=persona_token.column,
            name=tokens[1].value,
            tone=tokens[5].value,
        )
        context_token = tokens[7]
        context = IRContext(
            source_line=context_token.line,
            source_column=context_token.column,
            name=tokens[8].value,
            memory_scope=tokens[12].value,
        )
        anchor_token = tokens[14]
        anchor = IRAnchor(
            source_line=anchor_token.line,
            source_column=anchor_token.column,
            name=tokens[15].value,
            require=tokens[19].value,
        )

        flow_token = tokens[21]
        flow_name = tokens[22].value
        run_token = tokens[27]
        flow = IRFlow(
            source_line=flow_token.line,
            source_column=flow_token.column,
            name=flow_name,
        )
        run = IRRun(
            source_line=run_token.line,
            source_column=run_token.column,
            flow_name=flow_name,
            persona_name=run_config["persona_name"],
            context_name=run_config["context_name"],
            anchor_names=run_config["anchor_names"],
            on_failure=run_config["on_failure"],
            on_failure_params=on_failure_params,
            output_to=run_config["output_to"],
            effort=run_config["effort"],
            resolved_flow=flow,
            resolved_persona=persona if run_config["persona_name"] else None,
            resolved_context=context if run_config["context_name"] else None,
            resolved_anchors=(anchor,) if run_config["anchor_names"] else (),
        )
        return (
            IRProgram(
                source_line=persona_token.line,
                source_column=persona_token.column,
                personas=(persona,),
                contexts=(context,),
                anchors=(anchor,),
                flows=(flow,),
                runs=(run,),
            ),
            len(tokens) + 1,
            5,
        )

    @staticmethod
    def _supports_persona_context_anchor_prefixed_run_config(run_config: dict[str, Any]) -> bool:
        persona_name = run_config["persona_name"]
        context_name = run_config["context_name"]
        anchor_names = run_config["anchor_names"]
        on_failure = run_config["on_failure"]
        on_failure_params = run_config["on_failure_params"]
        if persona_name or context_name or anchor_names:
            return (
                len(anchor_names) <= 1
                and not on_failure
                and not on_failure_params
                and not run_config["output_to"]
                and not run_config["effort"]
            )
        if on_failure not in ("", "log", "retry", "raise"):
            return False
        if not on_failure_params:
            return True
        if on_failure == "raise":
            return len(on_failure_params) == 1 and on_failure_params[0][0] == "target"
        if on_failure == "retry":
            return len(on_failure_params) >= 1
        return False

    @classmethod
    def _matches_persona_context_anchor_prefixed_success_prefix(cls, tokens: tuple[Token, ...]) -> bool:
        return (
            tokens[0].type == TokenType.PERSONA
            and tokens[1].type == TokenType.IDENTIFIER
            and tokens[2].type == TokenType.LBRACE
            and cls._is_identifier_like_value_token(tokens[3])
            and tokens[3].value == "tone"
            and tokens[4].type == TokenType.COLON
            and cls._is_identifier_like_value_token(tokens[5])
            and tokens[5].value in VALID_TONES
            and tokens[6].type == TokenType.RBRACE
            and tokens[7].type == TokenType.CONTEXT
            and tokens[8].type == TokenType.IDENTIFIER
            and tokens[9].type == TokenType.LBRACE
            and cls._is_identifier_like_value_token(tokens[10])
            and tokens[10].value == "memory"
            and tokens[11].type == TokenType.COLON
            and cls._is_identifier_like_value_token(tokens[12])
            and tokens[12].value in VALID_MEMORY_SCOPES
            and tokens[13].type == TokenType.RBRACE
            and tokens[14].type == TokenType.ANCHOR
            and tokens[15].type == TokenType.IDENTIFIER
            and tokens[16].type == TokenType.LBRACE
            and cls._is_identifier_like_value_token(tokens[17])
            and tokens[17].value == "require"
            and tokens[18].type == TokenType.COLON
            and cls._is_identifier_like_value_token(tokens[19])
            and tokens[20].type == TokenType.RBRACE
            and cls._matches_minimal_success_flow_run_prefix(tokens[21:])
        )

    @classmethod
    def _match_context_anchor_prefixed_native_success_program(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[IRProgram, int, int] | None:
        if len(tokens) != 24:
            return None
        if not cls._matches_context_anchor_prefixed_success_prefix(tokens):
            return None

        run_config = cls._match_minimal_success_flow_run_tokens(tokens[14:])
        if run_config is None or run_config["on_failure"] or run_config["output_to"] or run_config["effort"]:
            return None

        context_token = tokens[0]
        context = IRContext(
            source_line=context_token.line,
            source_column=context_token.column,
            name=tokens[1].value,
            memory_scope=tokens[5].value,
        )
        anchor_token = tokens[7]
        anchor = IRAnchor(
            source_line=anchor_token.line,
            source_column=anchor_token.column,
            name=tokens[8].value,
            require=tokens[12].value,
        )

        flow_token = tokens[14]
        flow_name = tokens[15].value
        run_token = tokens[20]
        flow = IRFlow(
            source_line=flow_token.line,
            source_column=flow_token.column,
            name=flow_name,
        )
        run = IRRun(
            source_line=run_token.line,
            source_column=run_token.column,
            flow_name=flow_name,
            resolved_flow=flow,
        )
        return (
            IRProgram(
                source_line=context_token.line,
                source_column=context_token.column,
                contexts=(context,),
                anchors=(anchor,),
                flows=(flow,),
                runs=(run,),
            ),
            len(tokens) + 1,
            4,
        )

    @classmethod
    def _matches_context_anchor_prefixed_success_prefix(cls, tokens: tuple[Token, ...]) -> bool:
        return (
            tokens[0].type == TokenType.CONTEXT
            and tokens[1].type == TokenType.IDENTIFIER
            and tokens[2].type == TokenType.LBRACE
            and cls._is_identifier_like_value_token(tokens[3])
            and tokens[3].value == "memory"
            and tokens[4].type == TokenType.COLON
            and cls._is_identifier_like_value_token(tokens[5])
            and tokens[5].value in VALID_MEMORY_SCOPES
            and tokens[6].type == TokenType.RBRACE
            and tokens[7].type == TokenType.ANCHOR
            and tokens[8].type == TokenType.IDENTIFIER
            and tokens[9].type == TokenType.LBRACE
            and cls._is_identifier_like_value_token(tokens[10])
            and tokens[10].value == "require"
            and tokens[11].type == TokenType.COLON
            and cls._is_identifier_like_value_token(tokens[12])
            and tokens[13].type == TokenType.RBRACE
            and cls._matches_minimal_success_flow_run_prefix(tokens[14:])
        )

    @classmethod
    def _match_persona_anchor_prefixed_native_success_program(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[IRProgram, int, int] | None:
        if len(tokens) != 24:
            return None
        if not cls._matches_persona_anchor_prefixed_success_prefix(tokens):
            return None

        run_config = cls._match_minimal_success_flow_run_tokens(tokens[14:])
        if run_config is None or run_config["on_failure"] or run_config["output_to"] or run_config["effort"]:
            return None

        persona_token = tokens[0]
        persona = IRPersona(
            source_line=persona_token.line,
            source_column=persona_token.column,
            name=tokens[1].value,
            tone=tokens[5].value,
        )
        anchor_token = tokens[7]
        anchor = IRAnchor(
            source_line=anchor_token.line,
            source_column=anchor_token.column,
            name=tokens[8].value,
            require=tokens[12].value,
        )

        flow_token = tokens[14]
        flow_name = tokens[15].value
        run_token = tokens[20]
        flow = IRFlow(
            source_line=flow_token.line,
            source_column=flow_token.column,
            name=flow_name,
        )
        run = IRRun(
            source_line=run_token.line,
            source_column=run_token.column,
            flow_name=flow_name,
            resolved_flow=flow,
        )
        return (
            IRProgram(
                source_line=persona_token.line,
                source_column=persona_token.column,
                personas=(persona,),
                anchors=(anchor,),
                flows=(flow,),
                runs=(run,),
            ),
            len(tokens) + 1,
            4,
        )

    @classmethod
    def _matches_persona_anchor_prefixed_success_prefix(cls, tokens: tuple[Token, ...]) -> bool:
        return (
            tokens[0].type == TokenType.PERSONA
            and tokens[1].type == TokenType.IDENTIFIER
            and tokens[2].type == TokenType.LBRACE
            and cls._is_identifier_like_value_token(tokens[3])
            and tokens[3].value == "tone"
            and tokens[4].type == TokenType.COLON
            and cls._is_identifier_like_value_token(tokens[5])
            and tokens[5].value in VALID_TONES
            and tokens[6].type == TokenType.RBRACE
            and tokens[7].type == TokenType.ANCHOR
            and tokens[8].type == TokenType.IDENTIFIER
            and tokens[9].type == TokenType.LBRACE
            and cls._is_identifier_like_value_token(tokens[10])
            and tokens[10].value == "require"
            and tokens[11].type == TokenType.COLON
            and cls._is_identifier_like_value_token(tokens[12])
            and tokens[13].type == TokenType.RBRACE
            and cls._matches_minimal_success_flow_run_prefix(tokens[14:])
        )

    @classmethod
    def _match_persona_context_prefixed_native_success_program(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[IRProgram, int, int] | None:
        if len(tokens) != 24:
            return None
        if not cls._matches_persona_context_prefixed_success_prefix(tokens):
            return None

        run_config = cls._match_minimal_success_flow_run_tokens(tokens[14:])
        if run_config is None or run_config["on_failure"] or run_config["output_to"] or run_config["effort"]:
            return None

        persona_token = tokens[0]
        persona = IRPersona(
            source_line=persona_token.line,
            source_column=persona_token.column,
            name=tokens[1].value,
            tone=tokens[5].value,
        )
        context_token = tokens[7]
        context = IRContext(
            source_line=context_token.line,
            source_column=context_token.column,
            name=tokens[8].value,
            memory_scope=tokens[12].value,
        )

        flow_token = tokens[14]
        flow_name = tokens[15].value
        run_token = tokens[20]
        flow = IRFlow(
            source_line=flow_token.line,
            source_column=flow_token.column,
            name=flow_name,
        )
        run = IRRun(
            source_line=run_token.line,
            source_column=run_token.column,
            flow_name=flow_name,
            resolved_flow=flow,
        )
        return (
            IRProgram(
                source_line=persona_token.line,
                source_column=persona_token.column,
                personas=(persona,),
                contexts=(context,),
                flows=(flow,),
                runs=(run,),
            ),
            len(tokens) + 1,
            4,
        )

    @classmethod
    def _matches_persona_context_prefixed_success_prefix(cls, tokens: tuple[Token, ...]) -> bool:
        return (
            tokens[0].type == TokenType.PERSONA
            and tokens[1].type == TokenType.IDENTIFIER
            and tokens[2].type == TokenType.LBRACE
            and cls._is_identifier_like_value_token(tokens[3])
            and tokens[3].value == "tone"
            and tokens[4].type == TokenType.COLON
            and cls._is_identifier_like_value_token(tokens[5])
            and tokens[5].value in VALID_TONES
            and tokens[6].type == TokenType.RBRACE
            and tokens[7].type == TokenType.CONTEXT
            and tokens[8].type == TokenType.IDENTIFIER
            and tokens[9].type == TokenType.LBRACE
            and cls._is_identifier_like_value_token(tokens[10])
            and tokens[10].value == "memory"
            and tokens[11].type == TokenType.COLON
            and cls._is_identifier_like_value_token(tokens[12])
            and tokens[12].value in VALID_MEMORY_SCOPES
            and tokens[13].type == TokenType.RBRACE
            and cls._matches_minimal_success_flow_run_prefix(tokens[14:])
        )

    @classmethod
    def _match_persona_prefixed_native_success_program(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[IRProgram, int, int] | None:
        if len(tokens) != 17:
            return None
        if not cls._matches_persona_prefixed_success_prefix(tokens):
            return None

        run_config = cls._match_minimal_success_flow_run_tokens(tokens[7:])
        if run_config is None or run_config["on_failure"] or run_config["output_to"] or run_config["effort"]:
            return None

        persona_token = tokens[0]
        persona = IRPersona(
            source_line=persona_token.line,
            source_column=persona_token.column,
            name=tokens[1].value,
            tone=tokens[5].value,
        )

        flow_token = tokens[7]
        flow_name = tokens[8].value
        run_token = tokens[13]
        flow = IRFlow(
            source_line=flow_token.line,
            source_column=flow_token.column,
            name=flow_name,
        )
        run = IRRun(
            source_line=run_token.line,
            source_column=run_token.column,
            flow_name=flow_name,
            resolved_flow=flow,
        )
        return (
            IRProgram(
                source_line=persona_token.line,
                source_column=persona_token.column,
                personas=(persona,),
                flows=(flow,),
                runs=(run,),
            ),
            len(tokens) + 1,
            3,
        )

    @classmethod
    def _matches_persona_prefixed_success_prefix(cls, tokens: tuple[Token, ...]) -> bool:
        return (
            tokens[0].type == TokenType.PERSONA
            and tokens[1].type == TokenType.IDENTIFIER
            and tokens[2].type == TokenType.LBRACE
            and cls._is_identifier_like_value_token(tokens[3])
            and tokens[3].value == "tone"
            and tokens[4].type == TokenType.COLON
            and cls._is_identifier_like_value_token(tokens[5])
            and tokens[5].value in VALID_TONES
            and tokens[6].type == TokenType.RBRACE
            and cls._matches_minimal_success_flow_run_prefix(tokens[7:])
        )

    @staticmethod
    def _structural_invalid_persona_tone_diagnostic(persona: IRPersona) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"Unknown tone '{persona.tone}' for persona '{persona.name}'. "
                f"Valid tones: {', '.join(sorted(VALID_TONES))}"
            ),
            line=persona.source_line,
            column=persona.source_column,
        )

    @staticmethod
    def _structural_invalid_persona_confidence_threshold_diagnostic(
        persona: IRPersona,
    ) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"confidence_threshold must be between 0.0 and 1.0, got {persona.confidence_threshold}"
            ),
            line=persona.source_line,
            column=persona.source_column,
        )

    @staticmethod
    def _append_structural_persona_validation_diagnostics(
        persona: IRPersona,
        validation_diagnostics: list[FrontendDiagnostic],
    ) -> None:
        if persona.tone and persona.tone not in VALID_TONES:
            validation_diagnostics.append(
                NativeDevelopmentFrontendImplementation._structural_invalid_persona_tone_diagnostic(
                    persona,
                )
            )
        if persona.confidence_threshold is not None and not 0.0 <= persona.confidence_threshold <= 1.0:
            validation_diagnostics.append(
                NativeDevelopmentFrontendImplementation._structural_invalid_persona_confidence_threshold_diagnostic(
                    persona,
                )
            )

    @staticmethod
    def _structural_invalid_anchor_confidence_floor_diagnostic(
        anchor: IRAnchor,
    ) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"confidence_floor must be between 0.0 and 1.0, got {anchor.confidence_floor}"
            ),
            line=anchor.source_line,
            column=anchor.source_column,
        )

    @staticmethod
    def _structural_invalid_intent_confidence_floor_diagnostic(
        intent: IRIntent,
    ) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"confidence_floor must be between 0.0 and 1.0, got {intent.confidence_floor}"
            ),
            line=intent.source_line,
            column=intent.source_column,
        )

    @staticmethod
    def _structural_invalid_endpoint_method_diagnostic(
        endpoint: IREndpoint,
    ) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"Unknown HTTP method '{endpoint.method}' in axonendpoint '{endpoint.name}'. "
                f"Valid: {', '.join(sorted(TypeChecker._VALID_ENDPOINT_METHODS))}"
            ),
            line=endpoint.source_line,
            column=endpoint.source_column,
        )

    @staticmethod
    def _structural_invalid_endpoint_path_diagnostic(
        endpoint: IREndpoint,
    ) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"axonendpoint '{endpoint.name}' path must start with '/': got '{endpoint.path}'"
            ),
            line=endpoint.source_line,
            column=endpoint.source_column,
        )

    @staticmethod
    def _structural_undefined_endpoint_flow_diagnostic(
        endpoint: IREndpoint,
    ) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"axonendpoint '{endpoint.name}' references undefined flow '{endpoint.execute_flow}'"
            ),
            line=endpoint.source_line,
            column=endpoint.source_column,
        )

    @staticmethod
    def _structural_undefined_endpoint_shield_diagnostic(
        endpoint: IREndpoint,
    ) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"axonendpoint '{endpoint.name}' references undefined shield '{endpoint.shield_ref}'"
            ),
            line=endpoint.source_line,
            column=endpoint.source_column,
        )

    @staticmethod
    def _structural_not_a_shield_diagnostic(
        endpoint: IREndpoint,
        declaration_kind: str,
    ) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"'{endpoint.shield_ref}' is a {declaration_kind}, not a shield"
            ),
            line=endpoint.source_line,
            column=endpoint.source_column,
        )

    @staticmethod
    def _structural_invalid_anchor_on_violation_diagnostic(
        anchor: IRAnchor,
    ) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="type_checker",
            message=(
                f"Unknown on_violation action '{anchor.on_violation}' in anchor '{anchor.name}'. "
                f"Valid: {', '.join(sorted(VALID_VIOLATION_ACTIONS))}"
            ),
            line=anchor.source_line,
            column=anchor.source_column,
        )

    @staticmethod
    def _append_structural_anchor_validation_diagnostics(
        anchor: IRAnchor,
        validation_diagnostics: list[FrontendDiagnostic],
    ) -> None:
        if anchor.confidence_floor is not None and not 0.0 <= anchor.confidence_floor <= 1.0:
            validation_diagnostics.append(
                NativeDevelopmentFrontendImplementation._structural_invalid_anchor_confidence_floor_diagnostic(
                    anchor,
                )
            )
        if anchor.on_violation and anchor.on_violation not in VALID_VIOLATION_ACTIONS:
            validation_diagnostics.append(
                NativeDevelopmentFrontendImplementation._structural_invalid_anchor_on_violation_diagnostic(
                    anchor,
                )
            )

    @classmethod
    def _match_context_prefixed_native_success_program(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[IRProgram, int, int] | None:
        if len(tokens) != 17:
            return None
        if not cls._matches_context_prefixed_success_prefix(tokens):
            return None

        run_config = cls._match_minimal_success_flow_run_tokens(tokens[7:])
        if run_config is None or run_config["on_failure"] or run_config["output_to"] or run_config["effort"]:
            return None

        context_token = tokens[0]
        context = IRContext(
            source_line=context_token.line,
            source_column=context_token.column,
            name=tokens[1].value,
            memory_scope=tokens[5].value,
        )

        flow_token = tokens[7]
        flow_name = tokens[8].value
        run_token = tokens[13]
        flow = IRFlow(
            source_line=flow_token.line,
            source_column=flow_token.column,
            name=flow_name,
        )
        run = IRRun(
            source_line=run_token.line,
            source_column=run_token.column,
            flow_name=flow_name,
            resolved_flow=flow,
        )
        return (
            IRProgram(
                source_line=context_token.line,
                source_column=context_token.column,
                contexts=(context,),
                flows=(flow,),
                runs=(run,),
            ),
            len(tokens) + 1,
            3,
        )

    @classmethod
    def _matches_context_prefixed_success_prefix(cls, tokens: tuple[Token, ...]) -> bool:
        return (
            tokens[0].type == TokenType.CONTEXT
            and tokens[1].type == TokenType.IDENTIFIER
            and tokens[2].type == TokenType.LBRACE
            and cls._is_identifier_like_value_token(tokens[3])
            and tokens[3].value == "memory"
            and tokens[4].type == TokenType.COLON
            and cls._is_identifier_like_value_token(tokens[5])
            and tokens[5].value in VALID_MEMORY_SCOPES
            and tokens[6].type == TokenType.RBRACE
            and cls._matches_minimal_success_flow_run_prefix(tokens[7:])
        )

    @classmethod
    def _match_anchor_prefixed_native_success_program(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[IRProgram, int, int] | None:
        if len(tokens) != 17:
            return None
        if not cls._matches_anchor_prefixed_success_prefix(tokens):
            return None

        run_config = cls._match_minimal_success_flow_run_tokens(tokens[7:])
        if run_config is None or run_config["on_failure"] or run_config["output_to"] or run_config["effort"]:
            return None

        anchor_token = tokens[0]
        anchor = IRAnchor(
            source_line=anchor_token.line,
            source_column=anchor_token.column,
            name=tokens[1].value,
            require=tokens[5].value,
        )

        flow_token = tokens[7]
        flow_name = tokens[8].value
        run_token = tokens[13]
        flow = IRFlow(
            source_line=flow_token.line,
            source_column=flow_token.column,
            name=flow_name,
        )
        run = IRRun(
            source_line=run_token.line,
            source_column=run_token.column,
            flow_name=flow_name,
            resolved_flow=flow,
        )
        return (
            IRProgram(
                source_line=anchor_token.line,
                source_column=anchor_token.column,
                anchors=(anchor,),
                flows=(flow,),
                runs=(run,),
            ),
            len(tokens) + 1,
            3,
        )

    @classmethod
    def _matches_anchor_prefixed_success_prefix(cls, tokens: tuple[Token, ...]) -> bool:
        return (
            tokens[0].type == TokenType.ANCHOR
            and tokens[1].type == TokenType.IDENTIFIER
            and tokens[2].type == TokenType.LBRACE
            and cls._is_identifier_like_value_token(tokens[3])
            and tokens[3].value == "require"
            and tokens[4].type == TokenType.COLON
            and cls._is_identifier_like_value_token(tokens[5])
            and tokens[6].type == TokenType.RBRACE
            and cls._matches_minimal_success_flow_run_prefix(tokens[7:])
        )

    @classmethod
    def _match_minimal_success_flow_run_tokens(
        cls,
        tokens: tuple[Token, ...],
        *,
        available_personas: set[str] | None = None,
        available_contexts: set[str] | None = None,
        available_anchors: set[str] | None = None,
    ) -> dict[str, str | tuple[tuple[str, str], ...]] | None:
        if len(tokens) < 10:
            return None
        if not cls._matches_minimal_success_flow_run_prefix(tokens):
            return None
        if len(tokens) == 10:
            return cls._default_native_success_run_config()

        modifier_tokens = tokens[9:]
        if cls._is_as_run_modifier_tokens(modifier_tokens, available_personas=available_personas):
            return cls._native_success_run_config(persona_name=modifier_tokens[2].value)
        if cls._is_within_run_modifier_tokens(modifier_tokens, available_contexts=available_contexts):
            return cls._native_success_run_config(context_name=modifier_tokens[2].value)
        constrained_by_token_count = cls._match_constrained_by_run_modifier_tokens(
            modifier_tokens,
            available_anchors=available_anchors,
        )
        if constrained_by_token_count is not None:
            return cls._native_success_run_config(
                anchor_names=cls._extract_constrained_by_anchor_names(modifier_tokens[3:-1]),
            )
        if cls._is_output_to_run_modifier_tokens(modifier_tokens):
            return cls._native_success_run_config(output_to=modifier_tokens[3].value)
        if cls._is_effort_run_modifier_tokens(modifier_tokens):
            return cls._native_success_run_config(effort=modifier_tokens[3].value)
        if cls._is_simple_on_failure_run_modifier_tokens(modifier_tokens):
            return cls._native_success_run_config(on_failure=modifier_tokens[3].value)
        if cls._is_raise_on_failure_run_modifier_tokens(modifier_tokens):
            return cls._native_success_run_config(
                on_failure="raise",
                on_failure_params=(("target", modifier_tokens[4].value),),
            )
        if cls._matches_retry_on_failure_shape(modifier_tokens):
            return cls._native_success_run_config(
                on_failure="retry",
                on_failure_params=cls._extract_retry_on_failure_parameter_pairs(modifier_tokens[5:-1]),
            )
        return None

    @staticmethod
    def _matches_minimal_success_flow_run_prefix(tokens: tuple[Token, ...]) -> bool:
        return (
            tokens[0].type == TokenType.FLOW
            and tokens[1].type == TokenType.IDENTIFIER
            and tokens[2].type == TokenType.LPAREN
            and tokens[3].type == TokenType.RPAREN
            and tokens[4].type == TokenType.LBRACE
            and tokens[5].type == TokenType.RBRACE
            and tokens[6].type == TokenType.RUN
            and tokens[7].type == TokenType.IDENTIFIER
            and tokens[7].value == tokens[1].value
            and tokens[8].type == TokenType.LPAREN
            and tokens[9].type == TokenType.RPAREN
        )

    @staticmethod
    def _default_native_success_run_config() -> dict[str, str | tuple[tuple[str, str], ...]]:
        return {
            "persona_name": "",
            "context_name": "",
            "anchor_names": (),
            "on_failure": "",
            "on_failure_params": (),
            "output_to": "",
            "effort": "",
        }

    @classmethod
    def _native_success_run_config(
        cls,
        *,
        persona_name: str = "",
        context_name: str = "",
        anchor_names: tuple[str, ...] = (),
        on_failure: str = "",
        on_failure_params: tuple[tuple[str, str], ...] = (),
        output_to: str = "",
        effort: str = "",
    ) -> dict[str, str | tuple[tuple[str, str], ...]]:
        run_config = cls._default_native_success_run_config()
        run_config["persona_name"] = persona_name
        run_config["context_name"] = context_name
        run_config["anchor_names"] = anchor_names
        run_config["on_failure"] = on_failure
        run_config["on_failure_params"] = on_failure_params
        run_config["output_to"] = output_to
        run_config["effort"] = effort
        return run_config

    @staticmethod
    def _extract_constrained_by_anchor_names(tokens: tuple[Token, ...]) -> tuple[str, ...]:
        return tuple(tokens[index].value for index in range(0, len(tokens), 2))

    @classmethod
    def _match_native_run_subset(cls, source: str) -> tuple[str, int, int] | None:
        try:
            tokens = _NativeDevelopmentPrefixLexer(source).scan_all_tokens()
        except AxonLexerError:
            return None

        return cls._match_native_run_subset_tokens(tokens)

    @classmethod
    def _match_native_run_subset_tokens(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[str, int, int] | None:
        isolated_match = cls._match_isolated_standalone_run_tokens(tokens)
        if isolated_match is not None:
            run_name, token_count = isolated_match
            return run_name, token_count, 1

        type_prefixed_isolated_match = cls._match_type_prefixed_isolated_standalone_run_tokens(tokens)
        if type_prefixed_isolated_match is not None:
            return type_prefixed_isolated_match

        type_prefixed_shared_match = cls._match_type_prefixed_shared_block_run_tokens(tokens)
        if type_prefixed_shared_match is not None:
            return type_prefixed_shared_match

        prefixed_match = cls._match_shared_block_prefixed_run_tokens(tokens)
        if prefixed_match is not None:
            run_name, token_count, declaration_count = prefixed_match
            return run_name, token_count, declaration_count

        return None

    @classmethod
    def _match_isolated_standalone_run(cls, source: str) -> tuple[str, int] | None:
        try:
            tokens = _NativeDevelopmentPrefixLexer(source).scan_all_tokens()
        except AxonLexerError:
            return None

        return cls._match_isolated_standalone_run_tokens(tokens)

    @classmethod
    def _match_isolated_standalone_run_tokens(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[str, int] | None:

        if not cls._starts_isolated_run_signature(tokens):
            return None

        flow_name = tokens[1].value
        argument_tokens = tokens[3:]

        token_count = cls._match_isolated_run_argument_tokens(argument_tokens)
        if token_count is None:
            return None
        return flow_name, token_count

    @classmethod
    def _match_type_prefixed_isolated_standalone_run(
        cls,
        source: str,
    ) -> tuple[str, int, int] | None:
        try:
            tokens = _NativeDevelopmentPrefixLexer(source).scan_all_tokens()
        except AxonLexerError:
            return None

        return cls._match_type_prefixed_isolated_standalone_run_tokens(tokens)

    @classmethod
    def _match_type_prefixed_isolated_standalone_run_tokens(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[str, int, int] | None:

        parsed_types = cls._parse_native_type_prefix(tokens, allow_where_clause=True)
        if parsed_types is None:
            return None

        ir_types, next_index = parsed_types
        isolated_match = cls._match_isolated_standalone_run_tokens(tokens[next_index:])
        if isolated_match is None:
            return None

        flow_name, _ = isolated_match

        return flow_name, len(tokens) + 1, len(ir_types) + 1

    @classmethod
    def _match_shared_block_prefixed_run(
        cls,
        source: str,
    ) -> tuple[str, int, int] | None:
        try:
            tokens = _NativeDevelopmentPrefixLexer(source).scan_all_tokens()
        except AxonLexerError:
            return None

        return cls._match_shared_block_prefixed_run_tokens(tokens)

    @classmethod
    def _match_shared_block_prefixed_run_tokens(
        cls,
        tokens: tuple[Token, ...],
        *,
        total_token_count: int | None = None,
        declaration_offset: int = 0,
    ) -> tuple[str, int, int] | None:
        if total_token_count is None:
            total_token_count = len(tokens) + 1

        if len(tokens) < 8:
            return None
        if not cls._starts_supported_prefixed_block(tokens, start_index=0):
            return None

        declaration_count = declaration_offset
        next_index = 0
        available_personas: set[str] = set()
        available_contexts: set[str] = set()
        available_anchors: set[str] = set()

        while next_index < len(tokens) and cls._starts_supported_prefixed_block(tokens, start_index=next_index):
            cls._record_supported_prefix_block(
                tokens,
                start_index=next_index,
                available_personas=available_personas,
                available_contexts=available_contexts,
                available_anchors=available_anchors,
            )

            block_end_index = cls._find_top_level_block_end(tokens, open_brace_index=next_index + 2)
            if cls._is_invalid_block_end(block_end_index, tokens):
                return None

            declaration_count += 1
            next_index = block_end_index + 1
            matched_run = cls._match_prefixed_run_tokens(
                tokens[next_index:],
                available_personas=available_personas,
                available_contexts=available_contexts,
                available_anchors=available_anchors,
                total_token_count=total_token_count,
                declaration_count=declaration_count + 1,
            )
            if matched_run is not None:
                return matched_run

        return None

    @classmethod
    def _match_type_prefixed_shared_block_run(
        cls,
        source: str,
    ) -> tuple[str, int, int] | None:
        try:
            tokens = _NativeDevelopmentPrefixLexer(source).scan_all_tokens()
        except AxonLexerError:
            return None

        return cls._match_type_prefixed_shared_block_run_tokens(tokens)

    @classmethod
    def _match_type_prefixed_shared_block_run_tokens(
        cls,
        tokens: tuple[Token, ...],
    ) -> tuple[str, int, int] | None:

        parsed_types = cls._parse_native_type_prefix(tokens, allow_where_clause=True)
        if parsed_types is None:
            return None

        ir_types, next_index = parsed_types
        return cls._match_shared_block_prefixed_run_tokens(
            tokens[next_index:],
            total_token_count=len(tokens) + 1,
            declaration_offset=len(ir_types),
        )

    @staticmethod
    def _record_supported_prefix_block(
        tokens: tuple[Token, ...],
        *,
        start_index: int,
        available_personas: set[str],
        available_contexts: set[str],
        available_anchors: set[str],
    ) -> None:
        block_kind = tokens[start_index].value.lower()
        block_name = tokens[start_index + 1].value
        if block_kind == "persona":
            available_personas.add(block_name)
        elif block_kind == "context":
            available_contexts.add(block_name)
        elif block_kind == "anchor":
            available_anchors.add(block_name)

    @staticmethod
    def _is_invalid_block_end(
        block_end_index: int | None,
        tokens: tuple[Token, ...],
    ) -> bool:
        return block_end_index is None or block_end_index + 1 >= len(tokens)

    @classmethod
    def _match_prefixed_run_tokens(
        cls,
        run_tokens: tuple[Token, ...],
        *,
        available_personas: set[str],
        available_contexts: set[str],
        available_anchors: set[str],
        total_token_count: int,
        declaration_count: int,
    ) -> tuple[str, int, int] | None:
        if not run_tokens or not cls._starts_isolated_run_signature(run_tokens):
            return None
        token_count = cls._match_isolated_run_argument_tokens(
            run_tokens[3:],
            available_personas=available_personas,
            available_contexts=available_contexts,
            available_anchors=available_anchors,
        )
        if token_count is None:
            return None
        return run_tokens[1].value, total_token_count, declaration_count

    @classmethod
    def _starts_supported_prefixed_block(
        cls,
        tokens: tuple[Token, ...],
        *,
        start_index: int,
    ) -> bool:
        if len(tokens) - start_index < 4:
            return False
        first = tokens[start_index].value.lower()
        if first not in cls._BLOCK_FIELD_HEADER_RULES:
            return False
        return (
            tokens[start_index + 1].type == TokenType.IDENTIFIER
            and tokens[start_index + 2].type == TokenType.LBRACE
        )

    @staticmethod
    def _find_top_level_block_end(
        tokens: tuple[Token, ...],
        open_brace_index: int,
    ) -> int | None:
        depth = 0
        for index in range(open_brace_index, len(tokens)):
            token = tokens[index]
            if token.type == TokenType.LBRACE:
                depth += 1
            elif token.type == TokenType.RBRACE:
                depth -= 1
                if depth == 0:
                    return index
        return None

    @staticmethod
    def _starts_isolated_run_signature(tokens: tuple[Token, ...]) -> bool:
        if len(tokens) < 4:
            return False
        if tokens[0].type != TokenType.RUN:
            return False
        if tokens[1].type != TokenType.IDENTIFIER:
            return False
        return tokens[2].type == TokenType.LPAREN

    @classmethod
    def _match_isolated_run_argument_tokens(
        cls,
        tokens: tuple[Token, ...],
        *,
        available_personas: set[str] | None = None,
        available_contexts: set[str] | None = None,
        available_anchors: set[str] | None = None,
    ) -> int | None:
        if cls._is_empty_run_argument_tokens(tokens):
            return 5
        if cls._is_as_run_modifier_tokens(tokens, available_personas=available_personas):
            return 7
        if cls._is_within_run_modifier_tokens(tokens, available_contexts=available_contexts):
            return 7
        constrained_by_token_count = cls._match_constrained_by_run_modifier_tokens(
            tokens,
            available_anchors=available_anchors,
        )
        if constrained_by_token_count is not None:
            return constrained_by_token_count
        if cls._is_output_to_run_modifier_tokens(tokens):
            return 8
        if cls._is_effort_run_modifier_tokens(tokens):
            return 8
        if cls._is_simple_on_failure_run_modifier_tokens(tokens):
            return 8
        if cls._is_raise_on_failure_run_modifier_tokens(tokens):
            return 9
        retry_token_count = cls._match_retry_on_failure_run_modifier_tokens(tokens)
        if retry_token_count is not None:
            return retry_token_count
        if cls._is_scalar_run_argument_tokens(tokens):
            return 6
        if cls._is_dotted_run_argument_tokens(tokens):
            return 8
        if cls._is_key_value_run_argument_tokens(tokens):
            return 8
        return None

    @staticmethod
    def _is_as_run_modifier_tokens(
        tokens: tuple[Token, ...],
        *,
        available_personas: set[str] | None,
    ) -> bool:
        if len(tokens) != 3 or not available_personas:
            return False
        closing, modifier, persona = tokens
        return (
            closing.type == TokenType.RPAREN
            and modifier.type == TokenType.AS
            and persona.type == TokenType.IDENTIFIER
            and persona.value in available_personas
        )

    @staticmethod
    def _is_within_run_modifier_tokens(
        tokens: tuple[Token, ...],
        *,
        available_contexts: set[str] | None,
    ) -> bool:
        if len(tokens) != 3 or not available_contexts:
            return False
        closing, modifier, context = tokens
        return (
            closing.type == TokenType.RPAREN
            and modifier.type == TokenType.WITHIN
            and context.type == TokenType.IDENTIFIER
            and context.value in available_contexts
        )

    @classmethod
    def _match_constrained_by_run_modifier_tokens(
        cls,
        tokens: tuple[Token, ...],
        *,
        available_anchors: set[str] | None,
    ) -> int | None:
        if not available_anchors or len(tokens) < 5:
            return None
        closing, modifier, open_bracket = tokens[:3]
        if (
            closing.type != TokenType.RPAREN
            or modifier.type != TokenType.CONSTRAINED_BY
            or open_bracket.type != TokenType.LBRACKET
            or tokens[-1].type != TokenType.RBRACKET
        ):
            return None
        if not cls._matches_constrained_by_anchor_list(tokens[3:-1], available_anchors=available_anchors):
            return None
        return len(tokens) + 4

    @classmethod
    def _matches_constrained_by_anchor_list(
        cls,
        tokens: tuple[Token, ...],
        *,
        available_anchors: set[str],
    ) -> bool:
        if not tokens or len(tokens) % 2 == 0:
            return False
        index = 0
        while index < len(tokens):
            anchor = tokens[index]
            if anchor.type != TokenType.IDENTIFIER or anchor.value not in available_anchors:
                return False
            index += 1
            if index == len(tokens):
                return True
            if tokens[index].type != TokenType.COMMA:
                return False
            index += 1
        return True

    @staticmethod
    def _is_empty_run_argument_tokens(tokens: tuple[Token, ...]) -> bool:
        return len(tokens) == 1 and tokens[0].type == TokenType.RPAREN

    @staticmethod
    def _is_output_to_run_modifier_tokens(tokens: tuple[Token, ...]) -> bool:
        if len(tokens) != 4:
            return False
        closing, modifier, colon, value = tokens
        return (
            closing.type == TokenType.RPAREN
            and modifier.type == TokenType.OUTPUT_TO
            and colon.type == TokenType.COLON
            and value.type == TokenType.STRING
        )

    @classmethod
    def _is_effort_run_modifier_tokens(cls, tokens: tuple[Token, ...]) -> bool:
        if len(tokens) != 4:
            return False
        closing, modifier, colon, value = tokens
        return (
            closing.type == TokenType.RPAREN
            and modifier.type == TokenType.EFFORT
            and colon.type == TokenType.COLON
            and cls._is_identifier_like_value_token(value)
        )

    @classmethod
    def _is_simple_on_failure_run_modifier_tokens(cls, tokens: tuple[Token, ...]) -> bool:
        if len(tokens) != 4:
            return False
        closing, modifier, colon, value = tokens
        return (
            closing.type == TokenType.RPAREN
            and modifier.type == TokenType.ON_FAILURE
            and colon.type == TokenType.COLON
            and cls._is_identifier_like_value_token(value)
        )

    @classmethod
    def _is_raise_on_failure_run_modifier_tokens(cls, tokens: tuple[Token, ...]) -> bool:
        if len(tokens) != 5:
            return False
        closing, modifier, colon, strategy, target = tokens
        return (
            closing.type == TokenType.RPAREN
            and modifier.type == TokenType.ON_FAILURE
            and colon.type == TokenType.COLON
            and strategy.type == TokenType.IDENTIFIER
            and strategy.value == "raise"
            and target.type == TokenType.IDENTIFIER
        )

    @classmethod
    def _match_retry_on_failure_run_modifier_tokens(
        cls,
        tokens: tuple[Token, ...],
    ) -> int | None:
        if cls._matches_retry_on_failure_shape(tokens):
            return len(tokens) + 4
        return None

    @classmethod
    def _matches_retry_on_failure_shape(
        cls,
        tokens: tuple[Token, ...],
    ) -> bool:
        if len(tokens) < 9 or (len(tokens) - 9) % 4 != 0:
            return False
        closing, modifier, colon, strategy, open_paren = tokens[:5]
        close_paren = tokens[-1]
        return (
            closing.type == TokenType.RPAREN
            and modifier.type == TokenType.ON_FAILURE
            and colon.type == TokenType.COLON
            and strategy.type == TokenType.IDENTIFIER
            and strategy.value == "retry"
            and open_paren.type == TokenType.LPAREN
            and cls._matches_retry_on_failure_parameter_pairs(tokens[5:-1])
            and close_paren.type == TokenType.RPAREN
        )

    @classmethod
    def _matches_retry_on_failure_parameter_pairs(cls, tokens: tuple[Token, ...]) -> bool:
        if len(tokens) < 3 or (len(tokens) - 3) % 4 != 0:
            return False
        pair_start = 0
        while pair_start < len(tokens):
            pair_end = pair_start + 3
            if not cls._matches_retry_on_failure_parameter_pair(tokens[pair_start:pair_end]):
                return False
            if pair_end == len(tokens):
                return True
            if tokens[pair_end].type != TokenType.COMMA:
                return False
            pair_start = pair_end + 1
        return True

    @classmethod
    def _matches_retry_on_failure_parameter_pair(cls, tokens: tuple[Token, ...]) -> bool:
        if len(tokens) != 3:
            return False
        key, inner_colon, value = tokens
        return (
            cls._is_identifier_like_value_token(key)
            and inner_colon.type == TokenType.COLON
            and cls._is_identifier_like_value_token(value)
        )

    @staticmethod
    def _extract_retry_on_failure_parameter_pairs(
        tokens: tuple[Token, ...],
    ) -> tuple[tuple[str, str], ...]:
        parameter_pairs: list[tuple[str, str]] = []
        pair_start = 0
        while pair_start < len(tokens):
            key = tokens[pair_start]
            value = tokens[pair_start + 2]
            parameter_pairs.append((key.value, value.value))
            pair_start += 3
            if pair_start < len(tokens):
                pair_start += 1
        return tuple(parameter_pairs)

    @staticmethod
    def _is_scalar_run_argument_tokens(tokens: tuple[Token, ...]) -> bool:
        if len(tokens) != 2:
            return False
        value_token, closing = tokens
        if closing.type != TokenType.RPAREN:
            return False
        return value_token.type in (TokenType.STRING, TokenType.INTEGER, TokenType.FLOAT)

    @classmethod
    def _is_dotted_run_argument_tokens(cls, tokens: tuple[Token, ...]) -> bool:
        if len(tokens) != 4:
            return False
        first, second, third, closing = tokens
        if closing.type != TokenType.RPAREN:
            return False
        return (
            first.type == TokenType.IDENTIFIER
            and second.type == TokenType.DOT
            and cls._is_identifier_like_value_token(third)
        )

    @classmethod
    def _is_key_value_run_argument_tokens(cls, tokens: tuple[Token, ...]) -> bool:
        if len(tokens) != 4:
            return False
        first, second, third, closing = tokens
        if closing.type != TokenType.RPAREN:
            return False
        return (
            cls._is_identifier_like_value_token(first)
            and second.type == TokenType.COLON
            and third.type in (TokenType.STRING, TokenType.INTEGER, TokenType.FLOAT)
        )

    @classmethod
    def _preparse_top_level(cls, source: str) -> FrontendDiagnostic | None:
        tokens, diagnostic = cls._scan_prefix_tokens(source, limit=6)
        if diagnostic is not None:
            return diagnostic
        if not tokens:
            return None

        token = tokens[0]

        if token.value.lower() in cls._ALLOWED_TOP_LEVEL_STARTS:
            return cls._validate_signature_window(tokens)

        return FrontendDiagnostic(
            stage="parser",
            message=(
                f"Unexpected token at top level "
                f"(expected {cls._EXPECTED_DECLARATION}, found {token.value})"
            ),
            line=token.line,
            column=token.column,
        )

    @classmethod
    def _validate_signature_window(cls, tokens: tuple[Token, ...]) -> FrontendDiagnostic | None:
        first = tokens[0]
        expected_third = cls._SIGNATURE_WINDOW_RULES.get(first.value.lower())
        if expected_third is None:
            return None
        if len(tokens) >= 2 and tokens[1].type != TokenType.IDENTIFIER:
            return cls._unexpected_token_diagnostic("IDENTIFIER", tokens[1])
        if len(tokens) >= 3 and len(tokens) >= 2 and tokens[1].type == TokenType.IDENTIFIER:
            if tokens[2].type != expected_third:
                return cls._unexpected_token_diagnostic(expected_third.name, tokens[2])
        if first.value.lower() in cls._BLOCK_FIELD_HEADER_RULES:
            return cls._validate_block_field_header(tokens)
        if first.value.lower() == "flow":
            return cls._validate_flow_header(tokens)
        return None

    @staticmethod
    def _validate_block_field_header(tokens: tuple[Token, ...]) -> FrontendDiagnostic | None:
        if len(tokens) < 4:
            return None
        if tokens[2].type != TokenType.LBRACE:
            return None
        if tokens[3].type == TokenType.RBRACE:
            return None
        if len(tokens) < 5:
            return None
        if tokens[4].type == TokenType.COLON:
            return NativeDevelopmentFrontendImplementation._validate_first_block_field_value(tokens)
        return NativeDevelopmentFrontendImplementation._unexpected_token_diagnostic(
            "COLON",
            tokens[4],
        )

    @classmethod
    def _validate_first_block_field_value(
        cls,
        tokens: tuple[Token, ...],
    ) -> FrontendDiagnostic | None:
        diagnostic = cls._validate_identifier_like_block_value(tokens)
        if diagnostic is not None:
            return diagnostic
        return cls._validate_bool_block_value(tokens)

    @classmethod
    def _validate_identifier_like_block_value(
        cls,
        tokens: tuple[Token, ...],
    ) -> FrontendDiagnostic | None:
        if len(tokens) < 6:
            return None
        field_name = tokens[3].value
        if field_name not in cls._IDENTIFIER_LIKE_FIRST_FIELDS:
            return None
        value_token = tokens[5]
        if cls._is_identifier_like_value_token(value_token):
            return None
        return FrontendDiagnostic(
            stage="parser",
            message=(
                f"Expected identifier or keyword value "
                f"(found {value_token.type.name}({value_token.value!r}))"
            ),
            line=value_token.line,
            column=value_token.column,
        )

    @classmethod
    def _validate_bool_block_value(
        cls,
        tokens: tuple[Token, ...],
    ) -> FrontendDiagnostic | None:
        if len(tokens) < 6:
            return None
        field_name = tokens[3].value
        if field_name not in cls._BOOL_FIRST_FIELDS:
            return None
        value_token = tokens[5]
        if value_token.type == TokenType.BOOL:
            return None
        return cls._unexpected_token_diagnostic("BOOL", value_token)

    @staticmethod
    def _is_identifier_like_value_token(token: Token) -> bool:
        if token.type == TokenType.IDENTIFIER or token.type in (
            TokenType.BOOL,
            TokenType.STRING,
            TokenType.INTEGER,
            TokenType.FLOAT,
        ):
            return True
        return token.value.isalpha() or "_" in token.value

    @staticmethod
    def _validate_flow_header(tokens: tuple[Token, ...]) -> FrontendDiagnostic | None:
        if len(tokens) < 4:
            return None
        if tokens[2].type != TokenType.LPAREN:
            return None
        if tokens[3].type in (TokenType.RPAREN, TokenType.IDENTIFIER):
            return None
        return NativeDevelopmentFrontendImplementation._unexpected_token_diagnostic(
            "IDENTIFIER",
            tokens[3],
        )

    @staticmethod
    def _unexpected_token_diagnostic(expected: str, token: Token) -> FrontendDiagnostic:
        return FrontendDiagnostic(
            stage="parser",
            message=(
                f"Unexpected token (expected {expected}, "
                f"found {token.type.name}({token.value!r}))"
            ),
            line=token.line,
            column=token.column,
        )

    @staticmethod
    def _scan_prefix_tokens(
        source: str,
        limit: int,
    ) -> tuple[tuple[Token, ...], FrontendDiagnostic | None]:
        try:
            return _NativeDevelopmentPrefixLexer(source).scan_token_window(limit), None
        except AxonLexerError as exc:
            return (
                (),
                FrontendDiagnostic(
                    stage="lexer",
                    message=exc.message,
                    line=exc.line,
                    column=exc.column,
                ),
            )


class FrontendFacade:
    """Stable frontend facade delegating to a swappable implementation."""

    def __init__(self, implementation: FrontendImplementation | None = None) -> None:
        self._default_implementation = implementation or PythonFrontendImplementation()
        self._implementation: FrontendImplementation = self._default_implementation

    def check_source(self, source: str, filename: str) -> FrontendCheckResult:
        return self._implementation.check_source(source, filename)

    def compile_source(self, source: str, filename: str) -> FrontendCompileResult:
        return self._implementation.compile_source(source, filename)

    def get_implementation(self) -> FrontendImplementation:
        return self._implementation

    def set_implementation(self, implementation: FrontendImplementation) -> None:
        self._implementation = implementation

    def reset_implementation(self) -> None:
        self._implementation = self._default_implementation


def serialize_ir_program(ir_program: object) -> dict[str, Any]:
    """Serialize an IRProgram to a JSON-compatible dict."""
    try:
        return asdict(ir_program)  # type: ignore[arg-type]
    except (TypeError, AttributeError):
        result: dict[str, Any] = {}
        for attr in dir(ir_program):
            if attr.startswith("_"):
                continue
            value = getattr(ir_program, attr)
            if callable(value):
                continue
            try:
                json.dumps(value, default=str)
                result[attr] = value
            except (TypeError, ValueError):
                result[attr] = str(value)
        return result


frontend = FrontendFacade()


def get_frontend_implementation() -> FrontendImplementation:
    """Return the currently active frontend implementation."""
    return frontend.get_implementation()


def set_frontend_implementation(implementation: FrontendImplementation) -> None:
    """Replace the active frontend implementation behind the facade."""
    frontend.set_implementation(implementation)


def reset_frontend_implementation() -> None:
    """Restore the default Python-backed frontend implementation."""
    frontend.reset_implementation()
