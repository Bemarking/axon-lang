"""
Liveness probes for daemons (Fase 16.i).

Three probe styles, registered per-daemon:

  * **Heartbeat** — daemon must call `heartbeat()` at least every
    `interval_s × tolerance` or it's flagged stuck.
  * **Watchdog** — declarative max wall-clock per single iteration;
    a hung iteration is detected by a timer the daemon refreshes.
  * **Custom predicate** — user-provided async callable returning
    True if alive.

The supervisor invokes `liveness_check(name)` periodically (the
enterprise hooks impl wraps this in a background probe loop). False
return → cancel + restart.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Awaitable, Callable


class ProbeKind(Enum):
    HEARTBEAT = auto()
    WATCHDOG = auto()
    CUSTOM = auto()


@dataclass
class ProbeConfig:
    kind: ProbeKind
    interval_s: float = 5.0
    tolerance: float = 2.0
    custom_fn: Callable[[], Awaitable[bool]] | None = None


@dataclass
class _ProbeState:
    config: ProbeConfig
    last_heartbeat: float = 0.0
    last_watchdog_kick: float = 0.0


class HealthProbeRegistry:
    """Per-supervisor registry of liveness probes.

    Daemon code calls `heartbeat(name)` / `kick_watchdog(name)` from
    inside its loop to indicate liveness. The supervisor's hook impl
    invokes `is_alive(name)` periodically.
    """

    def __init__(self) -> None:
        self._probes: dict[str, _ProbeState] = {}

    def register(self, daemon_name: str, config: ProbeConfig) -> None:
        now = time.monotonic()
        self._probes[daemon_name] = _ProbeState(
            config=config,
            last_heartbeat=now,
            last_watchdog_kick=now,
        )

    def unregister(self, daemon_name: str) -> None:
        self._probes.pop(daemon_name, None)

    def heartbeat(self, daemon_name: str) -> None:
        """Daemon-side: called from inside the daemon's loop to
        signal liveness. Cheap, non-async."""
        state = self._probes.get(daemon_name)
        if state is None:
            return
        state.last_heartbeat = time.monotonic()

    def kick_watchdog(self, daemon_name: str) -> None:
        """Daemon-side: called at the start of each iteration to
        reset the watchdog timer."""
        state = self._probes.get(daemon_name)
        if state is None:
            return
        state.last_watchdog_kick = time.monotonic()

    async def is_alive(self, daemon_name: str) -> bool:
        """Supervisor-side: periodic probe. Returns False if the
        daemon should be considered stuck.

        For HEARTBEAT and WATCHDOG, the predicate is purely
        time-based against the per-state timestamps. For CUSTOM, the
        registered callable is awaited.

        Defaults to True (alive) for unregistered daemons so the
        absence of a probe is not interpreted as a stuck state.
        """
        state = self._probes.get(daemon_name)
        if state is None:
            return True
        cfg = state.config
        now = time.monotonic()
        if cfg.kind == ProbeKind.HEARTBEAT:
            deadline = state.last_heartbeat + cfg.interval_s * cfg.tolerance
            return now <= deadline
        if cfg.kind == ProbeKind.WATCHDOG:
            deadline = state.last_watchdog_kick + cfg.interval_s
            return now <= deadline
        if cfg.kind == ProbeKind.CUSTOM and cfg.custom_fn is not None:
            try:
                return bool(await cfg.custom_fn())
            except Exception:
                return False
        return True
