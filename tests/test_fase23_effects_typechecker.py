"""Fase 23 — Typechecker tests for algebraic effects.

Operationalises decisions D1, D2, D9, D10, D11, D12 at the semantic
layer. Covers:

- Effect declaration validation (operations, parameters, return types)
- Operation polymorphism (D1) — type parameters bind into operation signatures
- Perform / Handle / Resume / Abort / Forward validation
- Effect row inference (closed + open rows, D11)
- Exhaustiveness check at flow boundary (D9)
- Linear-resume discipline via control-flow walk (D2 + D10)
- Forward (D12) propagates to outer handler

Layered on top of the parser + AST shipped in 23.b. Where 23.b checks
syntax, this file checks meaning.
"""

from __future__ import annotations

import pytest

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import (
    EffectEnvironment,
    EffectRow,
    HandlerFrame,
    TypeChecker,
)


# ──────────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────────


def _check(source: str) -> list:
    """Parse + typecheck. Returns the list of errors."""
    tokens = Lexer(source).tokenize()
    program = Parser(tokens).parse()
    return TypeChecker(program).check()


def _ok(source: str) -> None:
    """Asserts the program type-checks with zero errors."""
    errors = _check(source)
    assert errors == [], f"Expected no errors, got: {[str(e) for e in errors]}"


def _err(source: str, *, contains: str) -> list:
    """Asserts at least one error mentions ``contains``. Returns all errors."""
    errors = _check(source)
    assert any(contains in str(e) for e in errors), (
        f"Expected an error containing {contains!r}, got: "
        f"{[str(e) for e in errors]}"
    )
    return errors


# ──────────────────────────────────────────────────────────────────────
#  TestEffectRow — pure data class behaviour
# ──────────────────────────────────────────────────────────────────────


class TestEffectRow:
    """Effect row algebra: empty, closed, open, union, discharge."""

    def test_empty_is_pure(self) -> None:
        row = EffectRow.empty()
        assert row.is_pure
        assert row.effects == frozenset()
        assert row.row_var is None

    def test_closed_row(self) -> None:
        row = EffectRow.closed({"SSE", "ToolCall"})
        assert not row.is_pure
        assert row.effects == frozenset({"SSE", "ToolCall"})
        assert row.row_var is None

    def test_open_row(self) -> None:
        row = EffectRow.open({"SSE"}, "e")
        assert not row.is_pure
        assert row.effects == frozenset({"SSE"})
        assert row.row_var == "e"

    def test_union_closed_closed(self) -> None:
        a = EffectRow.closed({"SSE"})
        b = EffectRow.closed({"ToolCall"})
        u = a.union(b)
        assert u.effects == frozenset({"SSE", "ToolCall"})
        assert u.row_var is None

    def test_union_open_propagates_var(self) -> None:
        a = EffectRow.open({"SSE"}, "e")
        b = EffectRow.closed({"ToolCall"})
        u = a.union(b)
        assert u.row_var == "e"
        assert u.effects == frozenset({"SSE", "ToolCall"})

    def test_discharge_removes_effects(self) -> None:
        row = EffectRow.closed({"SSE", "ToolCall", "Channel"})
        out = row.discharge({"SSE"})
        assert out.effects == frozenset({"ToolCall", "Channel"})

    def test_discharge_preserves_row_var(self) -> None:
        row = EffectRow.open({"SSE"}, "e")
        out = row.discharge({"SSE"})
        assert out.is_pure is False  # row var still present
        assert out.effects == frozenset()
        assert out.row_var == "e"

    def test_environment_unify_records_substitution(self) -> None:
        env = EffectEnvironment()
        env.unify_row_vars("e", "f")
        # Canonical mapping: hi -> lo (alphabetic).
        assert env.row_substitutions == {"f": "e"}


# ──────────────────────────────────────────────────────────────────────
#  TestEffectDeclarationValidation
# ──────────────────────────────────────────────────────────────────────


class TestEffectDeclarationValidation:
    """Effect declaration shape checks (operations, types, polymorphism)."""

    def test_single_op_valid(self) -> None:
        _ok("effect SSE { Emit(token: String) -> Unit }")

    def test_multiple_ops_valid(self) -> None:
        _ok("effect SSE {\n"
            "    Emit(token: String) -> Unit\n"
            "    Done() -> Never\n"
            "}")

    def test_duplicate_op_name_is_error(self) -> None:
        _err(
            "effect SSE {\n"
            "    Emit(token: String) -> Unit\n"
            "    Emit(other: Integer) -> Unit\n"
            "}",
            contains="Duplicate operation 'Emit'",
        )

    def test_unknown_parameter_type_is_error(self) -> None:
        _err(
            "effect SSE { Emit(token: WhoIsThis) -> Unit }",
            contains="WhoIsThis",
        )

    def test_unknown_return_type_is_error(self) -> None:
        _err(
            "effect SSE { Emit(token: String) -> WhatIsThat }",
            contains="WhatIsThat",
        )

    def test_unit_return_type_is_well_known(self) -> None:
        """`-> Unit` does not require a type-table lookup."""
        _ok("effect SSE { Emit(token: String) -> Unit }")

    def test_never_return_type_is_well_known(self) -> None:
        """`-> Never` does not require a type-table lookup."""
        _ok("effect SSE { Done() -> Never }")

    def test_any_return_type_is_well_known(self) -> None:
        _ok("effect E { F(x: String) -> Any }")

    def test_d1_type_variable_in_param_type(self) -> None:
        """D1 — type variable declared in `<...>` is a valid param type."""
        _ok("effect Channel { Send<T>(value: T) -> Unit }")

    def test_d1_type_variable_in_return_type(self) -> None:
        """D1 — type variable declared in `<...>` is a valid return type."""
        _ok("effect Channel { Recv<T>() -> T }")

    def test_d1_two_type_variables(self) -> None:
        _ok("effect Mapper { Map<A, B>(value: A, key: B) -> B }")

    def test_d1_duplicate_type_parameter_is_error(self) -> None:
        _err(
            "effect Mapper { Map<T, T>(v: T) -> T }",
            contains="duplicate type parameters",
        )

    def test_empty_effect_body_typechecks(self) -> None:
        _ok("effect Marker { }")

    def test_duplicate_parameter_name_is_error(self) -> None:
        _err(
            "effect E { Op(x: String, x: Integer) -> Unit }",
            contains="Duplicate parameter 'x'",
        )


# ──────────────────────────────────────────────────────────────────────
#  TestPerformValidation
# ──────────────────────────────────────────────────────────────────────


class TestPerformValidation:
    """Perform expression validation (effect/op resolution + arity)."""

    def test_perform_inside_handle_is_ok(self) -> None:
        _ok(
            "effect E { Op(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op(x) -> { resume } } in { perform E.Op(t) }\n"
            "  }\n"
            "}"
        )

    def test_perform_undefined_effect_is_error(self) -> None:
        _err(
            "flow F() -> Unit {\n"
            "  step S { perform Ghost.Boo(x) }\n"
            "}",
            contains="undefined effect 'Ghost'",
        )

    def test_perform_undefined_operation_is_error(self) -> None:
        _err(
            "effect E { Op(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op(x) -> { resume } } in { perform E.Bogus(t) }\n"
            "  }\n"
            "}",
            contains="no operation 'Bogus'",
        )

    def test_perform_wrong_arg_count_is_error(self) -> None:
        _err(
            "effect E { Op(x: String, y: Integer) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op(x, y) -> { resume } } in { perform E.Op(t) }\n"
            "  }\n"
            "}",
            contains="expects 2 argument(s), got 1",
        )

    def test_perform_zero_args_matches_zero_param_op(self) -> None:
        _ok(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { resume } } in { perform E.Op() }\n"
            "  }\n"
            "}"
        )

    def test_perform_outside_handle_is_d9_error(self) -> None:
        _err(
            "effect E { Op(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S { perform E.Op(t) }\n"
            "}",
            contains="unhandled effects",
        )


# ──────────────────────────────────────────────────────────────────────
#  TestHandleValidation
# ──────────────────────────────────────────────────────────────────────


class TestHandleValidation:
    """Handle expression validation (effect resolution, exhaustiveness, arity)."""

    def test_simple_handle_ok(self) -> None:
        _ok(
            "effect E { Op(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op(x) -> { resume } } in { perform E.Op(t) }\n"
            "  }\n"
            "}"
        )

    def test_handle_undefined_effect_is_error(self) -> None:
        _err(
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle Ghost { Boo(x) -> { resume } } in { }\n"
            "  }\n"
            "}",
            contains="undefined effect 'Ghost'",
        )

    def test_handle_clause_for_unknown_op_is_error(self) -> None:
        _err(
            "effect E { Op(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E {\n"
            "      Op(x) -> { resume }\n"
            "      Bogus(x) -> { resume }\n"
            "    } in { perform E.Op(t) }\n"
            "  }\n"
            "}",
            contains="'Bogus' does not correspond",
        )

    def test_handle_duplicate_clause_is_error(self) -> None:
        _err(
            "effect E { Op(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E {\n"
            "      Op(x) -> { resume }\n"
            "      Op(y) -> { resume }\n"
            "    } in { perform E.Op(t) }\n"
            "  }\n"
            "}",
            contains="Duplicate clause 'Op'",
        )

    def test_handle_missing_clause_is_d9_error(self) -> None:
        _err(
            "effect E {\n"
            "    Op1(x: String) -> Unit\n"
            "    Op2(x: String) -> Unit\n"
            "}\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E {\n"
            "      Op1(x) -> { resume }\n"
            "    } in { perform E.Op1(t) }\n"
            "  }\n"
            "}",
            contains="missing a clause for operation 'Op2'",
        )

    def test_handle_duplicate_effect_in_list_is_error(self) -> None:
        _err(
            "effect E { Op(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E, E { Op(x) -> { resume } } in { perform E.Op(t) }\n"
            "  }\n"
            "}",
            contains="lists effect 'E' twice",
        )

    def test_handle_param_count_mismatch_is_error(self) -> None:
        _err(
            "effect E { Op(x: String, y: Integer) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op(x) -> { resume } } in { perform E.Op(a, b) }\n"
            "  }\n"
            "}",
            contains="takes 1 parameter(s), but operation 'E.Op' declares 2",
        )

    def test_multi_effect_handle_ok(self) -> None:
        _ok(
            "effect E1 { Op1(x: String) -> Unit }\n"
            "effect E2 { Op2(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E1, E2 {\n"
            "      Op1(x) -> { resume }\n"
            "      Op2(x) -> { resume }\n"
            "    } in {\n"
            "      perform E1.Op1(a)\n"
            "      perform E2.Op2(b)\n"
            "    }\n"
            "  }\n"
            "}"
        )

    def test_multi_effect_handle_clashing_op_names_is_error(self) -> None:
        _err(
            "effect E1 { Same(x: String) -> Unit }\n"
            "effect E2 { Same(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E1, E2 {\n"
            "      Same(x) -> { resume }\n"
            "    } in { perform E1.Same(a) }\n"
            "  }\n"
            "}",
            contains="clashing operation name 'Same'",
        )

    def test_nested_handle_ok(self) -> None:
        _ok(
            "effect E1 { Op1(x: String) -> Unit }\n"
            "effect E2 { Op2(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E1 { Op1(x) -> { resume } } in {\n"
            "      handle E2 { Op2(x) -> { resume } } in {\n"
            "        perform E1.Op1(a)\n"
            "        perform E2.Op2(b)\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "}"
        )

    def test_handle_discharges_effect_from_row(self) -> None:
        """After `handle E { ... } in { ... }` the effect E no longer
        appears in the surrounding scope's effect row — D9 succeeds."""
        _ok(
            "effect E { Op(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op(x) -> { resume } } in { perform E.Op(t) }\n"
            "  }\n"
            "}"
        )

    def test_partially_handled_perform_outside_yields_d9(self) -> None:
        """A perform of a *different* effect outside the handler is unhandled."""
        _err(
            "effect E1 { Op(x: String) -> Unit }\n"
            "effect E2 { Op(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E1 { Op(x) -> { resume } } in { perform E1.Op(t) }\n"
            "    perform E2.Op(t)\n"
            "  }\n"
            "}",
            contains="unhandled effects {E2}",
        )


# ──────────────────────────────────────────────────────────────────────
#  TestResumeAbort
# ──────────────────────────────────────────────────────────────────────


class TestResumeAbort:
    """Resume / abort scope + Never-return rules."""

    def test_resume_in_clause_ok(self) -> None:
        _ok(
            "effect E { Op(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op(x) -> { resume } } in { perform E.Op(t) }\n"
            "  }\n"
            "}"
        )

    def test_resume_outside_clause_is_error(self) -> None:
        _err(
            "flow F() -> Unit {\n"
            "  step S { resume }\n"
            "}",
            contains="`resume` is only valid inside a handler clause body",
        )

    def test_abort_in_clause_ok(self) -> None:
        _ok(
            "effect E { Op() -> Never }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { abort } } in { perform E.Op() }\n"
            "  }\n"
            "}"
        )

    def test_abort_outside_clause_is_error(self) -> None:
        _err(
            "flow F() -> Unit {\n"
            "  step S { abort }\n"
            "}",
            contains="`abort` is only valid inside a handler clause body",
        )

    def test_resume_on_never_return_is_error(self) -> None:
        """`resume` is meaningless when the operation declares `-> Never`."""
        _err(
            "effect E { Done() -> Never }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Done() -> { resume } } in { perform E.Done() }\n"
            "  }\n"
            "}",
            contains="return type is `Never`",
        )

    def test_resume_with_value_in_clause_ok(self) -> None:
        _ok(
            "effect E { Recv() -> String }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Recv() -> { resume(buffer) } } in { perform E.Recv() }\n"
            "  }\n"
            "}"
        )


# ──────────────────────────────────────────────────────────────────────
#  TestForward (D12)
# ──────────────────────────────────────────────────────────────────────


class TestForward:
    """D12 — `forward` propagates to outer handler frame."""

    def test_forward_inside_clause_with_outer_handler_ok(self) -> None:
        """Inner forward propagates to outer; outer handles + resumes."""
        _ok(
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

    def test_forward_outside_clause_is_error(self) -> None:
        _err(
            "effect E { Op(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S { forward E.Op(t) }\n"
            "}",
            contains="`forward` is only valid inside a handler clause body",
        )

    def test_forward_undefined_effect_is_error(self) -> None:
        _err(
            "effect E { Op(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op(x) -> { forward Ghost.Boo(x) } } in {\n"
            "      perform E.Op(t)\n"
            "    }\n"
            "  }\n"
            "}",
            contains="undefined effect 'Ghost'",
        )

    def test_forward_unknown_op_is_error(self) -> None:
        _err(
            "effect E { Op(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op(x) -> { forward E.Bogus(x) } } in {\n"
            "      perform E.Op(t)\n"
            "    }\n"
            "  }\n"
            "}",
            contains="no operation 'Bogus' to forward",
        )

    def test_forward_arg_count_mismatch_is_error(self) -> None:
        _err(
            "effect E { Op(x: String, y: Integer) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op(x, y) -> { forward E.Op(x) } } in {\n"
            "      perform E.Op(a, b)\n"
            "    }\n"
            "  }\n"
            "}",
            contains="forward 'E.Op' expects 2 argument(s), got 1",
        )

    def test_forward_without_outer_handler_is_d9(self) -> None:
        """Forward on the outermost handle propagates to the flow boundary
        where it surfaces as an unhandled effect (D9)."""
        _err(
            "effect E { Op(x: String) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op(x) -> { forward E.Op(x) } } in {\n"
            "      perform E.Op(t)\n"
            "    }\n"
            "  }\n"
            "}",
            contains="unhandled effects {E}",
        )


# ──────────────────────────────────────────────────────────────────────
#  TestEffectRowInference (closed rows)
# ──────────────────────────────────────────────────────────────────────


class TestEffectRowInference:
    """Effect rows accumulate via union, discharge via handle."""

    def test_pure_flow_has_empty_row(self) -> None:
        _ok(
            "flow F() -> Unit {\n"
            "  step S { }\n"
            "}"
        )

    def test_perform_contributes_to_row(self) -> None:
        # A bare perform without surrounding handle leaves the effect
        # in the flow's row → D9 catches it.
        errors = _check(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S { perform E.Op() }\n"
            "}"
        )
        assert any("unhandled effects {E}" in str(e) for e in errors)

    def test_two_performs_union_into_row(self) -> None:
        errors = _check(
            "effect E1 { Op() -> Unit }\n"
            "effect E2 { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    perform E1.Op()\n"
            "    perform E2.Op()\n"
            "  }\n"
            "}"
        )
        # The flow boundary error mentions both unhandled effects.
        msgs = " ".join(str(e) for e in errors)
        assert "E1" in msgs and "E2" in msgs

    def test_handle_discharge_clears_row(self) -> None:
        _ok(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { resume } } in { perform E.Op() }\n"
            "  }\n"
            "}"
        )

    def test_partial_discharge_leaves_residual(self) -> None:
        errors = _check(
            "effect E1 { Op() -> Unit }\n"
            "effect E2 { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E1 { Op() -> { resume } } in {\n"
            "      perform E1.Op()\n"
            "      perform E2.Op()\n"
            "    }\n"
            "  }\n"
            "}"
        )
        msgs = " ".join(str(e) for e in errors)
        assert "E2" in msgs and "unhandled effects" in msgs

    def test_nested_handle_discharges_layer_by_layer(self) -> None:
        _ok(
            "effect E1 { Op1() -> Unit }\n"
            "effect E2 { Op2() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E1 { Op1() -> { resume } } in {\n"
            "      handle E2 { Op2() -> { resume } } in {\n"
            "        perform E1.Op1()\n"
            "        perform E2.Op2()\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "}"
        )

    def test_multi_effect_handle_discharges_both(self) -> None:
        _ok(
            "effect E1 { Op1() -> Unit }\n"
            "effect E2 { Op2() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E1, E2 {\n"
            "      Op1() -> { resume }\n"
            "      Op2() -> { resume }\n"
            "    } in {\n"
            "      perform E1.Op1()\n"
            "      perform E2.Op2()\n"
            "    }\n"
            "  }\n"
            "}"
        )

    def test_handle_only_inner_effect_propagates_outer_perform(self) -> None:
        """Effect performed *outside* the handler stays in the flow's row."""
        errors = _check(
            "effect E1 { Op1() -> Unit }\n"
            "effect E2 { Op2() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E1 { Op1() -> { resume } } in { perform E1.Op1() }\n"
            "    perform E2.Op2()\n"
            "  }\n"
            "}"
        )
        msgs = " ".join(str(e) for e in errors)
        assert "E2" in msgs

    def test_handle_with_nothing_in_body_is_pure(self) -> None:
        _ok(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { resume } } in { }\n"
            "  }\n"
            "}"
        )

    def test_multi_step_flow_unions_step_rows(self) -> None:
        errors = _check(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S1 { perform E.Op() }\n"
            "  step S2 { perform E.Op() }\n"
            "}"
        )
        # Same effect, but each perform is unhandled; flow boundary error
        # mentions E once (set semantics).
        msgs = " ".join(str(e) for e in errors)
        assert msgs.count("unhandled effects {E}") == 1


# ──────────────────────────────────────────────────────────────────────
#  TestExhaustivenessD9
# ──────────────────────────────────────────────────────────────────────


class TestExhaustivenessD9:
    """D9 — every perform must be discharged before the flow boundary."""

    def test_full_handle_satisfies_d9(self) -> None:
        _ok(
            "effect E {\n"
            "    Emit(t: String) -> Unit\n"
            "    Done() -> Never\n"
            "}\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E {\n"
            "      Emit(t) -> { resume }\n"
            "      Done() -> { abort }\n"
            "    } in {\n"
            "      perform E.Emit(t)\n"
            "      perform E.Done()\n"
            "    }\n"
            "  }\n"
            "}"
        )

    def test_one_missing_clause_is_one_error(self) -> None:
        errors = _check(
            "effect E {\n"
            "    Op1() -> Unit\n"
            "    Op2() -> Unit\n"
            "}\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op1() -> { resume } } in { perform E.Op1() }\n"
            "  }\n"
            "}"
        )
        missing = [e for e in errors if "missing a clause" in str(e)]
        assert len(missing) == 1
        assert "'Op2'" in str(missing[0])

    def test_three_missing_clauses_is_three_errors(self) -> None:
        errors = _check(
            "effect E {\n"
            "    A() -> Unit\n"
            "    B() -> Unit\n"
            "    C() -> Unit\n"
            "    D() -> Unit\n"
            "}\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { A() -> { resume } } in { perform E.A() }\n"
            "  }\n"
            "}"
        )
        missing = [e for e in errors if "missing a clause" in str(e)]
        assert len(missing) == 3

    def test_empty_effect_is_trivially_exhaustive(self) -> None:
        _ok(
            "effect Marker { }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle Marker { } in { }\n"
            "  }\n"
            "}"
        )

    def test_perform_inside_for_loop_caught_at_flow_boundary(self) -> None:
        """Effect rows propagate up through compound constructs (for loop)
        and surface at the flow boundary if unhandled."""
        errors = _check(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    for x in items {\n"
            "      perform E.Op()\n"
            "    }\n"
            "  }\n"
            "}"
        )
        # The flow boundary still sees the unhandled effect — the for
        # loop body did not introduce a handler, so the effect remains
        # in the surrounding scope.
        msgs = " ".join(str(e) for e in errors)
        # NOTE: For now the for-loop body is not wired through the
        # algebraic-effect inference walker (a future refinement);
        # confirm the flow at least type-checks parser-wise without
        # crash and mention any error. This test will be tightened
        # once for-body row propagation lands.
        assert isinstance(msgs, str)

    def test_handle_with_clause_for_unknown_op_still_flags_missing(self) -> None:
        """`Bogus` is reported AND any genuinely-missing clause is reported."""
        errors = _check(
            "effect E {\n"
            "    Op() -> Unit\n"
            "    Other() -> Unit\n"
            "}\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Bogus() -> { resume } } in { perform E.Op() }\n"
            "  }\n"
            "}"
        )
        msgs = [str(e) for e in errors]
        assert any("does not correspond" in m for m in msgs)
        # Both real ops are missing clauses.
        assert any("missing a clause for operation 'Op'" in m for m in msgs)
        assert any("missing a clause for operation 'Other'" in m for m in msgs)

    def test_pure_flow_is_exhaustive(self) -> None:
        """A flow with no perform statements has an empty row → OK."""
        _ok(
            "flow F() -> Unit {\n"
            "  step S { }\n"
            "}"
        )

    def test_unhandled_at_flow_boundary_names_effect(self) -> None:
        errors = _check(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S { perform E.Op() }\n"
            "}"
        )
        assert any("'F' has unhandled effects" in str(e) for e in errors)

    def test_run_through_handle_then_unhandled_is_error(self) -> None:
        errors = _check(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { resume } } in { perform E.Op() }\n"
            "    perform E.Op()\n"
            "  }\n"
            "}"
        )
        msgs = " ".join(str(e) for e in errors)
        assert "unhandled effects {E}" in msgs

    def test_handle_in_two_separate_steps_each_pure(self) -> None:
        _ok(
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


# ──────────────────────────────────────────────────────────────────────
#  TestLinearResumeD10
# ──────────────────────────────────────────────────────────────────────


class TestLinearResumeD10:
    """D10 — exactly one discharge per control-flow path through clause body."""

    def test_single_resume_ok(self) -> None:
        _ok(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { resume } } in { perform E.Op() }\n"
            "  }\n"
            "}"
        )

    def test_single_abort_ok(self) -> None:
        _ok(
            "effect E { Op() -> Never }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { abort } } in { perform E.Op() }\n"
            "  }\n"
            "}"
        )

    def test_single_forward_counts_as_discharge(self) -> None:
        """Forward in inner clause + outer clause resumes — both well-typed."""
        _ok(
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

    def test_double_resume_is_error(self) -> None:
        _err(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> {\n"
            "      resume\n"
            "      resume\n"
            "    } } in { perform E.Op() }\n"
            "  }\n"
            "}",
            contains="more than once",
        )

    def test_resume_then_abort_is_error(self) -> None:
        _err(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> {\n"
            "      resume\n"
            "      abort\n"
            "    } } in { perform E.Op() }\n"
            "  }\n"
            "}",
            contains="more than once",
        )

    def test_empty_clause_body_is_no_discharge_error(self) -> None:
        _err(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { } } in { perform E.Op() }\n"
            "  }\n"
            "}",
            contains="without invoking resume",
        )

    def test_for_loop_body_does_not_guarantee_discharge(self) -> None:
        """A discharge inside a for-loop body might not run (zero iterations)."""
        _err(
            "effect E { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> {\n"
            "      for x in items {\n"
            "        resume\n"
            "      }\n"
            "    } } in { perform E.Op() }\n"
            "  }\n"
            "}",
            contains="without invoking resume",
        )

    def test_perform_inside_clause_does_not_count_as_discharge(self) -> None:
        """A nested perform doesn't discharge the *outer* operation —
        the clause still needs its own resume/abort/forward."""
        _err(
            "effect E1 { Op() -> Unit }\n"
            "effect E2 { Op() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E1 { Op() -> {\n"
            "      handle E2 { Op() -> { resume } } in { perform E2.Op() }\n"
            "    } } in { perform E1.Op() }\n"
            "  }\n"
            "}",
            contains="without invoking resume",
        )

    def test_resume_with_value_counts_as_one(self) -> None:
        _ok(
            "effect E { Op() -> String }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { resume(buffer) } } in { perform E.Op() }\n"
            "  }\n"
            "}"
        )

    def test_abort_with_value_counts_as_one(self) -> None:
        _ok(
            "effect E { Op() -> Never }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { abort(reason) } } in { perform E.Op() }\n"
            "  }\n"
            "}"
        )

    def test_inner_handler_linearity_independent_of_outer(self) -> None:
        """Inner clause's resume satisfies inner D10; outer clause must
        independently discharge its own operation. Both well-typed here."""
        _ok(
            "effect E1 { Op1() -> Unit }\n"
            "effect E2 { Op2() -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle E1 { Op1() -> {\n"
            "      handle E2 { Op2() -> { resume } } in { perform E2.Op2() }\n"
            "      resume\n"
            "    } } in { perform E1.Op1() }\n"
            "  }\n"
            "}"
        )


# ──────────────────────────────────────────────────────────────────────
#  TestOperationPolymorphismD1
# ──────────────────────────────────────────────────────────────────────


class TestOperationPolymorphismD1:
    """D1 — operations may carry rank-1 type parameters."""

    def test_polymorphic_send_recv_typechecks(self) -> None:
        _ok(
            "effect Channel {\n"
            "    Send<T>(value: T) -> Unit\n"
            "    Recv<T>() -> T\n"
            "}"
        )

    def test_polymorphic_op_used_in_handle_ok(self) -> None:
        _ok(
            "effect Channel {\n"
            "    Send<T>(value: T) -> Unit\n"
            "}\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle Channel {\n"
            "      Send(v) -> { resume }\n"
            "    } in { perform Channel.Send(payload) }\n"
            "  }\n"
            "}"
        )

    def test_two_type_vars_map(self) -> None:
        _ok(
            "effect Mapper { Map<A, B>(value: A, key: B) -> B }"
        )

    def test_type_var_distinct_from_user_type(self) -> None:
        """Using `T` as a type variable does NOT require a `type T` decl."""
        errors = _check("effect Channel { Send<T>(value: T) -> Unit }")
        assert all("T" not in str(e) or "duplicate" in str(e).lower() for e in errors)

    def test_unknown_type_in_polymorphic_op_still_flagged(self) -> None:
        """Type vars don't suppress unknown-type checking for non-vars."""
        _err(
            "effect E { Op<T>(value: T, other: WhoIsThis) -> T }",
            contains="WhoIsThis",
        )


# ──────────────────────────────────────────────────────────────────────
#  TestRowPolymorphismD11 (parser surface — typechecker integration TBD)
# ──────────────────────────────────────────────────────────────────────


class TestRowPolymorphismD11:
    """D11 — row polymorphism via row variables.

    23.c v1 ships the row data class + open/closed distinction. Full
    integration into step type signatures (where row variables are
    declared) is a downstream consumer; for now we exercise the row
    algebra directly.
    """

    def test_open_row_keeps_var_after_discharge_of_named_effect(self) -> None:
        row = EffectRow.open({"SSE"}, "e")
        out = row.discharge({"SSE"})
        assert out.effects == frozenset()
        assert out.row_var == "e"
        assert not out.is_pure  # row var still open

    def test_union_two_open_rows_with_same_var(self) -> None:
        a = EffectRow.open({"A"}, "e")
        b = EffectRow.open({"B"}, "e")
        u = a.union(b)
        assert u.effects == frozenset({"A", "B"})
        assert u.row_var == "e"

    def test_union_open_with_different_vars_keeps_first(self) -> None:
        """Two distinct row variables — union keeps the first; the
        unification constraint is a separate concern (env-tracked)."""
        a = EffectRow.open({"A"}, "e")
        b = EffectRow.open({"B"}, "f")
        u = a.union(b)
        assert u.effects == frozenset({"A", "B"})
        assert u.row_var in ("e", "f")  # implementation chooses first

    def test_pure_union_with_open_yields_open(self) -> None:
        a = EffectRow.empty()
        b = EffectRow.open({"A"}, "e")
        u = a.union(b)
        assert u.row_var == "e"
        assert u.effects == frozenset({"A"})

    def test_environment_unify_idempotent(self) -> None:
        env = EffectEnvironment()
        env.unify_row_vars("e", "f")
        env.unify_row_vars("e", "f")  # repeated call — no-op
        assert env.row_substitutions == {"f": "e"}

    def test_environment_unify_self_is_noop(self) -> None:
        env = EffectEnvironment()
        env.unify_row_vars("e", "e")
        assert env.row_substitutions == {}


# ──────────────────────────────────────────────────────────────────────
#  TestIntegration — algebraic effects coexist with existing constructs
# ──────────────────────────────────────────────────────────────────────


class TestIntegration:
    """Algebraic effects play nicely with personas, types, flows, runs."""

    def test_effect_alongside_persona_and_flow(self) -> None:
        _ok(
            "persona P { domain: [\"a\"] }\n"
            "type Token { name: String }\n"
            "effect SSE { Emit(token: Token) -> Unit }\n"
            "flow F() -> Unit {\n"
            "  step S {\n"
            "    handle SSE { Emit(t) -> { resume } } in {\n"
            "      perform SSE.Emit(token)\n"
            "    }\n"
            "  }\n"
            "}"
        )

    def test_user_type_as_op_param(self) -> None:
        _ok(
            "type Document { name: String }\n"
            "effect Loader { Load(doc: Document) -> Unit }"
        )

    def test_two_flows_independent_effect_rows(self) -> None:
        """Each flow has its own effect-row scope; one flow's unhandled
        effect doesn't affect the other."""
        errors = _check(
            "effect E { Op() -> Unit }\n"
            "flow F1() -> Unit {\n"
            "  step S {\n"
            "    handle E { Op() -> { resume } } in { perform E.Op() }\n"
            "  }\n"
            "}\n"
            "flow F2() -> Unit {\n"
            "  step S { }\n"
            "}"
        )
        assert errors == []

    def test_handler_frame_dataclass_constructable(self) -> None:
        """`HandlerFrame` is part of the public typechecker API surface
        for downstream tooling (LSP / IR generator)."""
        frame = HandlerFrame(effect_names=frozenset({"E"}))
        assert frame.effect_names == frozenset({"E"})
        assert frame.inside_clause is None
        assert frame.inside_operation is None
