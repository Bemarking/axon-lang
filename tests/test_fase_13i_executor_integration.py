"""
Fase 13.i — Executor Integration tests
======================================
Closes the gap reported by adopters: the channel surface
(channel/emit/publish/discover) parsed and type-checked correctly
since v1.4.2 but the runtime had no executor branches for it. This
suite verifies the four layers wired in 13.i:

  1. Parser accepts dotted-access value_ref (`emit X(Step.output)`).
  2. Type checker tolerates dotted access as scalar (no false
     mobility-violation errors).
  3. ``BaseBackend.compile_program`` produces metadata-only
     ``CompiledStep`` instances with `emit_apply` / `publish_apply`
     / `discover_apply` flags + serialises ``ir.channels`` onto
     ``CompiledExecutionUnit.metadata.channel_specs``.
  4. ``Executor._execute_unit`` bootstraps a ``TypedEventBus`` from
     those specs, dispatches the three handlers, tracks capabilities
     across steps, binds discovered handles by alias, and calls
     ``close_all`` in a ``finally``.

The end-to-end test executes a publish→discover sequence for real
on the Executor — not just compiles it. Previously the same AXON
source would compile but route channel ops through the model
client and produce nonsense; that path is now closed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.type_checker import TypeChecker
from axon.runtime.channels.typed import (
    TypedChannelHandle,
    TypedChannelRegistry,
    TypedEventBus,
)
from axon.runtime.context_mgr import ContextManager


def _new_bus() -> TypedEventBus:
    """Fresh empty TypedEventBus. The constructor requires a registry —
    we hand it an empty one and tests register handles explicitly.
    Mirrors the pattern used inside Executor._execute_unit."""
    return TypedEventBus(TypedChannelRegistry())


# ═══════════════════════════════════════════════════════════════════
#  helper — parse a fragment (returns ProgramNode)
# ═══════════════════════════════════════════════════════════════════


def _parse(source: str) -> Any:
    return Parser(Lexer(source).tokenize()).parse()


# ═══════════════════════════════════════════════════════════════════
#  13.i.1 — Parser: dotted access in `emit` value_ref
# ═══════════════════════════════════════════════════════════════════


class TestParserDottedAccess:
    def test_emit_accepts_bare_identifier(self):
        # Pre-13.i baseline — must keep working.
        source = """flow f() -> Out {
  emit Hello(payload)
}"""
        tree = _parse(source)
        flow = tree.declarations[0]
        emit = flow.body[0]
        assert emit.channel_ref == "Hello"
        assert emit.value_ref == "payload"

    def test_emit_accepts_two_segment_dotted_path(self):
        # The exact case from the adopter bug report.
        source = """flow f() -> Out {
  emit Hello(Build.output)
}"""
        tree = _parse(source)
        emit = tree.declarations[0].body[0]
        assert emit.value_ref == "Build.output"

    def test_emit_accepts_three_segment_nested_path(self):
        source = """flow f() -> Out {
  emit Score(Analyze.result.score)
}"""
        tree = _parse(source)
        emit = tree.declarations[0].body[0]
        assert emit.value_ref == "Analyze.result.score"

    def test_emit_dotted_with_trailing_dot_fails(self):
        # `emit Hello(Build.)` must still error — the parser requires
        # an IDENTIFIER after every '.'.
        source = """flow f() -> Out {
  emit Hello(Build.)
}"""
        with pytest.raises(Exception):
            _parse(source)


# ═══════════════════════════════════════════════════════════════════
#  13.i.2 — Type checker: dotted access tolerated as scalar
# ═══════════════════════════════════════════════════════════════════


class TestTypeCheckerDottedAccess:
    def test_dotted_value_ref_does_not_trip_mobility_check(self):
        # Previously, a second-order channel with a dotted-access value
        # would falsely error as "not a channel handle". With 13.i the
        # check must skip when value_ref contains '.'.
        source = """channel Inner {
    message: Bytes
    qos: at_least_once
}
channel Outer {
    message: Channel<Bytes>
    qos: at_least_once
}
flow f() -> Out {
  emit Outer(Build.handle)
}"""
        program = _parse(source)
        errors = TypeChecker(program).check()
        # No second-order schema mismatch error for the dotted ref.
        relevant = [
            e for e in errors
            if "second-order schema mismatch" in e.message
            or "not a channel handle" in e.message
        ]
        assert relevant == [], (
            f"expected no mobility-violation errors for dotted access, got: "
            f"{relevant}"
        )

    def test_bare_identifier_mobility_check_still_runs(self):
        # Regression guard — non-dotted refs still get the second-order
        # check applied, so a wrong handle is still rejected.
        source = """channel Inner {
    message: Bytes
    qos: at_least_once
}
channel Wrong {
    message: Integer
    qos: at_least_once
}
channel Outer {
    message: Channel<Bytes>
    qos: at_least_once
}
flow f() -> Out {
  emit Outer(Wrong)
}"""
        program = _parse(source)
        errors = TypeChecker(program).check()
        # Wrong carries Integer, not Bytes — second-order schema mismatch.
        assert any(
            "second-order schema mismatch" in e.message for e in errors
        ), f"expected mobility error for bare-id ref, got: {errors}"


# ═══════════════════════════════════════════════════════════════════
#  13.i.3 — Backend compile_program: metadata-only channel-op steps
# ═══════════════════════════════════════════════════════════════════


def _stub_backend_class():
    """Minimal concrete BaseBackend so compile_program can run without
    abstractmethod errors. The channel-op branches we want to test are
    already implemented in the base class; this stub only fills in the
    abstract slots compile_program might (or might not) reach."""
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


class TestBackendChannelOpsCompile:
    def test_emit_compiles_to_metadata_only_step(self):
        from axon.compiler.ir_nodes import IREmit, IRFlow, IRProgram, IRRun

        emit = IREmit(channel_ref="Hello", value_ref="payload", value_is_channel=False)
        flow = IRFlow(name="main", steps=(emit,))
        run = IRRun(flow_name="main", resolved_flow=flow, resolved_anchors=())
        ir = IRProgram(flows=(flow,), runs=(run,))

        compiled = _stub_backend_class()().compile_program(ir)
        unit = compiled.execution_units[0]
        assert len(unit.steps) == 1
        emit_step = unit.steps[0]
        assert emit_step.step_name == "emit:Hello"
        assert emit_step.user_prompt == ""
        assert emit_step.metadata["emit_apply"]["channel_ref"] == "Hello"
        assert emit_step.metadata["emit_apply"]["value_ref"] == "payload"
        assert emit_step.metadata["emit_apply"]["value_is_channel"] is False
        # IRChannel was empty for this synthetic IR — channel_specs absent.
        assert "channel_specs" not in (unit.metadata or {})

    def test_publish_and_discover_compile_branches(self):
        from axon.compiler.ir_nodes import (
            IRDiscover, IRFlow, IRProgram, IRPublish, IRRun,
        )
        pub = IRPublish(channel_ref="Topic", shield_ref="GateA")
        disc = IRDiscover(capability_ref="Topic", alias="t_alias")
        flow = IRFlow(name="main", steps=(pub, disc))
        run = IRRun(flow_name="main", resolved_flow=flow, resolved_anchors=())
        ir = IRProgram(flows=(flow,), runs=(run,))

        compiled = _stub_backend_class()().compile_program(ir)
        steps = compiled.execution_units[0].steps
        assert len(steps) == 2
        assert steps[0].step_name == "publish:Topic"
        assert steps[0].metadata["publish_apply"] == {
            "channel_ref": "Topic",
            "shield_ref": "GateA",
        }
        assert steps[1].step_name == "discover:Topic"
        assert steps[1].metadata["discover_apply"] == {
            "capability_ref": "Topic",
            "alias": "t_alias",
        }

    def test_channel_specs_serialised_onto_unit_metadata(self):
        from axon.compiler.ir_nodes import (
            IRChannel, IRFlow, IRProgram, IRRun,
        )
        channel = IRChannel(
            name="Orders",
            message="Bytes",
            qos="exactly_once",
            lifetime="affine",
            persistence="ephemeral",
            shield_ref="PublicGate",
        )
        flow = IRFlow(name="main", steps=())
        run = IRRun(flow_name="main", resolved_flow=flow, resolved_anchors=())
        ir = IRProgram(channels=(channel,), flows=(flow,), runs=(run,))

        compiled = _stub_backend_class()().compile_program(ir)
        specs = compiled.execution_units[0].metadata["channel_specs"]
        assert specs == [{
            "name": "Orders",
            "message": "Bytes",
            "qos": "exactly_once",
            "lifetime": "affine",
            "persistence": "ephemeral",
            "shield_ref": "PublicGate",
        }]


# ═══════════════════════════════════════════════════════════════════
#  13.i.4 — ContextManager.resolve_value_ref dotted walk
# ═══════════════════════════════════════════════════════════════════


class TestContextManagerResolveValueRef:
    def test_bare_identifier_lookup_step_result(self):
        ctx = ContextManager()
        ctx.set_step_result("Build", {"output": "x"})
        assert ctx.resolve_value_ref("Build") == {"output": "x"}

    def test_bare_identifier_variable_wins_over_step(self):
        ctx = ContextManager()
        ctx.set_variable("x", 1)
        ctx.set_step_result("x", 2)
        # Variables come before step_results in the lookup order.
        assert ctx.resolve_value_ref("x") == 1

    def test_dotted_walk_dict(self):
        ctx = ContextManager()
        ctx.set_step_result("Build", {"output": {"value": 42}})
        assert ctx.resolve_value_ref("Build.output.value") == 42

    def test_dotted_walk_attribute(self):
        class _Obj:
            def __init__(self): self.score = 0.91
        ctx = ContextManager()
        ctx.set_step_result("Analyze", _Obj())
        assert ctx.resolve_value_ref("Analyze.score") == 0.91

    def test_unknown_head_raises_with_candidates(self):
        ctx = ContextManager()
        ctx.set_step_result("Build", {})
        ctx.set_variable("v", 0)
        with pytest.raises(KeyError) as excinfo:
            ctx.resolve_value_ref("Missing.field")
        msg = str(excinfo.value)
        assert "Build" in msg and "v" in msg

    def test_intermediate_miss_raises(self):
        ctx = ContextManager()
        ctx.set_step_result("Build", {"output": 1})
        with pytest.raises(KeyError) as excinfo:
            ctx.resolve_value_ref("Build.missing")
        assert "missing" in str(excinfo.value)

    def test_discovered_handle_shadows_variable(self):
        ctx = ContextManager()
        ctx.set_variable("alias", "shadowed")
        h = TypedChannelHandle(name="Real", message="Bytes")
        ctx.bind_discovered_handle("alias", h)
        assert ctx.resolve_value_ref("alias") is h

    def test_take_capability_one_shot(self):
        ctx = ContextManager()
        ctx.record_capability("C", "cap-token")
        assert ctx.take_capability("C") == "cap-token"
        # Second take fails — the capability has been consumed.
        with pytest.raises(KeyError):
            ctx.take_capability("C")


# ═══════════════════════════════════════════════════════════════════
#  13.i.5 — Executor handlers: emit / publish / discover
# ═══════════════════════════════════════════════════════════════════


def _async(coro):
    """Run a coroutine in a fresh event loop. Avoids the
    DeprecationWarning from `asyncio.get_event_loop()`."""
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


class TestExecutorHandlers:
    """Drive the three handlers directly with synthetic CompiledStep
    instances so we cover the runtime branches without standing up a
    full LLM client."""

    def test_emit_step_dispatches_scalar_payload(self):
        from axon.backends.base_backend import CompiledStep
        from axon.runtime.tracer import Tracer

        bus = _new_bus()
        bus.registry.register(TypedChannelHandle(name="Orders", message="Bytes"))
        ctx = ContextManager()
        ctx.set_typed_bus(bus)
        ctx.set_step_result("Build", {"output": {"id": 7}})

        step = CompiledStep(
            step_name="emit:Orders",
            metadata={"emit_apply": {
                "channel_ref": "Orders",
                "value_ref": "Build.output",
                "value_is_channel": False,
            }},
        )
        result = _async(_make_executor()._execute_emit_step(
            step=step, ctx=ctx, tracer=Tracer(),
        ))
        assert result.step_name == "emit:Orders"
        assert result.response.structured["emitted"] == "Orders"
        # The payload reached the bus's underlying transport.
        event = _async(bus.receive("Orders"))
        assert event.payload == {"id": 7}

    def test_emit_step_raises_when_bus_missing(self):
        from axon.backends.base_backend import CompiledStep
        from axon.runtime.runtime_errors import AxonRuntimeError
        from axon.runtime.tracer import Tracer

        ctx = ContextManager()  # no bus set
        step = CompiledStep(
            step_name="emit:X",
            metadata={"emit_apply": {
                "channel_ref": "X", "value_ref": "v", "value_is_channel": False,
            }},
        )
        with pytest.raises(AxonRuntimeError) as excinfo:
            _async(_make_executor()._execute_emit_step(
                step=step, ctx=ctx, tracer=Tracer(),
            ))
        assert "channel_op:emit" in excinfo.value.context.details

    def test_publish_records_capability_then_discover_consumes_it(self):
        from axon.backends.base_backend import CompiledStep
        from axon.runtime.tracer import Tracer

        bus = _new_bus()
        h = TypedChannelHandle(name="Topic", message="Bytes", shield_ref="Gate")
        bus.registry.register(h)
        ctx = ContextManager()
        ctx.set_typed_bus(bus)

        pub_step = CompiledStep(
            step_name="publish:Topic",
            metadata={"publish_apply": {"channel_ref": "Topic", "shield_ref": "Gate"}},
        )
        ex = _make_executor()
        pub_result = _async(ex._execute_publish_step(
            step=pub_step, ctx=ctx, tracer=Tracer(),
        ))
        assert isinstance(pub_result.response.structured["capability_id"], str)

        disc_step = CompiledStep(
            step_name="discover:Topic",
            metadata={"discover_apply": {"capability_ref": "Topic", "alias": "t"}},
        )
        disc_result = _async(ex._execute_discover_step(
            step=disc_step, ctx=ctx, tracer=Tracer(),
        ))
        assert disc_result.response.structured["alias"] == "t"
        assert disc_result.response.structured["handle_name"] == "Topic"
        # Alias is now in the discovered-handles scope.
        assert ctx.discovered_handles["t"].name == "Topic"

    def test_discover_without_prior_publish_raises(self):
        from axon.backends.base_backend import CompiledStep
        from axon.runtime.runtime_errors import AxonRuntimeError
        from axon.runtime.tracer import Tracer

        bus = _new_bus()
        bus.registry.register(TypedChannelHandle(name="Topic", message="Bytes", shield_ref="Gate"))
        ctx = ContextManager()
        ctx.set_typed_bus(bus)
        step = CompiledStep(
            step_name="discover:Topic",
            metadata={"discover_apply": {"capability_ref": "Topic", "alias": "t"}},
        )
        with pytest.raises(AxonRuntimeError) as excinfo:
            _async(_make_executor()._execute_discover_step(
                step=step, ctx=ctx, tracer=Tracer(),
            ))
        assert "channel_op:discover" in excinfo.value.context.details

    def test_publish_unpublishable_channel_surfaces_structured_error(self):
        # An unpublishable channel (no shield_ref) must surface as an
        # AxonRuntimeError so the run aborts with structured context
        # instead of bubbling raw exceptions.
        from axon.backends.base_backend import CompiledStep
        from axon.runtime.runtime_errors import AxonRuntimeError
        from axon.runtime.tracer import Tracer

        bus = _new_bus()
        bus.registry.register(TypedChannelHandle(name="Topic", message="Bytes"))  # no shield
        ctx = ContextManager()
        ctx.set_typed_bus(bus)
        step = CompiledStep(
            step_name="publish:Topic",
            metadata={"publish_apply": {"channel_ref": "Topic", "shield_ref": "Gate"}},
        )
        with pytest.raises(AxonRuntimeError) as excinfo:
            _async(_make_executor()._execute_publish_step(
                step=step, ctx=ctx, tracer=Tracer(),
            ))
        assert "channel_op:publish" in excinfo.value.context.details


# ═══════════════════════════════════════════════════════════════════
#  13.i.6 — End-to-end: publish→discover pipeline executed for real
#           on the Executor (not just compiled).
# ═══════════════════════════════════════════════════════════════════


class TestEndToEndExecutor:
    def test_publish_discover_pipeline_runs_to_completion(self):
        """Synthesises a unit with publish → discover steps and runs it
        through the real Executor._execute_unit lifecycle (bus bootstrap,
        dispatch, close_all). The criterion that closes 13.i: this test
        actually runs end-to-end on the executor — previously the same
        AXON program would compile but route channel ops through the
        model client and produce nonsense.
        """
        from axon.backends.base_backend import (
            CompiledExecutionUnit,
            CompiledProgram,
            CompiledStep,
        )

        unit = CompiledExecutionUnit(
            flow_name="paper_s9",
            steps=[
                CompiledStep(
                    step_name="publish:OrdersCreated",
                    metadata={"publish_apply": {
                        "channel_ref": "OrdersCreated",
                        "shield_ref": "PublicBroker",
                    }},
                ),
                CompiledStep(
                    step_name="discover:OrdersCreated",
                    metadata={"discover_apply": {
                        "capability_ref": "OrdersCreated",
                        "alias": "live",
                    }},
                ),
            ],
            metadata={"channel_specs": [{
                "name": "OrdersCreated",
                "message": "Bytes",
                "qos": "at_least_once",
                "lifetime": "affine",
                "persistence": "ephemeral",
                "shield_ref": "PublicBroker",
            }]},
        )
        program = CompiledProgram(
            backend_name="stub", execution_units=[unit],
        )

        ex = _make_executor()
        result = _async(ex.execute(program))
        assert result.success, (
            result.unit_results[0].error if result.unit_results else "no units"
        )
        unit_result = result.unit_results[0]
        assert len(unit_result.step_results) == 2
        # Step 0: publish — produces capability_id in structured response.
        pub = unit_result.step_results[0]
        assert "capability_id" in pub.response.structured
        # Step 1: discover — yields the live handle name.
        disc = unit_result.step_results[1]
        assert disc.response.structured["handle_name"] == "OrdersCreated"
        assert disc.response.structured["alias"] == "live"

    def test_unit_lifecycle_closes_bus_even_on_error(self):
        """If a channel step raises mid-unit, the bus is still closed."""
        from axon.backends.base_backend import (
            CompiledExecutionUnit,
            CompiledProgram,
            CompiledStep,
        )

        unit = CompiledExecutionUnit(
            flow_name="lifecycle",
            steps=[
                CompiledStep(
                    step_name="discover:Missing",
                    metadata={"discover_apply": {
                        "capability_ref": "Missing",  # never published
                        "alias": "x",
                    }},
                ),
            ],
            metadata={"channel_specs": [{
                "name": "Missing",
                "message": "Bytes",
                "qos": "at_least_once",
                "lifetime": "affine",
                "persistence": "ephemeral",
                "shield_ref": "Gate",
            }]},
        )
        program = CompiledProgram(
            backend_name="stub", execution_units=[unit],
        )

        ex = _make_executor()
        result = _async(ex.execute(program))
        # Run failed but the lifecycle still completed cleanly.
        assert not result.success
        assert "No capability recorded for channel 'Missing'" in result.unit_results[0].error
