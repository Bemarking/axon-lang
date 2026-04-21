"""SecretValue — opaque byte container that redacts itself everywhere.

Anywhere a plaintext secret lives in Python we wrap it in ``SecretValue``.
The wrapper:

- prints ``<SecretValue len=42 fingerprint='abcd1234'>`` in repr / str
- raises in ``__format__`` when a non-empty format spec is used, so
  f-strings like ``f"key = {secret}"`` never leak by accident
- excludes the raw bytes from ``copy()`` / ``pickle`` output —
  serialising a SecretValue produces a redacted placeholder
- exposes one explicit unwrap path (``reveal()``), which callers use
  only when handing the bytes off to HTTP / Postgres / AWS SDK code
- ``fingerprint`` = first 8 hex chars of SHA-256 of the value,
  safe to include in audit events for correlation without revealing
  the secret itself

Callers treat ``SecretValue`` like a ``SecretStr`` from pydantic but
with audit-ready hooks and stricter ergonomics.
"""

from __future__ import annotations

import hashlib
from typing import Any


class SecretValue:
    """Opaque wrapper around a secret string.

    Construct from bytes or str; the internal representation is
    always ``bytes`` (UTF-8) so binary secrets (e.g. keyfiles) are
    possible without extra ceremony.
    """

    __slots__ = ("_value", "_length", "_fingerprint")

    def __init__(self, value: str | bytes) -> None:
        if isinstance(value, str):
            raw = value.encode("utf-8")
        elif isinstance(value, (bytes, bytearray)):
            raw = bytes(value)
        else:
            raise TypeError(
                f"SecretValue requires str or bytes, got {type(value).__name__}"
            )
        self._value: bytes = raw
        self._length: int = len(raw)
        self._fingerprint: str = hashlib.sha256(raw).hexdigest()[:8]

    # ── Redaction ──────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"<SecretValue len={self._length} fingerprint='{self._fingerprint}'>"
        )

    __str__ = __repr__

    def __format__(self, format_spec: str) -> str:
        if format_spec:
            raise ValueError(
                "SecretValue does not support format specs — "
                "call `.reveal()` explicitly to unwrap"
            )
        return repr(self)

    def __reduce__(self) -> tuple[Any, ...]:
        # pickle / copy path — substitute a placeholder.
        return (SecretValue, ("[REDACTED]",))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SecretValue):
            return NotImplemented
        # Constant-time comparison to deny timing leakage when secrets
        # are compared directly (rare — usually the backend handles it).
        import hmac

        return hmac.compare_digest(self._value, other._value)

    def __hash__(self) -> int:
        # Hashed using the fingerprint, not the raw bytes — so a
        # SecretValue can go into a set without risk of collision
        # leaking the value via timing.
        return hash(self._fingerprint)

    # ── Accessors ──────────────────────────────────────────────────────

    @property
    def fingerprint(self) -> str:
        """8-char SHA-256 prefix — safe to log in audit events."""
        return self._fingerprint

    @property
    def length(self) -> int:
        return self._length

    def reveal(self) -> str:
        """Return the plaintext as a UTF-8 string. Use at boundary points only."""
        return self._value.decode("utf-8")

    def reveal_bytes(self) -> bytes:
        """Return the plaintext bytes (preferred over ``reveal`` for binary)."""
        return self._value
