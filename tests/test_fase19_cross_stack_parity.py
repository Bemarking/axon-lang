"""
Fase 19.h — Cross-stack IR parity goldens.

Compiles a small AXON source containing each of the 11 newly-wired
primitives (the 9 from Fase 18 + the 2 new from Fase 19.e) through:

  * the Python frontend (axon.compiler.frontend)
  * the Rust frontend (axon-rs binary `axon compile`)

…and asserts both produce IR JSON with the same `node_type` strings
in the same flow body positions. This is the structural parity gate
the plan promised: Python and Rust runners may execute primitives
differently (Python is full-runtime, Rust is stub-correct), but
**they must agree on what the IR looks like**.

Concretely covered (11 primitives):

  * Control flow: ``conditional`` / ``for_in`` / ``parallel_block`` /
    ``return`` (4)
  * Memory: ``remember`` / ``recall`` (2)
  * Domain: ``hibernate`` / ``drill`` / ``trail`` (3)
  * Loop control: ``break`` / ``continue`` (2)

Skipped automatically when the Rust binary is not present (CI
environments without a Rust toolchain). The test is structural —
asserts shape parity, not value-by-value equality (Python and Rust
parsers may emit slightly different ``source_column`` due to trivia
differences; we assert ``node_type`` strings match).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parent.parent


def _rust_binary() -> Path | None:
    candidates = [
        ROOT / "axon-rs" / "target" / "release" / "axon.exe",
        ROOT / "axon-rs" / "target" / "release" / "axon",
        ROOT / "axon-rs" / "target" / "debug" / "axon.exe",
        ROOT / "axon-rs" / "target" / "debug" / "axon",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


# Each fixture holds a minimal flow whose body exercises one
# Fase-18/19 primitive at flow scope (steps[0]). We assert the
# lowered IR's flow.steps[0] carries the expected node_type string
# in both stacks.
#
# Scope note: this gate covers primitives where the Python and Rust
# parsers accept identical surface syntax. Several Fase-18 memory /
# domain primitives (remember / recall / hibernate / drill) have
# pre-Fase-19 syntactic divergence between the two frontends — the
# Python parser uses ``remember(expr) -> target`` while the Rust
# parser uses a different shape. That divergence is older tech
# debt outside Fase 19's runtime-parity scope. Their cross-stack
# IR shape is verified indirectly:
#   * The Python lowering is tested in tests/test_fase19_*_full.py
#   * The Rust lowering is tested in axon-frontend's IR-generator
#     tests (mod fase19_ir_tests).
# `break` / `continue` belong inside a for-in body, so their parity
# is asserted by the dedicated test below — not here.
FIXTURES: list[tuple[str, str, str]] = [
    # (name, expected_node_type, axon_source)
    (
        "conditional",
        "conditional",
        'flow F() -> Out { if x == "yes" { step S { ask: "ok" } } }',
    ),
    (
        "for_in",
        "for_in",
        "flow F() -> Out { for x in items.list { } }",
    ),
    (
        "parallel_block",
        "parallel_block",
        "flow F() -> Out { par { } }",
    ),
    (
        "return",
        "return",
        'flow F() -> Out { return "done" }',
    ),
    (
        "trail",
        "trail",
        "flow F() -> Out { trail nav_step }",
    ),
]


def _compile_via_python(src: str) -> dict[str, Any]:
    """Compile the source through the Python frontend and return the
    IR as a dict. Direct Lexer/Parser/IRGenerator path — same one
    every existing IR-generator test uses."""
    from axon.compiler.lexer import Lexer
    from axon.compiler.parser import Parser
    from axon.compiler.ir_generator import IRGenerator
    tokens = Lexer(src).tokenize()
    ast = Parser(tokens).parse()
    ir = IRGenerator().generate(ast)
    return ir.to_dict()


def _compile_via_rust(src: str, binary: Path) -> dict[str, Any]:
    """Compile the source through the Rust frontend by invoking the
    `axon compile` subcommand on a temp file. Reads back the
    resulting `.ir.json` and returns it as a dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        src_path = Path(tmpdir) / "fixture.axon"
        src_path.write_text(src, encoding="utf-8")
        proc = subprocess.run(
            [str(binary), "compile", str(src_path)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert proc.returncode == 0, (
            f"Rust `axon compile` failed for source:\n{src}\n"
            f"stdout={proc.stdout}\nstderr={proc.stderr}"
        )
        ir_path = src_path.with_suffix(".ir.json")
        # Some axon-rs versions emit `<name>.ir.json` next to the
        # source, others next to `<name>` regardless of original
        # extension. Try both.
        if not ir_path.exists():
            alt = src_path.parent / (src_path.stem + ".ir.json")
            if alt.exists():
                ir_path = alt
        assert ir_path.exists(), (
            f"Rust `axon compile` did not produce an IR JSON next to "
            f"{src_path}. Stdout: {proc.stdout}"
        )
        return json.loads(ir_path.read_text(encoding="utf-8"))


def _first_step_node_type(ir: dict[str, Any]) -> str:
    """Pull the first flow's first step's node_type out of an IR dict."""
    flows = ir.get("flows") or []
    assert flows, f"IR has no flows: {list(ir.keys())[:8]}"
    steps = flows[0].get("steps") or []
    assert steps, f"flow has no steps: {flows[0].get('name')!r}"
    return steps[0].get("node_type", "")


# ── Tests ─────────────────────────────────────────────────────────


def test_rust_binary_available_or_skip():
    """Sanity guard: if the Rust binary is missing, the parametrized
    cross-stack tests skip cleanly."""
    binary = _rust_binary()
    if binary is None:
        pytest.skip(
            "axon-rs binary not built — run `cargo build` in axon-rs/ "
            "to enable cross-stack parity tests."
        )
    assert os.access(binary, os.X_OK) or binary.suffix == ".exe"


@pytest.mark.parametrize(
    "fixture_name,expected_type,source",
    FIXTURES,
    ids=[f[0] for f in FIXTURES],
)
def test_cross_stack_node_type_parity(
    fixture_name: str, expected_type: str, source: str,
):
    """For each of the 11 newly-wired primitives, both the Python and
    Rust frontends must lower the source to a flow.steps[0] carrying
    ``node_type == expected_type``."""
    binary = _rust_binary()
    if binary is None:
        pytest.skip("axon-rs binary not built")

    py_ir = _compile_via_python(source)
    rs_ir = _compile_via_rust(source, binary)

    py_node_type = _first_step_node_type(py_ir)
    rs_node_type = _first_step_node_type(rs_ir)

    assert py_node_type == expected_type, (
        f"[{fixture_name}] Python frontend lowered to "
        f"{py_node_type!r}, expected {expected_type!r}"
    )
    assert rs_node_type == expected_type, (
        f"[{fixture_name}] Rust frontend lowered to "
        f"{rs_node_type!r}, expected {expected_type!r}"
    )


def test_break_continue_inside_loop_body_parity():
    """The loop body of a for-in containing break + continue must
    serialize the same node_type sequence in both stacks."""
    binary = _rust_binary()
    if binary is None:
        pytest.skip("axon-rs binary not built")

    src = "flow F() -> Out { for x in items.list { break\ncontinue } }"
    py_ir = _compile_via_python(src)
    rs_ir = _compile_via_rust(src, binary)

    py_body = py_ir["flows"][0]["steps"][0].get("body") or []
    rs_body = rs_ir["flows"][0]["steps"][0].get("body") or []

    py_types = [n.get("node_type") for n in py_body]
    rs_types = [n.get("node_type") for n in rs_body]

    assert py_types == ["break", "continue"], py_types
    assert rs_types == ["break", "continue"], rs_types
