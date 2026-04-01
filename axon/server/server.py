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
import asyncio
import json
import math
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Any

from axon.runtime.tracer import TraceEventType, Tracer

from axon.runtime.channels import make_channel_factory
from axon.runtime.event_bus import EventBus
from axon.runtime.state_backend import InMemoryStateBackend, StateBackend
from axon.runtime.supervisor import DaemonSupervisor

from axon.server.config import AxonServerConfig
from axon.server.model_clients import create_endpoint_model_client

logger = logging.getLogger(__name__)
_ENDPOINT_LATENCY_WINDOW = 512


# ═══════════════════════════════════════════════════════════════════
#  DEPLOY RESULT
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DeployResult:
    """Result of deploying an .axon source to the server."""
    success: bool
    deployment_id: str = ""
    daemons_registered: tuple[str, ...] = ()
    endpoints_registered: tuple[str, ...] = ()
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


@dataclass
class EndpointInfo:
    """Runtime status of a deployed axonendpoint."""
    name: str
    method: str = "POST"
    path: str = ""
    execute_flow: str = ""
    output_type: str = ""
    shield_ref: str = ""
    retries: int = 0
    timeout: str = ""
    deployment_id: str = ""


@dataclass(frozen=True)
class EndpointExecutionResult:
    """Result of serving an HTTP request through an axonendpoint flow."""
    success: bool
    status_code: int
    trace_id: str
    endpoint_name: str
    output_type: str = ""
    response: Any = None
    error: str = ""
    duration_ms: float = 0.0


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
        self._endpoint_info: dict[str, EndpointInfo] = {}  # endpoint_name → EndpointInfo
        self._running = False
        self._started_at: float = 0.0
        self._endpoint_semaphore: Any = None
        self._endpoint_model_client: Any = None
        self._endpoint_model_metrics: dict[str, Any] = {}
        self._endpoint_route_metrics: dict[str, dict[str, Any]] = {}
        self._endpoint_traces: dict[str, dict[str, Any]] = {}
        self._endpoint_trace_order: deque[str] = deque()
        self._tracer = Tracer(program_name="axonserver", backend_name="server")

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
        self._endpoint_semaphore = asyncio.Semaphore(
            max(1, self._config.endpoint_max_concurrency)
        )
        self._endpoint_model_client = self._build_endpoint_model_client()
        self._endpoint_model_metrics = self._init_endpoint_model_metrics()
        self._endpoint_route_metrics = {}

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
            compiled, daemon_names, endpoint_specs = self._compile_source(source, backend_name)
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

        endpoint_names: list[str] = []
        for spec in endpoint_specs:
            self._endpoint_info[spec.name] = EndpointInfo(
                name=spec.name,
                method=spec.method,
                path=spec.path,
                execute_flow=spec.execute_flow,
                output_type=spec.output_type,
                shield_ref=spec.shield_ref,
                retries=spec.retries,
                timeout=spec.timeout,
                deployment_id=deploy_id,
            )
            endpoint_names.append(spec.name)

        logger.info(
            "Deployed %s: %d daemons, %d endpoints",
            deploy_id,
            len(daemon_names),
            len(endpoint_names),
        )

        return DeployResult(
            success=True,
            deployment_id=deploy_id,
            daemons_registered=tuple(daemon_names),
            endpoints_registered=tuple(endpoint_names),
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

    def list_endpoints(self) -> list[EndpointInfo]:
        """List all deployed endpoints."""
        return list(self._endpoint_info.values())

    def get_endpoint(self, name: str) -> EndpointInfo | None:
        """Get status/config of a specific endpoint."""
        return self._endpoint_info.get(name)

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

    async def execute_endpoint_request(
        self,
        endpoint: EndpointInfo,
        *,
        payload: dict[str, Any],
        trace_id: str,
    ) -> EndpointExecutionResult:
        """Execute an endpoint request with backpressure and per-request isolation."""
        unavailable = self._endpoint_unavailable_result(endpoint, trace_id)
        if unavailable is not None:
            return self._finalize_endpoint_result(unavailable)

        queue_timeout = max(0.001, float(self._config.endpoint_queue_timeout_seconds))
        req_start = time.perf_counter()

        try:
            await asyncio.wait_for(self._endpoint_semaphore.acquire(), timeout=queue_timeout)
        except asyncio.TimeoutError:
            return self._finalize_endpoint_result(self._endpoint_error_result(
                endpoint,
                trace_id,
                status_code=429,
                error="Endpoint is saturated. Retry later.",
            ))

        try:
            result = await self._execute_endpoint_with_slot(
                endpoint=endpoint,
                payload=payload,
                trace_id=trace_id,
                req_start=req_start,
            )
            return self._finalize_endpoint_result(result)
        except asyncio.TimeoutError:
            return self._finalize_endpoint_result(self._endpoint_error_result(
                endpoint,
                trace_id,
                status_code=504,
                error="Endpoint execution timeout.",
                duration_ms=(time.perf_counter() - req_start) * 1000,
            ))
        except Exception as exc:
            return self._finalize_endpoint_result(self._endpoint_error_result(
                endpoint,
                trace_id,
                status_code=500,
                error=str(exc),
                duration_ms=(time.perf_counter() - req_start) * 1000,
            ))
        finally:
            self._endpoint_semaphore.release()

    def get_endpoint_trace(self, trace_id: str) -> dict[str, Any] | None:
        """Return a recorded endpoint execution trace by trace id."""
        return self._endpoint_traces.get(trace_id)

    # ── Metrics ───────────────────────────────────────────────

    def metrics(
        self,
        top_n: int = 5,
        score_weights: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Server metrics snapshot."""
        safe_top_n = max(1, int(top_n))
        effective_weights = self._score_weights_snapshot(score_weights)
        route_snapshot = self._endpoint_route_metrics_snapshot(effective_weights)
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
            "endpoints_total": len(self._endpoint_info),
            "endpoint_inflight": self._endpoint_inflight_count(),
            "endpoint_trace_cache": len(self._endpoint_traces),
            "endpoint_model": self._endpoint_model_metrics_snapshot(),
            "endpoint_routes": route_snapshot,
            "endpoint_routes_top": self._endpoint_route_top_summary(
                route_snapshot,
                top_n=safe_top_n,
                score_weights=effective_weights,
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
    ) -> tuple[Any, list[str], list[Any]]:
        """
        Compile AXON source through the full pipeline.

        Returns:
            (CompiledProgram, list of daemon names, list of endpoint specs)
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
        endpoint_specs = list(ir_program.endpoints)

        return compiled, daemon_names, endpoint_specs

    def record_endpoint_event(
        self,
        endpoint_name: str,
        *,
        method: str,
        path: str,
        trace_id: str,
        status_code: int,
    ) -> None:
        """Emit holographic endpoint telemetry for each HTTP ingress call."""
        self._tracer.start_span(
            f"endpoint:{endpoint_name}",
            metadata={"trace_id": trace_id, "method": method, "path": path},
        )
        self._tracer.emit(
            TraceEventType.ENDPOINT_REQUEST_START,
            step_name=endpoint_name,
            data={"phase": "ingress", "method": method, "path": path},
        )
        self._tracer.emit(
            TraceEventType.ENDPOINT_REQUEST_END,
            step_name=endpoint_name,
            data={"phase": "egress", "status_code": status_code, "trace_id": trace_id},
        )
        self._tracer.end_span()

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

    def _endpoint_inflight_count(self) -> int:
        if self._endpoint_semaphore is None:
            return 0
        value = getattr(self._endpoint_semaphore, "_value", None)
        if not isinstance(value, int):
            return 0
        return max(0, self._config.endpoint_max_concurrency - value)

    def _resolve_endpoint_unit(self, endpoint: EndpointInfo) -> Any:
        compiled = self._deployments.get(endpoint.deployment_id)
        if compiled is None:
            return None
        return next(
            (u for u in compiled.execution_units if u.flow_name == endpoint.execute_flow),
            None,
        )

    def _bind_endpoint_request(self, unit: Any, payload: dict[str, Any], trace_id: str) -> Any:
        """Create a request-local execution unit with payload prelude in first step."""
        from axon.backends.base_backend import CompiledExecutionUnit

        payload_json = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        steps = list(unit.steps)
        if steps:
            first = steps[0]
            prelude = (
                "Endpoint request payload (JSON):\n"
                f"{payload_json}\n\n"
                f"Trace ID: {trace_id}\n\n"
            )
            steps[0] = replace(first, user_prompt=prelude + first.user_prompt)

        metadata = dict(unit.metadata)
        metadata["endpoint_trace_id"] = trace_id
        metadata["endpoint_payload"] = payload

        return CompiledExecutionUnit(
            flow_name=unit.flow_name,
            persona_name=unit.persona_name,
            context_name=unit.context_name,
            system_prompt=unit.system_prompt,
            steps=steps,
            tool_declarations=list(unit.tool_declarations),
            anchor_instructions=list(unit.anchor_instructions),
            active_anchors=list(unit.active_anchors),
            effort=unit.effort,
            metadata=metadata,
        )

    def _store_endpoint_trace(self, trace_id: str, trace: dict[str, Any]) -> None:
        limit = max(1, int(self._config.endpoint_trace_history_size))
        if trace_id in self._endpoint_traces:
            self._endpoint_traces[trace_id] = trace
            return

        self._endpoint_traces[trace_id] = trace
        self._endpoint_trace_order.append(trace_id)
        while len(self._endpoint_trace_order) > limit:
            old_id = self._endpoint_trace_order.popleft()
            self._endpoint_traces.pop(old_id, None)

    def _endpoint_unavailable_result(
        self,
        endpoint: EndpointInfo,
        trace_id: str,
    ) -> EndpointExecutionResult | None:
        if not self._running:
            return self._endpoint_error_result(
                endpoint,
                trace_id,
                status_code=503,
                error="Server not running.",
            )
        if self._endpoint_semaphore is None:
            return self._endpoint_error_result(
                endpoint,
                trace_id,
                status_code=503,
                error="Server execution gate unavailable.",
            )
        if self._endpoint_model_client is None:
            return self._endpoint_error_result(
                endpoint,
                trace_id,
                status_code=503,
                error="Server model client unavailable.",
            )
        return None

    def _endpoint_error_result(
        self,
        endpoint: EndpointInfo,
        trace_id: str,
        *,
        status_code: int,
        error: str,
        duration_ms: float = 0.0,
    ) -> EndpointExecutionResult:
        return EndpointExecutionResult(
            success=False,
            status_code=status_code,
            trace_id=trace_id,
            endpoint_name=endpoint.name,
            output_type=endpoint.output_type,
            error=error,
            duration_ms=duration_ms,
        )

    async def _execute_endpoint_with_slot(
        self,
        *,
        endpoint: EndpointInfo,
        payload: dict[str, Any],
        trace_id: str,
        req_start: float,
    ) -> EndpointExecutionResult:
        from axon.backends.base_backend import CompiledProgram
        from axon.runtime.executor import Executor

        unit = self._resolve_endpoint_unit(endpoint)
        if unit is None:
            return self._endpoint_error_result(
                endpoint,
                trace_id,
                status_code=422,
                error=(
                    f"Flow '{endpoint.execute_flow}' not found in deployment "
                    f"'{endpoint.deployment_id}'."
                ),
            )

        request_unit = self._bind_endpoint_request(unit, payload, trace_id)
        program = CompiledProgram(
            backend_name=self._config.default_backend,
            execution_units=[request_unit],
            metadata={"program_name": f"endpoint:{endpoint.name}", "trace_id": trace_id},
        )
        request_timeout = max(0.1, float(self._config.endpoint_request_timeout_seconds))
        executor = Executor(client=self._endpoint_model_client)
        execution = await asyncio.wait_for(executor.execute(program), timeout=request_timeout)
        unit_result = execution.unit_results[0] if execution.unit_results else None

        response_payload: Any = {"ok": execution.success}
        if unit_result and unit_result.step_results:
            last = unit_result.step_results[-1]
            if last.response:
                response_payload = last.response.structured or last.response.content

        trace_dict = execution.trace.to_dict() if execution.trace else {}
        self._store_endpoint_trace(trace_id, trace_dict)

        status = 200 if execution.success else 422
        err = unit_result.error if (unit_result and unit_result.error) else ""
        duration_ms = (time.perf_counter() - req_start) * 1000

        return EndpointExecutionResult(
            success=execution.success,
            status_code=status,
            trace_id=trace_id,
            endpoint_name=endpoint.name,
            output_type=endpoint.output_type,
            response=response_payload,
            error=err,
            duration_ms=duration_ms,
        )

    def _build_endpoint_model_client(self) -> Any:
        return create_endpoint_model_client(self._config, logger=logger)

    def _init_endpoint_model_metrics(self) -> dict[str, Any]:
        provider = self._endpoint_model_provider()
        model = self._endpoint_model_name()
        transport = self._endpoint_model_transport()
        return {
            "provider": provider,
            "model": model,
            "transport": transport,
            "requests_total": 0,
            "success_total": 0,
            "error_total": 0,
            "backpressure_total": 0,
            "timeout_total": 0,
            "latency_total_ms": 0.0,
            "latency_avg_ms": 0.0,
            "providers": {
                provider: {
                    "requests_total": 0,
                    "success_total": 0,
                    "error_total": 0,
                    "latency_total_ms": 0.0,
                    "latency_avg_ms": 0.0,
                }
            },
        }

    def _endpoint_model_metrics_snapshot(self) -> dict[str, Any]:
        if not self._endpoint_model_metrics:
            return self._init_endpoint_model_metrics()
        snapshot = dict(self._endpoint_model_metrics)
        providers = snapshot.get("providers", {})
        snapshot["providers"] = {k: dict(v) for k, v in providers.items()}
        return snapshot

    def _endpoint_model_provider(self) -> str:
        return str(getattr(self._endpoint_model_client, "provider_name", "deterministic"))

    def _endpoint_model_name(self) -> str:
        return str(getattr(self._endpoint_model_client, "model_name", "deterministic"))

    def _endpoint_model_transport(self) -> str:
        return str(getattr(self._endpoint_model_client, "transport_kind", "local"))

    def _finalize_endpoint_result(self, result: EndpointExecutionResult) -> EndpointExecutionResult:
        self._record_endpoint_model_metrics(result)
        self._record_endpoint_route_metrics(result)
        return result

    def _record_endpoint_model_metrics(self, result: EndpointExecutionResult) -> None:
        if not self._endpoint_model_metrics:
            self._endpoint_model_metrics = self._init_endpoint_model_metrics()

        provider = self._endpoint_model_provider()
        top = self._endpoint_model_metrics
        top["provider"] = provider
        top["model"] = self._endpoint_model_name()
        top["transport"] = self._endpoint_model_transport()
        top["requests_total"] += 1
        top["latency_total_ms"] += float(result.duration_ms)
        top["latency_avg_ms"] = round(
            top["latency_total_ms"] / max(1, top["requests_total"]),
            2,
        )

        if result.success:
            top["success_total"] += 1
        else:
            top["error_total"] += 1

        if result.status_code == 429:
            top["backpressure_total"] += 1
        if result.status_code == 504:
            top["timeout_total"] += 1

        providers = top.setdefault("providers", {})
        bucket = providers.setdefault(
            provider,
            {
                "requests_total": 0,
                "success_total": 0,
                "error_total": 0,
                "latency_total_ms": 0.0,
                "latency_avg_ms": 0.0,
            },
        )
        bucket["requests_total"] += 1
        bucket["latency_total_ms"] += float(result.duration_ms)
        bucket["latency_avg_ms"] = round(
            bucket["latency_total_ms"] / max(1, bucket["requests_total"]),
            2,
        )
        if result.success:
            bucket["success_total"] += 1
        else:
            bucket["error_total"] += 1

    def _record_endpoint_route_metrics(self, result: EndpointExecutionResult) -> None:
        endpoint = self._endpoint_info.get(result.endpoint_name)
        if endpoint is None:
            return

        route_key = f"{endpoint.method.upper()} {endpoint.path}"
        bucket = self._endpoint_route_metrics.setdefault(
            route_key,
            {
                "endpoint_name": endpoint.name,
                "method": endpoint.method.upper(),
                "path": endpoint.path,
                "requests_total": 0,
                "success_total": 0,
                "error_total": 0,
                "backpressure_total": 0,
                "timeout_total": 0,
                "latency_total_ms": 0.0,
                "latency_avg_ms": 0.0,
                "latency_min_ms": 0.0,
                "latency_max_ms": 0.0,
                "latency_p95_ms": 0.0,
                "latency_p99_ms": 0.0,
                "error_rate": 0.0,
                "priority_score": 0.0,
                "_latencies": deque(maxlen=_ENDPOINT_LATENCY_WINDOW),
            },
        )

        latency_ms = float(result.duration_ms)
        bucket["requests_total"] += 1
        bucket["latency_total_ms"] += latency_ms
        bucket["latency_avg_ms"] = round(
            bucket["latency_total_ms"] / max(1, bucket["requests_total"]),
            2,
        )
        latencies: deque[float] = bucket["_latencies"]
        latencies.append(latency_ms)
        bucket["latency_min_ms"] = round(min(latencies), 2) if latencies else 0.0
        bucket["latency_max_ms"] = round(max(latencies), 2) if latencies else 0.0
        bucket["latency_p95_ms"] = self._percentile(list(latencies), 95)
        bucket["latency_p99_ms"] = self._percentile(list(latencies), 99)

        if result.success:
            bucket["success_total"] += 1
        else:
            bucket["error_total"] += 1

        if result.status_code == 429:
            bucket["backpressure_total"] += 1
        if result.status_code == 504:
            bucket["timeout_total"] += 1

        bucket["error_rate"] = round(
            bucket["error_total"] / max(1, bucket["requests_total"]),
            4,
        )
        bucket["priority_score"] = self._priority_score(
            error_rate=float(bucket["error_rate"]),
            p95_ms=float(bucket["latency_p95_ms"]),
            requests_total=int(bucket["requests_total"]),
        )

    def _endpoint_route_metrics_snapshot(
        self,
        score_weights: dict[str, float] | None = None,
    ) -> dict[str, dict[str, Any]]:
        snapshot: dict[str, dict[str, Any]] = {}
        effective_weights = self._score_weights_snapshot(score_weights)
        for key, raw in self._endpoint_route_metrics.items():
            view = dict(raw)
            view.pop("_latencies", None)
            view["priority_score"] = self._priority_score(
                error_rate=float(view.get("error_rate", 0.0)),
                p95_ms=float(view.get("latency_p95_ms", 0.0)),
                requests_total=int(view.get("requests_total", 0)),
                weights=effective_weights,
            )
            snapshot[key] = view
        return snapshot

    def _endpoint_route_top_summary(
        self,
        route_snapshot: dict[str, dict[str, Any]],
        *,
        top_n: int,
        score_weights: dict[str, float],
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for route_key, row in route_snapshot.items():
            item = dict(row)
            item["route"] = route_key
            rows.append(item)

        slowest = sorted(
            rows,
            key=lambda r: (
                float(r.get("latency_p95_ms", 0.0)),
                float(r.get("latency_avg_ms", 0.0)),
                int(r.get("requests_total", 0)),
            ),
            reverse=True,
        )[:top_n]
        error_prone = sorted(
            rows,
            key=lambda r: (
                float(r.get("error_rate", 0.0)),
                int(r.get("error_total", 0)),
                int(r.get("requests_total", 0)),
            ),
            reverse=True,
        )[:top_n]
        by_volume = sorted(
            rows,
            key=lambda r: (
                int(r.get("requests_total", 0)),
                float(r.get("latency_p95_ms", 0.0)),
            ),
            reverse=True,
        )[:top_n]
        by_score = sorted(
            rows,
            key=lambda r: (
                float(r.get("priority_score", 0.0)),
                float(r.get("error_rate", 0.0)),
                float(r.get("latency_p95_ms", 0.0)),
            ),
            reverse=True,
        )[:top_n]

        return {
            "top_n": top_n,
            "score_weights": score_weights,
            "slowest_p95": slowest,
            "highest_error_rate": error_prone,
            "top_by_volume": by_volume,
            "top_by_score": by_score,
        }

    def _priority_score(
        self,
        *,
        error_rate: float,
        p95_ms: float,
        requests_total: int,
        weights: dict[str, float] | None = None,
    ) -> float:
        resolved = self._score_weights_snapshot(weights)
        w_error = max(0.0, float(resolved["error"]))
        w_latency = max(0.0, float(resolved["latency"]))
        w_volume = max(0.0, float(resolved["volume"]))
        volume = math.log1p(max(0, requests_total))
        score = (
            max(0.0, error_rate) * w_error
            * max(0.0, p95_ms) * w_latency
            * volume * w_volume
        )
        return round(score, 4)

    def _score_weights_snapshot(
        self,
        override: dict[str, float] | None = None,
    ) -> dict[str, float]:
        base = {
            "error": float(getattr(self._config, "endpoint_score_weight_error", 1.0)),
            "latency": float(getattr(self._config, "endpoint_score_weight_latency", 1.0)),
            "volume": float(getattr(self._config, "endpoint_score_weight_volume", 1.0)),
        }
        if not override:
            return base

        result = dict(base)
        for key in ("error", "latency", "volume"):
            if key in override and override[key] is not None:
                try:
                    result[key] = float(override[key])
                except (TypeError, ValueError):
                    pass
        return result

    @staticmethod
    def _percentile(values: list[float], p: int) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        idx = max(0, min(len(sorted_vals) - 1, int((p / 100) * len(sorted_vals) + 0.999999) - 1))
        return round(float(sorted_vals[idx]), 2)
