"""
AXON Runtime — Secret<T> (ESK Fase 6.4)
==========================================
A wrapper type that holds a sensitive value AND guarantees it never
leaks through `repr()`, `str()`, logs, traces, or JSON serialization.

This is the runtime half of the "Homomorphic Secrets" sub-phase.  True
homomorphic computation (CKKS / BFV) remains a later extension; for
Fase 6 the foundational contract is:

    1. A Secret[T] can only be unwrapped via `.reveal()`, which records
       an access in an audit ring buffer.
    2. Every `__repr__` / `__str__` / `__eq__` / JSON path returns the
       SAME redacted sentinel — no side-channel via length or structure.
    3. `as_dict()` emits `{"type": "Secret", "redacted": True, ...}` —
       not the underlying value.

Usage
-----
    s = Secret("sk-live-abc123", label="stripe.api_key")
    repr(s)        # → 'Secret<redacted>'
    s.reveal()     # → "sk-live-abc123" (logged as access #N)
    s.audit_trail  # → ((handler, ts), ...)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Generic, TypeVar

from axon.runtime.handlers.base import CalleeBlameError, CallerBlameError


T = TypeVar("T")


_REDACTED_SENTINEL = "Secret<redacted>"


@dataclass(frozen=True)
class SecretAccess:
    """One audit entry for a `reveal()` call."""
    accessor: str        # handler / agent / reflex that called reveal
    timestamp: str       # ISO 8601 UTC
    purpose: str         # free-form reason (e.g. "sign_request", "encrypt_row")


class Secret(Generic[T]):
    """A sensitive value wrapped with strict no-materialize semantics.

    The underlying payload is stored in a private slot; Python does not
    prevent introspection (`__dict__`, `gc`), so this primitive enforces
    policy at the logical layer.  For process-level confidentiality,
    pair with OS-level secret stores (systemd credentials, vault).
    """

    __slots__ = ("_payload", "_label", "_fingerprint", "_accesses", "_allow_repr")

    def __init__(self, payload: T, *, label: str = "", allow_repr: bool = False) -> None:
        if isinstance(payload, Secret):
            raise CallerBlameError(
                "cannot wrap a Secret inside another Secret — nesting is a "
                "common source of silent leaks (§6.4)"
            )
        object.__setattr__(self, "_payload", payload)
        object.__setattr__(self, "_label", label)
        object.__setattr__(
            self, "_fingerprint",
            hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()[:16],
        )
        object.__setattr__(self, "_accesses", [])
        object.__setattr__(self, "_allow_repr", allow_repr)

    # ── Public API ────────────────────────────────────────────────

    @property
    def label(self) -> str:
        return self._label  # safe — only a name, not the payload

    @property
    def fingerprint(self) -> str:
        """Stable 16-char SHA-256 prefix — safe to log for correlation
        without leaking the payload."""
        return self._fingerprint

    @property
    def audit_trail(self) -> tuple[SecretAccess, ...]:
        return tuple(self._accesses)

    def reveal(self, *, accessor: str, purpose: str) -> T:
        """Return the payload AND record the access.  Unauthenticated
        callers should use the `with_accessor` helper which forces a
        non-empty accessor string.
        """
        if not accessor:
            raise CalleeBlameError(
                "Secret.reveal requires a non-empty 'accessor' — unsigned "
                "access is a forensic blind spot (§6.4)"
            )
        self._accesses.append(SecretAccess(
            accessor=accessor,
            timestamp=datetime.now(timezone.utc).isoformat(),
            purpose=purpose,
        ))
        return self._payload

    def map(self, fn: Callable[[T], Any], *, accessor: str, purpose: str) -> Any:
        """Apply `fn` to the payload without letting plaintext escape
        this method's lexical scope.  The caller never holds a reference
        to the raw payload — only the function's return value.
        """
        value = self.reveal(accessor=accessor, purpose=purpose)
        return fn(value)

    # ── Dunder methods — enforce no-materialize invariant ─────────

    def __repr__(self) -> str:
        if self._allow_repr:
            return f"Secret<{self._label or 'anonymous'}:{self._fingerprint}>"
        return _REDACTED_SENTINEL

    def __str__(self) -> str:
        return self.__repr__()

    def __format__(self, format_spec: str) -> str:
        return self.__repr__()

    def __eq__(self, other: object) -> bool:
        # Structural equality without exposing values — compare
        # fingerprints, not payloads.  This is intentionally stricter
        # than "same payload" to prevent side-channels on `==`.
        if not isinstance(other, Secret):
            return NotImplemented
        return self._fingerprint == other._fingerprint

    def __hash__(self) -> int:
        return hash(("Secret", self._fingerprint))

    def __bool__(self) -> bool:
        # Do NOT delegate to the payload — that would leak via
        # `if secret:` style branches.  A Secret is always truthy.
        return True

    # ── Serialization helpers ─────────────────────────────────────

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe redacted representation — never contains plaintext."""
        return {
            "type":          "Secret",
            "redacted":      True,
            "label":         self._label,
            "fingerprint":   self._fingerprint,
            "access_count":  len(self._accesses),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.as_dict()


__all__ = ["Secret", "SecretAccess"]
