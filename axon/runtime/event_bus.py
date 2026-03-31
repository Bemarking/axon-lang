"""
AXON Runtime — Event Bus (π-Calculus Channel Infrastructure)
=============================================================
Implements the event channel layer for the daemon primitive.

The event bus provides the communication substrate upon which
daemon listeners operate. Each channel is a typed conduit for
events, grounded in π-calculus channel theory:

  - EventChannel protocol:  the abstract channel signature
  - InMemoryChannel:        asyncio.Queue-backed channel (dev/test)
  - EventBus:               channel registry + topic routing

π-Calculus correspondence:
  EventBus   ≡  (ν ch₁)(ν ch₂)…  — channel creation (restriction)
  publish()  ≡  c̄⟨v⟩             — channel output (send on c)
  subscribe()≡  c(x)              — channel input (receive from c)

Girard's Linear Logic (resource semantics):
  Each event is consumed exactly once per listener (⊗ monoidal,
  not duplicated). The bus enforces this via asyncio.Queue FIFO.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable


# ═══════════════════════════════════════════════════════════════════
#  EVENT — the unit of communication
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Event:
    """
    An immutable event flowing through a channel.

    Fields:
        topic:     channel/topic this event was published to
        payload:   the event data (any JSON-serializable value)
        event_id:  unique identifier for tracing/dedup
        timestamp: when the event was created (epoch seconds)
    """
    topic: str = ""
    payload: Any = None
    event_id: str = ""
    timestamp: float = 0.0


# ═══════════════════════════════════════════════════════════════════
#  EVENT CHANNEL PROTOCOL
# ═══════════════════════════════════════════════════════════════════

@runtime_checkable
class EventChannel(Protocol):
    """
    Protocol for event channels.

    π-Calculus: a channel c supporting send c̄⟨v⟩ and receive c(x).
    """

    async def publish(self, event: Event) -> None:
        """Send an event into the channel (c̄⟨v⟩ — output)."""
        ...

    async def receive(self) -> Event:
        """Receive the next event from the channel (c(x) — input)."""
        ...

    def close(self) -> None:
        """Close the channel (no more events will be sent)."""
        ...

    @property
    def is_closed(self) -> bool:
        """Whether the channel has been closed."""
        ...


# ═══════════════════════════════════════════════════════════════════
#  IN-MEMORY CHANNEL — asyncio.Queue-backed (dev/test)
# ═══════════════════════════════════════════════════════════════════

class InMemoryChannel:
    """
    Queue-backed channel for testing and single-process deployments.

    Girard's linear logic: each event is consumed exactly once
    per subscriber (FIFO, no duplication, no discarding).
    """

    def __init__(self, topic: str, maxsize: int = 0) -> None:
        self._topic = topic
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._closed = False

    async def publish(self, event: Event) -> None:
        if self._closed:
            raise RuntimeError(f"Channel '{self._topic}' is closed")
        await self._queue.put(event)

    async def receive(self) -> Event:
        return await self._queue.get()

    def close(self) -> None:
        self._closed = True

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def topic(self) -> str:
        return self._topic

    @property
    def pending(self) -> int:
        return self._queue.qsize()


# ═══════════════════════════════════════════════════════════════════
#  CHANNEL FACTORY TYPE
# ═══════════════════════════════════════════════════════════════════

ChannelFactory = Callable[[str, int], EventChannel]
"""
Factory signature: (topic, maxsize) → EventChannel.

The default factory creates InMemoryChannel instances.
Custom factories (Kafka, RabbitMQ, EventBridge) must return
objects satisfying the EventChannel protocol.
"""


def _default_channel_factory(topic: str, maxsize: int = 0) -> InMemoryChannel:
    """Default factory — creates asyncio.Queue-backed channels."""
    return InMemoryChannel(topic=topic, maxsize=maxsize)


# ═══════════════════════════════════════════════════════════════════
#  EVENT BUS — channel registry + topic routing
# ═══════════════════════════════════════════════════════════════════

class EventBus:
    """
    Central event routing hub — manages channels and dispatches events.

    π-Calculus correspondence:
      EventBus ≡ (ν ch₁)(ν ch₂)…(P | Q | …)
      The bus creates restricted channels and composes listeners.

    The ``channel_factory`` parameter enables plugging in external
    message brokers (Kafka, RabbitMQ, EventBridge) while keeping
    the same EventBus API. Default: InMemoryChannel (asyncio.Queue).

    Usage:
        bus = EventBus()                                    # in-memory
        bus = EventBus(channel_factory=kafka_factory)       # Kafka

        channel = bus.get_or_create("orders")
        await bus.publish("orders", Event(topic="orders", payload={...}))
        event = await channel.receive()
    """

    def __init__(
        self,
        channel_factory: ChannelFactory | None = None,
    ) -> None:
        self._factory: ChannelFactory = channel_factory or _default_channel_factory
        self._channels: dict[str, EventChannel] = {}

    def get_or_create(self, topic: str, maxsize: int = 0) -> EventChannel:
        """Get existing channel or create a new one for the topic."""
        if topic not in self._channels:
            self._channels[topic] = self._factory(topic, maxsize)
        return self._channels[topic]

    async def publish(self, topic: str, event: Event) -> None:
        """Publish an event to a topic channel."""
        channel = self.get_or_create(topic)
        await channel.publish(event)

    def topics(self) -> list[str]:
        """List all registered topics."""
        return list(self._channels.keys())

    def close_all(self) -> None:
        """Close all channels (daemon shutdown)."""
        for channel in self._channels.values():
            channel.close()

    @property
    def channel_count(self) -> int:
        return len(self._channels)
