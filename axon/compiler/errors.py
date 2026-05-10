"""
AXON Compiler — Error Hierarchy
================================
All compile-time errors for the AXON language.

Hierarchy:
  AxonError
  ├── AxonLexerError   — bad character, unterminated string
  ├── AxonParseError   — unexpected token, missing delimiter
  └── AxonTypeError    — semantic type violation

§Fase 28.d — Source-context diagnostic block
--------------------------------------------
Errors carry an optional ``SourceSnippet`` (D4: 2 context lines
before + 2 after). The block renders rustc-style with line numbers
and a caret pointing at the error column. The Rust frontend
mirrors this exactly so adopters see the same shape across stacks.
"""

from __future__ import annotations
from dataclasses import dataclass, field


# §Fase 28.d — Source-context constants. D4 ratified 2026-05-10:
# 2 lines before + 2 lines after the error line.
_SOURCE_CONTEXT_LINES_BEFORE: int = 2
_SOURCE_CONTEXT_LINES_AFTER: int = 2


@dataclass
class SourceSnippet:
    """Rustc-style source-context block for a compile error.

    Holds a reference to the source text plus the line/column the
    error points at. Rendering is lazy — call ``render()`` to format
    the block (line numbers + caret + 2 lines before + 2 after).

    The renderer is pure and deterministic: no ANSI colors, no
    terminal-width detection, no environment lookup. The Rust
    frontend produces the exact same byte shape on the same input
    so the cross-stack drift gate (28.i) can compare strings.
    """

    source: str
    line: int
    column: int
    filename: str = "<source>"
    context_before: int = _SOURCE_CONTEXT_LINES_BEFORE
    context_after: int = _SOURCE_CONTEXT_LINES_AFTER

    def render(self) -> str:
        """Format the snippet as a multi-line rustc-style block.

        Output shape (when line=3, col=5, context=2/2)::

              --> filename:3:5
               |
             1 | first line
             2 | second line
             3 | third line
               |     ^
             4 | fourth line
             5 | fifth line

        Empty source → empty string. Out-of-range line → empty
        string. Caret column is clamped to the line length so a
        column past EOL still renders as the last char + 1.
        """
        if not self.source or self.line < 1:
            return ""
        lines = self.source.splitlines()
        if not lines or self.line > len(lines):
            return ""

        start = max(1, self.line - self.context_before)
        end = min(len(lines), self.line + self.context_after)

        # Gutter width = max line-number digit count in the rendered
        # range. Keeps line numbers right-aligned like rustc.
        gutter = len(str(end))
        empty_gutter = " " * gutter

        out: list[str] = []
        out.append(f"{empty_gutter} --> {self.filename}:{self.line}:{self.column}")
        out.append(f"{empty_gutter} |")
        for n in range(start, end + 1):
            line_text = lines[n - 1]
            out.append(f"{n:>{gutter}} | {line_text}")
            if n == self.line:
                # Caret column is 1-based; clamp to [1, len+1].
                col = max(1, min(self.column, len(line_text) + 1))
                out.append(f"{empty_gutter} | {' ' * (col - 1)}^")
        return "\n".join(out)


class AxonError(Exception):
    """Base error for all AXON compile-time errors."""

    def __init__(
        self,
        message: str,
        line: int = 0,
        column: int = 0,
        source_snippet: SourceSnippet | None = None,
    ):
        self.line = line
        self.column = column
        self.message = message
        # §Fase 28.d — Optional source-context block. None preserves
        # the legacy single-line error format (callers that haven't
        # migrated still work).
        self.source_snippet: SourceSnippet | None = source_snippet
        super().__init__(self._format())

    def _format(self) -> str:
        location = f"[line {self.line}, col {self.column}]" if self.line else ""
        head = f"{self.__class__.__name__} {location}: {self.message}"
        if self.source_snippet is not None:
            block = self.source_snippet.render()
            if block:
                return f"{head}\n{block}"
        return head

    def attach_source(
        self,
        source: str,
        filename: str = "<source>",
    ) -> "AxonError":
        """Attach a ``SourceSnippet`` from raw source text + filename.

        Returns ``self`` so the call can be chained at the raise
        site::

            raise AxonParseError(...).attach_source(src, fname)

        Idempotent: calling twice replaces the existing snippet.
        Re-renders the formatted message so ``str(err)`` reflects
        the new context. No-op when ``line == 0``.
        """
        if self.line < 1:
            return self
        self.source_snippet = SourceSnippet(
            source=source,
            line=self.line,
            column=self.column,
            filename=filename,
        )
        # Re-build args[0] so str(self) shows the new snippet.
        self.args = (self._format(),)
        return self


class AxonLexerError(AxonError):
    """Raised when the lexer encounters invalid input."""
    pass


class AxonParseError(AxonError):
    """Raised when the parser encounters unexpected tokens."""

    def __init__(
        self,
        message: str,
        line: int = 0,
        column: int = 0,
        expected: str | None = None,
        found: str | None = None,
        source_snippet: SourceSnippet | None = None,
    ):
        self.expected = expected
        self.found = found
        if expected and found:
            message = f"{message} (expected {expected}, found {found})"
        super().__init__(message, line, column, source_snippet=source_snippet)


@dataclass
class TypeErrorInfo:
    """Structured info for a single type-checking violation."""
    message: str
    line: int = 0
    column: int = 0
    severity: str = "error"  # "error" | "warning"
    code: str = ""  # e.g. "AXON_T001"


class AxonTypeError(AxonError):
    """Raised when semantic type validation fails."""

    def __init__(
        self,
        message: str,
        line: int = 0,
        column: int = 0,
        errors: list[TypeErrorInfo] | None = None,
        source_snippet: SourceSnippet | None = None,
    ):
        self.errors = errors or []
        super().__init__(message, line, column, source_snippet=source_snippet)
