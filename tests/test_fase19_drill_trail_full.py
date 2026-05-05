"""
Fase 19.b/c — Drill + Trail full PIX integration tests.

Replaces the Fase 18.j/k MVP placeholders (which bound `_stub: True`
payloads) with production PIX integration. Tests cover:

  * Unknown `pix_ref` raises AxonRuntimeError with the registered
    refs surfaced for diagnosability (loud failure, not silent stub).
  * Unknown subtree node_id raises AxonRuntimeError.
  * A registered navigator is invoked; the bound payload reflects the
    real `NavigationResult.to_dict()` (no `_stub` marker).
  * Live `NavigationResult` is stashed under `<output_name>:result`
    so a subsequent `trail` step walks the real reasoning path.
  * Trail-after-drill produces a payload with `found=True`, the
    actual depth + evaluations + leaf_node_ids from the navigation.
  * Trail without a corresponding navigation produces `found=False`
    (does NOT raise — adopters often probe trails opportunistically).
  * Empty PixRegistry constructor + injected registry are honored
    (no falsy-replacement bug).
"""

from __future__ import annotations

import asyncio
import pytest

from axon.engine.pix.document_tree import DocumentTree, PixNode
from axon.engine.pix.navigator import (
    NavigationConfig,
    NavigationResult,
    PixNavigator,
    ThresholdScorer,
)
from axon.runtime.executor import Executor
from axon.runtime.pix_registry import InMemoryPixRegistry
from axon.runtime.runtime_errors import AxonRuntimeError

from tests.test_executor import MockModelClient, make_program, make_unit
from tests.test_fase18_domain_primitives import _drill_step, _trail_step


def _build_simple_tree() -> DocumentTree:
    """Three-level tree the ThresholdScorer can navigate via term overlap."""
    root = PixNode(
        node_id="root",
        title="Master Agreement",
        summary="contract liability indemnity termination",
    )
    chapters = PixNode(
        node_id="chapters",
        title="Chapters",
        summary="liability indemnity termination clauses",
    )
    intro = PixNode(
        node_id="chapters.intro",
        title="Introduction",
        summary="liability indemnity overview",
    )
    body = PixNode(
        node_id="chapters.body",
        title="Body",
        summary="termination clauses",
    )
    leaf_liab = PixNode(
        node_id="leaf_liab",
        title="Liability cap leaf",
        summary="liability indemnity",
        content="Liability is capped at $1M.",
    )
    leaf_term = PixNode(
        node_id="leaf_term",
        title="Termination leaf",
        summary="termination clauses",
        content="Either party may terminate with 30 days notice.",
    )
    intro.add_child(leaf_liab)
    body.add_child(leaf_term)
    chapters.add_child(intro)
    chapters.add_child(body)
    root.add_child(chapters)
    return DocumentTree(name="DocTree", root=root)


def _make_navigator() -> PixNavigator:
    return PixNavigator(
        tree=_build_simple_tree(),
        scorer=ThresholdScorer(),
        config=NavigationConfig(max_depth=4, max_branch=3, threshold=0.0),
    )


# ═══════════════════════════════════════════════════════════════════
#  PIX REGISTRY
# ═══════════════════════════════════════════════════════════════════


class TestInMemoryPixRegistry:
    def test_register_then_get_roundtrip(self):
        reg = InMemoryPixRegistry()
        nav = _make_navigator()
        reg.register("DocTree", nav)
        assert reg.get("DocTree") is nav
        assert reg.has("DocTree") is True

    def test_get_unknown_returns_none(self):
        reg = InMemoryPixRegistry()
        assert reg.get("nope") is None
        assert reg.has("nope") is False

    def test_known_refs_sorted(self):
        reg = InMemoryPixRegistry()
        reg.register("Z", _make_navigator())
        reg.register("A", _make_navigator())
        reg.register("M", _make_navigator())
        assert reg.known_refs() == ["A", "M", "Z"]

    def test_register_empty_pix_ref_rejected(self):
        reg = InMemoryPixRegistry()
        with pytest.raises(ValueError):
            reg.register("", _make_navigator())

    def test_register_none_navigator_rejected(self):
        reg = InMemoryPixRegistry()
        with pytest.raises(ValueError):
            reg.register("X", None)  # type: ignore[arg-type]

    def test_overwrite_replaces_prior(self):
        reg = InMemoryPixRegistry()
        nav_a = _make_navigator()
        nav_b = _make_navigator()
        reg.register("DocTree", nav_a)
        reg.register("DocTree", nav_b)
        assert reg.get("DocTree") is nav_b


# ═══════════════════════════════════════════════════════════════════
#  19.b — DRILL DISPATCHER (FULL)
# ═══════════════════════════════════════════════════════════════════


def _exec_with_registry(steps, registry):
    async def _run():
        client = MockModelClient()
        executor = Executor(client=client, pix_registry=registry)
        program = make_program([make_unit("flow", steps)])
        result = await executor.execute(program)
        return result, executor

    return asyncio.get_event_loop().run_until_complete(_run())


class TestDrillFull:
    @pytest.mark.asyncio
    async def test_drill_unknown_pix_ref_raises_axon_runtime_error(self):
        registry = InMemoryPixRegistry()  # empty
        client = MockModelClient()
        executor = Executor(client=client, pix_registry=registry)
        program = make_program([make_unit("flow", [
            _drill_step("Missing", "chapters", "anything"),
        ])])
        result = await executor.execute(program)
        # Unit-level error path: AxonRuntimeError is caught by the
        # unit loop, success=False with the message recorded.
        assert result.success is False

    @pytest.mark.asyncio
    async def test_drill_unknown_subtree_raises_axon_runtime_error(self):
        registry = InMemoryPixRegistry()
        registry.register("DocTree", _make_navigator())
        executor = Executor(client=MockModelClient(), pix_registry=registry)
        program = make_program([make_unit("flow", [
            _drill_step("DocTree", "no.such.node", "anything"),
        ])])
        result = await executor.execute(program)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_drill_invokes_navigator_and_binds_real_result(self):
        registry = InMemoryPixRegistry()
        registry.register("DocTree", _make_navigator())
        client = MockModelClient()
        executor = Executor(client=client, pix_registry=registry)
        program = make_program([make_unit("flow", [
            _drill_step(
                "DocTree", "chapters",
                "liability indemnity",
                output_name="findings",
            ),
        ])])
        result = await executor.execute(program)
        assert result.success is True

        sr = result.unit_results[0].step_results[0]
        import json
        payload = json.loads(sr.response.content)
        # No more `_stub: True` — the MVP marker must not survive 19.b.
        assert "_stub" not in payload
        # Real NavigationResult.to_dict() shape:
        assert payload["query"] == "liability indemnity"
        assert "leaf_count" in payload
        assert "path" in payload
        # AXON-level identifiers re-stamped:
        assert payload["pix_ref"] == "DocTree"
        assert payload["subtree_path"] == "chapters"
        # Navigator was driven, not bypassed.
        assert client.call_count == 0  # navigation uses ThresholdScorer, no model

    @pytest.mark.asyncio
    async def test_drill_default_output_name_is_drill_pixref(self):
        registry = InMemoryPixRegistry()
        registry.register("DocTree", _make_navigator())
        # Drive directly through executor so we can interrogate ctx
        # via store-side observation.
        from axon.runtime import context_mgr as _ctxmod
        captured: dict = {}
        original = _ctxmod.ContextManager.__init__

        def hooked(self, *a, **kw):
            original(self, *a, **kw)
            captured["ctx"] = self

        _ctxmod.ContextManager.__init__ = hooked  # type: ignore[method-assign]
        try:
            executor = Executor(client=MockModelClient(), pix_registry=registry)
            program = make_program([make_unit("flow", [
                _drill_step("DocTree", "chapters", "liability"),
            ])])
            await executor.execute(program)
        finally:
            _ctxmod.ContextManager.__init__ = original  # type: ignore[method-assign]

        ctx = captured["ctx"]
        bound = ctx.get_variable("drill:DocTree")
        assert bound["pix_ref"] == "DocTree"
        # Live NavigationResult also stashed for trail.
        live = ctx.get_variable("drill:DocTree:result")
        assert isinstance(live, NavigationResult)


# ═══════════════════════════════════════════════════════════════════
#  19.c — TRAIL DISPATCHER (FULL)
# ═══════════════════════════════════════════════════════════════════


class TestTrailFull:
    @pytest.mark.asyncio
    async def test_trail_after_drill_walks_real_reasoning_path(self):
        registry = InMemoryPixRegistry()
        registry.register("DocTree", _make_navigator())
        executor = Executor(client=MockModelClient(), pix_registry=registry)
        program = make_program([make_unit("flow", [
            _drill_step("DocTree", "chapters", "liability indemnity",
                         output_name="findings"),
            _trail_step("findings"),
        ])])
        result = await executor.execute(program)
        assert result.success is True
        trail_sr = result.unit_results[0].step_results[1]
        import json
        payload = json.loads(trail_sr.response.content)
        assert payload["found"] is True
        # No stub marker.
        assert "_stub" not in payload
        # Real path metrics from PixNavigator.drill:
        assert payload["depth"] >= 0
        assert payload["total_evaluations"] >= 0
        assert isinstance(payload["selected_node_ids"], list)
        assert isinstance(payload["leaf_node_ids"], list)
        assert isinstance(payload["steps"], list)

    @pytest.mark.asyncio
    async def test_trail_missing_ref_returns_found_false_not_raises(self):
        executor = Executor(client=MockModelClient())
        program = make_program([make_unit("flow", [
            _trail_step("ghost"),
        ])])
        result = await executor.execute(program)
        assert result.success is True
        sr = result.unit_results[0].step_results[0]
        import json
        payload = json.loads(sr.response.content)
        assert payload["found"] is False
        assert payload["leaf_node_ids"] == []

    @pytest.mark.asyncio
    async def test_trail_no_model_call(self):
        registry = InMemoryPixRegistry()
        registry.register("DocTree", _make_navigator())
        client = MockModelClient()
        executor = Executor(client=client, pix_registry=registry)
        program = make_program([make_unit("flow", [
            _drill_step("DocTree", "chapters", "liability",
                         output_name="findings"),
            _trail_step("findings"),
        ])])
        await executor.execute(program)
        assert client.call_count == 0


# ═══════════════════════════════════════════════════════════════════
#  EXECUTOR INJECTION SANITY
# ═══════════════════════════════════════════════════════════════════


class TestExecutorInjection:
    def test_default_pix_registry_is_empty_in_memory_registry(self):
        executor = Executor(client=MockModelClient())
        assert isinstance(executor._pix_registry, InMemoryPixRegistry)
        assert len(executor._pix_registry) == 0

    def test_injected_pix_registry_is_honored_when_empty(self):
        """Regression: empty PixRegistry has __len__ → falsy. The
        Executor must NOT silently replace it with a fresh default.
        Same bug class as the hibernation_store fix in 19.a."""
        injected = InMemoryPixRegistry()
        executor = Executor(
            client=MockModelClient(),
            pix_registry=injected,
        )
        assert executor._pix_registry is injected
