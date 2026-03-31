"""
AXON AxonServer — Comprehensive Test Suite
=============================================
Tests for Phase 1 (EventBus FFI Channels) and Phase 2 (AxonServer).

Coverage:
  - EventBus channel factory injection (backwards compatible)
  - Channel registry & auto-discovery
  - KafkaChannel / RabbitMQChannel / EventBridgeChannel (import + structure)
  - AxonServerConfig defaults
  - AxonServer lifecycle (start/stop, deploy, daemon management)
  - HTTP API endpoints (Starlette TestClient)
  - WebSocket event streaming
  - RedisStateBackend structure
  - CLI argument parsing (serve, deploy)
"""

from __future__ import annotations

import asyncio
import time

import pytest


# ═══════════════════════════════════════════════════════════════════
#  PHASE 1: EVENT BUS CHANNEL FACTORY
# ═══════════════════════════════════════════════════════════════════


class TestEventBusFactory:
    """EventBus channel factory injection — backwards compatible."""

    async def test_default_factory_creates_in_memory(self):
        """EventBus() with no args still creates InMemoryChannel."""
        from axon.runtime.event_bus import EventBus, InMemoryChannel

        bus = EventBus()
        ch = bus.get_or_create("test")
        assert isinstance(ch, InMemoryChannel)

    async def test_custom_factory_is_used(self):
        """EventBus(channel_factory=...) uses the provided factory."""
        from axon.runtime.event_bus import Event, EventBus

        calls: list[tuple[str, int]] = []

        class MockChannel:
            def __init__(self, topic: str, maxsize: int = 0) -> None:
                self.topic_name = topic
                calls.append((topic, maxsize))

            async def publish(self, event: Event) -> None:
                pass

            async def receive(self) -> Event:
                return Event()

            def close(self) -> None:
                pass

            @property
            def is_closed(self) -> bool:
                return False

        def mock_factory(topic: str, maxsize: int = 0) -> MockChannel:
            return MockChannel(topic, maxsize)

        bus = EventBus(channel_factory=mock_factory)
        bus.get_or_create("orders")
        bus.get_or_create("alerts")

        assert len(calls) == 2
        assert calls[0] == ("orders", 0)
        assert calls[1] == ("alerts", 0)

    async def test_factory_publish_receive_cycle(self):
        """Channel factory integration — full publish/receive."""
        from axon.runtime.event_bus import Event, EventBus

        bus = EventBus()  # default factory
        await bus.publish("topic1", Event(topic="topic1", payload="hello"))
        ch = bus.get_or_create("topic1")
        event = await ch.receive()
        assert event.payload == "hello"

    async def test_channel_factory_type_alias_exported(self):
        """ChannelFactory type alias is importable."""
        from axon.runtime.event_bus import ChannelFactory
        assert ChannelFactory is not None

    async def test_default_channel_factory_function(self):
        """_default_channel_factory creates InMemoryChannel."""
        from axon.runtime.event_bus import _default_channel_factory, InMemoryChannel

        ch = _default_channel_factory("test_topic", 10)
        assert isinstance(ch, InMemoryChannel)
        assert ch.topic == "test_topic"


# ═══════════════════════════════════════════════════════════════════
#  PHASE 1: CHANNEL REGISTRY
# ═══════════════════════════════════════════════════════════════════


class TestChannelRegistry:
    """Channel registry and auto-discovery."""

    def test_get_memory_channel(self):
        """get_channel_class('memory') returns InMemoryChannel."""
        from axon.runtime.channels import get_channel_class
        from axon.runtime.event_bus import InMemoryChannel

        cls = get_channel_class("memory")
        assert cls is InMemoryChannel

    def test_unknown_backend_raises(self):
        """get_channel_class('unknown') raises ValueError."""
        from axon.runtime.channels import get_channel_class

        with pytest.raises(ValueError, match="Unknown channel backend"):
            get_channel_class("unknown_backend")

    def test_available_backends_list(self):
        """available_backends() returns all backend names."""
        from axon.runtime.channels import available_backends

        backends = available_backends()
        assert "memory" in backends
        assert "kafka" in backends
        assert "rabbitmq" in backends
        assert "eventbridge" in backends

    def test_make_channel_factory_memory(self):
        """make_channel_factory for memory backend creates InMemoryChannel."""
        from axon.runtime.channels import make_channel_factory
        from axon.runtime.event_bus import InMemoryChannel

        factory = make_channel_factory({"backend": "memory"})
        ch = factory("test_topic", 0)
        assert isinstance(ch, InMemoryChannel)

    def test_make_channel_factory_default_is_memory(self):
        """make_channel_factory({}) defaults to memory."""
        from axon.runtime.channels import make_channel_factory
        from axon.runtime.event_bus import InMemoryChannel

        factory = make_channel_factory({})
        ch = factory("default_topic")
        assert isinstance(ch, InMemoryChannel)


# ═══════════════════════════════════════════════════════════════════
#  PHASE 1: CHANNEL IMPLEMENTATIONS (import + structure)
# ═══════════════════════════════════════════════════════════════════


class TestChannelStructure:
    """Verify channel classes are importable and structurally correct."""

    def test_kafka_channel_importable(self):
        """KafkaChannel class exists and has correct interface."""
        from axon.runtime.channels.kafka_channel import KafkaChannel

        ch = KafkaChannel(topic="test", bootstrap_servers="localhost:9092")
        assert ch.topic == "test"
        assert ch.is_closed is False
        assert ch.pending == 0
        assert hasattr(ch, "connect")
        assert hasattr(ch, "publish")
        assert hasattr(ch, "receive")
        assert hasattr(ch, "close")
        assert hasattr(ch, "close_async")

    def test_rabbitmq_channel_importable(self):
        """RabbitMQChannel class exists and has correct interface."""
        from axon.runtime.channels.rabbitmq_channel import RabbitMQChannel

        ch = RabbitMQChannel(topic="test.orders")
        assert ch.topic == "test.orders"
        assert ch.is_closed is False
        assert hasattr(ch, "connect")
        assert hasattr(ch, "publish")
        assert hasattr(ch, "receive")

    def test_eventbridge_channel_importable(self):
        """EventBridgeChannel class exists and has correct interface."""
        from axon.runtime.channels.eventbridge_channel import EventBridgeChannel

        ch = EventBridgeChannel(
            topic="orders.new",
            bus_name="axon-events",
            queue_url="https://sqs.us-east-1.amazonaws.com/123/q",
        )
        assert ch.topic == "orders.new"
        assert ch.is_closed is False
        assert hasattr(ch, "connect")
        assert hasattr(ch, "publish")
        assert hasattr(ch, "receive")

    def test_kafka_channel_close(self):
        """KafkaChannel.close() marks channel as closed."""
        from axon.runtime.channels.kafka_channel import KafkaChannel

        ch = KafkaChannel(topic="close_test")
        assert ch.is_closed is False
        ch.close()
        assert ch.is_closed is True

    def test_rabbitmq_channel_close(self):
        """RabbitMQChannel.close() marks channel as closed."""
        from axon.runtime.channels.rabbitmq_channel import RabbitMQChannel

        ch = RabbitMQChannel(topic="close_test")
        ch.close()
        assert ch.is_closed is True

    def test_eventbridge_channel_close(self):
        """EventBridgeChannel.close() marks channel as closed."""
        from axon.runtime.channels.eventbridge_channel import EventBridgeChannel

        ch = EventBridgeChannel(topic="close_test", queue_url="url")
        ch.close()
        assert ch.is_closed is True


# ═══════════════════════════════════════════════════════════════════
#  PHASE 2: AXON SERVER CONFIG
# ═══════════════════════════════════════════════════════════════════


class TestAxonServerConfig:
    """AxonServerConfig defaults and construction."""

    def test_defaults(self):
        from axon.server.config import AxonServerConfig

        config = AxonServerConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 8420
        assert config.channel_backend == "memory"
        assert config.state_backend == "memory"
        assert config.auth_token == ""
        assert config.max_daemons == 100
        assert config.log_level == "INFO"
        assert config.default_backend == "anthropic"

    def test_custom_values(self):
        from axon.server.config import AxonServerConfig

        config = AxonServerConfig(
            host="0.0.0.0",
            port=9000,
            channel_backend="kafka",
            auth_token="secret123",
            max_daemons=50,
        )
        assert config.host == "0.0.0.0"
        assert config.port == 9000
        assert config.channel_backend == "kafka"
        assert config.auth_token == "secret123"
        assert config.max_daemons == 50

    def test_supervisor_config_embedded(self):
        from axon.server.config import AxonServerConfig
        from axon.runtime.supervisor import SupervisionStrategy

        config = AxonServerConfig()
        assert config.supervisor.max_restarts == 5
        assert config.supervisor.max_seconds == 60.0
        assert config.supervisor.strategy == SupervisionStrategy.ONE_FOR_ONE


# ═══════════════════════════════════════════════════════════════════
#  PHASE 2: AXON SERVER CORE
# ═══════════════════════════════════════════════════════════════════


class TestAxonServerCore:
    """AxonServer lifecycle and daemon management."""

    async def test_start_and_stop(self):
        """Server starts and stops cleanly."""
        from axon.server import AxonServer

        server = AxonServer()
        assert not server.is_running

        await server.start()
        assert server.is_running
        assert server.bus is not None
        assert server.supervisor is not None
        assert server.state_backend is not None

        await server.stop()
        assert not server.is_running

    async def test_start_idempotent(self):
        """Double start() does not crash."""
        from axon.server import AxonServer

        server = AxonServer()
        await server.start()
        await server.start()  # should be no-op
        assert server.is_running
        await server.stop()

    async def test_stop_idempotent(self):
        """Double stop() does not crash."""
        from axon.server import AxonServer

        server = AxonServer()
        await server.start()
        await server.stop()
        await server.stop()  # should be no-op

    async def test_deploy_before_start_fails(self):
        """deploy() requires server to be running."""
        from axon.server import AxonServer

        server = AxonServer()
        result = await server.deploy("daemon Test {}")
        assert not result.success
        assert "not started" in result.error.lower()

    async def test_deploy_valid_source(self):
        """deploy() compiles source and registers daemons."""
        from axon.server import AxonServer

        server = AxonServer()
        await server.start()

        source = '''
flow TestFlow() -> String {
    daemon TestDaemon(input: String) -> String {
        goal: "Test daemon"
        tools: [WebSearch]
        listen "events" as evt {
            step Process {
                ask: "Process event"
                output: String
            }
        }
    }
}
'''
        result = await server.deploy(source)
        assert result.success
        assert "TestDaemon" in result.daemons_registered
        assert result.deployment_id != ""

        await server.stop()

    async def test_deploy_invalid_source_returns_error(self):
        """deploy() with bad source returns error, doesn't crash."""
        from axon.server import AxonServer

        server = AxonServer()
        await server.start()

        result = await server.deploy("this is not valid axon code {}{{{{")
        assert not result.success
        assert result.error != ""

        await server.stop()

    async def test_list_daemons_after_deploy(self):
        """list_daemons() returns deployed daemons."""
        from axon.server import AxonServer

        server = AxonServer()
        await server.start()

        source = '''
flow TestFlow() -> String {
    daemon MyDaemon(input: String) -> String {
        goal: "Test"
        tools: [Search]
        listen "topic" as e {
            step S { ask: "Do" output: String }
        }
    }
}
'''
        await server.deploy(source)
        daemons = server.list_daemons()
        assert len(daemons) == 1
        assert daemons[0].name == "MyDaemon"

        await server.stop()

    async def test_get_daemon_detail(self):
        """get_daemon() returns info for a deployed daemon."""
        from axon.server import AxonServer

        server = AxonServer()
        await server.start()

        source = '''
flow F() -> String {
    daemon D(input: String) -> String {
        goal: "g"
        tools: [T]
        listen "t" as e {
            step S { ask: "q" output: String }
        }
    }
}
'''
        await server.deploy(source)
        info = server.get_daemon("D")
        assert info is not None
        assert info.name == "D"
        assert info.state == "registered"

        assert server.get_daemon("NonExistent") is None

        await server.stop()

    async def test_stop_daemon(self):
        """stop_daemon() removes the daemon."""
        from axon.server import AxonServer

        server = AxonServer()
        await server.start()

        source = '''
flow F() -> String {
    daemon D(x: String) -> String {
        goal: "g"
        tools: [T]
        listen "t" as e {
            step S { ask: "q" output: String }
        }
    }
}
'''
        await server.deploy(source)
        assert await server.stop_daemon("D") is True
        assert server.get_daemon("D") is None
        assert await server.stop_daemon("D") is False

        await server.stop()

    async def test_publish_event(self):
        """publish_event() sends event through bus."""
        from axon.server import AxonServer

        server = AxonServer()
        await server.start()

        ok = await server.publish_event("test_topic", {"key": "value"})
        assert ok is True

        # Verify event in bus
        ch = server.bus.get_or_create("test_topic")
        event = await ch.receive()
        assert event.payload == {"key": "value"}

        await server.stop()

    async def test_publish_event_before_start(self):
        """publish_event() returns False when server not started."""
        from axon.server import AxonServer

        server = AxonServer()
        ok = await server.publish_event("topic", {"data": 1})
        assert ok is False

    async def test_metrics(self):
        """metrics() returns server stats."""
        from axon.server import AxonServer

        server = AxonServer()
        await server.start()

        m = server.metrics()
        assert m["running"] is True
        assert m["deployments"] == 0
        assert m["daemons_total"] == 0
        assert m["channel_backend"] == "memory"

        await server.stop()

    async def test_daemon_limit_enforced(self):
        """deploy() respects max_daemons limit."""
        from axon.server import AxonServer
        from axon.server.config import AxonServerConfig

        server = AxonServer(AxonServerConfig(max_daemons=1))
        await server.start()

        source = '''
flow F() -> String {
    daemon D1(x: String) -> String {
        goal: "g"
        tools: [T]
        listen "t" as e {
            step S { ask: "q" output: String }
        }
    }
}
'''
        r1 = await server.deploy(source)
        assert r1.success

        source2 = '''
flow F2() -> String {
    daemon D2(x: String) -> String {
        goal: "g"
        tools: [T]
        listen "t" as e {
            step S { ask: "q" output: String }
        }
    }
}
'''
        r2 = await server.deploy(source2)
        assert not r2.success
        assert "limit" in r2.error.lower()

        await server.stop()


# ═══════════════════════════════════════════════════════════════════
#  PHASE 2: HTTP API
# ═══════════════════════════════════════════════════════════════════


class TestHTTPAPI:
    """AxonServer HTTP endpoints via Starlette TestClient."""

    def _make_client(self, auth_token: str = ""):
        """Create test client with embedded AxonServer.

        Uses TestClient as context manager so Starlette fires
        on_startup (server.start) and on_shutdown (server.stop).
        We return a tuple (client, ctx) — caller doesn't need to
        manage the context because pytest test methods run in
        sequence and the GC handles cleanup.
        """
        try:
            from starlette.testclient import TestClient
        except ImportError:
            pytest.skip("starlette not installed")

        from axon.server import AxonServer
        from axon.server.config import AxonServerConfig
        from axon.server.http_app import create_app

        config = AxonServerConfig(auth_token=auth_token)
        server = AxonServer(config)
        app = create_app(server)
        client = TestClient(app)
        # Enter context so that on_startup fires
        client.__enter__()
        return client

    def test_health_endpoint(self):
        """GET /v1/health returns ok."""
        client = self._make_client()
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.28.0"

    def test_metrics_endpoint(self):
        """GET /v1/metrics returns metrics."""
        client = self._make_client()
        resp = client.get("/v1/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data
        assert "daemons_total" in data

    def test_deploy_endpoint(self):
        """POST /v1/deploy compiles and registers daemons."""
        client = self._make_client()
        source = '''
flow F() -> String {
    daemon TestHTTPDaemon(x: String) -> String {
        goal: "test"
        tools: [T]
        listen "t" as e {
            step S { ask: "q" output: String }
        }
    }
}
'''
        resp = client.post(
            "/v1/deploy",
            json={"source": source, "backend": "anthropic"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "TestHTTPDaemon" in data["daemons_registered"]

    def test_deploy_invalid_source(self):
        """POST /v1/deploy with bad source returns 422."""
        client = self._make_client()
        resp = client.post(
            "/v1/deploy",
            json={"source": "this {{ is }} bad {{{{"},
        )
        assert resp.status_code == 422
        assert resp.json()["success"] is False

    def test_deploy_missing_source(self):
        """POST /v1/deploy without source returns 400."""
        client = self._make_client()
        resp = client.post("/v1/deploy", json={"backend": "anthropic"})
        assert resp.status_code == 400

    def test_deploy_no_json_body(self):
        """POST /v1/deploy without JSON returns 400."""
        client = self._make_client()
        resp = client.post("/v1/deploy", content=b"not json")
        assert resp.status_code == 400

    def test_list_daemons_endpoint(self):
        """GET /v1/daemons lists deployed daemons."""
        client = self._make_client()
        resp = client.get("/v1/daemons")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_get_daemon_not_found(self):
        """GET /v1/daemons/{name} returns 404 for unknown daemon."""
        client = self._make_client()
        resp = client.get("/v1/daemons/nonexistent")
        assert resp.status_code == 404

    def test_publish_event_endpoint(self):
        """POST /v1/events/{topic} publishes event."""
        client = self._make_client()
        resp = client.post(
            "/v1/events/test_topic",
            json={"payload": {"key": "value"}},
        )
        assert resp.status_code == 200
        assert resp.json()["published"] is True

    def test_auth_required_when_configured(self):
        """Endpoints require Bearer token when auth_token is set."""
        client = self._make_client(auth_token="secret123")

        # Health is exempt from auth
        resp = client.get("/v1/health")
        assert resp.status_code == 200

        # Other endpoints require auth
        resp = client.get("/v1/daemons")
        assert resp.status_code == 401

        resp = client.get(
            "/v1/daemons",
            headers={"Authorization": "Bearer wrong_token"},
        )
        assert resp.status_code == 403

        resp = client.get(
            "/v1/daemons",
            headers={"Authorization": "Bearer secret123"},
        )
        assert resp.status_code == 200

    def test_deploy_then_list_daemons(self):
        """Deploy → list daemons → verify daemon appears."""
        client = self._make_client()
        source = '''
flow F() -> String {
    daemon APIDaemon(x: String) -> String {
        goal: "test"
        tools: [T]
        listen "t" as e {
            step S { ask: "do" output: String }
        }
    }
}
'''
        client.post("/v1/deploy", json={"source": source})
        resp = client.get("/v1/daemons")
        data = resp.json()
        assert data["total"] == 1
        assert data["daemons"][0]["name"] == "APIDaemon"

    def test_delete_daemon_endpoint(self):
        """DELETE /v1/daemons/{name} removes daemon."""
        client = self._make_client()
        source = '''
flow F() -> String {
    daemon DelDaemon(x: String) -> String {
        goal: "test"
        tools: [T]
        listen "t" as e {
            step S { ask: "do" output: String }
        }
    }
}
'''
        client.post("/v1/deploy", json={"source": source})
        resp = client.delete("/v1/daemons/DelDaemon")
        assert resp.status_code == 200
        assert resp.json()["stopped"] is True

        resp = client.get("/v1/daemons/DelDaemon")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════
#  PHASE 2: REDIS STATE BACKEND (structure only)
# ═══════════════════════════════════════════════════════════════════


class TestRedisStateBackendStructure:
    """RedisStateBackend importable and structurally correct."""

    def test_importable(self):
        from axon.runtime.state_backends.redis_backend import RedisStateBackend

        backend = RedisStateBackend(redis_url="redis://localhost:6379/0")
        assert hasattr(backend, "connect")
        assert hasattr(backend, "save_state")
        assert hasattr(backend, "load_state")
        assert hasattr(backend, "delete_state")
        assert hasattr(backend, "list_pending")
        assert hasattr(backend, "close")

    def test_key_prefix(self):
        from axon.runtime.state_backends.redis_backend import RedisStateBackend

        backend = RedisStateBackend(key_prefix="test:")
        assert backend._key("abc") == "test:abc"

    def test_default_ttl(self):
        from axon.runtime.state_backends.redis_backend import RedisStateBackend

        backend = RedisStateBackend()
        assert backend._ttl == 86400 * 7  # 7 days


# ═══════════════════════════════════════════════════════════════════
#  PHASE 2: CLI ARGUMENTS
# ═══════════════════════════════════════════════════════════════════


class TestCLIServeAndDeploy:
    """CLI argument parsing for serve and deploy commands."""

    def test_serve_args_parsed(self):
        """axon serve accepts --host, --port, --channel."""
        from axon.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "serve",
            "--host", "0.0.0.0",
            "--port", "9000",
            "--channel", "kafka",
        ])
        assert args.command == "serve"
        assert args.host == "0.0.0.0"
        assert args.port == 9000
        assert args.channel == "kafka"

    def test_serve_defaults(self):
        """axon serve defaults."""
        from axon.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["serve"])
        assert args.host == "127.0.0.1"
        assert args.port == 8420
        assert args.channel == "memory"

    def test_deploy_args_parsed(self):
        """axon deploy accepts file, --server, --backend."""
        from axon.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args([
            "deploy",
            "test.axon",
            "--server", "http://remote:8420",
            "--backend", "gemini",
        ])
        assert args.command == "deploy"
        assert args.file == "test.axon"
        assert args.server == "http://remote:8420"
        assert args.backend == "gemini"

    def test_deploy_defaults(self):
        """axon deploy defaults."""
        from axon.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["deploy", "main.axon"])
        assert args.server == "http://localhost:8420"
        assert args.backend == "anthropic"


# ═══════════════════════════════════════════════════════════════════
#  PHASE 2: DEPLOY RESULT
# ═══════════════════════════════════════════════════════════════════


class TestDeployResult:
    """DeployResult dataclass."""

    def test_creation(self):
        from axon.server.server import DeployResult

        result = DeployResult(
            success=True,
            deployment_id="deploy_123",
            daemons_registered=("D1", "D2"),
            flows_compiled=3,
        )
        assert result.success is True
        assert result.deployment_id == "deploy_123"
        assert result.daemons_registered == ("D1", "D2")
        assert result.flows_compiled == 3

    def test_immutable(self):
        from axon.server.server import DeployResult

        result = DeployResult(success=True)
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore[misc]


class TestDaemonInfo:
    """DaemonInfo dataclass."""

    def test_creation(self):
        from axon.server.server import DaemonInfo

        info = DaemonInfo(name="TestDaemon", state="running")
        assert info.name == "TestDaemon"
        assert info.state == "running"
        assert info.events_processed == 0

    def test_defaults(self):
        from axon.server.server import DaemonInfo

        info = DaemonInfo(name="D")
        assert info.state == "idle"
        assert info.restart_count == 0
        assert info.last_event_time == 0.0
