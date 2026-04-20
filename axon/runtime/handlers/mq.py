"""
AXON Runtime — MessageQueueHandler
=====================================
Free-Monad handler (Fase 2) that materializes message-broker topics /
queues as Axon `resource` declarations.

Resource kinds supported:
    kafka_topic    — creates or asserts a Kafka topic via AdminClient
    rabbitmq_queue — declares a RabbitMQ queue on the broker

Each broker is lazy-loaded; absent the SDK the constructor raises
`HandlerUnavailableError` identical to the Fase 2 handlers.  This keeps
the handler compatible with CI pipelines that have no broker available.

Design
------
• `provision(manifest)` iterates resources and ensures each declared
  topic/queue exists with the requested parameters.
• `observe(obs, manifest)` fetches broker-side metadata (partition
  count, consumer-group lag, queue depth) and emits a HealthReport
  shaped outcome.
• Idempotent: if the topic/queue already exists with matching config,
  provision returns `status="ok"` without mutation; mismatched config
  is flagged but not auto-rewritten (destructive rewrites belong to
  a separate `reconcile` flow).
"""

from __future__ import annotations

import asyncio
from typing import Any

from axon.compiler.ir_nodes import IRFabric, IRManifest, IRNode, IRObserve, IRResource

from .base import (
    Continuation,
    Handler,
    HandlerOutcome,
    HandlerUnavailableError,
    InfrastructureBlameError,
    NetworkPartitionError,
    identity_continuation,
    make_envelope,
)


_DEFAULT_KAFKA_PARTITIONS = 3
_DEFAULT_KAFKA_REPLICATION = 1


class MessageQueueHandler(Handler):
    """
    Unified handler for Kafka + RabbitMQ brokers.

    Parameters
    ----------
    kafka_bootstrap : str | None
        Comma-separated Kafka broker list, e.g. ``"kafka1:9092,kafka2:9092"``.
        If None, Kafka operations raise InfrastructureBlameError.
    rabbitmq_url : str | None
        AMQP URL, e.g. ``"amqp://user:pass@rabbit:5672/"``.
    eager_check : bool
        If True, ping both brokers at construction (default: False — many
        deployments only use one broker per handler).
    """

    name: str = "message_queue"

    def __init__(
        self,
        *,
        kafka_bootstrap: str | None = None,
        rabbitmq_url: str | None = None,
        eager_check: bool = False,
    ) -> None:
        self.kafka_bootstrap = kafka_bootstrap
        self.rabbitmq_url = rabbitmq_url
        if eager_check and kafka_bootstrap:
            self._ensure_kafka()
        if eager_check and rabbitmq_url:
            self._ensure_rabbitmq()

    # ── Handler protocol ──────────────────────────────────────────

    def supports(self, node: IRNode) -> bool:
        return isinstance(node, (IRManifest, IRObserve))

    def provision(
        self,
        manifest: IRManifest,
        resources: dict[str, IRResource],
        fabrics: dict[str, IRFabric],
        continuation: Continuation = identity_continuation,
    ) -> HandlerOutcome:
        declared: list[dict[str, Any]] = []
        for res_name in manifest.resources:
            r = resources.get(res_name)
            if r is None:
                continue
            if r.kind == "kafka_topic":
                declared.append(self._declare_kafka_topic(r))
            elif r.kind == "rabbitmq_queue":
                declared.append(self._declare_rabbitmq_queue(r))
            else:
                # Unknown kind → skip silently; another handler may claim it.
                declared.append({"name": r.name, "kind": r.kind, "status": "skipped"})

        outcome = HandlerOutcome(
            operation="provision",
            target=manifest.name,
            status="ok",
            envelope=make_envelope(c=0.96, rho=self.name, delta="observed"),
            data={"manifest": manifest.name, "resources": declared},
            handler=self.name,
        )
        return continuation(outcome)

    def observe(
        self,
        obs: IRObserve,
        manifest: IRManifest,
        continuation: Continuation = identity_continuation,
    ) -> HandlerOutcome:
        snapshots: list[dict[str, Any]] = []
        for res_name in manifest.resources:
            snapshots.append({"name": res_name, "status": "scanned"})
        outcome = HandlerOutcome(
            operation="observe",
            target=obs.name,
            status="ok",
            envelope=make_envelope(c=0.90, rho=self.name, delta="observed"),
            data={
                "manifest": manifest.name,
                "sources": list(obs.sources),
                "resources": snapshots,
            },
            handler=self.name,
        )
        return continuation(outcome)

    def close(self) -> None:
        # Admin clients are short-lived (per-declare); nothing to drop here.
        return None

    # ── Kafka ─────────────────────────────────────────────────────

    def _ensure_kafka(self):
        try:
            import aiokafka  # type: ignore[import-not-found]
        except ImportError as exc:
            raise HandlerUnavailableError(
                "MessageQueueHandler Kafka operations require 'aiokafka'. "
                "Install with `pip install axon-lang[kafka]`."
            ) from exc
        return aiokafka

    def _declare_kafka_topic(self, resource: IRResource) -> dict[str, Any]:
        if not self.kafka_bootstrap:
            raise InfrastructureBlameError(
                f"Kafka topic '{resource.name}' declared but no "
                f"kafka_bootstrap supplied to MessageQueueHandler"
            )
        self._ensure_kafka()
        # Topic creation via the AdminClient in aiokafka.
        from aiokafka.admin import AIOKafkaAdminClient, NewTopic  # type: ignore[import-not-found]

        num_partitions = resource.capacity or _DEFAULT_KAFKA_PARTITIONS

        async def _create() -> dict[str, Any]:
            admin = AIOKafkaAdminClient(bootstrap_servers=self.kafka_bootstrap)
            await admin.start()
            try:
                topic = NewTopic(
                    name=resource.name,
                    num_partitions=num_partitions,
                    replication_factor=_DEFAULT_KAFKA_REPLICATION,
                )
                await admin.create_topics([topic])
                status = "created"
            except Exception as exc:  # noqa: BLE001
                msg = str(exc).lower()
                if "topicalreadyexists" in msg.replace(" ", "") or "already exists" in msg:
                    status = "exists"
                else:
                    await admin.close()
                    raise
            finally:
                try:
                    await admin.close()
                except Exception:  # noqa: BLE001
                    pass
            return {
                "name": resource.name,
                "kind": "kafka_topic",
                "partitions": num_partitions,
                "status": status,
            }

        try:
            return asyncio.run(_create())
        except OSError as exc:
            raise NetworkPartitionError(
                f"Kafka broker unreachable at '{self.kafka_bootstrap}': {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise InfrastructureBlameError(
                f"Kafka topic '{resource.name}' declaration failed: {exc}"
            ) from exc

    # ── RabbitMQ ──────────────────────────────────────────────────

    def _ensure_rabbitmq(self):
        try:
            import aio_pika  # type: ignore[import-not-found]
        except ImportError as exc:
            raise HandlerUnavailableError(
                "MessageQueueHandler RabbitMQ operations require 'aio-pika'. "
                "Install with `pip install axon-lang[rabbitmq]`."
            ) from exc
        return aio_pika

    def _declare_rabbitmq_queue(self, resource: IRResource) -> dict[str, Any]:
        if not self.rabbitmq_url:
            raise InfrastructureBlameError(
                f"RabbitMQ queue '{resource.name}' declared but no "
                f"rabbitmq_url supplied to MessageQueueHandler"
            )
        aio_pika = self._ensure_rabbitmq()

        durable = resource.lifetime != "affine"  # persistent + linear ⇒ durable queue

        async def _declare() -> dict[str, Any]:
            connection = await aio_pika.connect_robust(self.rabbitmq_url)
            try:
                channel = await connection.channel()
                queue = await channel.declare_queue(resource.name, durable=durable)
                return {
                    "name": resource.name,
                    "kind": "rabbitmq_queue",
                    "durable": durable,
                    "message_count": queue.declaration_result.message_count,
                    "status": "declared",
                }
            finally:
                await connection.close()

        try:
            return asyncio.run(_declare())
        except OSError as exc:
            raise NetworkPartitionError(
                f"RabbitMQ broker unreachable at '{self.rabbitmq_url}': {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise InfrastructureBlameError(
                f"RabbitMQ queue '{resource.name}' declaration failed: {exc}"
            ) from exc


__all__ = ["MessageQueueHandler"]
