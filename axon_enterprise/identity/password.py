"""Argon2id password hashing.

Parameters (OWASP 2024 upper-middle profile):

    time_cost   = 3
    memory_cost = 64 MiB
    parallelism = 4
    hash_len    = 32 bytes
    salt_len    = 16 bytes

Tuned for the 1 GiB default service container (starter-tier) and
bumped to 128 MiB on enterprise-tier deployments by overriding via
``AXON_IDENTITY_ARGON2_MEMORY_COST_KIB``.

``verify()`` uses ``argon2-cffi``'s constant-time comparator and
re-raises a single ``InvalidCredentialsError`` so timing behaviour
is identical whether the user exists or not (the hasher is also
invoked against a dummy hash by the AuthService when no user is
found — see ``auth.authenticate``).

``needs_rehash()`` detects stale parameters and lets the AuthService
transparently rotate the stored hash on successful login.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher as _Argon2Hasher
from argon2 import Type as Argon2Type
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from axon_enterprise.config import IdentitySettings, get_settings
from axon_enterprise.identity.errors import InvalidCredentialsError


# A baseline dummy hash generated once at startup. Used to spend the
# same CPU budget when the supplied email does not exist, so login
# timing is identical for existing vs non-existing users.
_DUMMY_HASH: str | None = None


@dataclass(frozen=True)
class PasswordHasher:
    """Thin, typed wrapper around ``argon2-cffi`` with timing parity baked in."""

    _inner: _Argon2Hasher

    # ── Construction ──────────────────────────────────────────────────

    @classmethod
    def from_settings(cls, settings: IdentitySettings) -> PasswordHasher:
        inner = _Argon2Hasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_cost_kib,
            parallelism=settings.argon2_parallelism,
            hash_len=settings.argon2_hash_len,
            salt_len=settings.argon2_salt_len,
            type=Argon2Type.ID,
        )
        return cls(_inner=inner)

    @classmethod
    def default(cls) -> PasswordHasher:
        return cls.from_settings(get_settings().identity)

    # ── Operations ────────────────────────────────────────────────────

    def hash(self, password: str) -> str:
        """Hash ``password`` using Argon2id. Salt is per-hash."""
        if not isinstance(password, str):
            raise TypeError("password must be str")
        return self._inner.hash(password)

    def verify(self, stored_hash: str, password: str) -> bool:
        """Constant-time verification.

        Returns True on match. Raises ``InvalidCredentialsError`` on
        mismatch (instead of returning False) so the exception-path is
        identical regardless of user existence.
        """
        try:
            ok = self._inner.verify(stored_hash, password)
        except (VerifyMismatchError, InvalidHashError) as exc:
            raise InvalidCredentialsError() from exc
        if not ok:  # defensive — argon2-cffi raises on mismatch
            raise InvalidCredentialsError()
        return True

    def needs_rehash(self, stored_hash: str) -> bool:
        """Return True when the stored hash was produced with weaker params."""
        try:
            return self._inner.check_needs_rehash(stored_hash)
        except InvalidHashError:
            # Unparseable hash: rotate on next successful login.
            return True

    # ── Timing parity ─────────────────────────────────────────────────

    def burn_equivalent_time(self, password: str) -> None:
        """Spend the same CPU as a real ``verify`` when the user is absent.

        Called by the AuthService when ``email`` does not resolve to a
        user so an attacker can't distinguish existing users by login
        latency. The comparison inevitably fails; we swallow the
        exception here.
        """
        global _DUMMY_HASH
        if _DUMMY_HASH is None:
            # 32 random bytes → hex → 64 chars; long enough to exercise
            # a full verify loop at current parameters.
            _DUMMY_HASH = self._inner.hash(secrets.token_hex(32))
        try:
            self._inner.verify(_DUMMY_HASH, password)
        except (VerifyMismatchError, InvalidHashError):
            pass
