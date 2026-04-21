"""SecretsBackend Protocol — the interface both AWS SM and in-memory implement.

Each method takes/returns ``SecretValue`` at the boundary to keep
plaintext out of structured logs. Backends do not touch Postgres;
persistence of metadata is the service layer's responsibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from axon_enterprise.secrets.value import SecretValue


@dataclass(frozen=True, slots=True)
class SecretStoreEntry:
    """What a backend returns when asked about a secret."""

    path: str
    version_id: str
    arn: str | None
    size_bytes: int


@runtime_checkable
class SecretsBackend(Protocol):
    """Persistence + retrieval of secret values keyed by path."""

    async def put(self, path: str, value: SecretValue, *, description: str | None = None) -> SecretStoreEntry:
        """Create on first write, new version on subsequent writes."""
        ...

    async def get(self, path: str) -> tuple[SecretValue, SecretStoreEntry]:
        """Return the current version's value + metadata."""
        ...

    async def delete(
        self, path: str, *, recovery_window_days: int
    ) -> None:
        """Schedule deletion — allows recovery within the window."""
        ...

    async def rotate(
        self, path: str, new_value: SecretValue
    ) -> SecretStoreEntry:
        """Put a new version, demote the previous to ``AWSPREVIOUS``."""
        ...

    async def exists(self, path: str) -> bool:
        """True when a backend entry exists at ``path``."""
        ...
