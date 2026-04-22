"""
PersistenceBackend — async abstract base + in-memory impl (Python).
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from axon.runtime.pem.state import CognitiveState, StateDecodeError


class PersistenceError(Exception):
    """Base for backend failures."""


class NotFoundError(PersistenceError):
    def __init__(self, session_id: str) -> None:
        super().__init__(f"cognitive state not found: {session_id!r}")
        self.session_id = session_id


class ExpiredError(PersistenceError):
    def __init__(self, session_id: str, expired_at: datetime) -> None:
        super().__init__(
            f"cognitive state for {session_id!r} expired at {expired_at.isoformat()}"
        )
        self.session_id = session_id
        self.expired_at = expired_at


class BackendError(PersistenceError):
    """Opaque wrapper for backend-specific failures (decode, DB, …)."""


class PersistenceBackend(ABC):
    """Abstract contract for cognitive-state storage.

    The Rust-side ``PersistenceBackend`` is async via ``async_trait``;
    Python's abstract methods are also async so adopters can back
    implementations with Postgres / Redis / S3 naturally."""

    @abstractmethod
    async def persist(
        self,
        session_id: str,
        state: CognitiveState,
        ttl: timedelta,
    ) -> None:
        ...

    @abstractmethod
    async def restore(self, session_id: str) -> CognitiveState:
        ...

    @abstractmethod
    async def evict(self, session_id: str) -> None:
        ...

    @abstractmethod
    async def evict_expired(self, before: datetime) -> int:
        ...


@dataclass
class _StoredEntry:
    state_bytes: bytes
    expires_at: datetime


class InMemoryBackend(PersistenceBackend):
    """Dev + test backend. Thread-safe; rejects stale reads so
    semantics match the Postgres production impl."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._inner: dict[str, _StoredEntry] = {}

    async def persist(
        self,
        session_id: str,
        state: CognitiveState,
        ttl: timedelta,
    ) -> None:
        expires_at = datetime.now(timezone.utc) + ttl
        bytes_ = state.encode()
        with self._lock:
            self._inner[session_id] = _StoredEntry(
                state_bytes=bytes_, expires_at=expires_at
            )

    async def restore(self, session_id: str) -> CognitiveState:
        with self._lock:
            entry = self._inner.get(session_id)
        if entry is None:
            raise NotFoundError(session_id)
        if entry.expires_at <= datetime.now(timezone.utc):
            raise ExpiredError(session_id, entry.expires_at)
        try:
            return CognitiveState.decode(entry.state_bytes)
        except StateDecodeError as exc:
            raise BackendError(str(exc)) from exc

    async def evict(self, session_id: str) -> None:
        with self._lock:
            self._inner.pop(session_id, None)

    async def evict_expired(self, before: datetime) -> int:
        with self._lock:
            stale = [
                sid
                for sid, entry in self._inner.items()
                if entry.expires_at <= before
            ]
            for sid in stale:
                del self._inner[sid]
            return len(stale)

    def __len__(self) -> int:
        with self._lock:
            return len(self._inner)


__all__ = [
    "BackendError",
    "ExpiredError",
    "InMemoryBackend",
    "NotFoundError",
    "PersistenceBackend",
    "PersistenceError",
]
