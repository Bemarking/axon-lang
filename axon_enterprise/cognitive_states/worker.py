"""CognitiveStateEvictionWorker — periodic TTL sweep.

Mirrors the ComplianceWorker pattern from §10.l: long-running
asyncio loop that polls every ``poll_interval_seconds`` and calls
:meth:`CognitiveStateService.evict_expired`. Safe to run N
replicas — the DELETE is idempotent and Postgres serialises the
row-level locks per batch.
"""

from __future__ import annotations

import asyncio
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import structlog

from axon_enterprise.cognitive_states.service import CognitiveStateService
from axon_enterprise.db.session import admin_session

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.cognitive_states.worker"
)


@dataclass
class CognitiveStateEvictionWorker:
    """Long-running sweeper. Operators run via
    ``axon-enterprise pem run-evictor`` or as a Kubernetes
    Deployment alongside the compliance worker."""

    poll_interval_seconds: float = 60.0
    service: CognitiveStateService = None  # type: ignore[assignment]
    worker_id: str = ""

    @classmethod
    def default(cls) -> "CognitiveStateEvictionWorker":
        return cls(
            poll_interval_seconds=60.0,
            service=CognitiveStateService.default(),
            worker_id=platform.node() or "pem-evictor",
        )

    async def run_forever(
        self, *, stop: Optional[asyncio.Event] = None
    ) -> None:
        _logger.info(
            "cognitive_state_evictor_started",
            worker_id=self.worker_id,
            poll_interval_s=self.poll_interval_seconds,
        )
        while stop is None or not stop.is_set():
            try:
                removed = await self.run_once()
                if removed > 0:
                    _logger.info(
                        "cognitive_state_evictor_tick",
                        removed=removed,
                    )
            except Exception as exc:  # noqa: BLE001
                # Never crash the loop on a single failure — log +
                # let the next tick retry.
                _logger.exception(
                    "cognitive_state_evictor_failure", error=str(exc)
                )
            if stop is None:
                await asyncio.sleep(self.poll_interval_seconds)
            else:
                try:
                    await asyncio.wait_for(
                        stop.wait(),
                        timeout=self.poll_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass

    async def run_once(self) -> int:
        """Single sweep. Returns the count of rows deleted —
        useful for unit tests + operator dashboards."""
        async with admin_session() as db:
            return await self.service.evict_expired(
                db, before=datetime.now(timezone.utc)
            )


__all__ = ["CognitiveStateEvictionWorker"]
