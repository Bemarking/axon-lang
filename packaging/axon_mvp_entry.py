"""Windows packaging entrypoint for the AXON Phase A MVP executable.

This entrypoint intentionally exposes only the Phase A MVP CLI surface:
version, check, compile, and trace.
"""

from __future__ import annotations

import argparse
import sys

import axon
from axon.cli.frontend_runtime import MVP_FRONTEND_COMMANDS, initialize_frontend_runtime


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="axon",
        description="AXON MVP executable - Phase A bridge toolchain.",
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

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

    sub.add_parser("version", help="Show axon-lang version")

    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"axon-lang {axon.__version__}",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    init_exit = initialize_frontend_runtime(args.command, allowed_commands=MVP_FRONTEND_COMMANDS)
    if init_exit is not None:
        return init_exit

    if args.command == "version":
        from axon.cli.version_cmd import cmd_version

        return cmd_version(args)

    if args.command == "check":
        from axon.cli.check_cmd import cmd_check

        return cmd_check(args)

    if args.command == "compile":
        from axon.cli.compile_cmd import cmd_compile

        return cmd_compile(args)

    if args.command == "trace":
        from axon.cli.trace_cmd import cmd_trace

        return cmd_trace(args)

    parser.print_help()
    return 1
if __name__ == "__main__":
    sys.exit(main())