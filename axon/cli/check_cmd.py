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
from axon.compiler import frontend

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

    result = frontend.check_source(source, str(path))

    if result.diagnostics:
        first = result.diagnostics[0]
        if first.stage in {"lexer", "parser"}:
            _print_frontend_diagnostic(first, path, no_color=no_color)
            return 1

        print(
            _c(f"✗ {path.name}", _RED + _BOLD, no_color=no_color)
            + f"  — {len(result.diagnostics)} type error(s)"
        )
        for diagnostic in result.diagnostics:
            line_info = f"  line {diagnostic.line}" if diagnostic.line else ""
            severity = _c("error", _RED, no_color=no_color)
            print(
                safe_text(
                    f"  {severity}{line_info}: {diagnostic.message}",
                    sys.stdout,
                )
            )
        return 1

    # ── Success ───────────────────────────────────────────────
    print(
        _c("✓", _GREEN + _BOLD, no_color=no_color)
        + f" {_c(path.name, _BOLD, no_color=no_color)}"
        + _c(
            f"  {result.token_count} tokens · {result.declaration_count} declarations · 0 errors",
            _DIM,
            no_color=no_color,
        )
    )
    return 0


def _print_frontend_diagnostic(diagnostic: object, path: Path, *, no_color: bool) -> None:
    """Format a frontend diagnostic for terminal display."""
    loc = ""
    line = getattr(diagnostic, "line", 0)
    column = getattr(diagnostic, "column", 0)
    if line:
        loc = f":{line}"
        if column:
            loc += f":{column}"

    print(
        _c(f"✗ {path.name}{loc}", _RED + _BOLD, no_color=no_color)
        + safe_text(f"  {getattr(diagnostic, 'message', diagnostic)}", sys.stderr),
        file=sys.stderr,
    )
