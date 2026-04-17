"""
axon run — Compile and execute an .axon file end-to-end.

Pipeline: Source → Compile → Backend → Execute → Output

This command requires:
  - A valid .axon source file
  - An API key for the chosen backend (e.g., ANTHROPIC_API_KEY)

Exit codes:
  0 — success
  1 — compilation or execution error
  2 — I/O or configuration error
"""

from __future__ import annotations

import asyncio
import json
import sys
from argparse import Namespace
from pathlib import Path


def cmd_run(args: Namespace) -> int:
    """Execute the ``axon run`` subcommand."""
    path = Path(args.file)

    if not path.exists():
        print(f"✗ File not found: {path}", file=sys.stderr)
        return 2

    source = path.read_text(encoding="utf-8")

    # ── Compile ───────────────────────────────────────────────
    ir_program = _compile_ir_for_run(path, source)
    if ir_program is None:
        return 1

    # ── Backend compile ───────────────────────────────────────
    from axon.backends import get_backend

    try:
        backend = get_backend(args.backend)
        compiled = backend.compile(ir_program)
    except ValueError as exc:
        print(f"✗ Backend error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"✗ Backend compilation failed: {exc}", file=sys.stderr)
        return 1

    # ── Execute ───────────────────────────────────────────────
    from axon.runtime.executor import Executor
    from axon.runtime.tracer import Tracer

    tracer = Tracer() if args.trace else None

    try:
        executor = Executor(tracer=tracer)
        result = asyncio.run(
            executor.execute(compiled, tool_mode=getattr(args, "tool_mode", "stub")),
        )
    except Exception as exc:
        print(f"✗ Execution failed: {exc}", file=sys.stderr)
        return 1

    # ── Output results ────────────────────────────────────────
    _print_result(result)

    # ── Save trace ────────────────────────────────────────────
    if args.trace and tracer is not None:
        _save_trace(path, tracer)

    return 0 if getattr(result, "success", True) else 1


def _compile_ir_for_run(path: Path, source: str):
    from axon.compiler import frontend

    compile_result = frontend.compile_source(source, str(path))
    if compile_result.diagnostics:
        _print_compile_diagnostics(compile_result.diagnostics)
        return None

    if compile_result.ir_program is None:
        print("✗ IR generation failed: empty compile result", file=sys.stderr)
        return None

    return compile_result.ir_program


def _print_compile_diagnostics(diagnostics: tuple[object, ...]) -> None:
    first = diagnostics[0]
    if getattr(first, "stage", "") == "ir_generator":
        print(f"✗ IR generation failed: {first.message}", file=sys.stderr)
        return

    print(f"✗ Compilation error: {first.message}", file=sys.stderr)
    for diagnostic in diagnostics[1:]:
        print(f"  {diagnostic.message}", file=sys.stderr)


def _save_trace(path: Path, tracer: object) -> None:
    trace_path = path.with_suffix(".trace.json")
    try:
        trace_data = tracer.export()  # type: ignore[union-attr]
        trace_json = json.dumps(
            trace_data, indent=2, ensure_ascii=False, default=str
        )
        trace_path.write_text(trace_json, encoding="utf-8")
        print(f"\n📋 Trace saved → {trace_path}")
    except Exception as exc:
        print(f"\n⚠ Could not save trace: {exc}", file=sys.stderr)


def _print_result(result: object) -> None:
    """Pretty-print an execution result."""
    data = _result_to_data(result)

    print("\n" + "═" * 60)
    print("  AXON Execution Result")
    print("═" * 60)

    if isinstance(data, dict):
        _print_result_mapping(data)
    else:
        print(f"  {data}")

    print("═" * 60)


def _result_to_data(result: object) -> object:
    if hasattr(result, "to_dict"):
        return result.to_dict()  # type: ignore[union-attr]
    if hasattr(result, "__dict__"):
        return result.__dict__
    return {"result": str(result)}


def _print_result_mapping(data: dict[str, object]) -> None:
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if isinstance(value, (dict, list, tuple)):
            _print_nested_result_value(key, value)
            continue
        print(f"  {key}: {value}")


def _print_nested_result_value(key: str, value: object) -> None:
    print(f"\n  {key}:")
    formatted = json.dumps(value, indent=4, default=str)
    for line in formatted.split("\n"):
        print(f"    {line}")
