"""
AXON Runtime — Daemon Supervisor (OTP-Style Restart Tree)
==========================================================
Implements the supervision layer for daemon processes.

Grounded in Erlang/OTP supervision theory (Armstrong, 2003):
  - "Let it crash" philosophy — daemons fail fast, supervisors restart
  - Bounded restart intensity — prevents restart storms
  - Optional `SupervisorHooks` extension surface (Fase 16.a) so external
    layers can plug in state persistence, telemetry, audit trails, and
    `on_stuck` policy dispatch without modifying this module

Supervision strategies:
  one_for_one:  restart only the crashed daemon
  one_for_all:  restart all daemons when one crashes
  rest_for_one: restart the crashed daemon and all started after it

The supervisor maintains a restart intensity window: if a daemon
crashes more than `max_restarts` times within `max_seconds`, the
supervisor stops restarting that daemon and (if hooks are registered)
notifies the hook layer via `on_intensity_exceeded`. The OSS code path
itself does not propagate failures upward — that responsibility is
delegated to the hook implementation. See `axon-enterprise/supervisor/`
for the production-grade hook implementation that ships failure
propagation, hierarchical escalation, audit logging, and distributed
leader election.

State preservation across restarts is OPTIONAL. The OSS supervisor does
NOT persist daemon state by itself: in-memory state is lost on crash,
and the daemon restarts fresh. If a `SupervisorHooks` instance is
registered with `snapshot_state` / `restore_state` implementations
(e.g., the enterprise Replay-token + Cognitive-States adapter), the
supervisor invokes those hooks across the crash boundary so the daemon
can recover its prior state.

Formal model:
  Sup = (Daemons, RestartPolicy, RestartCount, Hooks?)
  restart(d, Sup) → Sup' where Sup'.count = Sup.count + 1
  if Sup'.count > max_restarts within window → intensity-exceeded path
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Awaitable, Callable, Deque, Protocol, runtime_checkable


class SupervisionStrategy(Enum):
    """OTP supervision strategies."""
    ONE_FOR_ONE = auto()    # restart only the crashed daemon
    ONE_FOR_ALL = auto()    # restart all daemons when one crashes
    REST_FOR_ONE = auto()   # restart crashed + all started after it


# ── Hook protocol (Fase 16.a) ──────────────────────────────────────────
#
# All methods are `async` and return None / Optional. Default
# behavior of the supervisor is preserved when `hooks=None`. Each
# method is invoked exactly once per relevant lifecycle event from
# inside `_supervised_run`. Implementations MUST NOT raise — the
# supervisor catches and ignores hook exceptions to avoid turning a
# faulty hook into a supervisor crash.
#
# The enterprise hook implementation (`axon_enterprise/supervisor/`)
# fills these in with production behavior:
#   - StateBackend integration via Replay tokens + Cognitive States
#   - OTel spans + Prometheus counters + structlog
#   - on_stuck policy dispatch (hibernate / escalate / retry / forge)
#   - audit-trail integration (signed + Merkle-chained)
#   - multi-tenant isolation + compliance-aware restart gating
#   - hierarchical escalation + distributed leader election
#
# OSS adopters who don't need these can leave hooks=None and the
# supervisor behaves exactly as it did before Fase 16.


@runtime_checkable
class SupervisorHooks(Protocol):
    """Optional injection point for enterprise / observability layers.

    Default: no hooks registered → today's behavior preserved exactly.
    Every method is async and returns None / Optional.

    Hook methods are invoked by the supervisor at well-defined
    lifecycle moments. Exceptions raised by hooks are caught and
    ignored by the supervisor to prevent hook bugs from cascading.
    """

    async def on_daemon_start(self, name: str, attempt: int) -> None:
        """Fired before each `start_fn` invocation (initial start + every restart)."""

    async def on_daemon_crash(
        self, name: str, exc: BaseException, attempt: int,
    ) -> None:
        """Fired when `start_fn` raises (excluding CancelledError)."""

    async def on_daemon_restart(
        self, name: str, attempt: int, delay_s: float,
    ) -> None:
        """Fired after the backoff sleep, before the next `start_fn` call."""

    async def on_intensity_exceeded(
        self, name: str, restart_count: int,
    ) -> None:
        """Fired when restart-intensity gate trips and the supervisor gives up."""

    async def snapshot_state(self, name: str) -> Any | None:
        """Called pre-restart. Returning a non-None value will be passed
        to `restore_state` after the daemon comes back up. The OSS
        supervisor itself stores nothing — persistence is the hook's
        responsibility."""

    async def restore_state(self, name: str, snapshot: Any) -> None:
        """Called post-restart with whatever `snapshot_state` returned."""

    async def liveness_check(self, name: str) -> bool:
        """Optional health probe — return False to flag the daemon as
        stuck (the supervisor will cancel + restart it). The OSS
        supervisor does not invoke this proactively; enterprise
        wraps it in a periodic probe loop."""

    async def resolve_on_stuck(
        self, name: str, exc: BaseException,
    ) -> str:
        """Map a daemon crash to one of the on_stuck policies.
        Return value: 'restart' (default) | 'hibernate' | 'escalate'
        | 'retry' | 'forge' | 'noop'. The OSS supervisor only
        understands 'restart' and 'noop'; enterprise dispatches the
        full set."""


@dataclass
class DaemonSpec:
    """
    Specification for a supervised daemon process.

    Contains all information needed to start/restart a daemon:
    the callable, its arguments, and restart policy metadata.

    `on_stuck_policy` (Fase 16.a) is plumbed through to the hook
    layer's `resolve_on_stuck` method. The OSS default `'restart'`
    preserves pre-Fase-16 behavior; the enterprise hooks honor the
    full policy vocabulary declared in the .axon source.
    """
    name: str
    start_fn: Callable[..., Awaitable[Any]]
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    restart_count: int = 0
    last_restart: float = 0.0
    on_stuck_policy: str = "restart"


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
    applies the configured restart strategy. State preservation
    across crashes is opt-in via the `SupervisorHooks` protocol —
    the OSS supervisor itself does not persist state.

    Usage:
        supervisor = DaemonSupervisor(config=SupervisorConfig())
        supervisor.register("OrderDaemon", start_fn=run_order_daemon)
        await supervisor.start_all()
        # ... on crash, supervisor auto-restarts the daemon

    Enterprise usage with hooks:
        from axon_enterprise.supervisor import make_enterprise_supervisor
        supervisor = make_enterprise_supervisor(config=..., ...)
        # Now restarts persist state, emit telemetry, audit-log, etc.
    """

    def __init__(
        self,
        config: SupervisorConfig | None = None,
        *,
        hooks: SupervisorHooks | None = None,
    ) -> None:
        self._config = config or SupervisorConfig()
        self._daemons: dict[str, DaemonSpec] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        # Per-daemon ringbuffer of restart timestamps. Bounded by
        # `max_restarts + 1` so the eviction predicate in
        # `_exceeds_restart_intensity` only ever scans a small window
        # (Fase 16.b — replaces the previous unbounded list).
        self._restart_log: dict[str, Deque[float]] = {}
        self._running = False
        self._hooks = hooks
        # asyncio.Lock for serializing dict mutations across concurrent
        # restart paths (Fase 16.c — fixes the one_for_all / rest_for_one
        # race where two simultaneous crashes could clobber `self._tasks`
        # entries). Created lazily because asyncio.Lock construction
        # before there's a running loop is fine in modern Python but
        # we keep it explicit for clarity.
        self._lock = asyncio.Lock()
        # Fase 16.c — single-cascade flag. Prevents the mutual-await
        # deadlock when multiple daemons crash simultaneously under
        # ONE_FOR_ALL or REST_FOR_ONE: only the first cascade runs;
        # subsequent crashes that arrive while the cascade is in
        # progress short-circuit (they will be cancelled and re-spawned
        # by the in-flight cascade anyway).
        self._cascade_in_progress = False

    def register(
        self,
        name: str,
        start_fn: Callable[..., Awaitable[Any]],
        *args: Any,
        on_stuck_policy: str = "restart",
        **kwargs: Any,
    ) -> None:
        """Register a daemon specification for supervision."""
        self._daemons[name] = DaemonSpec(
            name=name,
            start_fn=start_fn,
            args=args,
            kwargs=kwargs,
            on_stuck_policy=on_stuck_policy,
        )

    async def start_all(self) -> None:
        """Start all registered daemons under supervision."""
        self._running = True
        async with self._lock:
            for name, spec in self._daemons.items():
                self._tasks[name] = asyncio.create_task(
                    self._supervised_run(spec),
                    name=f"daemon:{name}",
                )

    async def stop_all(self) -> None:
        """Gracefully stop all supervised daemons."""
        self._running = False
        # Materialize a snapshot tuple inside the lock so we have stable
        # task references after the lock is released; a `_restart_*`
        # path concurrent with shutdown could otherwise mutate the dict
        # while we iterate.
        async with self._lock:
            tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self._lock:
            self._tasks.clear()

    async def _supervised_run(self, spec: DaemonSpec) -> None:
        """
        Run a daemon with automatic restart on crash.

        Implements the restart intensity check: if the daemon has
        crashed more than max_restarts times within max_seconds,
        stop restarting and (if hooks are registered) notify via
        `on_intensity_exceeded`. The OSS supervisor's own response is
        to break out of the loop; failure propagation upward is the
        hook layer's job.
        """
        snapshot: Any | None = None
        while self._running:
            try:
                await self._fire_hook_safe(
                    "on_daemon_start", spec.name, spec.restart_count,
                )
                if snapshot is not None:
                    await self._fire_hook_safe(
                        "restore_state", spec.name, snapshot,
                    )
                    snapshot = None
                await spec.start_fn(*spec.args, **spec.kwargs)
                # Normal exit — daemon completed (unusual for daemons)
                break
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._running:
                    break

                await self._fire_hook_safe(
                    "on_daemon_crash", spec.name, exc, spec.restart_count,
                )

                # Snapshot state before restart so the next iteration
                # can pass it to restore_state. The OSS path's snapshot
                # is None unless a hook returns something.
                snapshot = await self._fire_hook_collect(
                    "snapshot_state", spec.name,
                )

                # Resolve on_stuck policy. OSS only honors 'restart'
                # (default) and 'noop' (terminal stop); the enterprise
                # hooks dispatch the full vocabulary.
                policy = await self._resolve_policy(spec, exc)
                if policy == "noop":
                    break

                # Record restart and check intensity
                now = time.monotonic()
                self._record_restart(spec.name, now)
                spec.restart_count += 1
                spec.last_restart = now

                if self._exceeds_restart_intensity(spec.name, now):
                    await self._fire_hook_safe(
                        "on_intensity_exceeded",
                        spec.name,
                        spec.restart_count,
                    )
                    break

                # Apply restart strategy. Mutations to self._tasks are
                # serialized under self._lock (Fase 16.c).
                if self._config.strategy == SupervisionStrategy.ONE_FOR_ALL:
                    await self._restart_all_except(spec.name)
                elif self._config.strategy == SupervisionStrategy.REST_FOR_ONE:
                    await self._restart_after(spec.name)

                # Brief backoff before restarting the crashed daemon.
                # Linear cap at 1s — enterprise replaces this with a
                # decorrelated-jitter exponential backoff via a hook
                # (Fase 16.h) but the OSS default keeps things simple.
                delay = 0.1 * min(spec.restart_count, 10)
                await self._fire_hook_safe(
                    "on_daemon_restart",
                    spec.name,
                    spec.restart_count,
                    delay,
                )
                await asyncio.sleep(delay)

    async def _resolve_policy(
        self, spec: DaemonSpec, exc: BaseException,
    ) -> str:
        """Resolve the on_stuck policy via the hook layer if available.

        OSS interpretation: only 'restart' (default behavior) and
        'noop' (terminate without restart) are honored. Other values
        (hibernate / escalate / retry / forge) require the enterprise
        hooks; in OSS they fall back to 'restart' to preserve liveness.
        """
        if self._hooks is None:
            return spec.on_stuck_policy if spec.on_stuck_policy in {
                "restart", "noop",
            } else "restart"
        try:
            policy = await self._hooks.resolve_on_stuck(spec.name, exc)
        except Exception:
            return "restart"
        if policy in {"restart", "noop"}:
            return policy
        # Unknown / enterprise-only policy in OSS code path → safe
        # fallback to restart. Enterprise hooks dispatch the full
        # vocabulary internally and never return values OSS doesn't
        # understand.
        return "restart"

    def _record_restart(self, name: str, now: float) -> None:
        """Append a restart timestamp; evict entries older than the
        configured intensity window so the log stays bounded
        (Fase 16.b).

        Per-daemon deque has maxlen = max_restarts + 1 so the predicate
        check in `_exceeds_restart_intensity` only ever scans
        O(max_restarts) entries.
        """
        log = self._restart_log.get(name)
        if log is None:
            log = deque(maxlen=self._config.max_restarts + 1)
            self._restart_log[name] = log
        log.append(now)
        # Drop entries older than the window
        cutoff = now - self._config.max_seconds
        while log and log[0] < cutoff:
            log.popleft()

    def _exceeds_restart_intensity(self, name: str, now: float) -> bool:
        """Check if restart intensity exceeds the configured limit."""
        log = self._restart_log.get(name)
        if log is None:
            return False
        cutoff = now - self._config.max_seconds
        recent = sum(1 for ts in log if ts >= cutoff)
        return recent > self._config.max_restarts

    async def _restart_all_except(self, except_name: str) -> None:
        """Restart all daemons except the one being restarted (ONE_FOR_ALL).

        Serialization (Fase 16.c):
          * Short-circuits during shutdown (`_running == False`).
          * Short-circuits if a cascade is already in progress; the
            in-flight cascade will pick up the concurrent-crash victims
            when it cancels-and-recreates everyone. This avoids the
            mutual-await deadlock where N concurrently crashing daemons
            each try to cancel the other N-1.
          * Dict mutations are serialized under `self._lock`.
        """
        if not self._running or self._cascade_in_progress:
            return
        self._cascade_in_progress = True
        try:
            async with self._lock:
                target_names = [
                    name for name, task in self._tasks.items()
                    if name != except_name and not task.done()
                ]
                tasks_to_cancel = [self._tasks[name] for name in target_names]

            for task in tasks_to_cancel:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

            async with self._lock:
                if not self._running:
                    return
                for name in target_names:
                    spec = self._daemons[name]
                    self._tasks[name] = asyncio.create_task(
                        self._supervised_run(spec),
                        name=f"daemon:{name}",
                    )
        finally:
            self._cascade_in_progress = False

    async def _restart_after(self, after_name: str) -> None:
        """Restart daemons registered after the crashed one (REST_FOR_ONE).

        Same serialization discipline as `_restart_all_except` (Fase 16.c).
        """
        if not self._running or self._cascade_in_progress:
            return
        self._cascade_in_progress = True
        try:
            async with self._lock:
                names = list(self._daemons.keys())
                try:
                    idx = names.index(after_name)
                except ValueError:
                    return
                target_names = [
                    name for name in names[idx + 1:]
                    if (task := self._tasks.get(name)) is not None and not task.done()
                ]
                tasks_to_cancel = [self._tasks[name] for name in target_names]

            for task in tasks_to_cancel:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

            async with self._lock:
                if not self._running:
                    return
                for name in target_names:
                    spec = self._daemons[name]
                    self._tasks[name] = asyncio.create_task(
                        self._supervised_run(spec),
                        name=f"daemon:{name}",
                    )
        finally:
            self._cascade_in_progress = False

    # ── Hook invocation helpers ──────────────────────────────────────
    #
    # Both helpers swallow hook exceptions so a buggy hook can't crash
    # the supervisor itself. `_fire_hook_safe` returns None always;
    # `_fire_hook_collect` returns the hook's return value (or None on
    # missing hook / exception). Using getattr with a sentinel lets us
    # treat partial Protocol implementations gracefully.

    _MISSING = object()

    async def _fire_hook_safe(self, method: str, *args: Any) -> None:
        if self._hooks is None:
            return
        fn = getattr(self._hooks, method, self._MISSING)
        if fn is self._MISSING:
            return
        try:
            await fn(*args)
        except Exception:
            pass

    async def _fire_hook_collect(self, method: str, *args: Any) -> Any:
        if self._hooks is None:
            return None
        fn = getattr(self._hooks, method, self._MISSING)
        if fn is self._MISSING:
            return None
        try:
            return await fn(*args)
        except Exception:
            return None

    @property
    def daemon_count(self) -> int:
        return len(self._daemons)

    @property
    def active_count(self) -> int:
        return sum(1 for t in self._tasks.values() if not t.done())

    def get_restart_count(self, name: str) -> int:
        spec = self._daemons.get(name)
        return spec.restart_count if spec else 0
