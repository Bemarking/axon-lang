"""
axon fmt — Round-trip formatter for .axon source files (Fase 14.d MVP).

Consumes the lossless lexing channel from Fase 14.a (extended in 14.c
with inner doc comments) to format AXON source while preserving every
comment verbatim. The MVP normalises only trailing whitespace and the
final newline; layout canonicalisation is deferred to a future
sub-phase.

Modes:
  default   — write the formatted output to stdout
  --check   — exit non-zero if the file is not already formatted; do
              not modify the file. Suitable for CI gates.
  --write   — write the formatted output back to the file in place.

Exit codes:
  0 — success (default mode, or --check on already-formatted input,
      or --write on success)
  1 — --check failed: file would be reformatted
  2 — file not found, I/O error, or lexer error
"""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

from axon.cli.display import format_cli_path, safe_text
from axon.compiler.errors import AxonLexerError
from axon.compiler.formatter import format_source


_RED = "\033[31m"
_GREEN = "\033[32m"
_BOLD = "\033[1m"
_RESET = "\033[0m"
_DIM = "\033[2m"


def _c(text: str, code: str, *, no_color: bool = False) -> str:
    """Wrap *text* in ANSI color codes (unless --no-color or non-TTY)."""
    text = safe_text(text, sys.stdout)
    if no_color or not sys.stdout.isatty():
        return text
    return f"{code}{text}{_RESET}"


def cmd_fmt(args: Namespace) -> int:
    """Execute the ``axon fmt`` subcommand."""
    path = Path(args.file)
    no_color = getattr(args, "no_color", False)
    check_mode = getattr(args, "check", False)
    write_mode = getattr(args, "write", False)

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

    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover — defensive
        print(
            _c(f"✗ Could not read {format_cli_path(path)}: {exc}", _RED, no_color=no_color),
            file=sys.stderr,
        )
        return 2

    try:
        formatted = format_source(source)
    except AxonLexerError as exc:
        print(
            _c(f"✗ Lexer error: {exc.message}", _RED, no_color=no_color),
            file=sys.stderr,
        )
        return 2

    if check_mode:
        if formatted == source:
            print(
                _c("✓", _GREEN + _BOLD, no_color=no_color)
                + f" {_c(path.name, _BOLD, no_color=no_color)}"
                + _c("  already formatted", _DIM, no_color=no_color)
            )
            return 0
        print(
            _c("✗", _RED + _BOLD, no_color=no_color)
            + f" {_c(path.name, _BOLD, no_color=no_color)}"
            + _c("  would be reformatted", _DIM, no_color=no_color),
            file=sys.stderr,
        )
        return 1

    if write_mode:
        if formatted != source:
            path.write_text(formatted, encoding="utf-8")
            print(
                _c("✓", _GREEN + _BOLD, no_color=no_color)
                + f" {_c(path.name, _BOLD, no_color=no_color)}"
                + _c("  reformatted", _DIM, no_color=no_color)
            )
        else:
            print(
                _c("✓", _GREEN + _BOLD, no_color=no_color)
                + f" {_c(path.name, _BOLD, no_color=no_color)}"
                + _c("  already formatted", _DIM, no_color=no_color)
            )
        return 0

    # Default mode: write to stdout.
    sys.stdout.write(formatted)
    return 0
