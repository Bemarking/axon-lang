"""In-process SecretsBackend for development + integration tests.

Holds a dict of ``{path: [versions]}``. No external calls. Rejected
by the production settings validator — operators must configure
``backend=aws_sm`` for production deployments.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from axon_enterprise.secrets.backend import SecretStoreEntry, SecretsBackend
from axon_enterprise.secrets.errors import (
    SecretNotFound,
    SecretValueTooLarge,
)
from axon_enterprise.secrets.value import SecretValue

# AWS SM limit — we enforce the same ceiling locally so tests catch
# "value too large" issues before hitting prod.
_MAX_VALUE_BYTES: int = 65_536


@dataclass
class _VersionedEntry:
    value: SecretValue
    version_id: str
    size_bytes: int


@dataclass
class InMemoryBackend(SecretsBackend):
    """Dict-backed implementation. Thread-safe, single-process."""

    _store: dict[str, list[_VersionedEntry]] = field(default_factory=dict)
    _deleted: dict[str, bool] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    # ── SecretsBackend protocol ───────────────────────────────────────

    async def put(
        self, path: str, value: SecretValue, *, description: str | None = None
    ) -> SecretStoreEntry:
        self._check_size(value)
        with self._lock:
            versions = self._store.setdefault(path, [])
            versions.append(
                _VersionedEntry(
                    value=value,
                    version_id=str(uuid.uuid4()),
                    size_bytes=value.length,
                )
            )
            self._deleted.pop(path, None)
            current = versions[-1]
        return SecretStoreEntry(
            path=path,
            version_id=current.version_id,
            arn=f"mem://{path}",
            size_bytes=current.size_bytes,
        )

    async def get(self, path: str) -> tuple[SecretValue, SecretStoreEntry]:
        with self._lock:
            versions = self._store.get(path)
            if not versions or self._deleted.get(path):
                raise SecretNotFound(path)
            current = versions[-1]
        return current.value, SecretStoreEntry(
            path=path,
            version_id=current.version_id,
            arn=f"mem://{path}",
            size_bytes=current.size_bytes,
        )

    async def delete(self, path: str, *, recovery_window_days: int) -> None:
        with self._lock:
            if path not in self._store:
                raise SecretNotFound(path)
            self._deleted[path] = True

    async def rotate(
        self, path: str, new_value: SecretValue
    ) -> SecretStoreEntry:
        with self._lock:
            if path not in self._store:
                raise SecretNotFound(path)
        return await self.put(path, new_value)

    async def exists(self, path: str) -> bool:
        with self._lock:
            return path in self._store and not self._deleted.get(path)

    # ── Helpers ───────────────────────────────────────────────────────

    def _check_size(self, value: SecretValue) -> None:
        if value.length > _MAX_VALUE_BYTES:
            raise SecretValueTooLarge(
                f"value of {value.length} bytes exceeds the {_MAX_VALUE_BYTES}-byte limit"
            )

    # ── Test helpers ──────────────────────────────────────────────────

    def _forget_all(self) -> None:
        """Drop every stored secret. Only used by tests to reset state."""
        with self._lock:
            self._store.clear()
            self._deleted.clear()
