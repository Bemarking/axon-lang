"""Fase 23 — IR + CPS lowering tests for algebraic effects.

Verifies the 23.d lowering pass: AST nodes (EffectDeclaration,
PerformExpression, HandleExpression, HandlerClause, ResumeStatement,
AbortStatement, ForwardExpression) → IR nodes (IREffectDeclaration,
IRPerform, IRHandlerFrame, IRHandlerClause, IRResume, IRAbort,
IRForward) with assigned CPS state_ids and frame_ids.

CPS lowering invariants verified here:
  • state_ids are monotonic per-flow, starting at 0
  • frame_ids are monotonic per-flow, starting at 0
  • each perform/forward gets a unique state_id
  • each handle gets a unique frame_id
  • resume/abort record the immediately-enclosing handler's frame_id
  • forward records the inner handler's source_frame_id + new state_id
  • body_states list contains the state_ids of perform sites in the
    handle's `in { body }` block (not in clause bodies)
  • per-flow scoping: separate flows get fresh counters

These IR shape invariants are the contract the Rust runtime depends
on (D6) — `(flow_name, state_id)` is the canonical FSM coordinate.
A drift gate in 23.h verifies the Python frontend emits exactly the
opcodes the Rust runtime consumes.
"""

from __future__ import annotations

import pytest

from axon.compiler.ast_nodes import ProgramNode
from axon.compiler.ir_generator import IRGenerator
from axon.compiler.ir_nodes import (
    IRAbort,
    IREffectDeclaration,
    IREffectOperation,
    IRForward,
    IRFlow,
    IRHandlerClause,
    IRHandlerFrame,
    IRPerform,
    IRProgram,
    IRResume,
    IRStep,
)
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser


# ──────────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────────


def _ast(source: str) -> ProgramNode:
    return Parser(Lexer(source).tokenize()).parse()


def _ir(source: str) -> IRProgram:
    return IRGenerator().generate(_ast(source))


def _flow(ir: IRProgram, name: str) -> IRFlow:
    for f in ir.flows:
        if f.name == name:
            return f
    raise AssertionError(f"flow '{name}' not in IR")


def _step_body(ir: IRProgram, flow_name: str, step_idx: int = 0) -> tuple:
    flow = _flow(ir, flow_name)
    step = flow.steps[step_idx]
    assert isinstance(step, IRStep)
    return step.body


# ──────────────────────────────────────────────────────────────────────
#  TestEffectDeclarationLowering
# ──────────────────────────────────────────────────────────────────────


class TestEffectDeclarationLowering:
    """`effect Name { ops... }` → IREffectDeclaration."""

    def test_effect_appears_in_ir_program_effects_field(self) -> None:
        ir = _ir("effect SSE { Emit(t: String) -> Unit }")
        assert len(ir.effects) == 1
        eff = ir.effects[0]
        assert isinstance(eff, IREffectDeclaration)
        assert eff.name == "SSE"

    def test_operation_lowers_with_param_names_and_types(self) -> None:
        ir = _ir(
            "effect E { Op(x: String, y: Integer) -> Boolean }"
        )
        op = ir.effects[0].operations[0]
        assert isinstance(op, IREffectOperation)
        assert op.name == "Op"
        assert op.parameter_names == ("x", "y")
        assert op.parameter_types == ("String", "Integer")
        assert op.return_type == "Boolean"

    def test_zero_arg_operation_has_empty_param_tuples(self) -> None:
        ir = _ir("effect E { Done() -> Never }")
        op = ir.effects[0].operations[0]
        assert op.parameter_names == ()
        assert op.parameter_types == ()
        assert op.return_type == "Never"

    def test_d1_type_parameters_preserved(self) -> None:
        """D1 — operation polymorphism survives lowering."""
        ir = _ir("effect Channel { Send<T>(value: T) -> Unit }")
        op = ir.effects[0].operations[0]
        assert op.type_parameters == ("T",)
        # The Rust runtime monomorphises at perform-site dispatch.

    def test_multi_typevar_operation(self) -> None:
        ir = _ir("effect Mapper { Map<A, B>(value: A, key: B) -> B }")
        op = ir.effects[0].operations[0]
        assert op.type_parameters == ("A", "B")

    def test_multiple_operations_preserve_order(self) -> None:
        ir = _ir(
            "effect SSE {\n"
            "    Emit(t: String) -> Unit\n"
            "    Done() -> Never\n"
            "}"
        )
        names = tuple(op.name for op in ir.effects[0].operations)
        assert names == ("Emit", "Done")

    def test_two_effects_both_in_ir(self) -> None:
        ir = _ir(
            "effect E1 { Op() -> Unit }\n"
            "effect E2 { Op() -> Unit }\n"
        )
        names = sorted(e.name for e in ir.effects)
        assert names == ["E1", "E2"]

    def test_effect_carries_source_position(self) -> None:
        ir = _ir("\n\n  effect SSE { Emit(t: String) -> Unit }")
        eff = ir.effects[0]
        assert eff.source_line == 3
        assert eff.source_column == 3


# ──────────────────────────────────────────────────────────────────────
#  TestPerformLowering — state_id assignment
# ──────────────────────────────────────────────────────────────────────


class TestPerformLowering:
    """`perform Effect.Op(args)` → IRPerform with monotonic state_id."""

    def _handle(self, body: str) -> IRHandlerFrame:
        ir = _ir(
            "effect E {\n"
            "    Op() -> Unit\n"
            "    Op2() -> Unit\n"
            "    Op3() -> Unit\n"
            "}\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E {\n"
            "      Op() -> { resume }\n"
            "      Op2() -> { resume }\n"
            "      Op3() -> { resume }\n"
            "    } in {\n"
            f"      {body}\n"
            "    }\n"
            "  }\n"
            "}"
        )
        return _step_body(ir, "F")[0]

    def test_perform_emits_irperform_with_state_id_zero(self) -> None:
        handle = self._handle("perform E.Op()")
        node = handle.body[0]
        assert isinstance(node, IRPerform)
        assert node.state_id == 0
        assert node.effect_name == "E"
        assert node.operation_name == "Op"

    def test_two_performs_get_monotonic_state_ids(self) -> None:
        handle = self._handle(
            "perform E.Op()\n      perform E.Op2()"
        )
        sids = tuple(n.state_id for n in handle.body)
        assert sids == (0, 1)

    def test_three_performs_get_monotonic_state_ids(self) -> None:
        handle = self._handle(
            "perform E.Op()\n      perform E.Op2()\n      perform E.Op3()"
        )
        sids = tuple(n.state_id for n in handle.body)
        assert sids == (0, 1, 2)

    def test_resume_label_is_per_perform(self) -> None:
        handle = self._handle("perform E.Op()")
        node = handle.body[0]
        assert node.resume_label == "resume_E_Op_0"

    def test_resume_label_includes_state_id(self) -> None:
        handle = self._handle(
            "perform E.Op()\n      perform E.Op2()"
        )
        labels = tuple(n.resume_label for n in handle.body)
        assert labels == ("resume_E_Op_0", "resume_E_Op2_1")

    def test_perform_arguments_preserved(self) -> None:
        ir = _ir(
            "effect E { Op(x: String, y: Integer) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op(x, y) -> { resume } } in {\n"
            "      perform E.Op(a, b)\n"
            "    }\n"
            "  }\n"
            "}"
        )
        handle = _step_body(ir, "F")[0]
        node = handle.body[0]
        assert node.arguments == ("a", "b")


# ──────────────────────────────────────────────────────────────────────
#  TestHandleLowering — frame_id assignment + body_states
# ──────────────────────────────────────────────────────────────────────


class TestHandleLowering:
    """`handle E { ... } in { ... }` → IRHandlerFrame with frame_id."""

    def test_simple_handle_gets_frame_id_zero(self) -> None:
        ir = _ir(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { resume } } in { perform E.Op() }\n"
            "  }\n"
            "}"
        )
        handle = _step_body(ir, "F")[0]
        assert isinstance(handle, IRHandlerFrame)
        assert handle.frame_id == 0

    def test_handle_records_effect_names(self) -> None:
        ir = _ir(
            "effect E1 { Op() -> Unit }\n"
            "effect E2 { Op2() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E1, E2 {\n"
            "      Op() -> { resume }\n"
            "      Op2() -> { resume }\n"
            "    } in {\n"
            "      perform E1.Op()\n"
            "      perform E2.Op2()\n"
            "    }\n"
            "  }\n"
            "}"
        )
        handle = _step_body(ir, "F")[0]
        assert handle.effect_names == ("E1", "E2")

    def test_handle_body_states_lists_inner_perform_state_ids(self) -> None:
        """Each perform inside the body contributes its state_id to body_states."""
        ir = _ir(
            "effect E {\n"
            "    A() -> Unit\n"
            "    B() -> Unit\n"
            "}\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E {\n"
            "      A() -> { resume }\n"
            "      B() -> { resume }\n"
            "    } in {\n"
            "      perform E.A()\n"
            "      perform E.B()\n"
            "    }\n"
            "  }\n"
            "}"
        )
        handle = _step_body(ir, "F")[0]
        # Both inner performs land in body_states.
        assert handle.body_states == (0, 1)

    def test_nested_handles_get_distinct_frame_ids(self) -> None:
        ir = _ir(
            "effect E1 { Op() -> Unit }\n"
            "effect E2 { Op2() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E1 { Op() -> { resume } } in {\n"
            "      handle E2 { Op2() -> { resume } } in {\n"
            "        perform E2.Op2()\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        outer = _step_body(ir, "F")[0]
        inner = outer.body[0]
        assert isinstance(outer, IRHandlerFrame)
        assert isinstance(inner, IRHandlerFrame)
        assert outer.frame_id == 0
        assert inner.frame_id == 1
        # Different effect lists — different scopes.
        assert outer.effect_names == ("E1",)
        assert inner.effect_names == ("E2",)

    def test_handle_clauses_preserve_operation_names(self) -> None:
        ir = _ir(
            "effect E {\n"
            "    A() -> Unit\n"
            "    B() -> Unit\n"
            "}\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E {\n"
            "      A() -> { resume }\n"
            "      B() -> { abort }\n"
            "    } in { perform E.A() }\n"
            "  }\n"
            "}"
        )
        handle = _step_body(ir, "F")[0]
        op_names = tuple(c.operation_name for c in handle.clauses)
        assert op_names == ("A", "B")
        for clause in handle.clauses:
            assert isinstance(clause, IRHandlerClause)

    def test_handler_clause_parameter_names_preserved(self) -> None:
        ir = _ir(
            "effect E { Op(x: String, y: Integer) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op(x, y) -> { resume } } in {\n"
            "      perform E.Op(a, b)\n"
            "    }\n"
            "  }\n"
            "}"
        )
        handle = _step_body(ir, "F")[0]
        assert handle.clauses[0].parameter_names == ("x", "y")


# ──────────────────────────────────────────────────────────────────────
#  TestResumeAbortLowering — frame_id linkage
# ──────────────────────────────────────────────────────────────────────


class TestResumeAbortLowering:
    """`resume`/`abort` → IRResume/IRAbort with enclosing frame_id."""

    def test_resume_records_enclosing_frame_id(self) -> None:
        ir = _ir(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { resume } } in { perform E.Op() }\n"
            "  }\n"
            "}"
        )
        handle = _step_body(ir, "F")[0]
        resume = handle.clauses[0].body[0]
        assert isinstance(resume, IRResume)
        assert resume.frame_id == handle.frame_id == 0

    def test_resume_with_value_preserves_value_expr(self) -> None:
        ir = _ir(
            "effect E { Op() -> String }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { resume(buffer) } } in {\n"
            "      perform E.Op()\n"
            "    }\n"
            "  }\n"
            "}"
        )
        handle = _step_body(ir, "F")[0]
        resume = handle.clauses[0].body[0]
        assert resume.value_expr == "buffer"

    def test_abort_records_enclosing_frame_id(self) -> None:
        ir = _ir(
            "effect E { Op() -> Never }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { abort } } in { perform E.Op() }\n"
            "  }\n"
            "}"
        )
        handle = _step_body(ir, "F")[0]
        abort = handle.clauses[0].body[0]
        assert isinstance(abort, IRAbort)
        assert abort.frame_id == 0

    def test_abort_with_value(self) -> None:
        ir = _ir(
            "effect E { Op() -> Never }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { abort(reason) } } in {\n"
            "      perform E.Op()\n"
            "    }\n"
            "  }\n"
            "}"
        )
        handle = _step_body(ir, "F")[0]
        abort = handle.clauses[0].body[0]
        assert abort.value_expr == "reason"

    def test_inner_resume_targets_inner_frame_not_outer(self) -> None:
        """A resume inside a nested handler targets the *innermost* handler."""
        ir = _ir(
            "effect E1 { Op() -> Unit }\n"
            "effect E2 { Op2() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E1 { Op() -> { resume } } in {\n"
            "      handle E2 { Op2() -> { resume } } in {\n"
            "        perform E2.Op2()\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        outer = _step_body(ir, "F")[0]
        inner = outer.body[0]
        outer_resume = outer.clauses[0].body[0]
        inner_resume = inner.clauses[0].body[0]
        assert outer_resume.frame_id == outer.frame_id == 0
        assert inner_resume.frame_id == inner.frame_id == 1


# ──────────────────────────────────────────────────────────────────────
#  TestForwardLowering — D12 propagation linkage
# ──────────────────────────────────────────────────────────────────────


class TestForwardLowering:
    """D12 — `forward` → IRForward with source_frame_id + new state_id."""

    def test_forward_records_source_frame_id(self) -> None:
        ir = _ir(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { resume } } in {\n"
            "      handle E { Op() -> { forward E.Op() } } in {\n"
            "        perform E.Op()\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        outer = _step_body(ir, "F")[0]
        inner = outer.body[0]
        forward = inner.clauses[0].body[0]
        assert isinstance(forward, IRForward)
        # forward escapes the *inner* handler — its source is inner.frame_id.
        assert forward.source_frame_id == inner.frame_id == 1

    def test_forward_gets_fresh_state_id(self) -> None:
        ir = _ir(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { resume } } in {\n"
            "      handle E { Op() -> { forward E.Op() } } in {\n"
            "        perform E.Op()\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        outer = _step_body(ir, "F")[0]
        inner = outer.body[0]
        forward = inner.clauses[0].body[0]
        # Inner body's perform got state_id=0; the forward gets state_id=1.
        assert forward.state_id == 1
        assert forward.resume_label == "forward_E_Op_1"

    def test_forward_arguments_preserved(self) -> None:
        ir = _ir(
            "effect E { Op(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op(x) -> { resume } } in {\n"
            "      handle E { Op(x) -> { forward E.Op(x) } } in {\n"
            "        perform E.Op(t)\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        outer = _step_body(ir, "F")[0]
        inner = outer.body[0]
        forward = inner.clauses[0].body[0]
        assert forward.arguments == ("x",)


# ──────────────────────────────────────────────────────────────────────
#  TestPerFlowScoping — counters reset between flows
# ──────────────────────────────────────────────────────────────────────


class TestPerFlowScoping:
    """state_id and frame_id counters reset per flow."""

    def test_two_flows_each_start_at_state_id_zero(self) -> None:
        ir = _ir(
            "effect E { Op() -> Unit }\n"
            "flow F1() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { resume } } in { perform E.Op() }\n"
            "  }\n"
            "}\n"
            "flow F2() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { resume } } in { perform E.Op() }\n"
            "  }\n"
            "}"
        )
        h1 = _step_body(ir, "F1")[0]
        h2 = _step_body(ir, "F2")[0]
        assert h1.frame_id == 0
        assert h2.frame_id == 0
        assert h1.body[0].state_id == 0
        assert h2.body[0].state_id == 0

    def test_two_handles_in_same_flow_get_distinct_frame_ids(self) -> None:
        ir = _ir(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S1 {\n"
            "    handle E { Op() -> { resume } } in { perform E.Op() }\n"
            "  }\n"
            "  step S2 {\n"
            "    handle E { Op() -> { resume } } in { perform E.Op() }\n"
            "  }\n"
            "}"
        )
        flow = _flow(ir, "F")
        # Topologically sorted — both steps end up in `steps`.
        handles = []
        for st in flow.steps:
            if isinstance(st, IRStep):
                for child in st.body:
                    if isinstance(child, IRHandlerFrame):
                        handles.append(child)
        assert len(handles) == 2
        # Both handles are in the same flow → distinct frame_ids.
        assert {h.frame_id for h in handles} == {0, 1}


# ──────────────────────────────────────────────────────────────────────
#  TestSerialization — IR nodes serialise to dict
# ──────────────────────────────────────────────────────────────────────


class TestSerialization:
    """IR nodes serialise via to_dict() for cross-stack contract."""

    def test_irperform_to_dict(self) -> None:
        ir = _ir(
            "effect E { Op(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op(x) -> { resume } } in {\n"
            "      perform E.Op(t)\n"
            "    }\n"
            "  }\n"
            "}"
        )
        handle = _step_body(ir, "F")[0]
        perform_dict = handle.body[0].to_dict()
        assert perform_dict["node_type"] == "perform"
        assert perform_dict["effect_name"] == "E"
        assert perform_dict["operation_name"] == "Op"
        assert perform_dict["state_id"] == 0
        assert "resume_label" in perform_dict

    def test_irhandlerframe_to_dict_includes_body_states(self) -> None:
        ir = _ir(
            "effect E {\n"
            "    A() -> Unit\n"
            "    B() -> Unit\n"
            "}\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E {\n"
            "      A() -> { resume }\n"
            "      B() -> { resume }\n"
            "    } in {\n"
            "      perform E.A()\n"
            "      perform E.B()\n"
            "    }\n"
            "  }\n"
            "}"
        )
        handle = _step_body(ir, "F")[0]
        d = handle.to_dict()
        assert d["node_type"] == "handler_frame"
        assert d["frame_id"] == 0
        assert d["body_states"] == (0, 1)

    def test_irprogram_effects_field_serialises(self) -> None:
        ir = _ir("effect SSE { Emit(t: String) -> Unit }")
        d = ir.to_dict()
        assert "effects" in d
        assert len(d["effects"]) == 1
        assert d["effects"][0]["node_type"] == "effect_declaration"
        assert d["effects"][0]["name"] == "SSE"

    def test_ireffectoperation_serialises_type_parameters(self) -> None:
        """D1 — type_parameters survive JSON serialization."""
        ir = _ir("effect Channel { Send<T>(value: T) -> Unit }")
        op_dict = ir.effects[0].operations[0].to_dict()
        assert op_dict["type_parameters"] == ("T",)
        assert op_dict["parameter_names"] == ("value",)
        assert op_dict["parameter_types"] == ("T",)

    def test_irresume_serialises_with_frame_id(self) -> None:
        ir = _ir(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { resume(value) } } in {\n"
            "      perform E.Op()\n"
            "    }\n"
            "  }\n"
            "}"
        )
        handle = _step_body(ir, "F")[0]
        resume_dict = handle.clauses[0].body[0].to_dict()
        assert resume_dict["node_type"] == "resume"
        assert resume_dict["frame_id"] == 0
        assert resume_dict["value_expr"] == "value"


# ──────────────────────────────────────────────────────────────────────
#  TestIntegration — end-to-end paper §1-§6 example
# ──────────────────────────────────────────────────────────────────────


class TestIntegration:
    """End-to-end CPS lowering on the canonical paper example."""

    def test_paper_canonical_sse_example_lowers_completely(self) -> None:
        """The exact shape from `docs/algebraic_effects_streaming.md`."""
        ir = _ir(
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
        # Effect declaration present.
        assert len(ir.effects) == 1
        eff = ir.effects[0]
        assert eff.name == "SSE"
        assert tuple(o.name for o in eff.operations) == ("Emit", "Done")

        # Flow + handler frame structure.
        handle = _step_body(ir, "Stream")[0]
        assert isinstance(handle, IRHandlerFrame)
        assert handle.frame_id == 0
        assert handle.effect_names == ("SSE",)

        # Two perform sites, monotonic state IDs in body_states.
        assert handle.body_states == (0, 1)
        emit_perf = handle.body[0]
        done_perf = handle.body[1]
        assert isinstance(emit_perf, IRPerform)
        assert isinstance(done_perf, IRPerform)
        assert emit_perf.state_id == 0
        assert done_perf.state_id == 1

        # Both clauses present, discharging via resume + abort.
        assert isinstance(handle.clauses[0].body[0], IRResume)
        assert isinstance(handle.clauses[1].body[0], IRAbort)
        # Both reference the outer (and only) frame.
        assert handle.clauses[0].body[0].frame_id == 0
        assert handle.clauses[1].body[0].frame_id == 0

    def test_decorator_pattern_with_forward_lowers_correctly(self) -> None:
        """D12 — middleware-style decorator chain compiles to correct
        frame_id linkage. Inner clause forwards to outer; outer resumes."""
        ir = _ir(
            "effect SSE { Emit(t: String) -> Unit }\n"
            "flow Stream() -> Unit {\n"
            "  step Loop {\n"
            "    handle SSE { Emit(t) -> { resume } } in {\n"
            "      handle SSE { Emit(t) -> { forward SSE.Emit(t) } } in {\n"
            "        perform SSE.Emit(token)\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "}"
        )
        outer = _step_body(ir, "Stream")[0]
        inner = outer.body[0]
        # Two distinct frame IDs.
        assert outer.frame_id == 0
        assert inner.frame_id == 1
        # Forward escapes inner → records source_frame_id=1.
        forward = inner.clauses[0].body[0]
        assert isinstance(forward, IRForward)
        assert forward.source_frame_id == 1
        # Outer's resume targets outer.
        outer_resume = outer.clauses[0].body[0]
        assert outer_resume.frame_id == 0
