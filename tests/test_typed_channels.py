"""
AXON Runtime — Typed Channels (Fase 13.d) — Unit Tests
========================================================
Verifies the runtime layer for `Channel<τ, q, ℓ, π>`:
  - registry bootstrap from IR (compiler ↔ runtime parity)
  - emit / publish / discover semantics
  - schema enforcement at runtime (defense-in-depth over D3)
  - capability gating (D8) and per-hop certainty bookkeeping
  - QoS variants (at_most_once, at_least_once, exactly_once,
    broadcast, queue)
  - lifetime accounting (linear/affine/persistent)
  - dual-mode coexistence with the legacy string-topic EventBus
"""

from __future__ import annotations

import asyncio

import pytest

from axon.compiler.ir_nodes import IRChannel, IRProgram
from axon.compiler.lexer import Lexer
from axon.compiler.parser import Parser
from axon.compiler.ir_generator import IRGenerator
from axon.runtime.event_bus import Event, EventBus
from axon.runtime.channels import (
    Capability,
    CapabilityGateError,
    ChannelNotFoundError,
    LifetimeViolationError,
    SchemaMismatchError,
    TypedChannelError,
    TypedChannelHandle,
    TypedChannelRegistry,
    TypedEventBus,
)


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────


def _ir(source: str) -> IRProgram:
    """Compile source → IRProgram for runtime bootstrap tests."""
    tokens = Lexer(source).tokenize()
    tree = Parser(tokens).parse()
    return IRGenerator().generate(tree)


def _handle(
    name: str,
    message: str = "Order",
    qos: str = "at_least_once",
    lifetime: str = "affine",
    persistence: str = "ephemeral",
    shield_ref: str = "",
) -> TypedChannelHandle:
    return TypedChannelHandle(
        name=name,
        message=message,
        qos=qos,
        lifetime=lifetime,
        persistence=persistence,
        shield_ref=shield_ref,
    )


def _bus_with(*handles: TypedChannelHandle, **kwargs) -> TypedEventBus:
    reg = TypedChannelRegistry()
    for h in handles:
        reg.register(h)
    return TypedEventBus(reg, **kwargs)


# ────────────────────────────────────────────────────────────────────
# TestTypedChannelHandle — pure dataclass invariants
# ────────────────────────────────────────────────────────────────────


class TestTypedChannelHandle:
    """The handle preserves every static field needed for runtime dispatch."""

    def test_defaults_match_paper_d1(self):
        h = TypedChannelHandle(name="C", message="Order")
        assert h.qos == "at_least_once"
        assert h.lifetime == "affine"          # D1 — paper §3.1
        assert h.persistence == "ephemeral"
        assert h.shield_ref == ""
        assert h.consumed_count == 0

    def test_is_publishable_requires_shield(self):
        assert _handle("C").is_publishable is False
        assert _handle("C", shield_ref="Gate").is_publishable is True

    def test_carries_channel_detects_second_order(self):
        assert _handle("C", message="Order").carries_channel is False
        assert _handle("C", message="Channel<Order>").carries_channel is True
        assert _handle("C", message="Channel<Channel<Order>>").carries_channel is True

    def test_inner_message_unwraps_one_level(self):
        assert _handle("C", message="Order").inner_message_type() == "Order"
        assert _handle("C", message="Channel<Order>").inner_message_type() == "Order"
        assert (
            _handle("C", message="Channel<Channel<Order>>").inner_message_type()
            == "Channel<Order>"
        )


# ────────────────────────────────────────────────────────────────────
# TestTypedChannelRegistry — name → handle mapping
# ────────────────────────────────────────────────────────────────────


class TestTypedChannelRegistry:

    def test_register_and_get(self):
        reg = TypedChannelRegistry()
        h = _handle("C")
        reg.register(h)
        assert reg.has("C")
        assert reg.get("C") is h
        assert len(reg) == 1

    def test_get_unknown_raises(self):
        reg = TypedChannelRegistry()
        with pytest.raises(ChannelNotFoundError, match="not in TypedChannel"):
            reg.get("Bogus")

    def test_register_overwrites_same_name(self):
        reg = TypedChannelRegistry()
        h1 = _handle("C", message="Order")
        h2 = _handle("C", message="Invoice")
        reg.register(h1)
        reg.register(h2)
        assert reg.get("C") is h2
        assert len(reg) == 1

    def test_names_returns_sorted_list(self):
        reg = TypedChannelRegistry()
        for name in ("Gamma", "Alpha", "Beta"):
            reg.register(_handle(name))
        assert reg.names() == ["Alpha", "Beta", "Gamma"]

    def test_register_from_ir_channel(self):
        reg = TypedChannelRegistry()
        ir_ch = IRChannel(
            name="C", message="Order", qos="exactly_once",
            lifetime="linear", persistence="persistent_axonstore",
            shield_ref="Gate",
        )
        h = reg.register_from_ir_channel(ir_ch)
        assert h.name == "C"
        assert h.message == "Order"
        assert h.qos == "exactly_once"
        assert h.lifetime == "linear"
        assert h.persistence == "persistent_axonstore"
        assert h.shield_ref == "Gate"


# ────────────────────────────────────────────────────────────────────
# TestTypedEventBusBootstrap — bus creation from IR
# ────────────────────────────────────────────────────────────────────


class TestTypedEventBusBootstrap:

    def test_from_ir_program_registers_all_channels(self):
        ir = _ir('''
type Order { id: String }
channel A { message: Order }
channel B { message: Order qos: broadcast }
channel C { message: Channel<Order> }
''')
        bus = TypedEventBus.from_ir_program(ir)
        assert bus.registry.names() == ["A", "B", "C"]

    def test_underlying_event_bus_accessible(self):
        bus = _bus_with(_handle("C"))
        assert isinstance(bus.underlying, EventBus)

    def test_bootstrap_with_custom_underlying_bus(self):
        underlying = EventBus()
        bus = _bus_with(_handle("C"), underlying=underlying)
        assert bus.underlying is underlying


# ────────────────────────────────────────────────────────────────────
# TestEmit — Chan-Output and scalar payloads
# ────────────────────────────────────────────────────────────────────


class TestEmit:

    @pytest.mark.asyncio
    async def test_emit_scalar_then_receive(self):
        bus = _bus_with(_handle("C"))
        await bus.emit("C", {"id": "O-1"})
        ev = await bus.receive("C")
        assert ev.topic == "C"
        assert ev.payload == {"id": "O-1"}

    @pytest.mark.asyncio
    async def test_emit_unknown_channel_raises(self):
        bus = _bus_with(_handle("C"))
        with pytest.raises(ChannelNotFoundError):
            await bus.emit("Bogus", "payload")

    @pytest.mark.asyncio
    async def test_emit_assigns_event_id_and_timestamp(self):
        bus = _bus_with(_handle("C"))
        await bus.emit("C", "x")
        ev = await bus.receive("C")
        assert ev.event_id != ""
        assert ev.timestamp > 0


# ────────────────────────────────────────────────────────────────────
# TestEmitMobility — second-order Chan-Mobility (paper §3.2)
# ────────────────────────────────────────────────────────────────────


class TestEmitMobility:

    @pytest.mark.asyncio
    async def test_emit_handle_through_second_order_channel(self):
        inner = _handle("Inner", message="Order")
        outer = _handle("Outer", message="Channel<Order>")
        bus = _bus_with(inner, outer)
        await bus.emit("Outer", inner, payload_is_handle=True)
        ev = await bus.receive("Outer")
        assert isinstance(ev.payload, TypedChannelHandle)
        assert ev.payload.name == "Inner"

    @pytest.mark.asyncio
    async def test_emit_mobility_inner_schema_mismatch_rejected(self):
        wrong = _handle("Wrong", message="Other")
        outer = _handle("Outer", message="Channel<Order>")
        bus = _bus_with(wrong, outer)
        with pytest.raises(SchemaMismatchError, match="second-order schema"):
            await bus.emit("Outer", wrong, payload_is_handle=True)

    @pytest.mark.asyncio
    async def test_emit_handle_to_first_order_channel_rejected(self):
        inner = _handle("Inner", message="Order")
        first_order = _handle("Plain", message="Order")
        bus = _bus_with(inner, first_order)
        with pytest.raises(SchemaMismatchError, match="not second-order"):
            await bus.emit("Plain", inner, payload_is_handle=True)

    @pytest.mark.asyncio
    async def test_emit_scalar_to_second_order_channel_rejected(self):
        outer = _handle("Outer", message="Channel<Order>")
        bus = _bus_with(outer)
        with pytest.raises(SchemaMismatchError, match="payload_is_handle"):
            await bus.emit("Outer", {"id": "X"})

    @pytest.mark.asyncio
    async def test_emit_with_handle_flag_but_non_handle_payload_rejected(self):
        outer = _handle("Outer", message="Channel<Order>")
        bus = _bus_with(outer)
        with pytest.raises(SchemaMismatchError, match="not.*TypedChannelHandle"):
            await bus.emit("Outer", "not a handle", payload_is_handle=True)


# ────────────────────────────────────────────────────────────────────
# TestPublish — capability extrusion (D8, paper §4.3)
# ────────────────────────────────────────────────────────────────────


class TestPublish:

    @pytest.mark.asyncio
    async def test_publish_returns_capability(self):
        bus = _bus_with(_handle("C", shield_ref="Gate"))
        cap = await bus.publish("C", shield="Gate")
        assert isinstance(cap, Capability)
        assert cap.channel_name == "C"
        assert cap.shield_ref == "Gate"
        assert cap.capability_id != ""

    @pytest.mark.asyncio
    async def test_publish_empty_shield_rejected(self):
        bus = _bus_with(_handle("C", shield_ref="Gate"))
        with pytest.raises(CapabilityGateError, match="non-empty shield"):
            await bus.publish("C", shield="")

    @pytest.mark.asyncio
    async def test_publish_unpublishable_channel_rejected(self):
        bus = _bus_with(_handle("C"))
        with pytest.raises(CapabilityGateError, match="not publishable"):
            await bus.publish("C", shield="Gate")

    @pytest.mark.asyncio
    async def test_publish_wrong_shield_rejected(self):
        bus = _bus_with(_handle("C", shield_ref="GateA"))
        with pytest.raises(CapabilityGateError, match="GateA"):
            await bus.publish("C", shield="GateB")

    @pytest.mark.asyncio
    async def test_publish_unknown_channel_raises(self):
        bus = _bus_with(_handle("C", shield_ref="Gate"))
        with pytest.raises(ChannelNotFoundError):
            await bus.publish("Bogus", shield="Gate")

    @pytest.mark.asyncio
    async def test_capability_carries_default_delta_pub(self):
        """Default δ_pub = 0.05 per hop — paper §3.4 lower bound."""
        bus = _bus_with(_handle("C", shield_ref="Gate"))
        cap = await bus.publish("C", shield="Gate")
        assert cap.delta_pub == pytest.approx(0.05)

    @pytest.mark.asyncio
    async def test_compliance_rejection_via_predicate(self):
        """Injected ShieldComplianceFn can veto publish at runtime."""
        seen: list[tuple[str, str]] = []

        def deny_all(shield: str, handle: TypedChannelHandle) -> bool:
            seen.append((shield, handle.name))
            return False

        bus = _bus_with(
            _handle("C", shield_ref="Gate"),
            compliance_check=deny_all,
        )
        with pytest.raises(CapabilityGateError, match="does not cover"):
            await bus.publish("C", shield="Gate")
        assert seen == [("Gate", "C")]

    @pytest.mark.asyncio
    async def test_compliance_predicate_can_inspect_handle(self):
        """Predicate has full handle visibility — paper §3.4 gate is
        implemented as a callback, not a fixed-shape κ list."""
        decisions: list[str] = []

        def covers_hipaa(shield: str, handle: TypedChannelHandle) -> bool:
            # Allow shield "HIPAAGate" for any handle whose message
            # mentions PHI; reject otherwise.
            decisions.append(handle.message)
            return shield == "HIPAAGate" and "PHI" in handle.message

        h = _handle("Health", message="PHI", shield_ref="HIPAAGate")
        bus = _bus_with(h, compliance_check=covers_hipaa)
        cap = await bus.publish("Health", shield="HIPAAGate")
        assert cap.channel_name == "Health"
        assert decisions == ["PHI"]


# ────────────────────────────────────────────────────────────────────
# TestDiscover — dual of publish
# ────────────────────────────────────────────────────────────────────


class TestDiscover:

    @pytest.mark.asyncio
    async def test_discover_returns_underlying_handle(self):
        h = _handle("C", shield_ref="Gate")
        bus = _bus_with(h)
        cap = await bus.publish("C", shield="Gate")
        recovered = await bus.discover(cap)
        assert recovered is h

    @pytest.mark.asyncio
    async def test_discover_consumes_capability(self):
        bus = _bus_with(_handle("C", shield_ref="Gate"))
        cap = await bus.publish("C", shield="Gate")
        assert bus.issued_capabilities() == 1
        await bus.discover(cap)
        assert bus.issued_capabilities() == 0

    @pytest.mark.asyncio
    async def test_discover_revoked_capability_rejected(self):
        bus = _bus_with(_handle("C", shield_ref="Gate"))
        cap = await bus.publish("C", shield="Gate")
        await bus.discover(cap)
        with pytest.raises(CapabilityGateError, match="revoked"):
            await bus.discover(cap)

    @pytest.mark.asyncio
    async def test_discover_forged_capability_rejected(self):
        bus = _bus_with(_handle("C", shield_ref="Gate"))
        forged = Capability(
            capability_id="forgery", channel_name="C", shield_ref="Gate",
        )
        with pytest.raises(CapabilityGateError, match="revoked|never issued"):
            await bus.discover(forged)


# ────────────────────────────────────────────────────────────────────
# TestQoS — five delivery semantics
# ────────────────────────────────────────────────────────────────────


class TestQoSAtLeastOnce:

    @pytest.mark.asyncio
    async def test_default_qos_is_at_least_once(self):
        bus = _bus_with(_handle("C"))
        await bus.emit("C", "x")
        ev = await bus.receive("C")
        assert ev.payload == "x"


class TestQoSAtMostOnce:

    @pytest.mark.asyncio
    async def test_at_most_once_delivers_when_queue_open(self):
        bus = _bus_with(_handle("C", qos="at_most_once"))
        await bus.emit("C", "x")
        ev = await bus.receive("C")
        assert ev.payload == "x"

    @pytest.mark.asyncio
    async def test_at_most_once_drops_silently_on_closed_channel(self):
        h = _handle("C", qos="at_most_once")
        bus = _bus_with(h)
        # Force a backing queue to exist, then close it.
        bus.underlying.get_or_create("C").close()
        # Should not raise — best-effort drop.
        await bus.emit("C", "x")


class TestQoSExactlyOnce:

    @pytest.mark.asyncio
    async def test_exactly_once_dedups_within_process(self):
        bus = _bus_with(_handle("C", qos="exactly_once"))
        ev = Event(topic="C", payload="dup", event_id="E-1")
        # Direct dispatch to bypass new event_id generation in emit().
        h = bus.registry.get("C")
        await bus._dispatch(h, ev)
        await bus._dispatch(h, ev)
        # Receive once; second await would block if dedup fails.
        first = await bus.receive("C")
        assert first.event_id == "E-1"
        assert bus.underlying.get_or_create("C").pending == 0  # type: ignore[attr-defined]


class TestQoSBroadcast:

    @pytest.mark.asyncio
    async def test_broadcast_fans_out_to_all_subscribers(self):
        bus = _bus_with(_handle("Bus", qos="broadcast"))
        s1 = bus.subscribe_broadcast("Bus")
        s2 = bus.subscribe_broadcast("Bus")
        s3 = bus.subscribe_broadcast("Bus")
        await bus.emit("Bus", "fan-out")
        evs = await asyncio.gather(s1.get(), s2.get(), s3.get())
        assert all(e.payload == "fan-out" for e in evs)

    @pytest.mark.asyncio
    async def test_broadcast_subscribe_on_non_broadcast_rejected(self):
        bus = _bus_with(_handle("C"))
        with pytest.raises(SchemaMismatchError, match="not broadcast"):
            bus.subscribe_broadcast("C")

    @pytest.mark.asyncio
    async def test_receive_on_broadcast_rejected(self):
        bus = _bus_with(_handle("Bus", qos="broadcast"))
        with pytest.raises(SchemaMismatchError, match="subscribe_broadcast"):
            await bus.receive("Bus")


class TestQoSQueue:

    @pytest.mark.asyncio
    async def test_queue_qos_delivers_fifo(self):
        bus = _bus_with(_handle("Q", qos="queue"))
        for n in range(3):
            await bus.emit("Q", n)
        out = [(await bus.receive("Q")).payload for _ in range(3)]
        assert out == [0, 1, 2]


# ────────────────────────────────────────────────────────────────────
# TestLifetime — affine / linear / persistent enforcement
# ────────────────────────────────────────────────────────────────────


class TestLifetime:

    @pytest.mark.asyncio
    async def test_affine_allows_multiple_emits_at_handle_level(self):
        """Affine handles permit multiple emit calls — per-binding
        affinity is tracked separately (deferred to 13.e)."""
        bus = _bus_with(_handle("C", lifetime="affine"))
        await bus.emit("C", 1)
        await bus.emit("C", 2)
        h = bus.registry.get("C")
        assert h.consumed_count == 2  # not an error

    @pytest.mark.asyncio
    async def test_linear_first_emit_ok_second_raises(self):
        bus = _bus_with(_handle("C", lifetime="linear"))
        await bus.emit("C", "first")
        with pytest.raises(LifetimeViolationError, match="exactly once"):
            await bus.emit("C", "second")

    @pytest.mark.asyncio
    async def test_persistent_unrestricted(self):
        bus = _bus_with(_handle("C", lifetime="persistent"))
        for _ in range(10):
            await bus.emit("C", "ok")
        h = bus.registry.get("C")
        assert h.consumed_count == 10  # no violation


# ────────────────────────────────────────────────────────────────────
# TestPaperExample — §9 worked example end-to-end
# ────────────────────────────────────────────────────────────────────


class TestPaperExampleE2E:

    @pytest.mark.asyncio
    async def test_paper_example_e2e_flow(self):
        """Producer publishes; consumer discovers; mobility carries
        the inner channel; broadcast fan-out works in concert."""
        ir = _ir('''
type Order { id: String }
shield PublicBroker { scan: [pii_leak] }

channel OrdersCreated {
  message: Order
  qos: at_least_once
  shield: PublicBroker
}

channel BrokerHandoff {
  message: Channel<Order>
  qos: exactly_once
  persistence: persistent_axonstore
}
''')
        bus = TypedEventBus.from_ir_program(ir)

        # Producer flow: emit channel-as-value through BrokerHandoff,
        # then publish OrdersCreated through PublicBroker.
        inner = bus.registry.get("OrdersCreated")
        await bus.emit("BrokerHandoff", inner, payload_is_handle=True)
        cap = await bus.publish("OrdersCreated", shield="PublicBroker")

        # Consumer side: receive the channel handle, then discover the
        # capability to recover the same handle.
        ev = await bus.receive("BrokerHandoff")
        carried = ev.payload
        assert isinstance(carried, TypedChannelHandle)
        assert carried.name == "OrdersCreated"

        recovered = await bus.discover(cap)
        assert recovered is inner

        # Publish + emit on the recovered handle continues to work
        # (handle is the same object — affinity is at consumption sites,
        #  not at re-acquisition; full per-binding tracking lands in 13.e).
        await bus.emit("OrdersCreated", {"id": "O-final"})
        delivered = await bus.receive("OrdersCreated")
        assert delivered.payload == {"id": "O-final"}


# ────────────────────────────────────────────────────────────────────
# TestErrorHierarchy — every Fase-13 runtime error inherits a base
# ────────────────────────────────────────────────────────────────────


class TestErrorHierarchy:

    def test_all_typed_errors_inherit_typed_channel_error(self):
        for cls in (
            ChannelNotFoundError,
            SchemaMismatchError,
            CapabilityGateError,
            LifetimeViolationError,
        ):
            assert issubclass(cls, TypedChannelError), cls

    def test_typed_channel_error_inherits_runtime_error(self):
        assert issubclass(TypedChannelError, RuntimeError)


# ────────────────────────────────────────────────────────────────────
# TestDualModeCoexistence — typed bus + legacy string topics (D4)
# ────────────────────────────────────────────────────────────────────


class TestDualModeCoexistence:

    @pytest.mark.asyncio
    async def test_typed_emit_does_not_block_legacy_string_topic_use(self):
        """The typed bus reuses the underlying EventBus; legacy callers
        hitting the same EventBus still see their string topics work."""
        underlying = EventBus()
        bus = _bus_with(_handle("Typed"), underlying=underlying)
        # Legacy path — bypass the typed surface entirely.
        legacy_event = Event(topic="legacy.x", payload="legacy")
        await underlying.publish("legacy.x", legacy_event)
        legacy_ch = underlying.get_or_create("legacy.x")
        ev = await legacy_ch.receive()
        assert ev.payload == "legacy"
        # Typed path on the same bus continues to work.
        await bus.emit("Typed", "typed-payload")
        typed_ev = await bus.receive("Typed")
        assert typed_ev.payload == "typed-payload"

    @pytest.mark.asyncio
    async def test_close_all_drains_capabilities_and_underlying(self):
        bus = _bus_with(_handle("C", shield_ref="Gate"))
        await bus.publish("C", shield="Gate")
        assert bus.issued_capabilities() == 1
        bus.close_all()
        assert bus.issued_capabilities() == 0


# ────────────────────────────────────────────────────────────────────
# TestEdgeCases — additional coverage
# ────────────────────────────────────────────────────────────────────


class TestEdgeCases:

    @pytest.mark.asyncio
    async def test_each_publish_yields_unique_capability_id(self):
        bus = _bus_with(_handle("C", shield_ref="Gate"))
        ids = {(await bus.publish("C", shield="Gate")).capability_id for _ in range(20)}
        assert len(ids) == 20

    @pytest.mark.asyncio
    async def test_capabilities_are_per_bus_instance(self):
        """A capability issued by one bus is unknown to another bus."""
        h_a = _handle("C", shield_ref="Gate")
        h_b = _handle("C", shield_ref="Gate")
        bus_a = _bus_with(h_a)
        bus_b = _bus_with(h_b)
        cap_a = await bus_a.publish("C", shield="Gate")
        with pytest.raises(CapabilityGateError, match="revoked|never issued"):
            await bus_b.discover(cap_a)

    @pytest.mark.asyncio
    async def test_lifetime_counter_isolated_per_handle(self):
        """Linear violation on one handle doesn't taint a sibling channel."""
        bus = _bus_with(
            _handle("L", lifetime="linear"),
            _handle("A", lifetime="affine"),
        )
        await bus.emit("L", "first")
        # Sibling unaffected; many emits on A still fine.
        for _ in range(5):
            await bus.emit("A", "ok")
        assert bus.registry.get("A").consumed_count == 5
        # And L is still in violation territory on second emit.
        with pytest.raises(LifetimeViolationError):
            await bus.emit("L", "second")

    def test_from_ir_program_preserves_all_metadata(self):
        ir = _ir('''
type Order { id: String }
shield Gate { scan: [pii_leak] }
channel C {
  message: Order
  qos: exactly_once
  lifetime: linear
  persistence: persistent_axonstore
  shield: Gate
}
''')
        bus = TypedEventBus.from_ir_program(ir)
        h = bus.registry.get("C")
        assert h.message == "Order"
        assert h.qos == "exactly_once"
        assert h.lifetime == "linear"
        assert h.persistence == "persistent_axonstore"
        assert h.shield_ref == "Gate"
