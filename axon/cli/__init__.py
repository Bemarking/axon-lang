"""
AXON CLI — Command dispatcher.

Usage:
    axon check   <file.axon>                  Lex + parse + type-check
    axon compile <file.axon> [--backend=...]   Full pipeline → IR JSON
    axon run     <file.axon> [--backend=...]   Compile + execute
    axon trace   <file.trace.json>              Pretty-print a trace
    axon version                               Show version
"""

from __future__ import annotations

import argparse
import sys

import axon


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="axon",
        description="AXON — A programming language for AI cognition.",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"axon-lang {axon.__version__}",
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # ── axon check ────────────────────────────────────────────
    check = sub.add_parser(
        "check",
        help="Lex, parse, and type-check an .axon file.",
    )
    check.add_argument("file", help="Path to .axon source file")
    check.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output",
    )

    # ── axon compile ──────────────────────────────────────────
    compile_cmd = sub.add_parser(
        "compile",
        help="Compile an .axon file to IR JSON.",
    )
    compile_cmd.add_argument("file", help="Path to .axon source file")
    compile_cmd.add_argument(
        "-b",
        "--backend",
        default="anthropic",
        choices=["anthropic", "openai", "gemini", "ollama"],
        help="Target backend (default: anthropic)",
    )
    compile_cmd.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output path (default: <file>.ir.json)",
    )
    compile_cmd.add_argument(
        "--stdout",
        action="store_true",
        help="Print IR JSON to stdout instead of writing to file",
    )

    # ── axon run ──────────────────────────────────────────────
    run_cmd = sub.add_parser(
        "run",
        help="Compile and execute an .axon file.",
    )
    run_cmd.add_argument("file", help="Path to .axon source file")
    run_cmd.add_argument(
        "-b",
        "--backend",
        default="anthropic",
        choices=["anthropic", "openai", "gemini", "ollama"],
        help="Target backend (default: anthropic)",
    )
    run_cmd.add_argument(
        "--trace",
        action="store_true",
        help="Save execution trace to <file>.trace.json",
    )
    run_cmd.add_argument(
        "--tool-mode",
        default="stub",
        choices=["stub", "real", "hybrid"],
        help="Tool backend mode (default: stub)",
    )

    # ── axon trace ────────────────────────────────────────────
    trace = sub.add_parser(
        "trace",
        help="Pretty-print a saved execution trace.",
    )
    trace.add_argument("file", help="Path to .trace.json file")
    trace.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output",
    )

    # ── axon version ──────────────────────────────────────────
    sub.add_parser("version", help="Show axon-lang version")

    # ── axon repl ─────────────────────────────────────────────
    sub.add_parser(
        "repl",
        help="Start an interactive AXON REPL session.",
    )

    # ── axon inspect ──────────────────────────────────────────
    inspect_cmd = sub.add_parser(
        "inspect",
        help="Introspect the AXON standard library.",
    )
    inspect_cmd.add_argument(
        "target",
        nargs="?",
        default="anchors",
        help="Namespace (anchors|personas|flows|tools) or component name",
    )
    inspect_cmd.add_argument(
        "--all",
        action="store_true",
        help="List all stdlib components across all namespaces",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``axon`` CLI."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    # Dispatch to subcommand handlers.
    # Lazy imports keep startup fast.
    if args.command == "check":
        from axon.cli.check_cmd import cmd_check

        return cmd_check(args)

    if args.command == "compile":
        from axon.cli.compile_cmd import cmd_compile

        return cmd_compile(args)

    if args.command == "run":
        from axon.cli.run_cmd import cmd_run

        return cmd_run(args)

    if args.command == "trace":
        from axon.cli.trace_cmd import cmd_trace

        return cmd_trace(args)

    if args.command == "version":
        from axon.cli.version_cmd import cmd_version

        return cmd_version(args)

    if args.command == "repl":
        from axon.cli.repl_cmd import cmd_repl

        return cmd_repl(args)

    if args.command == "inspect":
        from axon.cli.inspect_cmd import cmd_inspect

        return cmd_inspect(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
