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
#  18.h — HIBERNATE DISPATCHER
# ═══════════════════════════════════════════════════════════════════


class TestHibernate:
    @pytest.mark.asyncio
    async def test_hibernate_binds_continuation_token(self):
        step = _hibernate_step(
            event_name="user_input",
            timeout="30s",
            continuation_id="cont-abc",
        )
        result, ctx, _ = await _exec([step])
        assert result.success is True
        token = ctx.get_variable("__hibernation_token__")
        assert token["event_name"] == "user_input"
        assert token["timeout"] == "30s"
        assert token["continuation_id"] == "cont-abc"
        assert "checkpoint_at" in token

    @pytest.mark.asyncio
    async def test_hibernate_no_model_call(self):
        step = _hibernate_step(continuation_id="cont-1")
        _, _, client = await _exec([step])
        assert client.call_count == 0

    @pytest.mark.asyncio
    async def test_hibernate_records_flow_name(self):
        step = _hibernate_step(continuation_id="x")
        _, ctx, _ = await _exec([step])
        token = ctx.get_variable("__hibernation_token__")
        assert token["flow_name"] == "test_flow"


# ═══════════════════════════════════════════════════════════════════
#  18.j — DRILL DISPATCHER
# ═══════════════════════════════════════════════════════════════════


class TestDrill:
    @pytest.mark.asyncio
    async def test_drill_binds_placeholder_result(self):
        step = _drill_step("DocTree", "chapters.intro", "conclusions")
        result, ctx, _ = await _exec([step])
        assert result.success is True
        # Default output binding: drill:<pix_ref>
        bound = ctx.get_variable("drill:DocTree")
        assert bound["pix_ref"] == "DocTree"
        assert bound["subtree_path"] == "chapters.intro"
        assert bound["query"] == "conclusions"
        assert bound["_stub"] is True

    @pytest.mark.asyncio
    async def test_drill_explicit_output_name(self):
        step = _drill_step(
            "DocTree", "chapters.intro", "q",
            output_name="findings",
        )
        result, ctx, _ = await _exec([step])
        assert result.success is True
        assert ctx.get_variable("findings")["pix_ref"] == "DocTree"

    @pytest.mark.asyncio
    async def test_drill_no_model_call(self):
        step = _drill_step("DocTree", "x", "y")
        _, _, client = await _exec([step])
        assert client.call_count == 0

    @pytest.mark.asyncio
    async def test_drill_response_content_is_json(self):
        step = _drill_step("DocTree", "x", "y", output_name="out")
        result, _, _ = await _exec([step])
        step_result = result.unit_results[0].step_results[0]
        parsed = json.loads(step_result.response.content)
        assert parsed["pix_ref"] == "DocTree"


# ═══════════════════════════════════════════════════════════════════
#  18.k — TRAIL DISPATCHER
# ═══════════════════════════════════════════════════════════════════


class TestTrail:
    @pytest.mark.asyncio
    async def test_trail_binds_placeholder(self):
        step = _trail_step("nav_step_1")
        result, ctx, _ = await _exec(
            [step],
            seed_vars={"nav_step_1": {"hits": ["a", "b"]}},
        )
        assert result.success is True
        bound = ctx.get_variable("trail:nav_step_1")
        assert bound["navigate_ref"] == "nav_step_1"
        assert bound["found"] is True
        assert bound["_stub"] is True

    @pytest.mark.asyncio
    async def test_trail_missing_ref_still_succeeds(self):
        """Trail on a missing ref binds a 'found: False' placeholder."""
        step = _trail_step("ghost")
        result, ctx, _ = await _exec([step])
        assert result.success is True
        bound = ctx.get_variable("trail:ghost")
        assert bound["found"] is False

    @pytest.mark.asyncio
    async def test_trail_no_model_call(self):
        step = _trail_step("nav")
        _, _, client = await _exec([step])
        assert client.call_count == 0
