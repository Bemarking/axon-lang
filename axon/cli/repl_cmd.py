"""
axon repl — Interactive Read-Eval-Print Loop for AXON.

Provides an interactive session where users can type AXON declarations
and see them lexed, parsed, and compiled to IR in real-time.

Features:
  - Multi-line input (detects open braces and waits for closing)
  - Real-time Lex → Parse → TypeCheck → IR pipeline
  - Dot-commands: .help, .clear, .quit, .anchors, .personas, .flows, .tools
  - Error recovery without session crash
  - Input history via readline (where available)

Exit codes:
  0 — normal exit
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace

import axon

# ── ANSI colors ──────────────────────────────────────────────────

_CYAN = "\033[36m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"

_USE_COLOR = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    """Wrap text in ANSI if stdout is a TTY."""
    if not _USE_COLOR:
        return text
    return f"{code}{text}{_RESET}"


# ── Banner ───────────────────────────────────────────────────────

_BANNER = f"""\
{_c("╔══════════════════════════════════════════╗", _CYAN) if _USE_COLOR else "+" + "=" * 42 + "+"}
{_c("║", _CYAN) if _USE_COLOR else "|"}  {_c("AXON REPL", _BOLD + _GREEN) if _USE_COLOR else "AXON REPL"}  v{axon.__version__}                   {_c("║", _CYAN) if _USE_COLOR else "|"}
{_c("║", _CYAN) if _USE_COLOR else "|"}  A cognitive language for AI              {_c("║", _CYAN) if _USE_COLOR else "|"}
{_c("╚══════════════════════════════════════════╝", _CYAN) if _USE_COLOR else "+" + "=" * 42 + "+"}
  Type {_c('.help', _YELLOW) if _USE_COLOR else '.help'} for commands, {_c('.quit', _YELLOW) if _USE_COLOR else '.quit'} to exit.
"""


# ── Dot-commands ─────────────────────────────────────────────────

def _handle_dot_command(cmd: str) -> bool:
    """Handle a dot-command. Returns True if session should continue."""
    cmd = cmd.strip().lower()

    if cmd in (".quit", ".exit", ".q"):
        print(_c("Goodbye. 🧠", _DIM))
        return False

    if cmd == ".help":
        print(
            f"\n  {_c('.help', _YELLOW)}      Show this message\n"
            f"  {_c('.clear', _YELLOW)}     Clear screen\n"
            f"  {_c('.quit', _YELLOW)}      Exit REPL\n"
            f"  {_c('.anchors', _YELLOW)}   List all stdlib anchors\n"
            f"  {_c('.personas', _YELLOW)}  List all stdlib personas\n"
            f"  {_c('.flows', _YELLOW)}     List all stdlib flows\n"
            f"  {_c('.tools', _YELLOW)}     List all stdlib tools\n"
        )
        return True

    if cmd == ".clear":
        print("\033[2J\033[H", end="")
        return True

    if cmd in (".anchors", ".personas", ".flows", ".tools"):
        _list_stdlib(cmd[1:])  # strip the dot
        return True

    print(_c(f"  Unknown command: {cmd}. Type .help", _RED))
    return True


def _list_stdlib(namespace: str) -> None:
    """List all entries in a stdlib namespace."""
    from axon.stdlib.base import StdlibRegistry

    registry = StdlibRegistry()
    try:
        entries = registry.list_all(namespace)
    except ValueError:
        print(_c(f"  Invalid namespace: {namespace}", _RED))
        return

    if not entries:
        print(_c(f"  No {namespace} registered.", _DIM))
        return

    print(f"\n  {_c(f'{namespace.upper()} ({len(entries)})', _BOLD + _CYAN)}\n")
    for entry in entries:
        desc = getattr(entry, "description", "")
        sev = getattr(entry, "severity", "")
        suffix = f"  [{sev}]" if sev else ""
        print(f"    {_c(entry.name, _GREEN)}{_c(suffix, _DIM)}")
        if desc:
            print(f"      {_c(desc, _DIM)}")
    print()


# ── Eval pipeline ────────────────────────────────────────────────

def _eval_source(source: str) -> None:
    """Lex → Parse → TypeCheck → IR and display the result."""
    from axon.compiler.errors import AxonError
    from axon.compiler.ir_generator import IRGenerator
    from axon.compiler.lexer import Lexer
    from axon.compiler.parser import Parser
    from axon.compiler.type_checker import TypeChecker

    # Lex
    try:
        tokens = Lexer(source, filename="<repl>").tokenize()
    except AxonError as exc:
        print(_c(f"  Lexer error: {exc}", _RED))
        return

    # Parse
    try:
        ast = Parser(tokens).parse()
    except AxonError as exc:
        print(_c(f"  Parse error: {exc}", _RED))
        return

    # Type-check
    errors = TypeChecker(ast).check()
    if errors:
        for err in errors:
            loc = f" (line {err.line})" if err.line else ""
            print(_c(f"  Type error{loc}: {err.message}", _YELLOW))

    # IR generation
    try:
        ir_program = IRGenerator().generate(ast)
    except Exception as exc:
        print(_c(f"  IR error: {exc}", _RED))
        return

    # Display IR
    ir_data = ir_program.to_dict()
    formatted = json.dumps(ir_data, indent=2, ensure_ascii=False, default=str)
    print(_c(formatted, _GREEN))


# ── Multi-line input ─────────────────────────────────────────────

def _read_multiline(first_line: str) -> str:
    """Accumulate lines until braces are balanced."""
    lines = [first_line]
    depth = first_line.count("{") - first_line.count("}")

    while depth > 0:
        try:
            cont = input(_c("  ... ", _DIM))
        except (EOFError, KeyboardInterrupt):
            print()
            return ""
        lines.append(cont)
        depth += cont.count("{") - cont.count("}")

    return "\n".join(lines)


# ── Main REPL loop ───────────────────────────────────────────────

def cmd_repl(_args: Namespace) -> int:
    """Execute the ``axon repl`` subcommand."""
    # Try to enable readline for input history
    try:
        import readline  # noqa: F401
    except ImportError:
        pass

    print(_BANNER)

    while True:
        try:
            line = input(_c("axon> ", _CYAN + _BOLD))
        except (EOFError, KeyboardInterrupt):
            print(_c("\nGoodbye. 🧠", _DIM))
            return 0

        stripped = line.strip()
        if not stripped:
            continue

        # Dot-commands
        if stripped.startswith("."):
            if not _handle_dot_command(stripped):
                return 0
            continue

        # Multi-line detection
        if "{" in stripped and stripped.count("{") > stripped.count("}"):
            source = _read_multiline(stripped)
            if not source:
                continue
        else:
            source = stripped

        _eval_source(source)

    return 0
