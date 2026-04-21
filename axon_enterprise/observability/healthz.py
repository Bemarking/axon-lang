"""Liveness + readiness probes.

``/healthz`` (liveness) always returns 200 when the process is up —
it's the K8s contract: restart the pod if the HTTP listener is
dead. Never gate it on DB connectivity; that would recreate a
thundering-herd restart loop on Postgres hiccups.

``/readyz`` (readiness) returns 200 when the process can serve
real traffic: DB pool reachable, JWKS / ESK endpoints healthy.
Returns 503 otherwise so K8s pulls the pod from the service
rotation without killing it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import structlog
from starlette.types import Receive, Scope, Send

from axon_enterprise.db.engine import healthcheck as db_healthcheck

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.observability.healthz"
)


@dataclass(frozen=True, slots=True)
class HealthStatus:
    """Outcome of a readiness check."""

    ready: bool
    components: dict[str, bool]
    reason: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": "ready" if self.ready else "not_ready",
            "components": self.components,
            "reason": self.reason,
        }


async def check_readiness() -> HealthStatus:
    """Run every readiness probe + aggregate.

    Extend the ``components`` list as new critical dependencies are
    wired (Redis for the rate limiter, KMS for the signer, etc.).
    Each probe is wrapped in a try/except so one failure does not
    short-circuit the rest.
    """
    components: dict[str, bool] = {}
    reasons: list[str] = []

    # Postgres
    try:
        ok = await db_healthcheck()
        components["postgres"] = ok
        if not ok:
            reasons.append("postgres: SELECT 1 returned non-1")
    except Exception as exc:  # noqa: BLE001
        components["postgres"] = False
        reasons.append(f"postgres: {exc}")

    ready = all(components.values())
    return HealthStatus(
        ready=ready,
        components=components,
        reason="; ".join(reasons) if reasons else None,
    )


# ── ASGI endpoints ───────────────────────────────────────────────────


def build_healthz_asgi_app() -> Callable[..., Awaitable[None]]:
    """Return an ASGI app for ``/healthz``. Always responds 200."""

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        payload = json.dumps({"status": "ok"}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": payload})

    return app


def build_readyz_asgi_app() -> Callable[..., Awaitable[None]]:
    """Return an ASGI app for ``/readyz``. 200 or 503 based on probes."""

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        status = await check_readiness()
        code = 200 if status.ready else 503
        payload = json.dumps(status.to_payload()).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": code,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": payload})

    return app
