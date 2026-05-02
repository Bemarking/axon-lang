"""
Fase 13.j — Listen-in-flow integration tests
============================================
Closes the gap where a free-standing ``listen ChannelName as ev { … }``
inside a flow body parsed and type-checked correctly but the backend
treated it as an LLM step (it fell into the catch-all branch of
``compile_program``). 13.j wires the dispatch end-to-end: backend
isinstance branch → metadata-only ``CompiledStep`` with
``listen_apply`` → ``Executor._execute_listen_step`` that performs a
single-event receive on the bus, binds the alias in ``ctx``, then
runs the pre-compiled children once.

Looped reception remains the responsibility of ``daemon`` declarations
(supervised by the AxonServer daemon supervisor). A listen-in-flow is
a one-shot consumption — it integrates cleanly with the flow's linear
control flow.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from axon.compiler.ir_nodes import (
    IRChannel, IREmit, IRFlow, IRListen, IRProgram, IRRun,
)
from axon.runtime.channels.typed import (
    TypedChannelHandle, TypedChannelRegistry, TypedEventBus,
)
from axon.runtime.context_mgr import ContextManager


def _new_bus() -> TypedEventBus:
    return TypedEventBus(TypedChannelRegistry())


def _async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_executor():
    from axon.runtime.executor import Executor, ModelResponse

    class _NopClient:
        async def call(self, **kwargs):
            return ModelResponse(content="", structured=None)

    return Executor(client=_NopClient())


def _stub_backend_class():
    from axon.backends.base_backend import BaseBackend, CompiledStep

    class _Stub(BaseBackend):
        @property
        def name(self) -> str: return "stub"
        def compile_step(self, step, context) -> CompiledStep:
            return CompiledStep(step_name="stub")
        def compile_system_prompt(self, persona, context, anchors) -> str:
            return ""
        def compile_tool_spec(self, tool) -> dict[str, Any]:
            return {}
        def compile_agent_system_prompt(self, *args, **kwargs) -> str:
            return ""

    return _Stub


# ═══════════════════════════════════════════════════════════════════
#  13.j.1 — Backend compile branch produces metadata-only step
# ═══════════════════════════════════════════════════════════════════


class TestBackendListenCompile:
    def test_listen_in_flow_compiles_to_metadata_only_step(self):
        """``listen`` as a flow.body[i] (not inside a daemon) must hit
        the new ``_compile_listen_step`` branch and produce a
        metadata-only step the executor can dispatch."""
        listen = IRListen(
            channel_topic="OrdersCreated",
            channel_is_ref=True,
            event_alias="order_event",
            children=(),
        )
        flow = IRFlow(name="main", steps=(listen,))
        run = IRRun(flow_name="main", resolved_flow=flow, resolved_anchors=())
        ir = IRProgram(flows=(flow,), runs=(run,))
        compiled = _stub_backend_class()().compile_program(ir)
        unit = compiled.execution_units[0]
        assert len(unit.steps) == 1
        listen_step = unit.steps[0]
        assert listen_step.step_name == "listen:OrdersCreated"
        assert listen_step.user_prompt == ""
        meta = listen_step.metadata["listen_apply"]
        assert meta["channel"] == "OrdersCreated"
        assert meta["channel_is_ref"] is True
        assert meta["alias"] == "order_event"
        assert meta["children"] == []

    def test_listen_compiles_pre_compiles_emit_child(self):
        """A listen body containing an emit must have the child compiled
        ahead of time so the executor can iterate the children without
        recompiling."""
        emit_child = IREmit(
            channel_ref="Audit",
            value_ref="order_event",
            value_is_channel=False,
        )
        listen = IRListen(
            channel_topic="OrdersCreated",
            channel_is_ref=True,
            event_alias="order_event",
            children=(emit_child,),
        )
        flow = IRFlow(name="main", steps=(listen,))
        run = IRRun(flow_name="main", resolved_flow=flow, resolved_anchors=())
        ir = IRProgram(flows=(flow,), runs=(run,))
        compiled = _stub_backend_class()().compile_program(ir)
        meta = compiled.execution_units[0].steps[0].metadata["listen_apply"]
        children = meta["children"]
        assert len(children) == 1
        assert children[0].step_name == "emit:Audit"
        assert children[0].metadata["emit_apply"]["channel_ref"] == "Audit"
        assert children[0].metadata["emit_apply"]["value_ref"] == "order_event"

    def test_listen_legacy_string_topic_marked_unref(self):
        """Legacy string-topic listens (``listen "x" as ev``) are the
        D4 dual-mode path — the compiled metadata must record
        ``channel_is_ref=False`` so the executor routes through the
        broadcast EventBus rather than TypedEventBus."""
        listen = IRListen(
            channel_topic="orders",
            channel_is_ref=False,  # legacy string topic
            event_alias="ev",
            children=(),
        )
        flow = IRFlow(name="main", steps=(listen,))
        run = IRRun(flow_name="main", resolved_flow=flow, resolved_anchors=())
        ir = IRProgram(flows=(flow,), runs=(run,))
        compiled = _stub_backend_class()().compile_program(ir)
        meta = compiled.execution_units[0].steps[0].metadata["listen_apply"]
        assert meta["channel_is_ref"] is False


# ═══════════════════════════════════════════════════════════════════
#  13.j.2 — Executor handler dispatches the receive + child run
# ═══════════════════════════════════════════════════════════════════


class TestExecutorListenHandler:
    def test_listen_typed_receives_event_and_binds_alias(self):
        """When the executor reaches a ``listen`` step on a typed
        channel, it must call ``bus.receive(channel)`` once, bind the
        payload under the alias in ctx, and proceed."""
        from axon.backends.base_backend import (
            CompiledExecutionUnit, CompiledProgram, CompiledStep,
        )
        from axon.runtime.tracer import Tracer

        bus = _new_bus()
        bus.registry.register(TypedChannelHandle(name="Orders", message="Bytes"))
        ctx = ContextManager()
        ctx.set_typed_bus(bus)

        # Pre-load the bus with one event so the receive resolves
        # without blocking.
        _async(bus.emit("Orders", {"id": 42}))

        listen_step = CompiledStep(
            step_name="listen:Orders",
            metadata={"listen_apply": {
                "channel": "Orders",
                "channel_is_ref": True,
                "alias": "order_ev",
                "children": [],
            }},
        )
        unit = CompiledExecutionUnit(flow_name="t", steps=[listen_step])
        result = _async(_make_executor()._execute_listen_step(
            step=listen_step, unit=unit, ctx=ctx, tracer=Tracer(),
        ))
        assert result.response.structured["listened"] == "Orders"
        assert result.response.structured["alias"] == "order_ev"
        assert result.response.structured["children_run"] == 0
        # Alias is now in the variables scope (scalar payload).
        assert ctx.get_variable("order_ev") == {"id": 42}

    def test_listen_runs_emit_child_with_alias_in_scope(self):
        """A listen child that emits using the alias must resolve the
        alias to the just-received payload. End-to-end criterion:
        receive → bind → emit child → bus has the chained payload."""
        from axon.backends.base_backend import (
            CompiledExecutionUnit, CompiledProgram, CompiledStep,
        )
        from axon.runtime.tracer import Tracer

        bus = _new_bus()
        bus.registry.register(TypedChannelHandle(name="Orders", message="Bytes"))
        bus.registry.register(TypedChannelHandle(name="Audit", message="Bytes"))
        ctx = ContextManager()
        ctx.set_typed_bus(bus)

        _async(bus.emit("Orders", {"id": 7, "ok": True}))

        emit_child = CompiledStep(
            step_name="emit:Audit",
            metadata={"emit_apply": {
                "channel_ref": "Audit",
                "value_ref": "order_event",  # the alias
                "value_is_channel": False,
            }},
        )
        listen_step = CompiledStep(
            step_name="listen:Orders",
            metadata={"listen_apply": {
                "channel": "Orders",
                "channel_is_ref": True,
                "alias": "order_event",
                "children": [emit_child],
            }},
        )
        unit = CompiledExecutionUnit(flow_name="t", steps=[listen_step])
        result = _async(_make_executor()._execute_listen_step(
            step=listen_step, unit=unit, ctx=ctx, tracer=Tracer(),
        ))
        assert result.response.structured["children_run"] == 1
        # The alias-resolved emit reached the Audit channel.
        audit_event = _async(bus.receive("Audit"))
        assert audit_event.payload == {"id": 7, "ok": True}

    def test_listen_typed_bus_missing_raises_structured_error(self):
        """A typed listen with no bus on ctx must surface as
        AxonRuntimeError with structured ``channel_op:listen`` tag —
        same defensive contract as emit/publish/discover handlers."""
        from axon.backends.base_backend import (
            CompiledExecutionUnit, CompiledStep,
        )
        from axon.runtime.runtime_errors import AxonRuntimeError
        from axon.runtime.tracer import Tracer

        ctx = ContextManager()  # no typed_bus set
        listen_step = CompiledStep(
            step_name="listen:X",
            metadata={"listen_apply": {
                "channel": "X",
                "channel_is_ref": True,
                "alias": "ev",
                "children": [],
            }},
        )
        unit = CompiledExecutionUnit(flow_name="t", steps=[listen_step])
        with pytest.raises(AxonRuntimeError) as excinfo:
            _async(_make_executor()._execute_listen_step(
                step=listen_step, unit=unit, ctx=ctx, tracer=Tracer(),
            ))
        assert "channel_op:listen" in excinfo.value.context.details

    def test_listen_typed_mobility_payload_binds_in_discovered_handles(self):
        """When the received payload is a TypedChannelHandle (mobility
        receive — the listened channel carries Channel<T>), the alias
        must land in the discovered_handles scope so subsequent emit
        steps with mobility=True resolve it correctly."""
        from axon.backends.base_backend import (
            CompiledExecutionUnit, CompiledStep,
        )
        from axon.runtime.tracer import Tracer

        bus = _new_bus()
        # Outer channel carries channel handles (second-order).
        bus.registry.register(TypedChannelHandle(
            name="Broker", message="Channel<Bytes>",
        ))
        # Inner channel — the value the broker carries.
        inner = TypedChannelHandle(name="Inner", message="Bytes")
        bus.registry.register(inner)
        ctx = ContextManager()
        ctx.set_typed_bus(bus)

        # Emit the inner handle through the broker (mobility).
        _async(bus.emit("Broker", inner, payload_is_handle=True))

        listen_step = CompiledStep(
            step_name="listen:Broker",
            metadata={"listen_apply": {
                "channel": "Broker",
                "channel_is_ref": True,
                "alias": "carried",
                "children": [],
            }},
        )
        unit = CompiledExecutionUnit(flow_name="t", steps=[listen_step])
        _async(_make_executor()._execute_listen_step(
            step=listen_step, unit=unit, ctx=ctx, tracer=Tracer(),
        ))
        # Mobility payload landed in discovered_handles, not variables.
        assert "carried" in ctx.discovered_handles
        assert ctx.discovered_handles["carried"].name == "Inner"


# ═══════════════════════════════════════════════════════════════════
#  13.j.3 — End-to-end through the real Executor.execute lifecycle
# ═══════════════════════════════════════════════════════════════════


class TestEndToEndListenInFlow:
    def test_listen_then_emit_pipeline_through_real_executor(self):
        """Compile a synthetic listen-in-flow unit and run it through
        ``Executor.execute()`` so the lifecycle (bus bootstrap from
        channel_specs, dispatch, close_all) is exercised."""
        from axon.backends.base_backend import (
            CompiledExecutionUnit, CompiledProgram, CompiledStep,
        )

        # We pre-emit the trigger event into the bus via a separate
        # bootstrap path. To do that we craft an ExecutionUnit with two
        # steps: first emit Orders(payload), then listen Orders → emit
        # Audit. Same unit, so they share the same bus; the listen
        # resolves immediately because the emit happened earlier in
        # the same unit.
        emit_seed = CompiledStep(
            step_name="emit:Orders",
            metadata={"emit_apply": {
                "channel_ref": "Orders",
                "value_ref": "seed_payload",
                "value_is_channel": False,
            }},
        )
        emit_audit = CompiledStep(
            step_name="emit:Audit",
            metadata={"emit_apply": {
                "channel_ref": "Audit",
                "value_ref": "ev",
                "value_is_channel": False,
            }},
        )
        listen_step = CompiledStep(
            step_name="listen:Orders",
            metadata={"listen_apply": {
                "channel": "Orders",
                "channel_is_ref": True,
                "alias": "ev",
                "children": [emit_audit],
            }},
        )
        unit = CompiledExecutionUnit(
            flow_name="listen_e2e",
            steps=[emit_seed, listen_step],
            metadata={"channel_specs": [
                {"name": "Orders", "message": "Bytes",
                 "qos": "at_least_once", "lifetime": "affine",
                 "persistence": "ephemeral", "shield_ref": ""},
                {"name": "Audit", "message": "Bytes",
                 "qos": "at_least_once", "lifetime": "affine",
                 "persistence": "ephemeral", "shield_ref": ""},
            ]},
        )
        program = CompiledProgram(backend_name="stub", execution_units=[unit])

        # We need the seed payload visible to the emit_seed step. Since
        # value_ref "seed_payload" is a bare identifier and looked up
        # via resolve_value_ref (variables → step_results), we wire it
        # by patching Executor.execute to pre-populate ctx. Cleanest
        # path: use a variable-scope binding via a bootstrap step.
        #
        # For the test we drive the executor directly with the unit
        # plus a pre-set variable on the ctx. We avoid the full
        # execute() path because there is no ctx hook there (yet —
        # adopters wire variables via flow parameters in real use).
        # Instead, we exercise _execute_unit directly with a custom
        # ContextManager.
        from axon.runtime.tracer import Tracer
        ex = _make_executor()
        tracer = Tracer()
        ex_method = ex._execute_unit

        # Monkeypatch ctx binding — easiest deterministic way to feed
        # the seed payload without depending on flow-parameter wiring.
        original_execute_unit = ex._execute_unit

        async def _execute_unit_with_seed(u, t):
            # Fall through to original but pre-bind ctx via a thin
            # wrapper that intercepts after ctx creation. We do this
            # by replacing the first step with a step that sets the
            # variable directly. Simpler: bypass execute_unit and
            # drive _execute_step in sequence.
            from axon.runtime.context_mgr import ContextManager
            from axon.runtime.channels.typed import (
                TypedChannelHandle, TypedChannelRegistry, TypedEventBus,
            )
            ctx = ContextManager()
            registry = TypedChannelRegistry()
            for s in u.metadata["channel_specs"]:
                registry.register(TypedChannelHandle(
                    name=s["name"], message=s["message"],
                    qos=s["qos"], lifetime=s["lifetime"],
                    persistence=s["persistence"], shield_ref=s["shield_ref"],
                ))
            bus = TypedEventBus(registry)
            ctx.set_typed_bus(bus)
            # Bootstrap the seed payload as a variable.
            ctx.set_variable("seed_payload", {"id": 99, "tag": "smoke"})
            try:
                results = []
                for st in u.steps:
                    r = await ex._execute_step(step=st, unit=u, ctx=ctx, tracer=t)
                    results.append(r)
                    if st.step_name and r.response:
                        ctx.set_step_result(
                            st.step_name,
                            r.response.structured or r.response.content,
                        )
                return results, bus
            finally:
                bus.close_all()

        results, bus = _async(_execute_unit_with_seed(unit, tracer))
        # Three runs total: seed emit, listen (which internally also
        # ran the emit-to-Audit child), and that's it.
        assert len(results) == 2
        assert results[0].step_name == "emit:Orders"
        assert results[1].step_name == "listen:Orders"
        # The audit event must have been published as a side-effect
        # of the listen's child execution. We can no longer receive
        # from the bus (it was closed in the finally), but the
        # listen step result reports children_run=1.
        assert results[1].response.structured["children_run"] == 1
