"""
Fase 18 wave 4 — Hibernate / Drill / Trail dispatcher tests.

These three primitives are domain-specific (CPS, PIX subtree, PIX
corroborated path). MVP dispatchers are stub-correct: they bind a
semantic placeholder + emit trace, without invoking the LLM. Full
subsystem integration (continuity_token serialization, PIX engine
queries) is a follow-up — but the LLM-fall-through gap is closed.
"""

from __future__ import annotations

import json

import pytest

from axon.backends.base_backend import BaseBackend, CompiledStep
from axon.compiler.ir_nodes import IRDrill, IRHibernate, IRTrail
from axon.runtime.executor import Executor
from tests.test_executor import MockModelClient, make_program, make_unit


def _step(meta_key: str, payload: dict, name: str = "test") -> CompiledStep:
    return CompiledStep(
        step_name=f"{meta_key}:{name}",
        user_prompt="",
        metadata={meta_key: payload},
    )


def _hibernate_step(event_name: str = "", timeout: str = "",
                    continuation_id: str = "") -> CompiledStep:
    return _step("hibernate", {
        "event_name": event_name,
        "timeout": timeout,
        "continuation_id": continuation_id,
    })


def _drill_step(pix_ref: str, subtree_path: str, query: str,
                output_name: str = "") -> CompiledStep:
    return _step("drill", {
        "pix_ref": pix_ref,
        "subtree_path": subtree_path,
        "query": query,
        "output_name": output_name,
    }, name=pix_ref)


def _trail_step(navigate_ref: str) -> CompiledStep:
    return _step("trail", {"navigate_ref": navigate_ref}, name=navigate_ref)


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
#  18.a — PHASE-2 LOWERING
# ═══════════════════════════════════════════════════════════════════


class TestPhase2Lowering:
    def test_hibernate_lowering(self):
        node = IRHibernate(
            event_name="user_input",
            timeout="30s",
            continuation_id="cont-abc",
        )
        step = BaseBackend._compile_hibernate_step(node)
        meta = step.metadata["hibernate"]
        assert meta["event_name"] == "user_input"
        assert meta["timeout"] == "30s"
        assert meta["continuation_id"] == "cont-abc"
        assert step.user_prompt == ""

    def test_drill_lowering(self):
        node = IRDrill(
            pix_ref="DocTree",
            subtree_path="chapters.intro",
            query="conclusions",
            output_name="found",
        )
        step = BaseBackend._compile_drill_step(node)
        meta = step.metadata["drill"]
        assert meta["pix_ref"] == "DocTree"
        assert meta["subtree_path"] == "chapters.intro"
        assert meta["query"] == "conclusions"
        assert meta["output_name"] == "found"

    def test_trail_lowering(self):
        node = IRTrail(navigate_ref="nav_step_1")
        step = BaseBackend._compile_trail_step(node)
        assert step.metadata["trail"]["navigate_ref"] == "nav_step_1"


# ═══════════════════════════════════════════════════════════════════
#  18.h — HIBERNATE DISPATCHER (Fase 18 MVP shape, retained for
#         coverage; full integration covered in Fase 19.a tests
#         further down + tests/test_fase19_hibernate_full.py).
# ═══════════════════════════════════════════════════════════════════


class TestHibernate:
    @pytest.mark.asyncio
    async def test_hibernate_binds_signed_token_string(self):
        """Fase 19.a: ``__hibernation_token__`` is the signed token
        string (base64url), not the placeholder dict that Fase 18.h
        bound. Adopter-facing metadata moved to dedicated
        ``__hibernation_*__`` variables."""
        step = _hibernate_step(
            event_name="user_input",
            timeout="30s",
            continuation_id="cont-abc",
        )
        result, ctx, _ = await _exec([step])
        assert result.success is True
        token = ctx.get_variable("__hibernation_token__")
        assert isinstance(token, str)
        assert token  # non-empty
        assert ctx.get_variable("__hibernation_event_name__") == "user_input"
        assert ctx.get_variable("__hibernation_session_id__") == "test_flow:cont-abc"
        # Expires-at is an ISO-8601 string.
        assert "T" in ctx.get_variable("__hibernation_expires_at__")

    @pytest.mark.asyncio
    async def test_hibernate_no_model_call(self):
        step = _hibernate_step(continuation_id="cont-1")
        _, _, client = await _exec([step])
        assert client.call_count == 0

    @pytest.mark.asyncio
    async def test_hibernate_session_id_includes_flow_name(self):
        step = _hibernate_step(continuation_id="x")
        _, ctx, _ = await _exec([step])
        assert ctx.get_variable("__hibernation_session_id__") == "test_flow:x"


# Drill/Trail dispatcher behavior moved to tests/test_fase19_drill_trail_full.py
# in Fase 19.b/c. The Fase 18.j/k MVP stubs (placeholder dicts with
# `_stub: True`) were replaced with full PixRegistry + PixNavigator
# integration; those dispatcher tests now exercise the production path,
# not the stub. The lowering tests in TestPhase2Lowering above still
# guard the IR → CompiledStep boundary.
