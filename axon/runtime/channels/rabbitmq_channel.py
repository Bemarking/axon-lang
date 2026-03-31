"""
AXON Runtime — RabbitMQ Event Channel
=======================================
EventChannel implementation backed by RabbitMQ via aio-pika (AMQP 0-9-1).

π-Calculus correspondence:
  Exchange + Queue  ≡  (ν c)    — channel creation (restriction)
  basic_publish     ≡  c̄⟨v⟩    — channel output (send on c)
  basic_consume     ≡  c(x)     — channel input (receive from c)

RabbitMQ provides natural topic routing through exchange bindings,
mapping cleanly to π-calculus channel restriction and composition.

Dependency: aio-pika>=9.4  (installed via ``pip install axon-lang[rabbitmq]``)
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


class RabbitMQChannel:
    """
    EventChannel backed by RabbitMQ via aio-pika.

    Uses a topic exchange with the daemon topic as the routing key.
    Each daemon gets its own queue bound to its listen topics.

    Usage:
        channel = RabbitMQChannel(
            topic="orders.new",
            amqp_url="amqp://guest:guest@localhost/",
        )
        await channel.connect()
        await channel.publish(Event(topic="orders.new", payload={"id": 1}))
        event = await channel.receive()
        await channel.close_async()
    """

    def __init__(
        self,
        topic: str,
        amqp_url: str = "amqp://guest:guest@localhost/",
        exchange_name: str = "axon.events",
        *,
        maxsize: int = 0,
    ) -> None:
        self._topic = topic
        self._amqp_url = amqp_url
        self._exchange_name = exchange_name
        self._closed = False
        self._connection: Any = None
        self._channel: Any = None
        self._exchange: Any = None
        self._queue: Any = None
        self._buffer: asyncio.Queue[Event] = asyncio.Queue(
            maxsize=maxsize or 0,
        )
        self._consume_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        """Establish AMQP connection, declare exchange and queue."""
        try:
            import aio_pika
        except ImportError as exc:
            raise ImportError(
                "aio-pika is required for RabbitMQChannel. "
                "Install it with: pip install axon-lang[rabbitmq]"
            ) from exc

        self._connection = await aio_pika.connect_robust(self._amqp_url)
        self._channel = await self._connection.channel()

        self._exchange = await self._channel.declare_exchange(
            self._exchange_name,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )

        queue_name = f"axon.daemon.{self._topic.replace('.', '_')}"
        self._queue = await self._channel.declare_queue(
            queue_name,
            durable=True,
        )
        await self._queue.bind(self._exchange, routing_key=self._topic)
        self._consume_task = asyncio.create_task(self._consume_loop())

    async def _consume_loop(self) -> None:
        """Background loop that processes AMQP messages into the buffer."""
        try:
            async with self._queue.iterator() as queue_iter:
                async for message in queue_iter:
                    async with message.process():
                        body = json.loads(message.body.decode("utf-8"))
                        event = Event(
                            topic=self._topic,
                            payload=body.get("payload", body),
                            event_id=body.get("event_id", str(uuid.uuid4())),
                            timestamp=body.get("timestamp", time.time()),
                        )
                        await self._buffer.put(event)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(
                "RabbitMQ consume loop error on topic '%s'", self._topic,
            )

    async def publish(self, event: Event) -> None:
        """Publish an event to RabbitMQ (c̄⟨v⟩ — channel output)."""
        if self._closed:
            raise RuntimeError(f"RabbitMQChannel '{self._topic}' is closed")
        if self._exchange is None:
            raise RuntimeError(
                "RabbitMQChannel not connected. Call connect() first."
            )

        try:
            import aio_pika
        except ImportError as exc:
            raise ImportError(
                "aio-pika is required for RabbitMQChannel."
            ) from exc

        body = json.dumps({
            "topic": event.topic or self._topic,
            "payload": event.payload,
            "event_id": event.event_id or str(uuid.uuid4()),
            "timestamp": event.timestamp or time.time(),
        }, default=str).encode("utf-8")

        message = aio_pika.Message(
            body=body,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await self._exchange.publish(message, routing_key=self._topic)

    async def receive(self) -> Event:
        """Receive the next event from RabbitMQ (c(x) — channel input)."""
        return await self._buffer.get()

    def close(self) -> None:
        """Mark channel as closed and cancel consumer."""
        self._closed = True
        if self._consume_task and not self._consume_task.done():
            self._consume_task.cancel()

    async def close_async(self) -> None:
        """Graceful async shutdown of AMQP connections."""
        self.close()
        if self._consume_task:
            try:
                await self._consume_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._connection and not self._connection.is_closed:
            await self._connection.close()

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def topic(self) -> str:
        return self._topic

    @property
    def pending(self) -> int:
        return self._buffer.qsize()
