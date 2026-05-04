"""
State snapshot + restore across the crash boundary (Fase 16.f).

Two persistence backends compose here:

  1. **Replay tokens** — every daemon snapshot emits a canonical-hashed
     Replay token (Fase 11.c surface) persisted via the enterprise
     Replay adapter. The token's inputs/outputs encode the snapshot
     payload so a daemon's history is reconstructable.
  2. **Cognitive States** — the BDI matrix + per-daemon PEM density
     matrix is serialized via the enterprise cognitive_states module
     (Q32.32 fixed-point encoding for bit-identical round-trips).

The supervisor invokes `snapshot_state` post-crash and `restore_state`
pre-restart. Best-effort: failures here do not block restart — a
daemon that loses its snapshot still runs (with degraded continuity).
The cooperative checkpoint API (16.f.2) is provided as `register_checkpoint`
which long-running daemons can call from inside their event loop to
publish snapshots at sensible points during normal execution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol


# ── Backend protocols (kept abstract so we don't hard-import the
#    enterprise modules at supervisor-package import time; that lets
#    the test suite spin up a supervisor with stub backends without
#    pulling in Postgres/Redis). ────────────────────────────────────

class _StateStore(Protocol):
    async def put(self, key: str, payload: bytes) -> None: ...
    async def get(self, key: str) -> bytes | None: ...
    async def delete(self, key: str) -> None: ...


@dataclass
class StatePersistence:
    """Snapshot/restore state for a daemon across crashes.

    `store` is the actual blob backend (a `_StateStore` impl wrapping
    the enterprise replay/cognitive_states adapters). `key_prefix` is
    appended to the daemon name to scope keys.

    The snapshot payload is opaque bytes from the supervisor's POV;
    the cooperative checkpoint API decides what goes inside (BDI
    matrix, replay log offset, AxonStore session, etc.).
    """

    store: _StateStore
    key_prefix: str = "supervisor:daemon:"
    # Optional callable invoked at snapshot time to gather live state
    # from a running daemon. Set via `register_checkpoint(daemon_name, fn)`.
    _checkpoint_fns: dict[str, Callable[[], Awaitable[dict[str, Any] | None]]] = None  # type: ignore

    def __post_init__(self) -> None:
        if self._checkpoint_fns is None:
            self._checkpoint_fns = {}

    def _key(self, daemon_name: str) -> str:
        return f"{self.key_prefix}{daemon_name}"

    def register_checkpoint(
        self,
        daemon_name: str,
        fn: Callable[[], Awaitable[dict[str, Any] | None]],
    ) -> None:
        """Cooperative checkpoint API (Fase 16.f.2).

        Long-running daemons call this once at startup to register a
        callable the supervisor invokes at snapshot time. The callable
        returns a JSON-serializable dict (or None to skip snapshot).
        """
        self._checkpoint_fns[daemon_name] = fn

    def unregister_checkpoint(self, daemon_name: str) -> None:
        self._checkpoint_fns.pop(daemon_name, None)

    async def snapshot(self, daemon_name: str) -> bytes | None:
        """Capture the daemon's current state to the store. Returns
        the serialized payload (for telemetry / size reporting) or
        None on no-op / failure.
        """
        fn = self._checkpoint_fns.get(daemon_name)
        if fn is None:
            return None
        try:
            payload = await fn()
        except Exception:
            return None
        if payload is None:
            return None
        try:
            blob = json.dumps(payload, default=str, sort_keys=True).encode("utf-8")
        except (TypeError, ValueError):
            return None
        try:
            await self.store.put(self._key(daemon_name), blob)
        except Exception:
            return None
        return blob

    async def restore(self, daemon_name: str) -> dict[str, Any] | None:
        """Read the daemon's last persisted state. Returns the parsed
        dict, or None on absent / failure.
        """
        try:
            blob = await self.store.get(self._key(daemon_name))
        except Exception:
            return None
        if blob is None:
            return None
        try:
            return json.loads(blob.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    async def clear(self, daemon_name: str) -> None:
        """Drop the persisted snapshot — call after a clean shutdown
        or a successful long-lived run if you don't want stale state
        to be restored on next start."""
        try:
            await self.store.delete(self._key(daemon_name))
        except Exception:
            pass


# ── In-memory stub for tests ──────────────────────────────────────


class InMemoryStateStore:
    """Trivial in-memory `_StateStore` impl for tests + local dev.

    Production deployments wire `StatePersistence` to the enterprise
    replay/cognitive_states adapters (Postgres-backed) instead.
    """

    def __init__(self) -> None:
        self._kv: dict[str, bytes] = {}

    async def put(self, key: str, payload: bytes) -> None:
        self._kv[key] = payload

    async def get(self, key: str) -> bytes | None:
        return self._kv.get(key)

    async def delete(self, key: str) -> None:
        self._kv.pop(key, None)
