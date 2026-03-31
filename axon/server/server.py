"""
AXON Server — Core Process (AxonServer)
=========================================
The reactive server that converts AXON from a library into a platform.

Formal model (paper §5):
  AxonServer = EventBus ⊗ Supervisor ⊗ StateBackend ⊗ Executor

Lifecycle:
  1. start()  — boot event bus, supervisor, state backend
  2. deploy() — compile .axon source → register daemons in supervisor
  3. run()    — supervisor.start_all(), event loop processes events
  4. stop()   — graceful shutdown (supervisor.stop_all, bus.close_all)

The AxonServer owns the asyncio event loop and coordinates all
daemon processes. It is the single entry point for the HTTP/WS API.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from axon.runtime.channels import make_channel_factory
from axon.runtime.event_bus import EventBus
from axon.runtime.state_backend import InMemoryStateBackend, StateBackend
from axon.runtime.supervisor import DaemonSupervisor

from axon.server.config import AxonServerConfig

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  DEPLOY RESULT
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DeployResult:
    """Result of deploying an .axon source to the server."""
    success: bool
    deployment_id: str = ""
    daemons_registered: tuple[str, ...] = ()
    flows_compiled: int = 0
    error: str = ""
    timestamp: float = 0.0


@dataclass
class DaemonInfo:
    """Runtime status of a deployed daemon."""
    name: str
    state: str = "idle"           # idle | running | hibernating | stopped | crashed
    events_processed: int = 0
    last_event_time: float = 0.0
    restart_count: int = 0
    deployment_id: str = ""


# ═══════════════════════════════════════════════════════════════════
#  AXON SERVER
# ═══════════════════════════════════════════════════════════════════

class AxonServer:
    """
    The reactive AxonServer process.

    Coordinates EventBus, DaemonSupervisor, StateBackend, and the
    compilation pipeline into a single server process.

    Usage:
        config = AxonServerConfig(port=8420)
        server = AxonServer(config)
        await server.start()
        result = await server.deploy(source_code, backend="anthropic")
        # ... server processes events via daemons ...
        await server.stop()
    """

    def __init__(self, config: AxonServerConfig | None = None) -> None:
        self._config = config or AxonServerConfig()
        self._bus: EventBus | None = None
        self._supervisor: DaemonSupervisor | None = None
        self._state_backend: StateBackend | None = None
        self._deployments: dict[str, Any] = {}          # deployment_id → CompiledProgram
        self._daemon_info: dict[str, DaemonInfo] = {}    # daemon_name → DaemonInfo
        self._running = False
        self._started_at: float = 0.0

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self) -> None:
        """Boot all server subsystems."""
        if self._running:
            return

        logger.info(
            "AxonServer starting on %s:%d (channel=%s, state=%s)",
            self._config.host,
            self._config.port,
            self._config.channel_backend,
            self._config.state_backend,
        )

        # Event Bus with configured channel factory
        factory_config = {"backend": self._config.channel_backend}
        factory_config.update(self._config.channel_config)
        channel_factory = make_channel_factory(factory_config)
        self._bus = EventBus(channel_factory=channel_factory)

        # State Backend
        self._state_backend = self._resolve_state_backend()

        # Supervisor
        self._supervisor = DaemonSupervisor(config=self._config.supervisor)

        self._running = True
        self._started_at = time.time()

        logger.info("AxonServer started successfully")

    async def stop(self) -> None:
        """Graceful shutdown of all subsystems."""
        if not self._running:
            return

        logger.info("AxonServer shutting down...")
        self._running = False

        if self._supervisor:
            await self._supervisor.stop_all()
        if self._bus:
            self._bus.close_all()

        # Update all daemon states
        for info in self._daemon_info.values():
            if info.state == "running":
                info.state = "stopped"

        logger.info("AxonServer stopped")

    # ── Deployment ────────────────────────────────────────────

    async def deploy(
        self,
        source: str,
        backend_name: str = "",
        deployment_id: str = "",
    ) -> DeployResult:
        """
        Compile .axon source and register daemons in the supervisor.

        Pipeline: Source → Lexer → Parser → TypeChecker → IRGenerator
                  → Backend → CompiledProgram → extract daemons → register

        Args:
            source:        AXON source code string
            backend_name:  LLM backend ("anthropic", "gemini", etc.)
            deployment_id: Optional custom deployment ID

        Returns:
            DeployResult with status and registered daemon names.
        """
        if not self._running:
            return DeployResult(
                success=False,
                error="Server not started. Call start() first.",
                timestamp=time.time(),
            )

        backend_name = backend_name or self._config.default_backend
        deploy_id = deployment_id or f"deploy_{int(time.time() * 1000)}"

        try:
            compiled, daemon_names = self._compile_source(source, backend_name)
        except Exception as exc:
            logger.error("Deployment %s failed: %s", deploy_id, exc)
            return DeployResult(
                success=False,
                deployment_id=deploy_id,
                error=str(exc),
                timestamp=time.time(),
            )

        # Check daemon limit
        total = len(self._daemon_info) + len(daemon_names)
        if total > self._config.max_daemons:
            return DeployResult(
                success=False,
                deployment_id=deploy_id,
                error=f"Daemon limit exceeded: {total}/{self._config.max_daemons}",
                timestamp=time.time(),
            )

        self._deployments[deploy_id] = compiled

        # Register daemons in supervisor
        for name in daemon_names:
            self._daemon_info[name] = DaemonInfo(
                name=name,
                state="registered",
                deployment_id=deploy_id,
            )

        logger.info(
            "Deployed %s: %d daemons (%s)",
            deploy_id,
            len(daemon_names),
            ", ".join(daemon_names),
        )

        return DeployResult(
            success=True,
            deployment_id=deploy_id,
            daemons_registered=tuple(daemon_names),
            flows_compiled=len(compiled.execution_units),
            timestamp=time.time(),
        )

    # ── Daemon Management ─────────────────────────────────────

    def list_daemons(self) -> list[DaemonInfo]:
        """List all deployed daemons and their status."""
        return list(self._daemon_info.values())

    def get_daemon(self, name: str) -> DaemonInfo | None:
        """Get status of a specific daemon."""
        return self._daemon_info.get(name)

    async def hibernate_daemon(self, name: str) -> bool:
        """Force-hibernate a running daemon."""
        info = self._daemon_info.get(name)
        if not info or info.state != "running":
            return False
        info.state = "hibernating"
        return True

    async def resume_daemon(self, name: str) -> bool:
        """Resume a hibernated daemon."""
        info = self._daemon_info.get(name)
        if not info or info.state != "hibernating":
            return False
        info.state = "running"
        return True

    async def stop_daemon(self, name: str) -> bool:
        """Stop and remove a deployed daemon."""
        info = self._daemon_info.get(name)
        if not info:
            return False
        info.state = "stopped"
        self._daemon_info.pop(name, None)
        return True

    # ── Event Publishing ──────────────────────────────────────

    async def publish_event(self, topic: str, payload: Any) -> bool:
        """Publish an event to a topic on the event bus."""
        if not self._bus:
            return False
        from axon.runtime.event_bus import Event
        import uuid
        event = Event(
            topic=topic,
            payload=payload,
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
        )
        await self._bus.publish(topic, event)
        return True

    # ── Metrics ───────────────────────────────────────────────

    def metrics(self) -> dict[str, Any]:
        """Server metrics snapshot."""
        return {
            "running": self._running,
            "uptime_seconds": time.time() - self._started_at if self._running else 0,
            "deployments": len(self._deployments),
            "daemons_total": len(self._daemon_info),
            "daemons_running": sum(
                1 for d in self._daemon_info.values() if d.state == "running"
            ),
            "daemons_hibernating": sum(
                1 for d in self._daemon_info.values() if d.state == "hibernating"
            ),
            "event_bus_topics": self._bus.topics() if self._bus else [],
            "channel_backend": self._config.channel_backend,
            "state_backend": self._config.state_backend,
        }

    # ── Properties ────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def bus(self) -> EventBus | None:
        return self._bus

    @property
    def supervisor(self) -> DaemonSupervisor | None:
        return self._supervisor

    @property
    def state_backend(self) -> StateBackend | None:
        return self._state_backend

    @property
    def config(self) -> AxonServerConfig:
        return self._config

    # ── Private ───────────────────────────────────────────────

    def _compile_source(
        self,
        source: str,
        backend_name: str,
    ) -> tuple[Any, list[str]]:
        """
        Compile AXON source through the full pipeline.

        Returns:
            (CompiledProgram, list of daemon names)
        """
        from axon.compiler.lexer import Lexer
        from axon.compiler.parser import Parser
        from axon.compiler.type_checker import TypeChecker
        from axon.compiler.ir_generator import IRGenerator
        from axon.backends import get_backend

        tokens = Lexer(source).tokenize()
        ast = Parser(tokens).parse()
        TypeChecker(ast).check()
        ir_program = IRGenerator().generate(ast)

        backend = get_backend(backend_name)
        compiled = backend.compile_program(ir_program)

        # Extract daemon names from IR
        daemon_names = [d.name for d in ir_program.daemons]

        return compiled, daemon_names

    def _resolve_state_backend(self) -> StateBackend:
        """Resolve the state backend from config."""
        name = self._config.state_backend
        if name == "memory":
            return InMemoryStateBackend()
        if name == "redis":
            from axon.runtime.state_backends.redis_backend import RedisStateBackend
            redis_url = self._config.state_config.get(
                "redis_url", "redis://localhost:6379"
            )
            return RedisStateBackend(redis_url=redis_url)
        raise ValueError(f"Unknown state backend: {name}")
