"""
axon check — Validate an .axon source file.

Runs the full front-end pipeline:
  1. Lexer    → tokenize
  2. Parser   → build AST
  3. TypeChecker → semantic validation (errors + warnings)

Exit codes:
  0 — clean, no errors (warnings allowed unless --strict)
  1 — errors detected (or warnings under --strict)
  2 — file not found or I/O error

Flags:
  --strict   — Promote warnings (D4 string-topic deprecation, future
               soft diagnostics) to errors.  Recommended for CI in
               adopters preparing for v2.0.
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
    strict = getattr(args, "strict", False)

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

    # Lexer/parser errors are fatal and arrive as a single diagnostic.
    errors = [d for d in result.diagnostics if d.severity == "error"]
    warnings = [d for d in result.diagnostics if d.severity == "warning"]

    if errors:
        first = errors[0]
        if first.stage in {"lexer", "parser"}:
            _print_frontend_diagnostic(first, path, no_color=no_color)
            return 1

        print(
            _c(f"✗ {path.name}", _RED + _BOLD, no_color=no_color)
            + f"  — {len(errors)} error(s)"
            + (f", {len(warnings)} warning(s)" if warnings else "")
        )
        for diagnostic in errors:
            _print_diagnostic(diagnostic, no_color=no_color)
        for diagnostic in warnings:
            _print_diagnostic(diagnostic, no_color=no_color)
        return 1

    # Errors clean — handle warnings (strict promotes to errors).
    if warnings:
        if strict:
            print(
                _c(f"✗ {path.name}", _RED + _BOLD, no_color=no_color)
                + f"  — 0 errors, {len(warnings)} warning(s) "
                + _c("(--strict)", _RED, no_color=no_color)
            )
            for diagnostic in warnings:
                _print_diagnostic(
                    diagnostic, no_color=no_color, force_severity="error",
                )
            return 1
        # Non-strict: warnings shown but check still passes.
        print(
            _c("⚠", _YELLOW + _BOLD, no_color=no_color)
            + f" {_c(path.name, _BOLD, no_color=no_color)}"
            + _c(
                f"  {result.token_count} tokens · "
                f"{result.declaration_count} declarations · 0 errors · "
                f"{len(warnings)} warning(s)",
                _DIM,
                no_color=no_color,
            )
        )
        for diagnostic in warnings:
            _print_diagnostic(diagnostic, no_color=no_color)
        return 0

    # ── Fully clean ───────────────────────────────────────────
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


def _print_diagnostic(
    diagnostic: object,
    *,
    no_color: bool,
    force_severity: str | None = None,
) -> None:
    """Render a single diagnostic with severity-appropriate color."""
    severity = force_severity or getattr(diagnostic, "severity", "error")
    color = _RED if severity == "error" else _YELLOW
    label = _c(severity, color, no_color=no_color)
    line = getattr(diagnostic, "line", 0)
    line_info = f"  line {line}" if line else ""
    message = getattr(diagnostic, "message", str(diagnostic))
    print(safe_text(f"  {label}{line_info}: {message}", sys.stdout))


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
