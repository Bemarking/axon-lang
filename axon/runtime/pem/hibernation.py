"""
HibernationStore — server-side state persistence for the
``hibernate`` primitive (Fase 19.a).

Architectural decision: the wire token (``ContinuityTokenSigner``)
carries only the ``session_id`` + ``expires_at`` + HMAC. The full
execution snapshot (variables, step results, flow position) is
persisted server-side keyed by ``session_id``. Resume is a
two-step handshake:

  1. Adopter presents the signed token. ``Executor.resume_from_token``
     verifies the HMAC + expiry via the shared
     :class:`ContinuityTokenSigner`.
  2. The verified ``session_id`` is used to look up the snapshot in
     a :class:`HibernationStore`. The snapshot contains everything
     needed to rebuild a ``ContextManager`` and continue execution
     past the hibernate step.

Industry pattern: this is JWT-as-reference (the token names a
session, the session lives in a server-side store) rather than
JWT-as-state (the token carries the state inline). Benefits:

  * Tokens stay small regardless of execution state size.
  * Wire format is unchanged from Fase 11.d (Rust mirror untouched).
  * Adopters can swap :class:`InMemoryHibernationStore` for a
    durable backend (Postgres / Redis) without touching the
    dispatcher, the signer, or the wire format.

Single-instance only: distributed resume across multiple Executor
processes requires a shared store — see plan §Out of Scope.
"""

from __future__ import annotations

import copy
import re
import threading
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol


# ═══════════════════════════════════════════════════════════════════
#  TIMEOUT PARSING
# ═══════════════════════════════════════════════════════════════════


_DEFAULT_HIBERNATION_TTL = timedelta(hours=1)
_TIMEOUT_RE = re.compile(r"^\s*(\d+)\s*(ms|s|m|h|d)?\s*$", re.IGNORECASE)
_TIMEOUT_UNITS = {
    "ms": ("milliseconds", 1),
    "s": ("seconds", 1),
    "m": ("minutes", 1),
    "h": ("hours", 1),
    "d": ("days", 1),
}


def parse_timeout(spec: str) -> timedelta:
    """Parse an AXON ``timeout`` spec into a ``timedelta``.

    Accepts ``"30s"``, ``"5m"``, ``"1h"``, ``"7d"``, ``"500ms"``.
    Returns ``_DEFAULT_HIBERNATION_TTL`` (1 hour) on empty / unparseable
    input — silently degrading is correct here because hibernate is
    expected to be resumable; refusing to checkpoint because of a
    malformed timeout would be a worse failure mode than checkpointing
    with the default TTL.
    """
    if not spec:
        return _DEFAULT_HIBERNATION_TTL
    m = _TIMEOUT_RE.match(spec)
    if not m:
        return _DEFAULT_HIBERNATION_TTL
    qty = int(m.group(1))
    unit = (m.group(2) or "s").lower()
    kw, _ = _TIMEOUT_UNITS[unit]
    return timedelta(**{kw: qty})


# ═══════════════════════════════════════════════════════════════════
#  HIBERNATION SNAPSHOT
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class HibernationSnapshot:
    """Server-side payload referenced by a signed ``ContinuityToken``.

    Captures everything the Executor needs to reconstruct a
    ``ContextManager`` and continue execution past the ``hibernate``
    step that produced this snapshot.

    Fields:
        session_id:        Stable identifier — also the lookup key in
                           the :class:`HibernationStore`. Equal to the
                           ``session_id`` carried by the signed token.
        flow_name:         Name of the flow that was hibernating.
        event_name:        The wakeup event the flow is waiting for.
        timeout:           Original timeout spec (e.g. ``"30s"``).
        continuation_id:   Adopter-supplied checkpoint label (may be
                           empty if the source flow did not provide one).
        checkpoint_at:     Wall-clock seconds since epoch when the
                           checkpoint was recorded.
        variables:         Deep-copied snapshot of
                           ``ContextManager._variables``.
        step_results:      Deep-copied snapshot of
                           ``ContextManager._step_results``.
        completed_steps:   Step names recorded *before* hibernate, in
                           insertion order. Used to know how far the
                           original unit progressed.
    """

    session_id: str
    flow_name: str
    event_name: str = ""
    timeout: str = ""
    continuation_id: str = ""
    checkpoint_at: float = 0.0
    variables: dict[str, Any] = field(default_factory=dict)
    step_results: dict[str, Any] = field(default_factory=dict)
    completed_steps: tuple[str, ...] = ()

    def deepcopy_variables(self) -> dict[str, Any]:
        """Return an independent copy of variables — for adopters that
        want to mutate the resumed state without aliasing the stored
        snapshot."""
        return copy.deepcopy(self.variables)

    def deepcopy_step_results(self) -> dict[str, Any]:
        """Return an independent copy of step results — same rationale
        as :meth:`deepcopy_variables`."""
        return copy.deepcopy(self.step_results)


# ═══════════════════════════════════════════════════════════════════
#  STORE PROTOCOL + IN-MEMORY BACKEND
# ═══════════════════════════════════════════════════════════════════


class HibernationStore(Protocol):
    """Persistence contract for hibernation snapshots.

    The default :class:`InMemoryHibernationStore` is appropriate for
    single-process deployments and tests. Adopters running multiple
    Executor processes (or wanting durability across restarts) can
    implement this Protocol over Postgres, Redis, or any other
    backing store.
    """

    def save(self, session_id: str, snapshot: HibernationSnapshot) -> None:
        """Persist a snapshot. Overwrites any prior snapshot for the
        same ``session_id`` — adopters relying on append-only history
        should layer that on top."""
        ...

    def load(self, session_id: str) -> HibernationSnapshot | None:
        """Return the snapshot for ``session_id`` or ``None`` if none
        was stored / it has been evicted."""
        ...

    def delete(self, session_id: str) -> bool:
        """Remove the snapshot. Returns ``True`` if a snapshot was
        deleted, ``False`` if no snapshot existed."""
        ...


class InMemoryHibernationStore:
    """Thread-safe in-memory implementation of :class:`HibernationStore`.

    Snapshots are kept in a ``dict`` guarded by a ``threading.Lock``.
    Suitable for tests and single-process deployments. Lost on
    Executor process exit — adopters needing durability should
    plug in a Postgres-backed implementation.
    """

    __slots__ = ("_snapshots", "_lock")

    def __init__(self) -> None:
        self._snapshots: dict[str, HibernationSnapshot] = {}
        self._lock = threading.Lock()

    def save(self, session_id: str, snapshot: HibernationSnapshot) -> None:
        if not session_id:
            raise ValueError("session_id must not be empty")
        with self._lock:
            self._snapshots[session_id] = snapshot

    def load(self, session_id: str) -> HibernationSnapshot | None:
        if not session_id:
            return None
        with self._lock:
            return self._snapshots.get(session_id)

    def delete(self, session_id: str) -> bool:
        if not session_id:
            return False
        with self._lock:
            return self._snapshots.pop(session_id, None) is not None

    def __len__(self) -> int:
        with self._lock:
            return len(self._snapshots)


__all__ = [
    "HibernationSnapshot",
    "HibernationStore",
    "InMemoryHibernationStore",
    "parse_timeout",
]
