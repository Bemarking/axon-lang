"""
axon compile — Compile an .axon file to AXON IR JSON.

Pipeline: Source → Lex → Parse → Type-check → IR Generate → JSON

Exit codes:
  0 — success
  1 — compilation error
  2 — I/O error
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path

from axon.cli.display import format_cli_path, safe_text
from axon.compiler import frontend, serialize_ir_program


_RED = "\033[31m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _c(text: str, code: str) -> str:
    text = safe_text(text, sys.stdout)
    if not sys.stdout.isatty():
        return text
    return f"{code}{text}{_RESET}"


def cmd_compile(args: Namespace) -> int:
    """Execute the ``axon compile`` subcommand."""
    path = Path(args.file)

    if not path.exists():
        print(
            safe_text(
                f"✗ File not found: {format_cli_path(path)}",
                sys.stderr,
            ),
            file=sys.stderr,
        )
        return 2

    source = path.read_text(encoding="utf-8")

    result = frontend.compile_source(source, str(path))

    if result.diagnostics:
        first = result.diagnostics[0]
        if first.stage in {"lexer", "parser"}:
            _print_frontend_diagnostic(first, path)
            return 1

        if first.stage == "ir_generator":
            print(safe_text(f"✗ IR generation failed: {first.message}", sys.stderr), file=sys.stderr)
            return 1

        print(
            _c(f"✗ {path.name}", _RED + _BOLD)
            + f"  — {len(result.diagnostics)} type error(s)",
            file=sys.stderr,
        )
        for diagnostic in result.diagnostics:
            line_info = f"  line {diagnostic.line}" if diagnostic.line else ""
            print(f"  error{line_info}: {diagnostic.message}", file=sys.stderr)
        return 1

    # ── Serialize ─────────────────────────────────────────────
    ir_dict = serialize_ir_program(result.ir_program)
    ir_dict["_meta"] = {
        "source": format_cli_path(path),
        "backend": args.backend,
        "axon_version": _get_version(),
    }

    ir_json = json.dumps(ir_dict, indent=2, ensure_ascii=False, default=str)

    if args.stdout:
        print(ir_json)
    else:
        out_path = Path(args.output) if args.output else path.with_suffix(".ir.json")
        out_path.write_text(ir_json, encoding="utf-8")
        print(safe_text(f"✓ Compiled → {format_cli_path(out_path)}", sys.stdout))

    return 0
def _get_version() -> str:
    try:
        import axon

        return axon.__version__
    except Exception:
        return "unknown"


def _print_frontend_diagnostic(diagnostic: object, path: Path) -> None:
    loc = ""
    line = getattr(diagnostic, "line", 0)
    column = getattr(diagnostic, "column", 0)
    if line:
        loc = f":{line}"
        if column:
            loc += f":{column}"

    print(
        _c(f"✗ {path.name}{loc}", _RED + _BOLD)
        + safe_text(f"  {getattr(diagnostic, 'message', diagnostic)}", sys.stderr),
        file=sys.stderr,
    )
