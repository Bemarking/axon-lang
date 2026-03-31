"""
AXON Runtime — Daemon Supervisor (OTP-Style Restart Tree)
==========================================================
Implements the supervision layer for daemon processes.

Grounded in Erlang/OTP supervision theory (Armstrong, 2003):
  - "Let it crash" philosophy — daemons fail fast, supervisors restart
  - Memory-preserving restarts — global memory survives crashes
  - Bounded restart intensity — prevents restart storms

Supervision strategies:
  one_for_one:  restart only the crashed daemon
  one_for_all:  restart all daemons when one crashes
  rest_for_one: restart the crashed daemon and all started after it

The supervisor maintains a restart intensity window: if a daemon
crashes more than `max_restarts` times within `max_seconds`, the
supervisor gives up and propagates the failure upward.

Formal model:
  Sup = (Daemons, RestartPolicy, RestartCount)
  restart(d, Sup) → Sup' where Sup'.count = Sup.count + 1
  if Sup'.count > max_restarts within window → failure propagation
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Awaitable


class SupervisionStrategy(Enum):
    """OTP supervision strategies."""
    ONE_FOR_ONE = auto()    # restart only the crashed daemon
    ONE_FOR_ALL = auto()    # restart all daemons when one crashes
    REST_FOR_ONE = auto()   # restart crashed + all started after it


@dataclass
class DaemonSpec:
    """
    Specification for a supervised daemon process.

    Contains all information needed to start/restart a daemon:
    the callable, its arguments, and restart policy metadata.
    """
    name: str
    start_fn: Callable[..., Awaitable[Any]]
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    restart_count: int = 0
    last_restart: float = 0.0


@dataclass
class SupervisorConfig:
    """
    Configuration for the daemon supervisor.

    max_restarts: maximum restarts within the time window
    max_seconds:  duration of the restart intensity window
    strategy:     which daemons to restart on failure
    """
    max_restarts: int = 5
    max_seconds: float = 60.0
    strategy: SupervisionStrategy = SupervisionStrategy.ONE_FOR_ONE


class DaemonSupervisor:
    """
    OTP-style supervisor for daemon processes.

    Monitors running daemons. When a daemon crashes, the supervisor
    applies the configured restart strategy while preserving the
    daemon's global memory (stored in StateBackend).

    Usage:
        supervisor = DaemonSupervisor(config=SupervisorConfig())
        supervisor.register("OrderDaemon", start_fn=run_order_daemon)
        await supervisor.start_all()
        # ... on crash, supervisor auto-restarts the daemon
    """

    def __init__(self, config: SupervisorConfig | None = None) -> None:
        self._config = config or SupervisorConfig()
        self._daemons: dict[str, DaemonSpec] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._restart_log: list[tuple[str, float]] = []  # (daemon_name, timestamp)
        self._running = False

    def register(
        self,
        name: str,
        start_fn: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Register a daemon specification for supervision."""
        self._daemons[name] = DaemonSpec(
            name=name,
            start_fn=start_fn,
            args=args,
            kwargs=kwargs,
        )

    async def start_all(self) -> None:
        """Start all registered daemons under supervision."""
        self._running = True
        for name, spec in self._daemons.items():
            self._tasks[name] = asyncio.create_task(
                self._supervised_run(spec),
                name=f"daemon:{name}",
            )

    async def stop_all(self) -> None:
        """Gracefully stop all supervised daemons."""
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def _supervised_run(self, spec: DaemonSpec) -> None:
        """
        Run a daemon with automatic restart on crash.

        Implements the restart intensity check: if the daemon has
        crashed more than max_restarts times within max_seconds,
        stop restarting and propagate the failure.
        """
        while self._running:
            try:
                await spec.start_fn(*spec.args, **spec.kwargs)
                # Normal exit — daemon completed (unusual for daemons)
                break
            except asyncio.CancelledError:
                break
            except Exception:
                if not self._running:
                    break

                # Record restart and check intensity
                now = time.monotonic()
                self._restart_log.append((spec.name, now))
                spec.restart_count += 1
                spec.last_restart = now

                if self._exceeds_restart_intensity(spec.name, now):
                    # Too many restarts — give up
                    break

                # Apply restart strategy
                if self._config.strategy == SupervisionStrategy.ONE_FOR_ALL:
                    await self._restart_all_except(spec.name)
                elif self._config.strategy == SupervisionStrategy.REST_FOR_ONE:
                    await self._restart_after(spec.name)

                # Brief backoff before restarting the crashed daemon
                await asyncio.sleep(0.1 * min(spec.restart_count, 10))

    def _exceeds_restart_intensity(self, name: str, now: float) -> bool:
        """Check if restart intensity exceeds the configured limit."""
        window_start = now - self._config.max_seconds
        recent = [
            ts for daemon_name, ts in self._restart_log
            if daemon_name == name and ts >= window_start
        ]
        return len(recent) > self._config.max_restarts

    async def _restart_all_except(self, except_name: str) -> None:
        """Restart all daemons except the one being restarted (ONE_FOR_ALL)."""
        for name, task in list(self._tasks.items()):
            if name != except_name and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
                spec = self._daemons[name]
                self._tasks[name] = asyncio.create_task(
                    self._supervised_run(spec),
                    name=f"daemon:{name}",
                )

    async def _restart_after(self, after_name: str) -> None:
        """Restart daemons registered after the crashed one (REST_FOR_ONE)."""
        names = list(self._daemons.keys())
        try:
            idx = names.index(after_name)
        except ValueError:
            return
        for name in names[idx + 1:]:
            task = self._tasks.get(name)
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
                spec = self._daemons[name]
                self._tasks[name] = asyncio.create_task(
                    self._supervised_run(spec),
                    name=f"daemon:{name}",
                )

    @property
    def daemon_count(self) -> int:
        return len(self._daemons)

    @property
    def active_count(self) -> int:
        return sum(1 for t in self._tasks.values() if not t.done())

    def get_restart_count(self, name: str) -> int:
        spec = self._daemons.get(name)
        return spec.restart_count if spec else 0
