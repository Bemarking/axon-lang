"""
axon check — Validate an .axon source file.

Runs the full front-end pipeline:
  1. Lexer    → tokenize
  2. Parser   → build AST
  3. TypeChecker → semantic validation

Exit codes:
  0 — clean, no errors
  1 — errors detected
  2 — file not found or I/O error
"""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

from axon.cli.display import format_cli_path, safe_text

# ── ANSI colors ──────────────────────────────────────────────────

_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_BOLD = "\033[1m"
_RESET = "\033[0m"
_DIM = "\033[2m"


def _c(text: str, code: str, *, no_color: bool = False) -> str:
    """Wrap *text* in an ANSI escape sequence (unless --no-color)."""
    text = safe_text(text, sys.stdout)
    if no_color or not sys.stdout.isatty():
        return text
    return f"{code}{text}{_RESET}"


def cmd_check(args: Namespace) -> int:
    """Execute the ``axon check`` subcommand."""
    path = Path(args.file)
    no_color = getattr(args, "no_color", False)

    # ── Read source ───────────────────────────────────────────
    if not path.exists():
        print(
            _c(
                f"✗ File not found: {format_cli_path(path)}",
                _RED,
                no_color=no_color,
            ),
            file=sys.stderr,
        )
        return 2

    source = path.read_text(encoding="utf-8")

    # ── Phase 1: Lex ──────────────────────────────────────────
    from axon.compiler.errors import AxonError, AxonLexerError
    from axon.compiler.lexer import Lexer

    try:
        tokens = Lexer(source, filename=str(path)).tokenize()
    except AxonLexerError as exc:
        _print_error(exc, path, no_color=no_color)
        return 1

    token_count = len(tokens)

    # ── Phase 2: Parse ────────────────────────────────────────
    from axon.compiler.parser import Parser

    try:
        ast = Parser(tokens).parse()
    except AxonError as exc:
        _print_error(exc, path, no_color=no_color)
        return 1

    decl_count = len(ast.declarations) if hasattr(ast, "declarations") else 0

    # ── Phase 3: Type-check ───────────────────────────────────
    from axon.compiler.type_checker import TypeChecker

    checker = TypeChecker(ast)
    errors = checker.check()

    if errors:
        print(
            _c(f"✗ {path.name}", _RED + _BOLD, no_color=no_color)
            + f"  — {len(errors)} type error(s)"
        )
        for err in errors:
            line_info = f"  line {err.line}" if err.line else ""
            severity = _c("error", _RED, no_color=no_color)
            print(safe_text(f"  {severity}{line_info}: {err.message}", sys.stdout))
        return 1

    # ── Success ───────────────────────────────────────────────
    print(
        _c("✓", _GREEN + _BOLD, no_color=no_color)
        + f" {_c(path.name, _BOLD, no_color=no_color)}"
        + _c(
            f"  {token_count} tokens · {decl_count} declarations · 0 errors",
            _DIM,
            no_color=no_color,
        )
    )
    return 0


def _print_error(exc: Exception, path: Path, *, no_color: bool) -> None:
    """Format a compile-time error for terminal display."""
    from axon.compiler.errors import AxonError

    if isinstance(exc, AxonError):
        loc = ""
        if exc.line:
            loc = f":{exc.line}"
            if exc.column:
                loc += f":{exc.column}"
        print(
            _c(f"✗ {path.name}{loc}", _RED + _BOLD, no_color=no_color)
            + safe_text(f"  {exc.message}", sys.stderr),
            file=sys.stderr,
        )
    else:
        print(
            _c(f"✗ {path.name}", _RED + _BOLD, no_color=no_color)
            + safe_text(f"  {exc}", sys.stderr),
            file=sys.stderr,
        )
