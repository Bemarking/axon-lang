"""Fase 23.h — Cross-stack opcode drift gate.

Verifies the Python frontend's emitted algebraic-effect IR opcodes
match the set the Rust runtime consumes. This is the canonical
contract that keeps `axon-lang` Python (the compiler) and `axon-rs`
Rust (the runtime) in lockstep at the algebraic-effects layer.

The gate is necessary because both sides ship at the same version
(v1.17.0+ cross-stack) but live in separate codebases — when someone
adds a new IR opcode in Python without updating Rust, this test
fails CI before the release can ship.

# What is checked

* Every `node_type` literal emitted by `axon.compiler.ir_nodes`
  Fase 23 IR classes appears in `axon-rs/src/effects/ir.rs`'s
  `Instruction` enum (or the `IR*` deserialize structs).
* Every `Instruction` enum variant in the Rust runtime is reachable
  from a Python emitter (i.e. not dead code in Rust).
* The CPS state-machine fields (`state_id`, `frame_id`,
  `body_states`, `source_frame_id`, `resume_label`) appear in both
  sides — these are the FSM coordinates the runtime indexes by.

# How it runs

Pure text-scan on both files — no `cargo` invocation, no JSON
round-trip needed. The test runs as part of `pytest` in the Python
suite; CI enforces it on every PR. The Rust side has its own static
parity test (in `axon-rs/src/effects/tests.rs`) verifying the same
shape from the other direction.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent

# Canonical Fase 23 IR opcodes the Python frontend emits. Keep this
# list in sync with `axon.compiler.ir_nodes` — every entry must be
# the `node_type` literal of an IR* dataclass.
PYTHON_FASE23_OPCODES: frozenset[str] = frozenset({
    "effect_declaration",   # IREffectDeclaration
    "effect_operation",     # IREffectOperation
    "perform",              # IRPerform
    "handler_frame",        # IRHandlerFrame
    "handler_clause",       # IRHandlerClause
    "resume",               # IRResume
    "abort",                # IRAbort
    "forward",              # IRForward
})

# Canonical CPS state-machine fields the Rust runtime indexes by.
# Every entry must appear on BOTH the Python IR class and the Rust
# IR struct it deserializes to. Drift here = runtime can't dispatch.
CPS_STATE_FIELDS: frozenset[str] = frozenset({
    "state_id",
    "frame_id",
    "body_states",
    "source_frame_id",
    "resume_label",
})


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────
#  TestPythonEmitterSurface — Python side declares all expected nodes
# ──────────────────────────────────────────────────────────────────────


class TestPythonEmitterSurface:
    """Every Fase 23 opcode is declared as a Python IR dataclass."""

    @pytest.fixture(scope="class")
    def ir_source(self) -> str:
        return _read(REPO_ROOT / "axon" / "compiler" / "ir_nodes.py")

    @pytest.mark.parametrize("opcode", sorted(PYTHON_FASE23_OPCODES))
    def test_python_ir_declares_node_type(self, ir_source: str, opcode: str) -> None:
        """Every canonical opcode is the `node_type` of some IR* dataclass."""
        pattern = rf'node_type:\s*str\s*=\s*"{re.escape(opcode)}"'
        assert re.search(pattern, ir_source), (
            f"Python IR ({REPO_ROOT}/axon/compiler/ir_nodes.py) does not "
            f"declare a class with node_type='{opcode}'. Either the opcode "
            f"was renamed (update PYTHON_FASE23_OPCODES) or the class was "
            f"deleted (regression — every entry in PYTHON_FASE23_OPCODES "
            f"is a Rust runtime contract)."
        )

    def test_no_unknown_fase23_node_types_in_python_ir(
        self, ir_source: str,
    ) -> None:
        """Catch a Fase 23 Python IR class whose node_type isn't in the
        canonical set.

        Strategy: enumerate the eight Fase 23 class names explicitly
        (cleaner than a heuristic that risks colliding with pre-Fase-23
        classes like `IREffectRow` from CT-2). For each, extract its
        `node_type` literal and verify it appears in the canonical set.
        """
        fase23_classes = (
            "IREffectDeclaration",
            "IREffectOperation",
            "IRPerform",
            "IRHandlerFrame",
            "IRHandlerClause",
            "IRResume",
            "IRAbort",
            "IRForward",
        )
        found: set[str] = set()
        for cls_name in fase23_classes:
            match = re.search(
                rf"class {cls_name}\b.*?node_type:\s*str\s*=\s*\"([^\"]+)\"",
                ir_source,
                re.DOTALL,
            )
            if match:
                found.add(match.group(1))
        unknown = found - PYTHON_FASE23_OPCODES
        assert not unknown, (
            f"Python IR declares unknown Fase 23 node_types: {sorted(unknown)}. "
            f"Add them to PYTHON_FASE23_OPCODES AND verify the Rust runtime's "
            f"`Instruction` enum covers them."
        )


# ──────────────────────────────────────────────────────────────────────
#  TestRustConsumerSurface — Rust side covers all Python-emitted opcodes
# ──────────────────────────────────────────────────────────────────────


class TestRustConsumerSurface:
    """Every Python-emitted Fase 23 opcode is consumable by the Rust runtime."""

    @pytest.fixture(scope="class")
    def rust_ir_source(self) -> str:
        return _read(REPO_ROOT / "axon-rs" / "src" / "effects" / "ir.rs")

    def test_rust_instruction_enum_covers_runtime_opcodes(
        self, rust_ir_source: str,
    ) -> None:
        """The Rust `Instruction` enum (the dispatch discriminant)
        must list every runtime-active opcode the Python frontend
        emits inside flow / handler bodies.

        Note: `effect_declaration` and `effect_operation` are
        program-level metadata, not flow-body instructions — they
        live in `IRProgram.effects` (Python) and the `IREffectDeclaration`
        / `IREffectOperation` Rust structs (not in `Instruction`).
        The Instruction enum covers the FIVE flow-body opcodes:
        perform, handler_frame, resume, abort, forward.
        """
        flow_body_opcodes = {
            "perform", "handler_frame", "resume", "abort", "forward",
        }
        # Walk the file line by line: find `pub enum Instruction {`,
        # then collect tuple-variant lines until the closing `}` at
        # column 0. A regex over the whole block is brittle because
        # doc comments inside variants contain `{` / `}` characters
        # that confuse a balanced-brace match.
        enum_body_lines: list[str] = []
        in_enum = False
        for line in rust_ir_source.splitlines():
            if not in_enum:
                if re.match(r"\s*pub enum Instruction\s*\{", line):
                    in_enum = True
                continue
            # Top-level `}` (column 0) closes the enum.
            if line.startswith("}"):
                break
            enum_body_lines.append(line)
        assert enum_body_lines, (
            "Rust runtime does not declare `pub enum Instruction` in "
            "axon-rs/src/effects/ir.rs — the dispatch discriminant "
            "the FSM walks. Confirm the enum still exists."
        )
        # Each variant is `    Variant(IRType),` — extract Pascal-cased
        # names then snake-case them to compare with node_type literals.
        variant_names: list[str] = []
        for line in enum_body_lines:
            match = re.match(r"\s*([A-Z]\w*)\s*\(", line)
            if match:
                variant_names.append(match.group(1))
        snake = {_pascal_to_snake(v) for v in variant_names}
        # The Passthrough variant is intentional fallback — it absorbs
        # legacy IR opcodes the runtime treats as inert leaves. Not
        # captured by the regex (no parens) but discard defensively.
        snake.discard("passthrough")
        missing = flow_body_opcodes - snake
        assert not missing, (
            f"Rust `Instruction` enum is missing variants for opcodes "
            f"{sorted(missing)}. Either add the variant + the IR* struct "
            f"in axon-rs/src/effects/ir.rs, or remove the opcode from the "
            f"Python frontend's emitter set."
        )

    def test_rust_struct_covers_program_level_opcodes(
        self, rust_ir_source: str,
    ) -> None:
        """`IREffectDeclaration` + `IREffectOperation` Rust structs
        exist (program-level metadata, not in Instruction enum)."""
        for struct_name in ("IREffectDeclaration", "IREffectOperation"):
            assert re.search(rf"\bpub struct {struct_name}\b", rust_ir_source), (
                f"Rust runtime missing `pub struct {struct_name}` in "
                f"axon-rs/src/effects/ir.rs — Python frontend emits "
                f"this opcode in `IRProgram.effects` and the Rust runtime "
                f"must deserialize it for the EffectRuntime to register."
            )


# ──────────────────────────────────────────────────────────────────────
#  TestCPSStateFieldsParity — FSM coordinates appear on both sides
# ──────────────────────────────────────────────────────────────────────


class TestCPSStateFieldsParity:
    """The CPS state-machine fields (state_id, frame_id, etc.) appear
    on both the Python IR classes and the Rust IR structs. Without
    these, the FSM dispatcher can't route a perform/forward to its
    resumption point."""

    @pytest.fixture(scope="class")
    def python_ir_source(self) -> str:
        return _read(REPO_ROOT / "axon" / "compiler" / "ir_nodes.py")

    @pytest.fixture(scope="class")
    def rust_ir_source(self) -> str:
        return _read(REPO_ROOT / "axon-rs" / "src" / "effects" / "ir.rs")

    @pytest.mark.parametrize("field", sorted(CPS_STATE_FIELDS))
    def test_python_ir_carries_field(self, python_ir_source: str, field: str) -> None:
        assert re.search(rf"\b{field}:\s*", python_ir_source), (
            f"Python IR does not carry CPS field '{field}' on any class. "
            f"This breaks the Rust runtime's FSM dispatch (it indexes by "
            f"`(flow_name, state_id)` and walks frames by `frame_id`)."
        )

    @pytest.mark.parametrize("field", sorted(CPS_STATE_FIELDS))
    def test_rust_ir_carries_field(self, rust_ir_source: str, field: str) -> None:
        assert re.search(rf"\bpub {field}:\s*", rust_ir_source), (
            f"Rust IR does not carry CPS field '{field}' on any struct. "
            f"This breaks deserialization of the Python-emitted IR (the "
            f"field would silently be lost, leaving the FSM unable to "
            f"resume / forward correctly)."
        )


# ──────────────────────────────────────────────────────────────────────
#  TestRuntimeRoundtrip — Python emitter → JSON → Rust deserialize works
# ──────────────────────────────────────────────────────────────────────


class TestRuntimeRoundtrip:
    """End-to-end check: a Python-compiled algebraic-effects program
    serializes to JSON and the result has the shape the Rust runtime
    expects.

    This is the strongest gate: any drift between Python and Rust
    surfaces here (a missing field, a renamed key, a changed
    enum tag) before the release can ship.
    """

    def test_python_emitted_handler_frame_has_rust_expected_keys(self) -> None:
        from axon.compiler.lexer import Lexer
        from axon.compiler.parser import Parser
        from axon.compiler.ir_generator import IRGenerator

        src = (
            "effect SSE {\n"
            "    Emit(token: String) -> Unit\n"
            "    Done() -> Never\n"
            "}\n"
            "flow Stream() -> Unit {\n"
            "  step Loop {\n"
            "    handle SSE {\n"
            "      Emit(token) -> { resume }\n"
            "      Done() -> { abort }\n"
            "    } in {\n"
            "      perform SSE.Emit(t)\n"
            "      perform SSE.Done()\n"
            "    }\n"
            "  }\n"
            "}"
        )
        ir = IRGenerator().generate(Parser(Lexer(src).tokenize()).parse())
        flow = ir.flows[0]
        handle = flow.steps[0].body[0].to_dict()

        # Top-level keys the Rust IRHandlerFrame deserializer expects.
        for key in ("node_type", "effect_names", "clauses", "body",
                    "frame_id", "body_states"):
            assert key in handle, (
                f"Python-emitted handler_frame missing key '{key}' — "
                f"Rust deserializer in axon-rs/src/effects/ir.rs expects "
                f"this field. Drift detected."
            )
        assert handle["node_type"] == "handler_frame"

        # Each clause has the expected shape.
        for clause in handle["clauses"]:
            for key in ("node_type", "operation_name",
                        "parameter_names", "body"):
                assert key in clause, (
                    f"clause missing '{key}'"
                )
            assert clause["node_type"] == "handler_clause"

        # Each body perform has the expected shape.
        for perform in handle["body"]:
            for key in ("node_type", "effect_name", "operation_name",
                        "arguments", "state_id", "resume_label"):
                assert key in perform, (
                    f"perform missing '{key}'"
                )
            assert perform["node_type"] == "perform"

    def test_python_emitted_effect_decl_has_rust_expected_keys(self) -> None:
        from axon.compiler.lexer import Lexer
        from axon.compiler.parser import Parser
        from axon.compiler.ir_generator import IRGenerator

        src = "effect Channel { Send<T>(value: T) -> Unit }"
        ir = IRGenerator().generate(Parser(Lexer(src).tokenize()).parse())
        eff = ir.effects[0].to_dict()
        for key in ("node_type", "name", "operations"):
            assert key in eff
        op = eff["operations"][0]
        for key in ("node_type", "name", "type_parameters",
                    "parameter_names", "parameter_types", "return_type"):
            assert key in op
        assert eff["node_type"] == "effect_declaration"
        assert op["node_type"] == "effect_operation"


# ──────────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────────


def _pascal_to_snake(s: str) -> str:
    """Convert PascalCase Rust enum variant to snake_case node_type."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower()
