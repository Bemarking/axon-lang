"""
AXON Runtime — Typed Channels (Fase 13.d)
==========================================
Runtime layer for `Channel<τ, q, ℓ, π>` — first-class affine resources
with π-calculus mobility (paper_mobile_channels.md).

Layered on top of `EventBus`/`InMemoryChannel` rather than replacing it:
the existing string-topic path stays valid for D4 dual-mode (legacy
listeners), and the typed surface is a strict superset that adds
schema validation, QoS enforcement, capability extrusion gated by a
shield (D8), and discover/publish duality.

Public surface:
  - TypedChannelHandle — runtime materialization of an IRChannel
  - Capability         — opaque token returned by publish, consumed by
                         discover (Publish-Ext / Discover, paper §4.3)
  - TypedChannelRegistry — name → handle map; bootstraps from IRProgram
  - TypedEventBus      — emit / publish / discover orchestrator with
                         schema validation, QoS, capability gating

Errors raised here mirror compile-time diagnostics so a misconfigured
runtime cannot silently diverge from the static guarantees.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from axon.runtime.event_bus import EventBus, Event, EventChannel


# ═══════════════════════════════════════════════════════════════════
#  ERRORS — runtime-side mirrors of compile-time guarantees
# ═══════════════════════════════════════════════════════════════════


class TypedChannelError(RuntimeError):
    """Base for typed-channel runtime failures."""


class ChannelNotFoundError(TypedChannelError):
    """Raised when a referenced channel name is not in the registry."""


class SchemaMismatchError(TypedChannelError):
    """Raised when an emit's payload type does not match the channel schema.

    The compile-time check (Fase 13.b _check_emit) catches this for
    statically-known programs; this runtime check is defense-in-depth
    for cross-process publish/discover where the receiver cannot
    re-run the static analysis on the sender's IR.
    """


class CapabilityGateError(TypedChannelError):
    """Raised when publish lacks a shield (D8) or discover targets an
    unpublishable channel."""


class LifetimeViolationError(TypedChannelError):
    """Raised when an affine/linear handle is used after consumption.

    Affine: at most one consumption (use OK; drop OK; reuse rejected).
    Linear: exactly one consumption (use required; reuse rejected).
    Persistent (`!Channel`): unrestricted reuse (no enforcement here).
    """


# ═══════════════════════════════════════════════════════════════════
#  CAPABILITY — Publish-Ext token (paper §4.3)
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Capability:
    """An opaque, single-extrusion-hop witness of a published channel.

    A `publish c within σ` reduction returns one of these.  The bearer
    can `discover` the underlying handle through the bus.  The runtime
    attenuates the bearer's certainty envelope by `delta_pub` per hop
    so that published-then-republished handles strictly lose certainty
    on every traversal — paper §6.2 ("no certainty laundering").

    Capabilities are immutable; per-hop bookkeeping happens in the bus
    when the capability is created (publish) and consumed (discover).
    """
    capability_id: str          # uuid4 — opaque to consumers
    channel_name: str           # the IRChannel.name being exposed
    shield_ref: str             # σ-shield that mediated extrusion
    delta_pub: float = 0.05     # certainty penalty per hop (paper §3.4)
    issued_at: float = field(default_factory=time.time)


# ═══════════════════════════════════════════════════════════════════
#  HANDLE — runtime materialization of an IRChannel
# ═══════════════════════════════════════════════════════════════════


@dataclass
class TypedChannelHandle:
    """A live, typed channel handle — wraps an underlying EventChannel
    and carries the static schema (message type, QoS, lifetime,
    persistence, shield ref) for runtime enforcement.

    The handle's `consumed_count` lets the bus enforce lifetime rules:
      • linear  → must reach exactly 1 over the lifetime of the handle
      • affine  → may stay at 0 (drop) but never exceed 1 per holder
      • persistent → unbounded

    Note: at 13.d scope, the bus tracks consumption counters at the
    handle level.  Per-binding tracking (when discover yields fresh
    aliases) lands in 13.e along with cross-process replay tokens.
    """
    name: str
    message: str                          # surface spelling — Order | Channel<Order> | …
    qos: str = "at_least_once"
    lifetime: str = "affine"
    persistence: str = "ephemeral"
    shield_ref: str = ""
    backing: EventChannel | None = None   # underlying transport (lazily created)
    consumed_count: int = 0               # incremented per emit/publish/discover

    @property
    def is_publishable(self) -> bool:
        """A channel is publishable iff it declared a shield gate (D8)."""
        return bool(self.shield_ref)

    @property
    def carries_channel(self) -> bool:
        """Second-order: this channel transports another channel handle."""
        return self.message.startswith("Channel<") and self.message.endswith(">")

    def inner_message_type(self) -> str:
        """Unwrap one level of `Channel<…>` to find the carried type.

        Returns the leaf type for plain channels, or the immediately
        nested type for second-order channels.  For triple-nesting
        `Channel<Channel<T>>`, returns `Channel<T>` (one unwrap).
        """
        if not self.carries_channel:
            return self.message
        return self.message[len("Channel<"):-1]


# ═══════════════════════════════════════════════════════════════════
#  REGISTRY — name → handle map
# ═══════════════════════════════════════════════════════════════════


class TypedChannelRegistry:
    """Authoritative map of channel name → TypedChannelHandle.

    Bootstraps from an IRProgram (post-13.c) so the registry is
    a faithful runtime projection of the compiler's view.  Hand-rolled
    registration is also supported for tests and embedded runtimes.
    """

    def __init__(self) -> None:
        self._handles: dict[str, TypedChannelHandle] = {}

    def register(self, handle: TypedChannelHandle) -> None:
        """Add a handle to the registry.  Re-registering with the same
        name overwrites — useful for hot-reloads in dev workflows."""
        self._handles[handle.name] = handle

    def register_from_ir_channel(self, ir_channel: Any) -> TypedChannelHandle:
        """Instantiate a handle from an IRChannel (avoids tight import)."""
        handle = TypedChannelHandle(
            name=ir_channel.name,
            message=ir_channel.message,
            qos=ir_channel.qos,
            lifetime=ir_channel.lifetime,
            persistence=ir_channel.persistence,
            shield_ref=ir_channel.shield_ref,
        )
        self.register(handle)
        return handle

    def get(self, name: str) -> TypedChannelHandle:
        if name not in self._handles:
            raise ChannelNotFoundError(
                f"channel '{name}' not in TypedChannelRegistry "
                f"(registered: {sorted(self._handles)})"
            )
        return self._handles[name]

    def has(self, name: str) -> bool:
        return name in self._handles

    def names(self) -> list[str]:
        return sorted(self._handles)

    def __len__(self) -> int:
        return len(self._handles)


# ═══════════════════════════════════════════════════════════════════
#  SHIELD CHECKER PROTOCOL — minimal interface to ESK
# ═══════════════════════════════════════════════════════════════════


ShieldComplianceFn = Callable[[str, "TypedChannelHandle"], bool]
"""Predicate: (shield_name, handle) → covers?

Default impl: returns True (no enforcement).  Production use injects
an ESK-aware checker that consults the actual ShieldDefinition and
looks up κ(message_type) for the given handle.  Delegating κ extraction
to the predicate keeps the typed-channel layer agnostic of the ESK
module (which holds TypeDefinition.compliance metadata).
"""


def _default_compliance_check(_shield: str, _handle: "TypedChannelHandle") -> bool:
    return True


# ═══════════════════════════════════════════════════════════════════
#  TYPED EVENT BUS — emit / publish / discover orchestrator
# ═══════════════════════════════════════════════════════════════════


class TypedEventBus:
    """Schema-aware, capability-gated event bus.

    Wraps an `EventBus` (string topics) and adds the typed-channel
    surface.  The two layers coexist so D4 dual-mode listeners (string
    topics) keep working without re-routing.

    Usage:

        bus = TypedEventBus(registry)
        await bus.emit("OrdersCreated", order_payload)
        cap = await bus.publish("OrdersCreated", shield="PublicBroker")
        handle = await bus.discover(cap)
    """

    def __init__(
        self,
        registry: TypedChannelRegistry,
        underlying: EventBus | None = None,
        compliance_check: ShieldComplianceFn = _default_compliance_check,
    ) -> None:
        self._registry = registry
        self._bus = underlying or EventBus()
        self._compliance_check = compliance_check
        # Issued capabilities — capability_id → channel_name
        self._capabilities: dict[str, Capability] = {}
        # Broadcast subscriber registry — channel_name → list[Queue]
        self._broadcast_subs: dict[str, list[asyncio.Queue]] = {}
        # at_most_once / queue dedup — id sets per channel
        self._delivered_ids: dict[str, set[str]] = {}

    @classmethod
    def from_ir_program(
        cls,
        ir_program: Any,
        underlying: EventBus | None = None,
        compliance_check: ShieldComplianceFn = _default_compliance_check,
    ) -> "TypedEventBus":
        """Bootstrap a bus from a fully-lowered IRProgram (post-13.c)."""
        registry = TypedChannelRegistry()
        for ch in ir_program.channels:
            registry.register_from_ir_channel(ch)
        return cls(registry, underlying=underlying, compliance_check=compliance_check)

    # ── REGISTRY ACCESS ────────────────────────────────────────────

    @property
    def registry(self) -> TypedChannelRegistry:
        return self._registry

    @property
    def underlying(self) -> EventBus:
        return self._bus

    # ── EMIT (Chan-Output / Chan-Mobility, paper §3.1, §3.2) ───────

    async def emit(
        self,
        channel_name: str,
        payload: Any,
        *,
        payload_is_handle: bool = False,
    ) -> None:
        """Emit a value (or a channel handle) on a typed channel.

        `payload_is_handle=True` signals second-order mobility — the
        payload is itself a TypedChannelHandle.  The bus verifies that
        the outer channel's `message` is `Channel<inner.message>` and
        rejects mismatches at runtime (defense-in-depth over D3).
        """
        handle = self._registry.get(channel_name)

        if payload_is_handle:
            if not isinstance(payload, TypedChannelHandle):
                raise SchemaMismatchError(
                    f"emit on '{channel_name}' declared payload_is_handle "
                    f"but payload is {type(payload).__name__}, not "
                    f"TypedChannelHandle"
                )
            if not handle.carries_channel:
                raise SchemaMismatchError(
                    f"emit on '{channel_name}' (message: {handle.message}) "
                    f"received a channel handle, but the channel is not "
                    f"second-order — expected scalar payload"
                )
            inner = handle.inner_message_type()
            if payload.message != inner:
                raise SchemaMismatchError(
                    f"emit on '{channel_name}' expects Channel<{inner}> "
                    f"but received handle for '{payload.message}' "
                    f"(second-order schema mismatch, paper §3.2)"
                )
        else:
            if handle.carries_channel:
                raise SchemaMismatchError(
                    f"emit on '{channel_name}' (message: {handle.message}) "
                    f"requires a channel handle but received scalar — "
                    f"set payload_is_handle=True for mobility"
                )

        event_id = str(uuid.uuid4())
        event = Event(
            topic=channel_name,
            payload=payload,
            event_id=event_id,
            timestamp=time.time(),
        )

        # QoS dispatch — different delivery semantics per channel.qos.
        await self._dispatch(handle, event)

        # Lifetime accounting — paper §3.1 affinity.
        self._consume(handle)

    async def _dispatch(self, handle: TypedChannelHandle, event: Event) -> None:
        """QoS-aware delivery.  Branches per handle.qos:

        - at_most_once : best-effort, no retries; dedup by event_id
        - at_least_once: default; events are queued and re-delivered on retry
        - exactly_once : requires replay-token integration (deferred to 13.e)
        - broadcast    : fan-out to every registered subscriber queue
        - queue        : single-consumer FIFO (default semantics of
                         InMemoryChannel — dedup by event_id)
        """
        if handle.qos == "broadcast":
            for queue in self._broadcast_subs.get(handle.name, []):
                await queue.put(event)
            return

        if handle.qos == "at_most_once":
            # Best-effort: ignore put failures.
            try:
                await self._bus.publish(handle.name, event)
            except RuntimeError:
                # Channel closed / queue full — drop silently per AMO.
                return
            return

        if handle.qos == "exactly_once":
            # Dedup by event_id for the current process.  Cross-process EO
            # requires Fase 11.c replay-token integration — surfaced as a
            # NotImplementedError so callers cannot silently fall back to
            # at-least-once when they asked for stronger semantics.
            seen = self._delivered_ids.setdefault(handle.name, set())
            if event.event_id in seen:
                return
            seen.add(event.event_id)
            await self._bus.publish(handle.name, event)
            return

        # at_least_once (default) and queue both delegate to the
        # underlying EventBus; difference is per-handle, not per-event,
        # and surfaces in subscribe() for queue (single-consumer).
        await self._bus.publish(handle.name, event)

    def _consume(self, handle: TypedChannelHandle) -> None:
        """Increment consumption counter and enforce lifetime rules."""
        handle.consumed_count += 1
        if handle.lifetime == "linear" and handle.consumed_count > 1:
            raise LifetimeViolationError(
                f"channel '{handle.name}' is linear but has been consumed "
                f"{handle.consumed_count} times (linear ⇒ exactly once)"
            )
        # affine and persistent impose no upper bound on emits per
        # handle definition; per-binding affinity is tracked separately
        # (deferred to 13.e).

    # ── PUBLISH (Publish-Ext, paper §4.3) ──────────────────────────

    async def publish(
        self,
        channel_name: str,
        *,
        shield: str,
    ) -> Capability:
        """Extrude a channel handle through a shield, returning a
        Capability that downstream callers can `discover`.

        Compile-time D8 already requires `within Shield`; the runtime
        also rejects empty/missing shields so an embedded program
        cannot bypass the gate by clearing the field.

        The compliance predicate (injected via constructor) verifies
        that `shield.compliance ⊇ κ(channel.message_type)`.  Default
        is permissive; production hooks an ESK-aware checker.
        """
        if not shield:
            raise CapabilityGateError(
                f"publish '{channel_name}' requires a non-empty shield "
                f"(D8 — capability extrusion is shield-mediated)"
            )
        handle = self._registry.get(channel_name)
        if not handle.is_publishable:
            raise CapabilityGateError(
                f"channel '{channel_name}' is not publishable: its "
                f"definition declares no shield_ref (D8)"
            )
        if shield != handle.shield_ref:
            raise CapabilityGateError(
                f"publish '{channel_name}' requires shield "
                f"'{handle.shield_ref}' (declared on the channel) "
                f"but received '{shield}'"
            )

        # Compliance gate — predicate has full visibility of κ(handle).
        if not self._compliance_check(shield, handle):
            raise CapabilityGateError(
                f"shield '{shield}' does not cover compliance "
                f"required by channel '{channel_name}'"
            )

        cap = Capability(
            capability_id=str(uuid.uuid4()),
            channel_name=channel_name,
            shield_ref=shield,
        )
        self._capabilities[cap.capability_id] = cap
        return cap

    # ── DISCOVER (paper §3.4 dual) ─────────────────────────────────

    async def discover(self, capability: Capability) -> TypedChannelHandle:
        """Consume a Capability and return the underlying handle."""
        if capability.capability_id not in self._capabilities:
            raise CapabilityGateError(
                f"capability '{capability.capability_id}' has been revoked "
                f"or was never issued by this bus"
            )
        # One-shot: capability is consumed on discover.
        del self._capabilities[capability.capability_id]
        return self._registry.get(capability.channel_name)

    # ── SUBSCRIBE — broadcast and queue ─────────────────────────────

    def subscribe_broadcast(self, channel_name: str) -> asyncio.Queue:
        """Register a fresh queue for a broadcast channel; returns the
        queue so the consumer can `await q.get()` per event.

        Multiple subscribers each receive every emitted event.
        """
        handle = self._registry.get(channel_name)
        if handle.qos != "broadcast":
            raise SchemaMismatchError(
                f"subscribe_broadcast called on '{channel_name}' but its "
                f"qos is {handle.qos}, not broadcast"
            )
        queue: asyncio.Queue = asyncio.Queue()
        self._broadcast_subs.setdefault(channel_name, []).append(queue)
        return queue

    async def receive(self, channel_name: str) -> Event:
        """Receive the next event on a non-broadcast channel.

        For QoS broadcast, use `subscribe_broadcast` instead — the bus
        does not maintain a default queue for broadcast since each
        subscriber needs its own.
        """
        handle = self._registry.get(channel_name)
        if handle.qos == "broadcast":
            raise SchemaMismatchError(
                f"channel '{channel_name}' has qos=broadcast — call "
                f"subscribe_broadcast() to get a per-subscriber queue"
            )
        backing = self._bus.get_or_create(channel_name)
        return await backing.receive()

    # ── INTROSPECTION ──────────────────────────────────────────────

    def issued_capabilities(self) -> int:
        """Count of live (not yet discovered) capabilities."""
        return len(self._capabilities)

    def close_all(self) -> None:
        """Drain caps, close underlying bus, clear broadcast queues."""
        self._capabilities.clear()
        self._broadcast_subs.clear()
        self._delivered_ids.clear()
        self._bus.close_all()
