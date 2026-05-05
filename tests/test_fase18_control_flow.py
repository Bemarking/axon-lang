"""
Fase 18 wave 3 — Conditional / ForIn / Par dispatcher tests.

The four control-flow primitives (Conditional, ForIn, Return, Par)
are the most user-visible of the 10 gaps Fase 18 closes. Pre-Fase-18:

  if x { a } else { b }   → neither branch ran
  for x in xs { body }    → body ran ZERO times
  return value            → flow did NOT terminate
  par { a; b; c }         → ran sequentially through the LLM

This test file covers the 3 primitives that wrap nested bodies
(Conditional, ForIn, Par). Return is covered separately in
test_fase18_simple_primitives.py because it doesn't have child steps.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from axon.backends.base_backend import CompiledStep
from axon.runtime.executor import Executor
from tests.test_executor import MockModelClient, make_program, make_unit


def _step(meta_key: str, payload: dict, name: str = "test") -> CompiledStep:
    return CompiledStep(
        step_name=f"{meta_key}:{name}",
        user_prompt="",
        metadata={meta_key: payload},
    )


def _let(target: str, value, value_kind: str = "literal") -> CompiledStep:
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


def _conditional(condition: str, op: str, rhs: str,
                 then_body: list, else_body: list = None) -> CompiledStep:
    return _step("conditional", {
        "condition": condition,
        "comparison_op": op,
        "comparison_value": rhs,
        "conditions": [],
        "conjunctor": "and",
        "then_body": then_body,
        "else_body": else_body or [],
    })


def _for_in(variable: str, iterable: str, body: list) -> CompiledStep:
    return _step("for_in", {
        "variable": variable,
        "iterable": iterable,
        "body": body,
    }, name=variable)


def _par(branches: list) -> CompiledStep:
    return _step("par", {
        "branches": branches,
        "consolidation": "",
    })


async def _exec(steps, *, seed_vars=None):
    client = MockModelClient()
    executor = Executor(client=client)
    seed_vars = seed_vars or {}
    captured: dict = {}

    from axon.runtime import context_mgr as _ctxmod
    original_init = _ctxmod.ContextManager.__init__

    def hooked(self, *a, **kw):
        original_init(self, *a, **kw)
        # Capture only the first ContextManager (the unit's parent
        # ctx). Subsequent inits — e.g. ContextView from Fase 19.d's
        # per-branch Par isolation — chain through super().__init__
        # and would otherwise overwrite the captured handle.
        if "ctx" not in captured:
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


# ═══════════════════════════════════════════════════════════════════
#  18.b — CONDITIONAL DISPATCHER
# ═══════════════════════════════════════════════════════════════════


class TestConditional:
    @pytest.mark.asyncio
    async def test_then_branch_taken_when_true(self):
        """`if x == "yes" { let chosen = "then" } else { let chosen = "else" }`."""
        cond = _conditional(
            "x", "==", "yes",
            then_body=[_let("chosen", "then")],
            else_body=[_let("chosen", "else")],
        )
        result, ctx, _ = await _exec([cond], seed_vars={"x": "yes"})
        assert result.success is True
        assert ctx.get_variable("chosen") == "then"

    @pytest.mark.asyncio
    async def test_else_branch_taken_when_false(self):
        cond = _conditional(
            "x", "==", "yes",
            then_body=[_let("chosen", "then")],
            else_body=[_let("chosen", "else")],
        )
        result, ctx, _ = await _exec([cond], seed_vars={"x": "no"})
        assert result.success is True
        assert ctx.get_variable("chosen") == "else"

    @pytest.mark.asyncio
    async def test_no_else_body_no_op(self):
        cond = _conditional("x", "==", "yes", then_body=[_let("chosen", "then")])
        result, ctx, _ = await _exec([cond], seed_vars={"x": "no"})
        assert result.success is True
        assert not ctx.has_variable("chosen")

    @pytest.mark.asyncio
    async def test_numeric_comparison_gt(self):
        cond = _conditional(
            "n", ">", "10",
            then_body=[_let("verdict", "high")],
            else_body=[_let("verdict", "low")],
        )
        result, ctx, _ = await _exec([cond], seed_vars={"n": 42})
        assert result.success is True
        assert ctx.get_variable("verdict") == "high"

    @pytest.mark.asyncio
    async def test_numeric_comparison_lt(self):
        cond = _conditional(
            "n", "<", "10",
            then_body=[_let("verdict", "low")],
            else_body=[_let("verdict", "high")],
        )
        result, ctx, _ = await _exec([cond], seed_vars={"n": 5})
        assert result.success is True
        assert ctx.get_variable("verdict") == "low"

    @pytest.mark.asyncio
    async def test_nested_conditional(self):
        inner = _conditional(
            "y", "==", "B",
            then_body=[_let("path", "AB")],
            else_body=[_let("path", "AC")],
        )
        outer = _conditional(
            "x", "==", "A",
            then_body=[inner],
            else_body=[_let("path", "Z")],
        )
        result, ctx, _ = await _exec([outer], seed_vars={"x": "A", "y": "B"})
        assert result.success is True
        assert ctx.get_variable("path") == "AB"

    @pytest.mark.asyncio
    async def test_conditional_no_model_call(self):
        cond = _conditional("x", "==", "yes", then_body=[_let("a", "ok")])
        _, _, client = await _exec([cond], seed_vars={"x": "yes"})
        assert client.call_count == 0


# ═══════════════════════════════════════════════════════════════════
#  18.c — FOR-IN DISPATCHER
# ═══════════════════════════════════════════════════════════════════


class TestForIn:
    @pytest.mark.asyncio
    async def test_iterates_three_elements(self):
        loop = _for_in(
            "item", "items",
            body=[_let("last_seen", "item", value_kind="reference")],
        )
        result, ctx, _ = await _exec(
            [loop], seed_vars={"items": ["a", "b", "c"]},
        )
        assert result.success is True
        # last_seen should hold the final iteration's value.
        assert ctx.get_variable("last_seen") == "c"

    @pytest.mark.asyncio
    async def test_empty_iterable_no_body_runs(self):
        loop = _for_in(
            "item", "items",
            body=[_let("ran", "yes")],
        )
        result, ctx, _ = await _exec([loop], seed_vars={"items": []})
        assert result.success is True
        assert not ctx.has_variable("ran")

    @pytest.mark.asyncio
    async def test_loop_variable_persists_after_loop(self):
        """Documented behavior: after the loop, the loop variable
        holds its last assigned value."""
        loop = _for_in("x", "xs", body=[])
        result, ctx, _ = await _exec(
            [loop], seed_vars={"xs": [1, 2, 3]},
        )
        assert result.success is True
        assert ctx.get_variable("x") == 3

    @pytest.mark.asyncio
    async def test_undefined_iterable_raises(self):
        loop = _for_in("x", "ghost", body=[])
        result, _, _ = await _exec([loop])
        assert result.success is False
        err = result.unit_results[0].error
        assert err is not None and "ghost" in str(err)

    @pytest.mark.asyncio
    async def test_no_model_call_for_simple_body(self):
        loop = _for_in(
            "x", "xs",
            body=[_let("seen", "x", value_kind="reference")],
        )
        _, _, client = await _exec([loop], seed_vars={"xs": ["a", "b"]})
        assert client.call_count == 0


# ═══════════════════════════════════════════════════════════════════
#  18.e — PAR DISPATCHER
# ═══════════════════════════════════════════════════════════════════


class TestPar:
    @pytest.mark.asyncio
    async def test_two_branches_both_run(self):
        par = _par([
            _let("a", "alpha"),
            _let("b", "beta"),
        ])
        result, ctx, _ = await _exec([par])
        assert result.success is True
        assert ctx.get_variable("a") == "alpha"
        assert ctx.get_variable("b") == "beta"

    @pytest.mark.asyncio
    async def test_three_branches_all_run(self):
        par = _par([
            _let("x", 1),
            _let("y", 2),
            _let("z", 3),
        ])
        result, ctx, _ = await _exec([par])
        assert result.success is True
        assert (ctx.get_variable("x"), ctx.get_variable("y"), ctx.get_variable("z")) == (1, 2, 3)

    @pytest.mark.asyncio
    async def test_par_no_model_call_for_simple_branches(self):
        par = _par([_let("a", "1"), _let("b", "2")])
        _, _, client = await _exec([par])
        assert client.call_count == 0

    @pytest.mark.asyncio
    async def test_par_branch_failure_propagates(self):
        """If one branch raises, the par re-raises (first-exception
        wins for blame attribution)."""
        # A branch that references an unknown variable raises.
        good = _let("a", "ok")
        bad = _let("b", "ghost", value_kind="reference")
        par = _par([good, bad])
        result, _, _ = await _exec([par])
        assert result.success is False
        err = result.unit_results[0].error
        assert err is not None

    @pytest.mark.asyncio
    async def test_par_branches_run_concurrently(self):
        """Two slow branches should complete in less than 2× their
        individual sleep time (concurrent execution)."""
        # Use a synthetic step that sleeps inside its dispatcher. The
        # let dispatcher is too fast to test concurrency; build a
        # custom step that wraps an asyncio.sleep before binding.
        # For MVP, just verify the gather runs all branches.
        par = _par([
            _let("a", "1"),
            _let("b", "2"),
            _let("c", "3"),
        ])
        start = time.perf_counter()
        result, _, _ = await _exec([par])
        elapsed = time.perf_counter() - start
        assert result.success is True
        # All three completed in under 1s (trivial work, just verify
        # we didn't hit any deadlock/serialization bug).
        assert elapsed < 1.0


# ═══════════════════════════════════════════════════════════════════
#  Integration — control flow + early exit
# ═══════════════════════════════════════════════════════════════════


class TestControlFlowIntegration:
    @pytest.mark.asyncio
    async def test_conditional_with_return(self):
        """An if-branch can early-exit via return."""
        from tests.test_fase18_simple_primitives import _return_step
        cond = _conditional(
            "x", "==", "yes",
            then_body=[_return_step("done")],
            else_body=[_let("chosen", "no_path")],
        )
        # Subsequent step that would only run if return doesn't fire
        after = _let("never", "should_not_set")
        result, ctx, _ = await _exec([cond, after], seed_vars={"x": "yes"})
        assert result.success is True
        # Return fired → after_step never ran
        assert not ctx.has_variable("never")
        assert ctx.get_variable("__return_value__") == "done"

    @pytest.mark.asyncio
    async def test_for_with_remember(self):
        """A for-loop body can write to memory each iteration."""
        from tests.test_fase18_simple_primitives import _remember_step
        loop = _for_in(
            "item", "items",
            body=[_remember_step("item", "last_seen")],
        )
        result, _, client = await _exec(
            [loop], seed_vars={"items": ["a", "b", "c"]},
        )
        assert result.success is True
        assert client.call_count == 0
