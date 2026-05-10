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
from axon.cli.frontend_runtime import FRONTEND_COMMANDS, initialize_frontend_runtime


_SOURCE_FILE_HELP = "Path to .axon source file"
_BACKEND_HELP = "Target backend (default: anthropic)"
_NO_COLOR_HELP = "Disable colored output"


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
    check.add_argument("file", help=_SOURCE_FILE_HELP)
    check.add_argument(
        "--no-color",
        action="store_true",
        help=_NO_COLOR_HELP,
    )
    check.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Treat warnings as errors (exit 1 on any warning). "
            "Recommended for CI in adopters preparing for v2.0 — "
            "see docs/migration_fase_13.md."
        ),
    )

    # ── axon compile ──────────────────────────────────────────
    compile_cmd = sub.add_parser(
        "compile",
        help="Compile an .axon file to IR JSON.",
    )
    compile_cmd.add_argument("file", help=_SOURCE_FILE_HELP)
    compile_cmd.add_argument(
        "-b",
        "--backend",
        default="anthropic",
        choices=["anthropic", "openai", "gemini", "ollama"],
        help=_BACKEND_HELP,
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
    run_cmd.add_argument("file", help=_SOURCE_FILE_HELP)
    run_cmd.add_argument(
        "-b",
        "--backend",
        default="anthropic",
        choices=["anthropic", "openai", "gemini", "ollama"],
        help=_BACKEND_HELP,
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
        help=_NO_COLOR_HELP,
    )

    # ── axon fmt ──────────────────────────────────────────────
    # Fase 14.d MVP — round-trip formatter built on the trivia
    # channel. Default writes to stdout; --check is the CI gate;
    # --write rewrites the file in place.
    fmt = sub.add_parser(
        "fmt",
        help="Format an .axon file (round-trip preserving comments).",
    )
    fmt.add_argument("file", help=_SOURCE_FILE_HELP)
    fmt.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the file is not already formatted (CI gate).",
    )
    fmt.add_argument(
        "--write",
        action="store_true",
        help="Write the formatted output back to the file in place.",
    )
    fmt.add_argument(
        "--no-color",
        action="store_true",
        help=_NO_COLOR_HELP,
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

    # ── axon serve ────────────────────────────────────────────
    serve = sub.add_parser(
        "serve",
        help="Start the AxonServer (reactive daemon platform).",
    )
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    serve.add_argument(
        "--port",
        type=int,
        default=8420,
        help="Listen port (default: 8420)",
    )
    serve.add_argument(
        "--channel",
        default="memory",
        choices=["memory", "kafka", "rabbitmq", "eventbridge"],
        help="Event channel backend (default: memory)",
    )
    serve.add_argument(
        "--auth-token",
        default="",
        help="Bearer token for API authentication",
    )
    serve.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    # ── axon deploy ───────────────────────────────────────────
    deploy = sub.add_parser(
        "deploy",
        help="Deploy .axon file to a running AxonServer.",
    )
    deploy.add_argument("file", help=_SOURCE_FILE_HELP)
    deploy.add_argument(
        "--server",
        default="http://localhost:8420",
        help="AxonServer URL (default: http://localhost:8420)",
    )
    deploy.add_argument(
        "-b",
        "--backend",
        default="anthropic",
        choices=["anthropic", "openai", "gemini", "ollama"],
        help=_BACKEND_HELP,
    )
    deploy.add_argument(
        "--auth-token",
        default="",
        help="Bearer token for AxonServer authentication",
    )

    # ── axon dossier ──────────────────────────────────────────
    # Emit an ESK Fase 6.1 + 6.6 regulatory compliance dossier (JSON).
    dossier = sub.add_parser(
        "dossier",
        help="Generate a JSON compliance dossier from an .axon file.",
    )
    dossier.add_argument("file", help=_SOURCE_FILE_HELP)
    dossier.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output path (default: stdout)",
    )

    # ── axon sbom ─────────────────────────────────────────────
    # Emit an ESK Fase 6.6 SupplyChainSBOM (JSON, deterministic).
    sbom = sub.add_parser(
        "sbom",
        help="Generate a JSON Software Bill of Materials from an .axon file.",
    )
    sbom.add_argument("file", help=_SOURCE_FILE_HELP)
    sbom.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output path (default: stdout)",
    )

    # ── axon audit ────────────────────────────────────────────
    # Run a gap analysis against external audit frameworks.
    audit = sub.add_parser(
        "audit",
        help="Gap analysis against SOC 2 / ISO 27001 / FIPS 140-3 / CC EAL 4+.",
    )
    audit.add_argument("file", help=_SOURCE_FILE_HELP)
    audit.add_argument(
        "--framework",
        default="all",
        choices=["all", "soc2", "iso27001", "fips", "cc"],
        help="Framework to analyse (default: all)",
    )
    audit.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output path (default: stdout)",
    )

    # ── axon parse ────────────────────────────────────────────
    # §Fase 28.f — Multi-file aggregator. Walks files / dirs / globs,
    # parses each `.axon` file with recovery mode (28.b), and prints
    # every diagnostic across the whole corpus in one pass. D6
    # ratified: no default cap on errors, opt-in via `--max-errors`.
    parse = sub.add_parser(
        "parse",
        help=(
            "Parse one or more .axon files and aggregate diagnostics "
            "across the corpus."
        ),
    )
    parse.add_argument(
        "patterns",
        nargs="+",
        help=(
            "File path, directory (walked recursively), or glob "
            "pattern (e.g. `src/**/*.axon`). Multiple patterns may "
            "be provided."
        ),
    )
    parse.add_argument(
        "--max-errors",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Cap the total number of parse errors reported across "
            "all files (D6, default unlimited). The CLI prints a "
            "truncation footer when the cap kicks in."
        ),
    )
    parse.add_argument(
        "--ignore",
        action="append",
        default=None,
        metavar="PATTERN",
        help=(
            "fnmatch-style ignore pattern; may be passed multiple "
            "times. `.axonignore` files in the root and walked "
            "subdirectories are honoured automatically."
        ),
    )
    parse.add_argument(
        "--jobs",
        type=int,
        default=None,
        metavar="N",
        help="Worker thread count (default: auto).",
    )
    parse.add_argument(
        "--json",
        action="store_true",
        help=(
            "§Fase 28.g — Emit machine-readable JSON diagnostics "
            "instead of human-friendly rendered output. The shape "
            "is rustc-compatible (D5 ratified) and maps cleanly to "
            "LSP `Diagnostic`. Use --format=ndjson for streaming."
        ),
    )
    parse.add_argument(
        "--format",
        choices=("array", "ndjson"),
        default="array",
        help=(
            "JSON framing when --json is set. `array` (default) "
            "emits a single JSON array; `ndjson` emits one "
            "diagnostic per line for streaming consumers."
        ),
    )
    parse.add_argument(
        "--strict",
        action="store_true",
        help=(
            "§Fase 28.h — Opt into legacy fail-on-first behavior "
            "(D8 ratified). The parser stops at the first error in "
            "the first failing file; subsequent files are skipped. "
            "Equivalent to `AXON_PARSER_STRICT=1` env var. CI "
            "pipelines that want a tight halt-on-failure loop set "
            "either; the default (no flag) uses recovery mode and "
            "surfaces every error in one pass."
        ),
    )
    parse.add_argument(
        "--no-color",
        action="store_true",
        help=_NO_COLOR_HELP,
    )

    # ── axon evidence-package ─────────────────────────────────
    # Bundle every audit artifact into a deterministic ZIP.
    evidence = sub.add_parser(
        "evidence-package",
        help="Assemble a deterministic audit evidence ZIP for external auditors.",
    )
    evidence.add_argument("file", help=_SOURCE_FILE_HELP)
    evidence.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output ZIP path (default: <file>.evidence.zip)",
    )
    evidence.add_argument(
        "--note",
        default="",
        help="Free-form auditor intake note embedded in README.md",
    )

    return parser


# Lazy-import dispatch table: each entry is the dotted path
# (`module:function`) of the handler. Lazy imports keep CLI startup fast.
_DISPATCH: dict[str, str] = {
    "check": "axon.cli.check_cmd:cmd_check",
    "compile": "axon.cli.compile_cmd:cmd_compile",
    "run": "axon.cli.run_cmd:cmd_run",
    "trace": "axon.cli.trace_cmd:cmd_trace",
    "fmt": "axon.cli.fmt_cmd:cmd_fmt",
    "version": "axon.cli.version_cmd:cmd_version",
    "repl": "axon.cli.repl_cmd:cmd_repl",
    "inspect": "axon.cli.inspect_cmd:cmd_inspect",
    "serve": "axon.cli.serve_cmd:cmd_serve",
    "deploy": "axon.cli.deploy_cmd:cmd_deploy",
    "dossier": "axon.cli.dossier_cmd:cmd_dossier",
    "sbom": "axon.cli.sbom_cmd:cmd_sbom",
    "audit": "axon.cli.audit_cmd:cmd_audit",
    "evidence-package": "axon.cli.evidence_package_cmd:cmd_evidence_package",
    # §Fase 28.f — multi-file aggregator
    "parse": "axon.cli.parse_cmd:cmd_parse",
}


def _resolve_handler(target: str):
    """Lazy-import ``module:function`` and return the callable."""
    import importlib

    module_name, func_name = target.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, func_name)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``axon`` CLI."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    init_exit = initialize_frontend_runtime(args.command, allowed_commands=FRONTEND_COMMANDS)
    if init_exit is not None:
        return init_exit

    target = _DISPATCH.get(args.command)
    if target is None:
        parser.print_help()
        return 1
    return _resolve_handler(target)(args)
if __name__ == "__main__":
    sys.exit(main())
