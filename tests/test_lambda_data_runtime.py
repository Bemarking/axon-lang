"""
AXON Lambda Data (ΛD) Apply — Phase-2 Lowering + Runtime Dispatcher Tests
==========================================================================
Verifies Fase 15 sub-phases 15.a (Phase-2 lowering: IR → CompiledStep)
and 15.b (Python runtime dispatcher: CompiledStep → bound ψ).

Coverage matrix follows docs/fase_15_lambda_apply_runtime.md §4 (15.e):

  1. lambda raw, certainty=1.0, derivation=raw applied → c=1.0 preserved
  2. lambda inferred, certainty=0.7 applied → c=0.7 propagated
  3. T5.1 violation in spec_snapshot (IR-tampered) → EpistemicDegradationError
  4. target undefined symbol → AxonRuntimeError
  5. output_type rebinding → succeeds (warn-on-trace path is a 15.d concern)
  6. Chained apply — apply spec1 to step1.out -> e1; apply spec2 to e1.V -> e2
  7. ψ JSON shape — round-trip serialization preserves ⟨T, V, E⟩
  8. Empty output_type — anonymous apply, trace-only, no binding

Plus lowering-specific tests:

  - IRLambdaDataApply produces CompiledStep with lambda_data_apply metadata
  - spec_snapshot is materialised inline (not a reference)
  - Missing spec name in IR → empty snapshot but no crash (defensive default)

Plus parity tests:

  - Vocabulary parity between runtime and compiler VALID_DERIVATIONS
"""

from __future__ import annotations

import json

import pytest

from axon.backends.base_backend import (
    BaseBackend,
    CompiledStep,
)
from axon.compiler.ir_nodes import (
    IRFlow,
    IRLambdaData,
    IRLambdaDataApply,
    IRProgram,
    IRRun,
)
from axon.runtime.executor import Executor
from axon.runtime.lambda_runtime import (
    LambdaPsi,
    LambdaTensor,
    VALID_DERIVATIONS,
    build_psi,
    enforce_theorem_5_1,
)
from axon.runtime.runtime_errors import (
    AxonRuntimeError,
    EpistemicDegradationError,
)
from tests.test_executor import MockModelClient, make_program, make_unit


# ═══════════════════════════════════════════════════════════════════
#  HELPERS — build a CompiledStep with lambda_data_apply metadata
# ═══════════════════════════════════════════════════════════════════


def _apply_step(
    *,
    spec_name: str,
    target: str,
    output_type: str = "",
    ontology: str = "test.ontology",
    certainty: float = 1.0,
    derivation: str = "raw",
    tau_start: str = "",
    tau_end: str = "",
    provenance: str = "",
) -> CompiledStep:
    """Build a CompiledStep mirroring what BaseBackend._compile_lambda_apply_step
    produces. Used by runtime tests that bypass the front-end and feed the
    executor directly."""
    return CompiledStep(
        step_name=f"lambda_apply:{spec_name}",
        user_prompt="",
        metadata={
            "lambda_data_apply": {
                "lambda_data_name": spec_name,
                "target": target,
                "output_type": output_type,
                "spec_snapshot": {
                    "name": spec_name,
                    "ontology": ontology,
                    "certainty": certainty,
                    "temporal_frame_start": tau_start,
                    "temporal_frame_end": tau_end,
                    "provenance": provenance,
                    "derivation": derivation,
                },
            },
        },
    )


async def _exec_with_ctx_hook(
    *,
    steps: list[CompiledStep],
    seed_vars: dict[str, object] | None = None,
):
    """Execute `steps` after seeding the per-unit ContextManager with
    `seed_vars`. Returns ``(ExecutionResult, ContextManager)`` so tests
    can inspect bound variables after execution.

    Implementation patches ``ContextManager.__init__`` for the duration
    of the call so the per-unit context the executor constructs gets
    pre-seeded and captured. This keeps the test free of executor
    internals and works for any future change to the unit lifecycle.
    """
    client = MockModelClient()
    executor = Executor(client=client)
    seed_vars = seed_vars or {}
    captured: dict[str, object] = {}

    from axon.runtime import context_mgr as _ctxmod

    original_ctx_init = _ctxmod.ContextManager.__init__

    def hooked_init(self, *a, **kw):
        original_ctx_init(self, *a, **kw)
        for name, value in seed_vars.items():
            self.set_variable(name, value)
        captured["ctx"] = self

    _ctxmod.ContextManager.__init__ = hooked_init  # type: ignore[method-assign]
    try:
        program = make_program([make_unit("test_flow", steps)])
        result = await executor.execute(program)
    finally:
        _ctxmod.ContextManager.__init__ = original_ctx_init  # type: ignore[method-assign]

    return result, captured.get("ctx")


# ═══════════════════════════════════════════════════════════════════
#  15.a — PHASE-2 LOWERING TESTS
# ═══════════════════════════════════════════════════════════════════


class TestPhase2Lowering:
    """IRLambdaDataApply → CompiledStep with lambda_data_apply metadata."""

    def _ir_with_apply(
        self,
        *,
        spec_name: str = "Sensor",
        target: str = "raw_data",
        output_type: str = "Reading",
        certainty: float = 0.95,
        derivation: str = "raw",
    ) -> IRProgram:
        spec = IRLambdaData(
            name=spec_name,
            ontology="measurement.temperature",
            certainty=certainty,
            temporal_frame_start="2026-01-01T00:00:00Z",
            temporal_frame_end="2026-12-31T23:59:59Z",
            provenance="HVAC_Sensor_Unit_3",
            derivation=derivation,
        )
        apply_node = IRLambdaDataApply(
            lambda_data_name=spec_name,
            target=target,
            output_type=output_type,
        )
        flow = IRFlow(name="Process", steps=(apply_node,))
        return IRProgram(
            flows=(flow,),
            runs=(IRRun(flow_name="Process", resolved_flow=flow),),
            lambda_data_specs=(spec,),
        )

    def test_lowering_produces_compiled_step(self):
        """The compile pass emits one CompiledStep per IRLambdaDataApply."""
        ir = self._ir_with_apply()
        compiled = BaseBackend._compile_lambda_apply_step(
            ir.runs[0].resolved_flow.steps[0], ir,
        )
        assert isinstance(compiled, CompiledStep)
        assert compiled.step_name == "lambda_apply:Sensor"
        assert compiled.metadata.get("lambda_data_apply") is not None

    def test_lowering_carries_full_spec_snapshot(self):
        """The metadata payload includes a verbatim copy of the spec
        (not just the name) so the runtime never needs the IR."""
        ir = self._ir_with_apply(certainty=0.7, derivation="inferred")
        compiled = BaseBackend._compile_lambda_apply_step(
            ir.runs[0].resolved_flow.steps[0], ir,
        )
        snapshot = compiled.metadata["lambda_data_apply"]["spec_snapshot"]
        assert snapshot["name"] == "Sensor"
        assert snapshot["ontology"] == "measurement.temperature"
        assert snapshot["certainty"] == pytest.approx(0.7)
        assert snapshot["derivation"] == "inferred"
        assert snapshot["provenance"] == "HVAC_Sensor_Unit_3"
        assert snapshot["temporal_frame_start"] == "2026-01-01T00:00:00Z"

    def test_lowering_carries_target_and_output_type(self):
        ir = self._ir_with_apply(target="raw_input", output_type="Validated")
        compiled = BaseBackend._compile_lambda_apply_step(
            ir.runs[0].resolved_flow.steps[0], ir,
        )
        meta = compiled.metadata["lambda_data_apply"]
        assert meta["target"] == "raw_input"
        assert meta["output_type"] == "Validated"
        assert meta["lambda_data_name"] == "Sensor"

    def test_lowering_unknown_spec_yields_empty_snapshot(self):
        """Defensive default — IR with no matching spec produces an empty
        snapshot rather than raising. The type checker rejects honest
        programs that hit this path; reaching it implies IR tampering
        and surfaces at runtime via EpistemicDegradationError on the
        bounds check."""
        apply_node = IRLambdaDataApply(
            lambda_data_name="Ghost",
            target="x",
            output_type="Y",
        )
        ir = IRProgram(lambda_data_specs=())  # no specs
        compiled = BaseBackend._compile_lambda_apply_step(apply_node, ir)
        snapshot = compiled.metadata["lambda_data_apply"]["spec_snapshot"]
        assert snapshot == {}

    def test_lowering_dispatch_arm_present_in_compile_program(self):
        """Structural check — the dispatch chain (Fase 18.a refactored
        it from inline in compile_program to a dedicated
        `_compile_one_step` helper for control-flow recursion) handles
        _LAMBDA_APPLY_IR_TYPES (Fase 15.a)."""
        from axon.backends.base_backend import (
            _LAMBDA_APPLY_IR_TYPES,
        )
        import inspect
        src = (
            inspect.getsource(BaseBackend.compile_program)
            + inspect.getsource(BaseBackend._compile_one_step)
        )
        assert "_LAMBDA_APPLY_IR_TYPES" in src
        assert "_compile_lambda_apply_step" in src
        # The constant itself must include IRLambdaDataApply.
        assert IRLambdaDataApply in _LAMBDA_APPLY_IR_TYPES


# ═══════════════════════════════════════════════════════════════════
#  Theorem 5.1 RUNTIME GUARD TESTS (mirror compile-time)
# ═══════════════════════════════════════════════════════════════════


class TestTheorem51RuntimeGuard:
    """enforce_theorem_5_1 mirrors the compile-time check exactly."""

    def test_raw_certainty_one_is_legal(self):
        # Raw + c=1.0 — the only legal absolute-certainty derivation.
        enforce_theorem_5_1(spec_name="X", certainty=1.0, derivation="raw")

    def test_inferred_below_one_is_legal(self):
        enforce_theorem_5_1(spec_name="X", certainty=0.7, derivation="inferred")

    def test_inferred_with_one_raises(self):
        with pytest.raises(EpistemicDegradationError) as exc_info:
            enforce_theorem_5_1(
                spec_name="Bad",
                certainty=1.0,
                derivation="inferred",
            )
        assert "Theorem 5.1" in str(exc_info.value)
        assert "Bad" in str(exc_info.value)

    def test_aggregated_with_one_raises(self):
        with pytest.raises(EpistemicDegradationError):
            enforce_theorem_5_1(
                spec_name="X", certainty=1.0, derivation="aggregated",
            )

    def test_certainty_out_of_range_raises(self):
        with pytest.raises(EpistemicDegradationError):
            enforce_theorem_5_1(spec_name="X", certainty=1.5, derivation="raw")
        with pytest.raises(EpistemicDegradationError):
            enforce_theorem_5_1(spec_name="X", certainty=-0.1, derivation="raw")

    def test_unknown_derivation_raises(self):
        with pytest.raises(EpistemicDegradationError) as exc_info:
            enforce_theorem_5_1(
                spec_name="X", certainty=0.5, derivation="unicornified",
            )
        assert "unicornified" in str(exc_info.value)

    def test_empty_derivation_passes_for_compat(self):
        """Compile-time guard treats empty derivation as legacy/observed
        and skips Theorem 5.1; runtime mirrors that."""
        enforce_theorem_5_1(spec_name="X", certainty=1.0, derivation="")

    def test_derivation_vocab_parity_with_compiler(self):
        """Runtime VALID_DERIVATIONS must equal compiler's set — drift
        would mean the runtime accepts specs the compiler rejected (or
        vice versa)."""
        from axon.compiler.type_checker import TypeChecker
        assert VALID_DERIVATIONS == TypeChecker._VALID_DERIVATIONS


# ═══════════════════════════════════════════════════════════════════
#  build_psi UNIT TESTS
# ═══════════════════════════════════════════════════════════════════


class TestBuildPsi:
    """build_psi materialises ψ = ⟨T, V, E⟩ from a spec snapshot."""

    def _snap(self, **overrides) -> dict:
        base = {
            "name": "S",
            "ontology": "measurement.temp",
            "certainty": 1.0,
            "temporal_frame_start": "2026-01-01T00:00:00Z",
            "temporal_frame_end": "2026-12-31T23:59:59Z",
            "provenance": "Sensor-A",
            "derivation": "raw",
        }
        base.update(overrides)
        return base

    def test_psi_carries_full_tensor(self):
        psi = build_psi(spec_snapshot=self._snap(), target_value=23.5)
        assert isinstance(psi, LambdaPsi)
        assert psi.T == "measurement.temp"
        assert psi.V == pytest.approx(23.5)
        assert isinstance(psi.E, LambdaTensor)
        assert psi.E.c == pytest.approx(1.0)
        assert psi.E.delta == "raw"
        assert psi.E.rho == "Sensor-A"
        assert psi.spec_name == "S"

    def test_psi_serialises_to_dict(self):
        psi = build_psi(spec_snapshot=self._snap(), target_value=23.5)
        d = psi.to_dict()
        assert d["T"] == "measurement.temp"
        assert d["V"] == pytest.approx(23.5)
        assert d["E"]["c"] == pytest.approx(1.0)
        assert d["E"]["delta"] == "raw"

    def test_psi_round_trip_via_json(self):
        psi = build_psi(spec_snapshot=self._snap(), target_value=23.5)
        s = json.dumps(psi.to_dict())
        d = json.loads(s)
        assert d["E"]["c"] == pytest.approx(1.0)
        assert d["spec_name"] == "S"

    def test_t51_violation_in_snapshot_raises(self):
        with pytest.raises(EpistemicDegradationError):
            build_psi(
                spec_snapshot=self._snap(certainty=1.0, derivation="inferred"),
                target_value=42,
            )

    def test_psi_accepts_complex_values(self):
        # V can be any object — dict, list, dataclass, etc.
        v = {"reading": 23.5, "unit": "°C"}
        psi = build_psi(spec_snapshot=self._snap(), target_value=v)
        assert psi.V == v


# ═══════════════════════════════════════════════════════════════════
#  15.b/15.e — RUNTIME DISPATCHER SCENARIOS
# ═══════════════════════════════════════════════════════════════════


class TestRuntimeDispatcher:
    """Executor dispatches lambda_data_apply CompiledSteps end-to-end."""

    @pytest.mark.asyncio
    async def test_scenario_1_raw_certainty_one_preserved(self):
        """Scenario 1: lambda raw, c=1.0 applied → c=1.0 preserved."""
        step = _apply_step(
            spec_name="Raw",
            target="raw_value",
            output_type="Bound",
            certainty=1.0,
            derivation="raw",
        )
        result, ctx = await _exec_with_ctx_hook(
            steps=[step],
            seed_vars={"raw_value": 23.5},
        )
        assert result.success is True, result.unit_results[0].error
        psi = ctx.get_variable("Bound")
        assert isinstance(psi, LambdaPsi)
        assert psi.E.c == pytest.approx(1.0)
        assert psi.E.delta == "raw"
        assert psi.V == pytest.approx(23.5)

    @pytest.mark.asyncio
    async def test_scenario_2_inferred_certainty_propagated(self):
        """Scenario 2: lambda inferred, c=0.7 applied → 0.7 propagated."""
        step = _apply_step(
            spec_name="Inferred",
            target="raw_value",
            output_type="Inferred_e",
            certainty=0.7,
            derivation="inferred",
        )
        result, ctx = await _exec_with_ctx_hook(
            steps=[step],
            seed_vars={"raw_value": "evidence text"},
        )
        assert result.success is True
        psi = ctx.get_variable("Inferred_e")
        assert psi.E.c == pytest.approx(0.7)
        assert psi.E.delta == "inferred"
        assert psi.V == "evidence text"

    @pytest.mark.asyncio
    async def test_scenario_3_t51_violation_raises_runtime(self):
        """Scenario 3: tampered spec_snapshot (c=1.0 + inferred) → error."""
        step = _apply_step(
            spec_name="Tampered",
            target="raw_value",
            output_type="Out",
            certainty=1.0,
            derivation="inferred",  # T5.1 violation
        )
        result, _ = await _exec_with_ctx_hook(
            steps=[step],
            seed_vars={"raw_value": 1},
        )
        # The executor catches the exception and surfaces it on the
        # unit_result.error; success = False.
        assert result.success is False
        err = result.unit_results[0].error
        assert err is not None
        assert "Theorem 5.1" in str(err) or "EpistemicDegradationError" in str(err)

    @pytest.mark.asyncio
    async def test_scenario_4_target_undefined_raises(self):
        """Scenario 4: target not in unit ctx → AxonRuntimeError."""
        step = _apply_step(
            spec_name="X",
            target="doesnt_exist",
            output_type="Out",
        )
        result, _ = await _exec_with_ctx_hook(
            steps=[step],
            seed_vars={},  # no seed
        )
        assert result.success is False
        err = result.unit_results[0].error
        assert err is not None
        assert "doesnt_exist" in str(err)

    @pytest.mark.asyncio
    async def test_scenario_5_output_rebinding_succeeds(self):
        """Scenario 5: rebinding output_type — succeeds, latest wins."""
        step1 = _apply_step(
            spec_name="A",
            target="raw_value",
            output_type="Shared",
            certainty=1.0,
            derivation="raw",
        )
        step2 = _apply_step(
            spec_name="B",
            target="raw_value",
            output_type="Shared",
            certainty=0.5,
            derivation="inferred",
        )
        result, ctx = await _exec_with_ctx_hook(
            steps=[step1, step2],
            seed_vars={"raw_value": 99},
        )
        assert result.success is True
        psi = ctx.get_variable("Shared")
        # Latest binding wins.
        assert psi.spec_name == "B"
        assert psi.E.c == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_scenario_6_chained_apply(self):
        """Scenario 6: chain — apply spec1 → e1; apply spec2 to e1.V → e2."""
        step1 = _apply_step(
            spec_name="First",
            target="raw_value",
            output_type="E1",
            certainty=0.9,
            derivation="raw",
        )
        # Reference e1.V via dotted access (resolve_value_ref handles it).
        # LambdaPsi exposes V as an attribute, so "E1.V" resolves through
        # the attribute walk in resolve_value_ref.
        step2 = _apply_step(
            spec_name="Second",
            target="E1.V",
            output_type="E2",
            certainty=0.6,
            derivation="inferred",
        )
        result, ctx = await _exec_with_ctx_hook(
            steps=[step1, step2],
            seed_vars={"raw_value": "payload"},
        )
        assert result.success is True, result.unit_results[0].error
        e2 = ctx.get_variable("E2")
        assert e2.V == "payload"
        # e2 carries spec2's certainty; the formal degradation bound
        # (e2.c ≤ min(e1.c, η)) is checked by spec authoring at compile
        # time, not runtime — the runtime trusts the spec.
        assert e2.E.c == pytest.approx(0.6)

    @pytest.mark.asyncio
    async def test_scenario_7_psi_json_round_trip_in_response(self):
        """Scenario 7: ψ JSON shape — StepResult.response.content is the
        serialised ψ; downstream consumers can parse it back."""
        step = _apply_step(
            spec_name="J",
            target="raw_value",
            output_type="Out",
            ontology="measurement.x",
            certainty=0.8,
            derivation="aggregated",
        )
        result, _ = await _exec_with_ctx_hook(
            steps=[step],
            seed_vars={"raw_value": 42},
        )
        assert result.success is True
        step_result = result.unit_results[0].step_results[0]
        parsed = json.loads(step_result.response.content)
        assert parsed["T"] == "measurement.x"
        assert parsed["V"] == 42
        assert parsed["E"]["c"] == pytest.approx(0.8)
        assert parsed["E"]["delta"] == "aggregated"
        assert parsed["spec_name"] == "J"

    @pytest.mark.asyncio
    async def test_scenario_8_empty_output_type_no_binding(self):
        """Scenario 8: anonymous apply (no -> OutputType) — trace fires,
        no variable binding."""
        step = _apply_step(
            spec_name="Anon",
            target="raw_value",
            output_type="",  # anonymous
        )
        result, ctx = await _exec_with_ctx_hook(
            steps=[step],
            seed_vars={"raw_value": "x"},
        )
        assert result.success is True
        # No variable named "" should appear; raw_value is still there.
        assert ctx.has_variable("raw_value")
        assert not ctx.has_variable("")

    @pytest.mark.asyncio
    async def test_dispatcher_sets_no_model_call(self):
        """Lambda apply must never invoke the model — pure binding."""
        client = MockModelClient()
        executor = Executor(client=client)

        step = _apply_step(
            spec_name="Pure",
            target="raw_value",
            output_type="Out",
        )

        from axon.runtime import context_mgr as _ctxmod
        original = _ctxmod.ContextManager.__init__

        def hooked(self, *a, **kw):
            original(self, *a, **kw)
            self.set_variable("raw_value", 1)

        _ctxmod.ContextManager.__init__ = hooked  # type: ignore[method-assign]
        try:
            program = make_program([make_unit("test_flow", [step])])
            result = await executor.execute(program)
        finally:
            _ctxmod.ContextManager.__init__ = original  # type: ignore[method-assign]

        assert result.success is True
        assert client.call_count == 0


# ═══════════════════════════════════════════════════════════════════
#  15.d — TYPE CHECKER HARDENING
# ═══════════════════════════════════════════════════════════════════


class TestTypeCheckerHardening:
    """Compile-time guards added by Fase 15.d:

      1. Undefined `lambda_data_name` is now an error (was: silent pass).
      2. `output_type` shadowing primitive type names is rejected.
    """

    def _check(self, source: str):
        from axon.compiler.lexer import Lexer
        from axon.compiler.parser import Parser
        from axon.compiler.type_checker import TypeChecker
        return TypeChecker(Parser(Lexer(source).tokenize()).parse()).check()

    def test_undefined_lambda_name_rejected(self):
        """Apply referencing an undeclared lambda spec is now an error."""
        src = '''flow Process() {
    lambda Ghost on raw_data
}'''
        errors = self._check(src)
        assert any(
            "undefined lambda data spec" in e.message.lower()
            and "ghost" in e.message.lower()
            for e in errors
        ), f"expected undefined-spec error, got: {[e.message for e in errors]}"

    def test_wrong_kind_still_rejected(self):
        """Pre-15.d behaviour preserved — persona used as lambda spec."""
        src = '''persona Expert {
    domain: ["physics"]
}

flow Process() {
    lambda Expert on raw_data
}'''
        errors = self._check(src)
        assert any("lambda apply" in e.message for e in errors)

    @pytest.mark.parametrize("primitive", ["int", "string", "bool", "float", "any"])
    def test_output_type_primitive_shadow_rejected(self, primitive):
        """`-> int` (or any reserved primitive) is rejected."""
        src = f'''lambda S {{ ontology: "x" }}

flow Process() {{
    lambda S on raw_data -> {primitive}
}}'''
        errors = self._check(src)
        assert any(
            "shadows a reserved" in e.message
            and primitive.lower() in e.message.lower()
            for e in errors
        ), f"expected shadow error for '{primitive}', got: {[e.message for e in errors]}"

    def test_output_type_case_insensitive_shadow_rejected(self):
        """Shadow check is case-insensitive — `-> Int`, `-> STRING` rejected."""
        src = '''lambda S { ontology: "x" }

flow Process() {
    lambda S on raw_data -> Int
}'''
        errors = self._check(src)
        assert any("shadows a reserved" in e.message for e in errors)

    def test_distinct_output_type_passes(self):
        """A non-shadowing output_type compiles green."""
        src = '''lambda S { ontology: "x" }

flow Process() {
    lambda S on raw_data -> ValidatedReading
}'''
        errors = self._check(src)
        # Filter out unrelated noise — assert no shadow / undefined errors.
        relevant = [
            e for e in errors
            if "shadows a reserved" in e.message
            or "undefined lambda data spec" in e.message
        ]
        assert relevant == [], [e.message for e in errors]


# ═══════════════════════════════════════════════════════════════════
#  CROSS-STACK PARITY (Fase 15.e — both stacks vs the same golden)
# ═══════════════════════════════════════════════════════════════════


class TestCrossStackParity:
    """Both Python and Rust `build_psi` consume the same input fixture
    and must produce the same ψ JSON. The Rust mirror lives in
    `axon-rs/tests/fase15_lambda_apply_parity.rs` and reads the same
    files — drift on either side breaks both gates.
    """

    _PARITY_DIR = "axon-rs/tests/parity"

    def _read_json(self, filename: str):
        from pathlib import Path
        path = Path(self._PARITY_DIR) / filename
        with path.open(encoding="utf-8") as f:
            return json.load(f)

    def test_python_psi_matches_golden(self):
        spec = self._read_json("fase15_lambda_apply.spec.json")
        target = self._read_json("fase15_lambda_apply.target.json")
        golden = self._read_json("fase15_lambda_apply.golden.json")

        psi = build_psi(spec_snapshot=spec, target_value=target)
        psi_dict = psi.to_dict()

        # JSON normalisation — read+write through json so float reprs
        # and key ordering are canonical on both sides.
        psi_canon = json.loads(json.dumps(psi_dict))
        assert psi_canon == golden, (
            f"Fase 15 ψ parity broke (Python):\n"
            f"--- expected (golden) ---\n{json.dumps(golden, indent=2)}\n"
            f"--- actual (python) ---\n{json.dumps(psi_canon, indent=2)}"
        )

    def test_psi_json_keys_use_formal_vocab(self):
        """Sanity check that the golden uses the formalism's keys
        (T, V, E, spec_name) rather than the handler-internal vocab."""
        golden = self._read_json("fase15_lambda_apply.golden.json")
        assert set(golden.keys()) == {"T", "V", "E", "spec_name"}
        assert set(golden["E"].keys()) == {"c", "tau_start", "tau_end", "rho", "delta"}

