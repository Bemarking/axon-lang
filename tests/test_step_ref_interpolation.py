"""Tests for v1.15.4 step-reference interpolation in Executor.

Pre-v1.15.4 the ``{{step_name}}`` placeholder substitution was
hardcoded inside ``_build_user_prompt`` (LLM prompts only). Every
other consumer of the same template syntax — most damagingly the
axonstore ``where_expr`` / ``fields`` flowing through
``_execute_store_step`` — passed metadata literal to the backend,
producing zero-row queries or persisting the literal placeholder
string into columns. Silent data corruption with no error fired.

v1.15.4 promotes the interpolation primitive to a shared method
``_interpolate_step_refs`` and routes both the LLM prompt path and
the axonstore step path through it. This file pins:

1. **Helper unit semantics** — string / list / tuple / dict
   recursion, primitives pass-through, no-match behaviour, fast
   path on placeholder-free strings.
2. **axonstore integration** — every operation that consumed
   metadata literal pre-v1.15.4 (``persist`` / ``retrieve`` /
   ``mutate`` / ``purge``) now sees substituted args at the
   dispatcher boundary.
3. **LLM prompt regression** — ``_build_user_prompt`` keeps its
   pre-v1.15.4 contract (it is now a thin wrapper around the
   helper).
4. **AST drift gate** — static check that
   ``_execute_store_step``'s body invokes
   ``_interpolate_step_refs`` BEFORE ``store_dispatcher.dispatch``.
   Catches a future refactor that removes the interpolation
   without removing the placeholder syntax — the exact failure
   mode v1.15.4 fixes.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass, field
from typing import Any

import pytest

from axon.backends.base_backend import (
    CompiledExecutionUnit,
    CompiledProgram,
    CompiledStep,
)
from axon.runtime.context_mgr import ContextManager
from axon.runtime.executor import Executor


# ═══════════════════════════════════════════════════════════════════
#  Test scaffolding
# ═══════════════════════════════════════════════════════════════════


def _executor_with_ctx() -> tuple[Executor, ContextManager]:
    """Return a fresh Executor + populated ContextManager for tests."""
    executor = Executor(client=None)  # type: ignore[arg-type]
    ctx = ContextManager()
    ctx.set_step_result("fetch_user", "alice")
    ctx.set_step_result("fetch_org", "bemarking")
    ctx.set_step_result("compute_total", 42)
    return executor, ctx


# ═══════════════════════════════════════════════════════════════════
#  Layer 1 — _interpolate_step_refs unit tests
# ═══════════════════════════════════════════════════════════════════


class TestInterpolateStepRefs:
    def test_string_single_placeholder(self) -> None:
        ex, ctx = _executor_with_ctx()
        assert ex._interpolate_step_refs("user={{fetch_user}}", ctx) == "user=alice"

    def test_string_multiple_placeholders(self) -> None:
        ex, ctx = _executor_with_ctx()
        assert (
            ex._interpolate_step_refs(
                "user={{fetch_user}} org={{fetch_org}}", ctx
            )
            == "user=alice org=bemarking"
        )

    def test_string_repeated_placeholder(self) -> None:
        ex, ctx = _executor_with_ctx()
        assert (
            ex._interpolate_step_refs("{{fetch_user}}+{{fetch_user}}", ctx)
            == "alice+alice"
        )

    def test_string_unknown_placeholder_left_literal(self) -> None:
        """Conservative behaviour matches pre-v1.15.4
        ``_build_user_prompt`` — unknown step names stay as the
        literal placeholder string. Adopters who typo a step name
        see the literal in the output, which is debuggable, instead
        of an unrecoverable runtime error mid-flow."""
        ex, ctx = _executor_with_ctx()
        assert (
            ex._interpolate_step_refs("{{unknown_step}}-real", ctx)
            == "{{unknown_step}}-real"
        )

    def test_string_no_placeholder_returns_original(self) -> None:
        """Fast path — strings without ``{{`` skip the loop."""
        ex, ctx = _executor_with_ctx()
        assert ex._interpolate_step_refs("plain text", ctx) == "plain text"

    def test_string_with_brace_but_no_step_match(self) -> None:
        ex, ctx = _executor_with_ctx()
        assert ex._interpolate_step_refs("a {{ b }} c", ctx) == "a {{ b }} c"

    def test_non_string_primitives_pass_through(self) -> None:
        ex, ctx = _executor_with_ctx()
        assert ex._interpolate_step_refs(42, ctx) == 42
        assert ex._interpolate_step_refs(3.14, ctx) == 3.14
        assert ex._interpolate_step_refs(True, ctx) is True
        assert ex._interpolate_step_refs(False, ctx) is False
        assert ex._interpolate_step_refs(None, ctx) is None

    def test_list_recursion(self) -> None:
        ex, ctx = _executor_with_ctx()
        result = ex._interpolate_step_refs(
            ["{{fetch_user}}", "literal", "{{fetch_org}}"], ctx
        )
        assert result == ["alice", "literal", "bemarking"]

    def test_tuple_recursion_preserves_tuple_type(self) -> None:
        """``fields`` in axonstore are tuple-shaped; the helper must
        return a tuple, not a list, to preserve dispatcher
        expectations downstream."""
        ex, ctx = _executor_with_ctx()
        result = ex._interpolate_step_refs(
            ("name", "{{fetch_user}}"), ctx
        )
        assert result == ("name", "alice")
        assert isinstance(result, tuple)

    def test_dict_recursion(self) -> None:
        ex, ctx = _executor_with_ctx()
        result = ex._interpolate_step_refs(
            {"where_expr": "id == '{{fetch_user}}'", "limit": 10}, ctx
        )
        assert result == {"where_expr": "id == 'alice'", "limit": 10}

    def test_deeply_nested_structure(self) -> None:
        """Realistic axonstore meta shape: dict → list of tuples →
        strings. This is the exact shape v1.15.4 needs to handle for
        the ``persist`` / ``mutate`` ``fields`` arg."""
        ex, ctx = _executor_with_ctx()
        nested = {
            "store_name": "UserStore",
            "fields": [
                ("user_id", "{{fetch_user}}"),
                ("org_id", "{{fetch_org}}"),
                ("total", 42),
            ],
            "where_expr": "user_id == '{{fetch_user}}'",
        }
        result = ex._interpolate_step_refs(nested, ctx)
        assert result == {
            "store_name": "UserStore",
            "fields": [
                ("user_id", "alice"),
                ("org_id", "bemarking"),
                ("total", 42),
            ],
            "where_expr": "user_id == 'alice'",
        }

    def test_step_result_with_non_string_value_is_stringified(self) -> None:
        """Step results aren't always strings (e.g., int from a
        compute step). Substitution coerces via ``str()`` — same
        contract as pre-v1.15.4 ``_build_user_prompt``."""
        ex, ctx = _executor_with_ctx()
        assert (
            ex._interpolate_step_refs("count={{compute_total}}", ctx)
            == "count=42"
        )


# ═══════════════════════════════════════════════════════════════════
#  Layer 2 — axonstore integration via stub StoreDispatcher
# ═══════════════════════════════════════════════════════════════════


@dataclass
class _RecordedDispatch:
    meta: dict[str, Any]
    context: dict[str, Any]


@dataclass
class _StubStoreResult:
    success: bool = True
    operation: str = "stub"
    data: dict[str, Any] = field(default_factory=lambda: {"rows": [], "count": 0})
    error: str = ""


@dataclass
class _StubStoreDispatcher:
    """Captures ``dispatch`` calls so tests can assert what the
    Executor passed downstream after interpolation."""
    calls: list[_RecordedDispatch] = field(default_factory=list)

    async def dispatch(
        self,
        meta: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> _StubStoreResult:
        self.calls.append(_RecordedDispatch(meta=meta, context=context or {}))
        return _StubStoreResult()


def _make_axonstore_step(
    name: str, operation: str, args: dict[str, Any]
) -> CompiledStep:
    return CompiledStep(
        step_name=name,
        system_prompt="",
        user_prompt="",
        metadata={"axonstore": {"operation": operation, "args": args}},
    )


@pytest.mark.asyncio
async def test_axonstore_retrieve_interpolates_where_expr() -> None:
    """The exact bug Kivi reported: ``where_expr`` with
    ``{{prior_step}}`` reaches the backend with the substituted value,
    not the literal placeholder string."""
    ex, ctx = _executor_with_ctx()
    stub = _StubStoreDispatcher()
    ex._store_dispatcher = stub

    step = _make_axonstore_step(
        name="get_user_record",
        operation="retrieve",
        args={
            "store_name": "UserStore",
            "where_expr": "user_id == '{{fetch_user}}'",
            "alias": "user",
        },
    )

    from axon.runtime.tracer import Tracer

    await ex._execute_store_step(step, ctx, Tracer())

    assert len(stub.calls) == 1
    recorded = stub.calls[0]
    assert recorded.meta["args"]["where_expr"] == "user_id == 'alice'"
    # Other fields untouched.
    assert recorded.meta["args"]["store_name"] == "UserStore"
    assert recorded.meta["args"]["alias"] == "user"


@pytest.mark.asyncio
async def test_axonstore_persist_interpolates_field_values() -> None:
    """The bug Kivi DIDN'T report but is structurally identical:
    ``fields`` values flowing through ``persist`` get persisted
    literal pre-v1.15.4 (``"{{fetch_user}}"`` written into the
    column instead of ``"alice"``)."""
    ex, ctx = _executor_with_ctx()
    stub = _StubStoreDispatcher()
    ex._store_dispatcher = stub

    step = _make_axonstore_step(
        name="record_event",
        operation="persist",
        args={
            "store_name": "EventStore",
            "fields": [
                ("user_id", "{{fetch_user}}"),
                ("org_id", "{{fetch_org}}"),
                ("count", 42),
            ],
        },
    )

    from axon.runtime.tracer import Tracer

    await ex._execute_store_step(step, ctx, Tracer())

    fields = stub.calls[0].meta["args"]["fields"]
    assert fields == [
        ("user_id", "alice"),
        ("org_id", "bemarking"),
        ("count", 42),
    ]


@pytest.mark.asyncio
async def test_axonstore_mutate_interpolates_both_where_and_fields() -> None:
    """``mutate`` is the worst-affected op: both ``where_expr``
    (which row to update) AND ``fields`` (what value to write)
    consumed metadata literal pre-v1.15.4. Either silent corruption
    on its own; together, an UPDATE that matches no rows AND would
    have written a literal placeholder if it had matched."""
    ex, ctx = _executor_with_ctx()
    stub = _StubStoreDispatcher()
    ex._store_dispatcher = stub

    step = _make_axonstore_step(
        name="bump_total",
        operation="mutate",
        args={
            "store_name": "OrgStore",
            "where_expr": "name == '{{fetch_org}}'",
            "fields": [("total", "{{compute_total}}")],
        },
    )

    from axon.runtime.tracer import Tracer

    await ex._execute_store_step(step, ctx, Tracer())

    args = stub.calls[0].meta["args"]
    assert args["where_expr"] == "name == 'bemarking'"
    assert args["fields"] == [("total", "42")]


@pytest.mark.asyncio
async def test_axonstore_purge_interpolates_where_expr() -> None:
    ex, ctx = _executor_with_ctx()
    stub = _StubStoreDispatcher()
    ex._store_dispatcher = stub

    step = _make_axonstore_step(
        name="cleanup_user",
        operation="purge",
        args={
            "store_name": "AuditStore",
            "where_expr": "user_id == '{{fetch_user}}'",
        },
    )

    from axon.runtime.tracer import Tracer

    await ex._execute_store_step(step, ctx, Tracer())

    assert (
        stub.calls[0].meta["args"]["where_expr"]
        == "user_id == 'alice'"
    )


# ═══════════════════════════════════════════════════════════════════
#  Layer 3 — LLM prompt regression (existing _build_user_prompt path)
# ═══════════════════════════════════════════════════════════════════


def test_build_user_prompt_still_substitutes_step_refs() -> None:
    """``_build_user_prompt`` is now a thin wrapper around
    ``_interpolate_step_refs``. The pre-v1.15.4 contract — substitute
    ``{{step_name}}`` with the matching step result — is preserved
    byte-for-byte."""
    ex, ctx = _executor_with_ctx()
    step = CompiledStep(
        step_name="summarise",
        system_prompt="",
        user_prompt="Summary of {{fetch_user}} ({{fetch_org}})",
        metadata={},
    )
    assert (
        ex._build_user_prompt(step, ctx) == "Summary of alice (bemarking)"
    )


def test_build_user_prompt_unknown_ref_leaves_literal() -> None:
    """Pre-v1.15.4 behaviour for unknown step refs preserved: leave
    the placeholder literal in the prompt rather than raising or
    blank-substituting. Adopters who typo a name see it in their
    output and can debug."""
    ex, ctx = _executor_with_ctx()
    step = CompiledStep(
        step_name="summarise",
        system_prompt="",
        user_prompt="Hello {{unknown_step}}!",
        metadata={},
    )
    assert ex._build_user_prompt(step, ctx) == "Hello {{unknown_step}}!"


# ═══════════════════════════════════════════════════════════════════
#  Layer 4 — AST drift gate
# ═══════════════════════════════════════════════════════════════════


def test_execute_store_step_calls_interpolate_before_dispatch() -> None:
    """Static guard against the v1.15.4 regression class. Walks the
    AST of ``_execute_store_step`` and asserts that
    ``self._interpolate_step_refs(...)`` is invoked BEFORE
    ``self._store_dispatcher.dispatch(...)`` in the same function
    body. A future refactor that removes the interpolation while
    keeping the dispatcher call would fail this test loud and
    early — exactly the regression mode that produced the original
    bug.
    """
    module = ast.parse(inspect.getsource(Executor))

    target_func: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == "_execute_store_step"
        ):
            target_func = node
            break
    assert target_func is not None, (
        "_execute_store_step disappeared from Executor — drift gate "
        "needs an updated function name"
    )

    interpolate_lineno: int | None = None
    dispatch_lineno: int | None = None

    for node in ast.walk(target_func):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        # Match self._interpolate_step_refs(...).
        if (
            isinstance(callee, ast.Attribute)
            and callee.attr == "_interpolate_step_refs"
            and isinstance(callee.value, ast.Name)
            and callee.value.id == "self"
        ):
            if interpolate_lineno is None or node.lineno < interpolate_lineno:
                interpolate_lineno = node.lineno
        # Match self._store_dispatcher.dispatch(...).
        if (
            isinstance(callee, ast.Attribute)
            and callee.attr == "dispatch"
            and isinstance(callee.value, ast.Attribute)
            and callee.value.attr == "_store_dispatcher"
        ):
            if dispatch_lineno is None or node.lineno < dispatch_lineno:
                dispatch_lineno = node.lineno

    assert interpolate_lineno is not None, (
        "_execute_store_step does NOT call self._interpolate_step_refs(). "
        "Pre-v1.15.4 regression: axonstore where_expr / fields would flow "
        "to the backend literal. Add the call before dispatching."
    )
    assert dispatch_lineno is not None, (
        "_execute_store_step does NOT call self._store_dispatcher.dispatch() — "
        "drift gate looking at wrong function?"
    )
    assert interpolate_lineno < dispatch_lineno, (
        f"_interpolate_step_refs (line {interpolate_lineno}) must run "
        f"BEFORE _store_dispatcher.dispatch (line {dispatch_lineno}); "
        "interpolating after dispatch is a no-op for this request"
    )


def test_build_user_prompt_routes_through_helper() -> None:
    """Soft drift gate ensuring ``_build_user_prompt`` doesn't drift
    back to a divergent local implementation. If someone re-inlines
    the substitution loop, the helper-routing behaviour is lost and
    the two consumers (LLM prompts, axonstore meta) can drift apart
    again — the original v1.15.4 bug shape."""
    source = inspect.getsource(Executor._build_user_prompt)
    assert "_interpolate_step_refs" in source, (
        "_build_user_prompt no longer routes through "
        "_interpolate_step_refs — divergent inlined substitution "
        "would re-create the v1.15.4 drift."
    )
