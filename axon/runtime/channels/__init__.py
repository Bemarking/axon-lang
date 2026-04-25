"""
AXON Runtime — Channel Registry & Auto-Discovery
===================================================
Pluggable event channel backends for the EventBus.

This module provides lazy-loaded channel factories for external
message brokers. The core AXON package has zero dependencies —
channel backends are installed as optional extras:

  pip install axon-lang[kafka]       # KafkaChannel via aiokafka
  pip install axon-lang[rabbitmq]    # RabbitMQChannel via aio-pika
  pip install axon-lang[aws]         # EventBridgeChannel via aiobotocore

Usage:
    from axon.runtime.channels import get_channel_class, make_channel_factory

    # Get channel class by name
    cls = get_channel_class("kafka")

    # Build a factory for EventBus from config dict
    factory = make_channel_factory({
        "backend": "kafka",
        "bootstrap_servers": "localhost:9092",
    })
    bus = EventBus(channel_factory=factory)
"""

from __future__ import annotations

from typing import Any

from axon.runtime.event_bus import EventChannel, InMemoryChannel
from axon.runtime.channels.typed import (
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


# ═══════════════════════════════════════════════════════════════════
#  CHANNEL REGISTRY
# ═══════════════════════════════════════════════════════════════════

_BUILTIN = "memory"


def get_channel_class(name: str) -> type:
    """
    Resolve a channel implementation by name.

    Lazy-imports external dependencies — never fails at import time
    if the backend package is not installed. Only raises when actually
    requesting a missing backend.

    Args:
        name: One of "memory", "kafka", "rabbitmq", "eventbridge".

    Returns:
        The channel class (not an instance).

    Raises:
        ValueError: If the name is unknown.
        ImportError: If the required package is not installed.
    """
    if name == "memory":
        return InMemoryChannel
    if name == "kafka":
        from axon.runtime.channels.kafka_channel import KafkaChannel
        return KafkaChannel
    if name == "rabbitmq":
        from axon.runtime.channels.rabbitmq_channel import RabbitMQChannel
        return RabbitMQChannel
    if name == "eventbridge":
        from axon.runtime.channels.eventbridge_channel import EventBridgeChannel
        return EventBridgeChannel

    raise ValueError(
        f"Unknown channel backend '{name}'. "
        f"Available: memory, kafka, rabbitmq, eventbridge"
    )


def available_backends() -> list[str]:
    """List all registered channel backend names."""
    return ["memory", "kafka", "rabbitmq", "eventbridge"]


def make_channel_factory(config: dict[str, Any]) -> Any:
    """
    Build a channel factory callable from a config dictionary.

    The factory is suitable for passing to ``EventBus(channel_factory=...)``.

    Config keys:
        backend:  "memory" | "kafka" | "rabbitmq" | "eventbridge"
        (remaining keys are passed as kwargs to the channel constructor)

    Returns:
        A callable ``(topic: str, maxsize: int) -> EventChannel``.

    Example config for Kafka::

        {
            "backend": "kafka",
            "bootstrap_servers": "kafka-1:9092,kafka-2:9092",
            "group_id": "axon-daemon",
        }
    """
    backend_name = config.get("backend", "memory")
    channel_cls = get_channel_class(backend_name)

    # Extract only channel-specific kwargs (remove our meta key)
    channel_kwargs = {k: v for k, v in config.items() if k != "backend"}

    def factory(topic: str, maxsize: int = 0) -> EventChannel:
        return channel_cls(topic=topic, maxsize=maxsize, **channel_kwargs)  # type: ignore[call-arg]

    return factory


__all__ = [
    "get_channel_class",
    "available_backends",
    "make_channel_factory",
    # Mobile Typed Channels — Fase 13.d
    "Capability",
    "CapabilityGateError",
    "ChannelNotFoundError",
    "LifetimeViolationError",
    "SchemaMismatchError",
    "TypedChannelError",
    "TypedChannelHandle",
    "TypedChannelRegistry",
    "TypedEventBus",
]
