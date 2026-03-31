"""
AXON Runtime — Kafka Event Channel
====================================
EventChannel implementation backed by Apache Kafka via aiokafka.

π-Calculus correspondence:
  Kafka Topic  ≡  (ν c)    — channel restriction (unique topic name)
  produce()    ≡  c̄⟨v⟩    — channel output (send on c)
  consume()    ≡  c(x)     — channel input (receive from c)

Girard's Linear Logic:
  Each consumer group processes each event exactly once (⊗ monoidal).
  Consumer offset tracking ensures no duplication in the steady state.

Dependency: aiokafka>=0.11  (installed via ``pip install axon-lang[kafka]``)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from axon.runtime.event_bus import Event

logger = logging.getLogger(__name__)


class KafkaChannel:
    """
    EventChannel backed by Apache Kafka via aiokafka.

    Usage:
        channel = KafkaChannel(
            topic="orders",
            bootstrap_servers="localhost:9092",
            group_id="axon-daemon-orders",
        )
        await channel.connect()
        await channel.publish(Event(topic="orders", payload={"id": 1}))
        event = await channel.receive()
        channel.close()
    """

    def __init__(
        self,
        topic: str,
        bootstrap_servers: str = "localhost:9092",
        group_id: str = "",
        *,
        maxsize: int = 0,
    ) -> None:
        self._topic = topic
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id or f"axon-daemon-{topic}"
        self._closed = False
        self._producer: Any = None
        self._consumer: Any = None
        self._buffer: asyncio.Queue[Event] = asyncio.Queue(
            maxsize=maxsize or 0,
        )
        self._consume_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        """Initialize Kafka producer and consumer connections."""
        try:
            from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
        except ImportError as exc:
            raise ImportError(
                "aiokafka is required for KafkaChannel. "
                "Install it with: pip install axon-lang[kafka]"
            ) from exc

        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
        )
        await self._producer.start()

        self._consumer = AIOKafkaConsumer(
            self._topic,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            auto_offset_reset="latest",
        )
        await self._consumer.start()
        self._consume_task = asyncio.create_task(self._consume_loop())

    async def _consume_loop(self) -> None:
        """Background loop that reads Kafka messages into the buffer."""
        try:
            async for msg in self._consumer:
                payload = msg.value
                event = Event(
                    topic=self._topic,
                    payload=payload.get("payload", payload),
                    event_id=payload.get("event_id", str(uuid.uuid4())),
                    timestamp=payload.get("timestamp", time.time()),
                )
                await self._buffer.put(event)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Kafka consume loop error on topic '%s'", self._topic)

    async def publish(self, event: Event) -> None:
        """Send an event to Kafka (c̄⟨v⟩ — channel output)."""
        if self._closed:
            raise RuntimeError(f"KafkaChannel '{self._topic}' is closed")
        if self._producer is None:
            raise RuntimeError("KafkaChannel not connected. Call connect() first.")
        value = {
            "topic": event.topic or self._topic,
            "payload": event.payload,
            "event_id": event.event_id or str(uuid.uuid4()),
            "timestamp": event.timestamp or time.time(),
        }
        await self._producer.send_and_wait(self._topic, value)

    async def receive(self) -> Event:
        """Receive the next event from Kafka (c(x) — channel input)."""
        return await self._buffer.get()

    def close(self) -> None:
        """Close producer and consumer connections."""
        self._closed = True
        if self._consume_task and not self._consume_task.done():
            self._consume_task.cancel()

    async def close_async(self) -> None:
        """Graceful async shutdown of Kafka connections."""
        self.close()
        if self._consume_task:
            try:
                await self._consume_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._producer:
            await self._producer.stop()
        if self._consumer:
            await self._consumer.stop()

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def topic(self) -> str:
        return self._topic

    @property
    def pending(self) -> int:
        return self._buffer.qsize()
