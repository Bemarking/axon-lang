"""
AXON Server — HTTP & WebSocket API
=====================================
Starlette-based ASGI application exposing AxonServer over HTTP/WS.

Endpoints:
  POST   /v1/deploy                  Deploy .axon source
  POST   /v1/events/{topic}          Publish event to topic
  GET    /v1/daemons                 List active daemons
  GET    /v1/daemons/{name}          Daemon detail
  POST   /v1/daemons/{name}/hibernate  Force hibernate
  POST   /v1/daemons/{name}/resume     Resume hibernated daemon
  DELETE /v1/daemons/{name}          Stop and remove daemon
  GET    /v1/health                  Health check
  GET    /v1/metrics                 Server metrics
  WS     /v1/ws/events/{topic}       WebSocket event streaming

Security:
  - Bearer token auth middleware (configurable)
  - Request body size limit (1MB default)
  - JSON content-type enforcement on POST

Dependency: starlette>=0.41, uvicorn>=0.32
  (installed via ``pip install axon-lang[server]``)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Maximum request body size (1 MB)
_MAX_BODY_SIZE = 1_048_576


def create_app(server: Any) -> Any:
    """
    Create the Starlette ASGI application wired to an AxonServer.

    Args:
        server: An AxonServer instance (already started or will be).

    Returns:
        A Starlette application.
    """
    try:
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from starlette.routing import Route, WebSocketRoute
        from starlette.websockets import WebSocket
    except ImportError as exc:
        raise ImportError(
            "starlette is required for AxonServer HTTP API. "
            "Install it with: pip install axon-lang[server]"
        ) from exc

    # ── Auth Middleware ────────────────────────────────────────

    from starlette.middleware.base import BaseHTTPMiddleware

    class AuthMiddleware(BaseHTTPMiddleware):
        """Bearer token authentication middleware."""

        async def dispatch(self, request: Request, call_next: Any) -> Any:
            token = server.config.auth_token
            if not token:
                return await call_next(request)

            # Skip auth for health check
            if request.url.path == "/v1/health":
                return await call_next(request)

            auth_header = request.headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                return JSONResponse(
                    {"error": "Missing or invalid Authorization header"},
                    status_code=401,
                )
            if auth_header[7:] != token:
                return JSONResponse(
                    {"error": "Invalid token"},
                    status_code=403,
                )
            return await call_next(request)

    # ── Request Helpers ───────────────────────────────────────

    async def _read_json(request: Request) -> dict[str, Any] | None:
        """Read and validate JSON body with size limit."""
        content_type = request.headers.get("content-type", "")
        if "application/json" not in content_type:
            return None

        body = await request.body()
        if len(body) > _MAX_BODY_SIZE:
            return None
        try:
            return json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    # ── Route Handlers ────────────────────────────────────────

    async def health(request: Request) -> JSONResponse:
        """GET /v1/health — Health check."""
        return JSONResponse({
            "status": "ok" if server.is_running else "stopped",
            "version": "0.28.0",
            "timestamp": time.time(),
        })

    async def metrics(request: Request) -> JSONResponse:
        """GET /v1/metrics — Server metrics."""
        return JSONResponse(server.metrics())

    async def deploy(request: Request) -> JSONResponse:
        """POST /v1/deploy — Deploy .axon source."""
        data = await _read_json(request)
        if data is None:
            return JSONResponse(
                {"error": "Invalid JSON body. Content-Type must be application/json."},
                status_code=400,
            )

        source = data.get("source", "")
        if not source or not isinstance(source, str):
            return JSONResponse(
                {"error": "Missing or empty 'source' field."},
                status_code=400,
            )

        backend = data.get("backend", "")
        deployment_id = data.get("deployment_id", "")

        result = await server.deploy(
            source=source,
            backend_name=backend,
            deployment_id=deployment_id,
        )

        status = 200 if result.success else 422
        return JSONResponse({
            "success": result.success,
            "deployment_id": result.deployment_id,
            "daemons_registered": list(result.daemons_registered),
            "flows_compiled": result.flows_compiled,
            "error": result.error,
            "timestamp": result.timestamp,
        }, status_code=status)

    async def publish_event(request: Request) -> JSONResponse:
        """POST /v1/events/{topic} — Publish event."""
        topic = request.path_params["topic"]
        data = await _read_json(request)
        if data is None:
            return JSONResponse(
                {"error": "Invalid JSON body."},
                status_code=400,
            )

        payload = data.get("payload", data)
        ok = await server.publish_event(topic, payload)

        if not ok:
            return JSONResponse(
                {"error": "Server not running or bus unavailable."},
                status_code=503,
            )
        return JSONResponse({
            "published": True,
            "topic": topic,
            "timestamp": time.time(),
        })

    async def list_daemons(request: Request) -> JSONResponse:
        """GET /v1/daemons — List all daemons."""
        daemons = server.list_daemons()
        return JSONResponse({
            "daemons": [
                {
                    "name": d.name,
                    "state": d.state,
                    "events_processed": d.events_processed,
                    "last_event_time": d.last_event_time,
                    "restart_count": d.restart_count,
                    "deployment_id": d.deployment_id,
                }
                for d in daemons
            ],
            "total": len(daemons),
        })

    async def get_daemon(request: Request) -> JSONResponse:
        """GET /v1/daemons/{name} — Daemon detail."""
        name = request.path_params["name"]
        info = server.get_daemon(name)
        if info is None:
            return JSONResponse(
                {"error": f"Daemon '{name}' not found."},
                status_code=404,
            )
        return JSONResponse({
            "name": info.name,
            "state": info.state,
            "events_processed": info.events_processed,
            "last_event_time": info.last_event_time,
            "restart_count": info.restart_count,
            "deployment_id": info.deployment_id,
        })

    async def hibernate_daemon(request: Request) -> JSONResponse:
        """POST /v1/daemons/{name}/hibernate — Force hibernate."""
        name = request.path_params["name"]
        ok = await server.hibernate_daemon(name)
        if not ok:
            return JSONResponse(
                {"error": f"Cannot hibernate daemon '{name}'."},
                status_code=409,
            )
        return JSONResponse({"hibernated": True, "daemon": name})

    async def resume_daemon(request: Request) -> JSONResponse:
        """POST /v1/daemons/{name}/resume — Resume daemon."""
        name = request.path_params["name"]
        ok = await server.resume_daemon(name)
        if not ok:
            return JSONResponse(
                {"error": f"Cannot resume daemon '{name}'."},
                status_code=409,
            )
        return JSONResponse({"resumed": True, "daemon": name})

    async def delete_daemon(request: Request) -> JSONResponse:
        """DELETE /v1/daemons/{name} — Stop and remove daemon."""
        name = request.path_params["name"]
        ok = await server.stop_daemon(name)
        if not ok:
            return JSONResponse(
                {"error": f"Daemon '{name}' not found."},
                status_code=404,
            )
        return JSONResponse({"stopped": True, "daemon": name})

    # ── WebSocket ─────────────────────────────────────────────

    async def ws_events(websocket: WebSocket) -> None:
        """WS /v1/ws/events/{topic} — Bidirectional event streaming."""
        topic = websocket.path_params["topic"]

        # Auth check for WebSocket
        if server.config.auth_token:
            token = websocket.query_params.get("token", "")
            if token != server.config.auth_token:
                await websocket.close(code=4003, reason="Forbidden")
                return

        await websocket.accept()

        if not server.bus:
            await websocket.close(code=4503, reason="Server not running")
            return

        channel = server.bus.get_or_create(topic)

        # Background task to push events from channel to WS client
        async def push_events() -> None:
            try:
                while True:
                    event = await channel.receive()
                    await websocket.send_json({
                        "topic": event.topic,
                        "payload": event.payload,
                        "event_id": event.event_id,
                        "timestamp": event.timestamp,
                    })
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("WS push ended for topic '%s'", topic)

        push_task = asyncio.create_task(push_events())

        try:
            while True:
                # Client → Server: publish events
                data = await websocket.receive_json()
                payload = data.get("payload", data)
                await server.publish_event(topic, payload)
        except Exception:
            pass
        finally:
            push_task.cancel()
            try:
                await push_task
            except (asyncio.CancelledError, Exception):
                pass

    # ── Application Assembly ──────────────────────────────────

    routes = [
        Route("/v1/health", health, methods=["GET"]),
        Route("/v1/metrics", metrics, methods=["GET"]),
        Route("/v1/deploy", deploy, methods=["POST"]),
        Route("/v1/events/{topic:path}", publish_event, methods=["POST"]),
        Route("/v1/daemons", list_daemons, methods=["GET"]),
        Route("/v1/daemons/{name}", get_daemon, methods=["GET"]),
        Route("/v1/daemons/{name}/hibernate", hibernate_daemon, methods=["POST"]),
        Route("/v1/daemons/{name}/resume", resume_daemon, methods=["POST"]),
        Route("/v1/daemons/{name}", delete_daemon, methods=["DELETE"]),
        WebSocketRoute("/v1/ws/events/{topic:path}", ws_events),
    ]

    middleware = [Middleware(AuthMiddleware)]

    app = Starlette(
        routes=routes,
        middleware=middleware,
        on_startup=[server.start],
        on_shutdown=[server.stop],
    )

    return app
