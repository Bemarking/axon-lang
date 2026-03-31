"""
AXON Runtime — AWS EventBridge Event Channel
===============================================
EventChannel implementation backed by AWS EventBridge + SQS.

Architecture:
  publish → EventBridge PutEvents API
  receive → SQS queue (attached to an EventBridge rule via target)

This is a poll-based channel: EventBridge delivers events to an
SQS queue, and the channel polls the queue for new messages.

π-Calculus correspondence:
  EventBridge Rule  ≡  (ν c)    — channel restriction
  PutEvents         ≡  c̄⟨v⟩    — channel output
  SQS ReceiveMessage ≡  c(x)    — channel input

Dependency: aiobotocore>=2.15  (installed via ``pip install axon-lang[aws]``)
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


class EventBridgeChannel:
    """
    EventChannel backed by AWS EventBridge (publish) + SQS (receive).

    Requires an existing EventBridge rule that routes events matching
    the daemon topic to the specified SQS queue.

    Usage:
        channel = EventBridgeChannel(
            topic="orders.new",
            bus_name="axon-events",
            queue_url="https://sqs.us-east-1.amazonaws.com/123456/axon-orders",
            region="us-east-1",
        )
        await channel.connect()
        await channel.publish(Event(topic="orders.new", payload={"id": 1}))
        event = await channel.receive()
        await channel.close_async()
    """

    def __init__(
        self,
        topic: str,
        bus_name: str = "default",
        queue_url: str = "",
        region: str = "us-east-1",
        source: str = "axon.daemon",
        *,
        poll_interval: float = 1.0,
        maxsize: int = 0,
    ) -> None:
        self._topic = topic
        self._bus_name = bus_name
        self._queue_url = queue_url
        self._region = region
        self._source = source
        self._poll_interval = poll_interval
        self._closed = False
        self._session: Any = None
        self._eb_client: Any = None
        self._sqs_client: Any = None
        self._buffer: asyncio.Queue[Event] = asyncio.Queue(
            maxsize=maxsize or 0,
        )
        self._poll_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        """Initialize AWS session and start SQS polling."""
        try:
            from aiobotocore.session import get_session
        except ImportError as exc:
            raise ImportError(
                "aiobotocore is required for EventBridgeChannel. "
                "Install it with: pip install axon-lang[aws]"
            ) from exc

        self._session = get_session()
        self._eb_client = self._session.create_client(
            "events", region_name=self._region,
        )
        self._sqs_client = self._session.create_client(
            "sqs", region_name=self._region,
        )
        self._eb_client = await self._eb_client.__aenter__()
        self._sqs_client = await self._sqs_client.__aenter__()
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        """Background loop that polls SQS for EventBridge events."""
        try:
            while not self._closed:
                response = await self._sqs_client.receive_message(
                    QueueUrl=self._queue_url,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=min(int(self._poll_interval), 20),
                )
                messages = response.get("Messages", [])
                for msg in messages:
                    try:
                        body = json.loads(msg["Body"])
                        # EventBridge wraps the detail
                        detail = body.get("detail", body)
                        event = Event(
                            topic=self._topic,
                            payload=detail.get("payload", detail),
                            event_id=detail.get("event_id", str(uuid.uuid4())),
                            timestamp=detail.get("timestamp", time.time()),
                        )
                        await self._buffer.put(event)
                    except (json.JSONDecodeError, KeyError):
                        logger.warning(
                            "Malformed SQS message on topic '%s'", self._topic,
                        )
                    # Delete processed message
                    await self._sqs_client.delete_message(
                        QueueUrl=self._queue_url,
                        ReceiptHandle=msg["ReceiptHandle"],
                    )
                if not messages:
                    await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(
                "EventBridge poll loop error on topic '%s'", self._topic,
            )

    async def publish(self, event: Event) -> None:
        """Publish an event to EventBridge (c̄⟨v⟩ — channel output)."""
        if self._closed:
            raise RuntimeError(
                f"EventBridgeChannel '{self._topic}' is closed"
            )
        if self._eb_client is None:
            raise RuntimeError(
                "EventBridgeChannel not connected. Call connect() first."
            )

        detail = json.dumps({
            "topic": event.topic or self._topic,
            "payload": event.payload,
            "event_id": event.event_id or str(uuid.uuid4()),
            "timestamp": event.timestamp or time.time(),
        }, default=str)

        await self._eb_client.put_events(
            Entries=[{
                "Source": self._source,
                "DetailType": self._topic,
                "Detail": detail,
                "EventBusName": self._bus_name,
            }],
        )

    async def receive(self) -> Event:
        """Receive the next event from SQS (c(x) — channel input)."""
        return await self._buffer.get()

    def close(self) -> None:
        """Mark channel as closed and cancel poller."""
        self._closed = True
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()

    async def close_async(self) -> None:
        """Graceful async shutdown of AWS clients."""
        self.close()
        if self._poll_task:
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._eb_client:
            await self._eb_client.__aexit__(None, None, None)
        if self._sqs_client:
            await self._sqs_client.__aexit__(None, None, None)

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def topic(self) -> str:
        return self._topic

    @property
    def pending(self) -> int:
        return self._buffer.qsize()
