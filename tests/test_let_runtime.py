"""
AXON `let` Runtime — Phase-2 Lowering + Dispatcher + Type-Checker (Fase 17).

Coverage matrix following docs/fase/fase_17_let_runtime_wiring.md §4 / §6:

  17.a Phase-2 lowering — IR → CompiledStep with `let_binding` metadata
  17.b Python runtime dispatcher — pure binding, no LLM, no I/O
  17.d Type-checker hardening — reserved-name shadowing, self-reference
  17.e Interpolation resolution — let-bound vars beat step results
  17.f Cross-stack parity — Python + Rust read the same golden
  17.g Test matrix — 25 scenarios

Doc-honesty regression test (17.h) verifies the docstring drift gate.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from axon.backends.base_backend import (
    BaseBackend,
    CompiledStep,
    _LET_IR_TYPES,
)
from axon.compiler.ir_nodes import IRLetBinding
from axon.runtime.executor import Executor
from tests.test_executor import MockModelClient, make_program, make_unit


# ═══════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════


def _let_step(target: str, value, value_kind: str = "literal") -> CompiledStep:
    """Construct a CompiledStep mirroring _compile_let_step output."""
    return CompiledStep(
        step_name=f"let:{target}",
        user_prompt="",
        metadata={
            "let_binding": {
                "target": target,
                "value": value,
                "value_kind": value_kind,
            },
        },
    )


async def _exec_with_ctx_hook(*, steps, seed_vars=None):
    """Run steps under a captured ContextManager (same pattern as
    test_lambda_data_runtime.py)."""
    client = MockModelClient()
    executor = Executor(client=client)
    seed_vars = seed_vars or {}
    captured: dict = {}

    from axon.runtime import context_mgr as _ctxmod

    original_init = _ctxmod.ContextManager.__init__

    def hooked(self, *a, **kw):
        original_init(self, *a, **kw)
        for name, value in seed_vars.items():
            self.set_variable(name, value)
        captured["ctx"] = self

    _ctxmod.ContextManager.__init__ = hooked  # type: ignore[method-assign]
    try:
        program = make_program([make_unit("test_flow", steps)])
        result = await executor.execute(program)
    finally:
        _ctxmod.ContextManager.__init__ = original_init  # type: ignore[method-assign]
    return result, captured.get("ctx"), client


def _check(source: str):
    """Lex + parse + type-check; return error list."""
    from axon.compiler.lexer import Lexer
    from axon.compiler.parser import Parser
    from axon.compiler.type_checker import TypeChecker
    return TypeChecker(Parser(Lexer(source).tokenize()).parse()).check()


# ═══════════════════════════════════════════════════════════════════
#  17.a — PHASE-2 LOWERING
# ═══════════════════════════════════════════════════════════════════


class TestPhase2Lowering:
    def test_let_ir_types_constant_includes_irletbinding(self):
        assert IRLetBinding in _LET_IR_TYPES

    def test_compile_let_step_produces_metadata(self):
        node = IRLetBinding(target="X", value="hello", value_kind="literal")
        step = BaseBackend._compile_let_step(node)
        assert step.metadata.get("let_binding") is not None
        meta = step.metadata["let_binding"]
        assert meta["target"] == "X"
        assert meta["value"] == "hello"
        assert meta["value_kind"] == "literal"

    def test_compile_let_step_step_name(self):
        node = IRLetBinding(target="myvar", value="v")
        step = BaseBackend._compile_let_step(node)
        assert step.step_name == "let:myvar"

    def test_compile_let_step_no_user_prompt(self):
        """The compiled step must not produce an LLM-bound prompt."""
        node = IRLetBinding(target="X", value="v")
        step = BaseBackend._compile_let_step(node)
        assert step.user_prompt == ""
        assert step.system_prompt == ""

    def test_dispatch_arm_present_in_compile_program(self):
        """Structural check — the dispatch chain (Fase 18.a refactored
        it from inline in compile_program to a dedicated
        `_compile_one_step` helper) references _LET_IR_TYPES."""
        import inspect
        src = (
            inspect.getsource(BaseBackend.compile_program)
            + inspect.getsource(BaseBackend._compile_one_step)
        )
        assert "_LET_IR_TYPES" in src
        assert "_compile_let_step" in src


# ═══════════════════════════════════════════════════════════════════
#  17.b — DISPATCHER (literal kinds + reference resolution)
# ═══════════════════════════════════════════════════════════════════


class TestDispatcher:
    @pytest.mark.asyncio
    async def test_literal_string_binds(self):
        step = _let_step("path", "workspace/drafts/tesis.md")
        result, ctx, _ = await _exec_with_ctx_hook(steps=[step])
        assert result.success is True
        assert ctx.get_variable("path") == "workspace/drafts/tesis.md"

    @pytest.mark.asyncio
    async def test_literal_int_binds(self):
        step = _let_step("n", 42)
        result, ctx, _ = await _exec_with_ctx_hook(steps=[step])
        assert result.success is True
        assert ctx.get_variable("n") == 42

    @pytest.mark.asyncio
    async def test_literal_float_binds(self):
        step = _let_step("pi", 3.14)
        result, ctx, _ = await _exec_with_ctx_hook(steps=[step])
        assert result.success is True
        assert ctx.get_variable("pi") == pytest.approx(3.14)

    @pytest.mark.asyncio
    async def test_literal_bool_binds(self):
        step = _let_step("flag", True)
        result, ctx, _ = await _exec_with_ctx_hook(steps=[step])
        assert result.success is True
        assert ctx.get_variable("flag") is True

    @pytest.mark.asyncio
    async def test_literal_list_binds(self):
        step = _let_step("items", [1, 2, "three"])
        result, ctx, _ = await _exec_with_ctx_hook(steps=[step])
        assert result.success is True
        assert ctx.get_variable("items") == [1, 2, "three"]

    @pytest.mark.asyncio
    async def test_reference_resolves_at_runtime(self):
        step = _let_step("derived", "source_var", value_kind="reference")
        result, ctx, _ = await _exec_with_ctx_hook(
            steps=[step], seed_vars={"source_var": "real_value"},
        )
        assert result.success is True
        assert ctx.get_variable("derived") == "real_value"

    @pytest.mark.asyncio
    async def test_reference_dotted_path(self):
        step = _let_step("inner", "obj.field", value_kind="reference")
        result, ctx, _ = await _exec_with_ctx_hook(
            steps=[step], seed_vars={"obj": {"field": "nested"}},
        )
        assert result.success is True
        assert ctx.get_variable("inner") == "nested"

    @pytest.mark.asyncio
    async def test_reference_unknown_raises(self):
        step = _let_step("x", "ghost", value_kind="reference")
        result, _ctx, _ = await _exec_with_ctx_hook(steps=[step])
        assert result.success is False
        err = result.unit_results[0].error
        assert err is not None and "ghost" in str(err)

    @pytest.mark.asyncio
    async def test_dispatcher_no_model_call(self):
        """The let step must NEVER invoke the model client."""
        step = _let_step("x", "literal")
        _, _, client = await _exec_with_ctx_hook(steps=[step])
        assert client.call_count == 0

    @pytest.mark.asyncio
    async def test_two_lets_chain(self):
        s1 = _let_step("a", "first")
        s2 = _let_step("b", "a", value_kind="reference")
        result, ctx, _ = await _exec_with_ctx_hook(steps=[s1, s2])
        assert result.success is True
        assert ctx.get_variable("a") == "first"
        assert ctx.get_variable("b") == "first"

    @pytest.mark.asyncio
    async def test_response_content_is_json_serialised(self):
        step = _let_step("payload", {"k": "v"})
        result, _, _ = await _exec_with_ctx_hook(steps=[step])
        assert result.success is True
        step_result = result.unit_results[0].step_results[0]
        parsed = json.loads(step_result.response.content)
        assert parsed == {"k": "v"}


# ═══════════════════════════════════════════════════════════════════
#  17.d — TYPE-CHECKER HARDENING
# ═══════════════════════════════════════════════════════════════════


class TestTypeCheckerHardening:
    def test_ssa_rebind_rejected(self):
        src = '''flow F() {
    let x = "first"
    let x = "second"
}'''
        errors = _check(src)
        assert any("ImmutableBindingError" in e.message for e in errors)

    @pytest.mark.parametrize("primitive", ["int", "string", "bool", "float", "any"])
    def test_reserved_primitive_shadowing_rejected(self, primitive):
        src = f'''flow F() {{
    let {primitive} = "shadow"
}}'''
        errors = _check(src)
        assert any(
            "shadows a reserved" in e.message
            and primitive.lower() in e.message.lower()
            for e in errors
        ), f"expected shadow error for '{primitive}', got: {[e.message for e in errors]}"

    def test_reserved_shadowing_case_insensitive(self):
        src = '''flow F() {
    let Int = "shadow"
}'''
        errors = _check(src)
        assert any("shadows a reserved" in e.message for e in errors)

    def test_self_reference_rejected(self):
        src = '''flow F() {
    let x = x
}'''
        errors = _check(src)
        assert any("self-referential" in e.message.lower() for e in errors)

    def test_self_reference_dotted_rejected(self):
        src = '''flow F() {
    let x = x.field
}'''
        errors = _check(src)
        assert any("self-referential" in e.message.lower() for e in errors)

    def test_distinct_identifier_passes(self):
        src = '''flow F() {
    let path = "ok"
    let count = 42
    let derived = path
}'''
        errors = _check(src)
        relevant = [
            e for e in errors
            if "shadows a reserved" in e.message
            or "self-referential" in e.message.lower()
            or "ImmutableBindingError" in e.message
        ]
        assert relevant == [], [e.message for e in errors]


# ═══════════════════════════════════════════════════════════════════
#  17.e — INTERPOLATION RESOLUTION
# ═══════════════════════════════════════════════════════════════════


class TestInterpolation:
    @pytest.mark.asyncio
    async def test_let_bound_var_resolvable_via_value_ref(self):
        """ctx.resolve_value_ref finds let-bound vars in the variable tier."""
        step = _let_step("greeting", "hello world")
        _, ctx, _ = await _exec_with_ctx_hook(steps=[step])
        assert ctx.resolve_value_ref("greeting") == "hello world"

    @pytest.mark.asyncio
    async def test_let_bound_dict_supports_dotted_access(self):
        step = _let_step("payload", {"a": {"b": 7}})
        _, ctx, _ = await _exec_with_ctx_hook(steps=[step])
        assert ctx.resolve_value_ref("payload.a.b") == 7


# ═══════════════════════════════════════════════════════════════════
#  17.f — CROSS-STACK PARITY GOLDEN
# ═══════════════════════════════════════════════════════════════════


class TestCrossStackParity:
    """Both Python and Rust read the same fixture under
    axon-rs/tests/parity/. Drift on either side breaks both gates."""

    _PARITY_DIR = "axon-rs/tests/parity"

    def _read_json(self, filename: str):
        from pathlib import Path
        path = Path(self._PARITY_DIR) / filename
        with path.open(encoding="utf-8") as f:
            return json.load(f)

    @pytest.mark.asyncio
    async def test_python_post_bind_matches_golden(self):
        spec = self._read_json("fase17_let_binding.spec.json")
        golden = self._read_json("fase17_let_binding.golden.json")

        step = _let_step(
            target=spec["target"],
            value=spec["value"],
            value_kind=spec.get("value_kind", "literal"),
        )
        result, ctx, _ = await _exec_with_ctx_hook(steps=[step])
        assert result.success is True

        post_bind = {spec["target"]: ctx.get_variable(spec["target"])}
        # Round-trip through json so floats / bools normalize.
        post_bind_canon = json.loads(json.dumps(post_bind))
        assert post_bind_canon == golden, (
            f"Python post-bind parity broke:\n"
            f"--- expected ---\n{json.dumps(golden, indent=2)}\n"
            f"--- actual ---\n{json.dumps(post_bind_canon, indent=2)}"
        )

    def test_spec_uses_documented_keys(self):
        spec = self._read_json("fase17_let_binding.spec.json")
        assert set(spec.keys()) == {"target", "value", "value_kind"}


# ═══════════════════════════════════════════════════════════════════
#  17.h — DOC HONESTY REGRESSION GATE
# ═══════════════════════════════════════════════════════════════════


class TestDocHonesty:
    """The previous `_visit_let` docstring promised 'runtime macro
    substitution' that never existed. After Fase 17 ships the docstring
    must either describe the actual shipped behavior or NOT use that
    phrase. This test catches future drift if someone copy-pastes the
    old language back."""

    def test_visit_let_docstring_describes_shipped_behavior(self):
        from axon.compiler.ir_generator import IRGenerator
        doc = IRGenerator._visit_let.__doc__ or ""
        # Must reference the runtime dispatcher OR explicitly say the
        # behavior is implemented.
        lower = doc.lower()
        forbidden = "deterministic, serializable value for runtime macro substitution"
        assert forbidden not in lower, (
            f"Docstring still uses the pre-Fase-17 lying phrase. "
            f"Update it to describe the actual dispatcher path."
        )

    def test_irletbinding_docstring_describes_runtime_path(self):
        from axon.compiler.ir_nodes import IRLetBinding
        doc = IRLetBinding.__doc__ or ""
        # Must mention Fase 17 / runtime / dispatcher to anchor reality.
        lower = doc.lower()
        assert ("fase 17" in lower or "_execute_let_step" in lower
                or "set_variable" in lower), (
            "IRLetBinding docstring should reference the runtime "
            "dispatcher (Fase 17.b) so readers can find the impl."
        )


# ═══════════════════════════════════════════════════════════════════
#  17.g extras — END-TO-END source compilation
# ═══════════════════════════════════════════════════════════════════


class TestEndToEnd:
    """Compile a real .axon source through lex+parse+IR+lowering and
    verify the resulting CompiledStep carries the right metadata."""

    def _ir_for(self, source: str):
        from axon.compiler.lexer import Lexer
        from axon.compiler.parser import Parser
        from axon.compiler.ir_generator import IRGenerator
        return IRGenerator().generate(Parser(Lexer(source).tokenize()).parse())

    def test_literal_string_kind_preserved_through_ir(self):
        ir = self._ir_for('flow F() { let x = "literal" }')
        let_node = ir.flows[0].steps[0]
        assert let_node.value == "literal"
        assert let_node.value_kind == "literal"

    def test_reference_kind_preserved_through_ir(self):
        ir = self._ir_for('flow F() { let x = step_a.output }')
        let_node = ir.flows[0].steps[0]
        assert let_node.value == "step_a.output"
        assert let_node.value_kind == "reference"

    def test_arithmetic_kind_marks_expression(self):
        ir = self._ir_for('flow F() { let x = 2 + 3 }')
        let_node = ir.flows[0].steps[0]
        assert let_node.value_kind == "expression"
