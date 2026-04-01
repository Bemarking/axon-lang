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
from dataclasses import asdict
from pathlib import Path


_RED = "\033[31m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _c(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{code}{text}{_RESET}"


def cmd_compile(args: Namespace) -> int:
    """Execute the ``axon compile`` subcommand."""
    path = Path(args.file)

    if not path.exists():
        print(f"✗ File not found: {path}", file=sys.stderr)
        return 2

    source = path.read_text(encoding="utf-8")

    # ── Front-end pipeline ────────────────────────────────────
    from axon.compiler.errors import AxonError
    from axon.compiler.ir_generator import IRGenerator
    from axon.compiler.lexer import Lexer
    from axon.compiler.parser import Parser
    from axon.compiler.type_checker import TypeChecker

    try:
        tokens = Lexer(source, filename=str(path)).tokenize()
        ast = Parser(tokens).parse()
    except AxonError as exc:
        _print_error(exc, path)
        return 1

    errors = TypeChecker(ast).check()
    if errors:
        print(
            _c(f"✗ {path.name}", _RED + _BOLD)
            + f"  — {len(errors)} type error(s)",
            file=sys.stderr,
        )
        for err in errors:
            line_info = f"  line {err.line}" if err.line else ""
            print(f"  error{line_info}: {err.message}", file=sys.stderr)
        return 1

    # ── IR Generation ─────────────────────────────────────────
    try:
        ir_program = IRGenerator().generate(ast)
    except Exception as exc:
        print(f"✗ IR generation failed: {exc}", file=sys.stderr)
        return 1

    # ── Serialize ─────────────────────────────────────────────
    ir_dict = _serialize_ir(ir_program)
    ir_dict["_meta"] = {
        "source": str(path),
        "backend": args.backend,
        "axon_version": _get_version(),
    }

    ir_json = json.dumps(ir_dict, indent=2, ensure_ascii=False, default=str)

    if args.stdout:
        print(ir_json)
    else:
        out_path = Path(args.output) if args.output else path.with_suffix(".ir.json")
        out_path.write_text(ir_json, encoding="utf-8")
        print(f"✓ Compiled → {out_path}")

    return 0


def _serialize_ir(ir_program: object) -> dict:
    """Serialize an IRProgram to a JSON-compatible dict.

    Uses ``dataclasses.asdict`` with a custom fallback for
    enum values and non-serializable fields.
    """
    try:
        return asdict(ir_program)  # type: ignore[arg-type]
    except (TypeError, AttributeError):
        # Fallback: manual attribute extraction
        result: dict = {}
        for attr in dir(ir_program):
            if attr.startswith("_"):
                continue
            val = getattr(ir_program, attr)
            if callable(val):
                continue
            try:
                json.dumps(val, default=str)
                result[attr] = val
            except (TypeError, ValueError):
                result[attr] = str(val)
        return result


def _get_version() -> str:
    try:
        import axon

        return axon.__version__
    except Exception:
        return "unknown"


def _print_error(exc: Exception, path: Path) -> None:
    from axon.compiler.errors import AxonError

    if isinstance(exc, AxonError):
        loc = ""
        if exc.line:
            loc = f":{exc.line}"
            if exc.column:
                loc += f":{exc.column}"
        print(
            _c(f"✗ {path.name}{loc}", _RED + _BOLD) + f"  {exc.message}",
            file=sys.stderr,
        )
    else:
        print(_c(f"✗ {path.name}", _RED + _BOLD) + f"  {exc}", file=sys.stderr)
