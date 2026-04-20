"""
AXON Runtime — LeaseKernel
=============================
τ-decay token manager for the `lease` primitive (Fase 3.2).

Implements Decision D2 verbatim:

  • Compile-time: a lease references an `affine` or `linear` resource.
    The type-checker already rejected `persistent` (!A) leases because
    the exponential needs no τ-decay.
  • Runtime: the kernel emits a revocable `LeaseToken` with an explicit
    τ (acquired_at, expires_at).  On post-expiry access, the token is
    considered consumed (c=0.0, Void ⊥) and any `use()` raises
    `LeaseExpiredError` (CT-2 Anchor Breach).
  • Policy: `on_expire ∈ {anchor_breach, release, extend}`:
      - anchor_breach → hard failure on use (default, strictest)
      - release       → silent release on τ expiry (permissive)
      - extend        → automatic renewal by the same Δt window

The kernel is a pure in-process dict of active tokens.  Distributed-token
coordination is deferred to a later phase (Fase 4+ or ESK integration).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from axon.compiler.ir_nodes import IRLease, IRResource

from .handlers.base import (
    CalleeBlameError,
    CallerBlameError,
    LambdaEnvelope,
    LeaseExpiredError,
    now_iso,
)


# ═══════════════════════════════════════════════════════════════════
#  DURATION PARSING — "30s" | "5m" | "2h" | "12ms" | "1d"
# ═══════════════════════════════════════════════════════════════════

_DURATION_PATTERN = re.compile(r"^(\d+)\s*(ms|s|m|h|d)$")

_UNIT_SECONDS = {
    "ms": 0.001,
    "s":  1.0,
    "m":  60.0,
    "h":  3600.0,
    "d":  86400.0,
}


def parse_duration(text: str) -> float:
    """Convert an Axon duration literal into seconds.

    Raises CalleeBlameError if the literal cannot be parsed, because the
    parser already validated the syntax — a failure here is a bug.
    """
    if not text:
        raise CalleeBlameError("parse_duration called with empty string")
    match = _DURATION_PATTERN.match(text.strip())
    if match is None:
        raise CalleeBlameError(
            f"unparseable duration literal: '{text}' (expected <int><ms|s|m|h|d>)"
        )
    value, unit = match.groups()
    return int(value) * _UNIT_SECONDS[unit]


# ═══════════════════════════════════════════════════════════════════
#  LEASE TOKEN — the τ-decaying affine capability
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class LeaseToken:
    """
    A single-use capability over a resource, valid only while τ is in
    the `[acquired_at, expires_at)` window.

    The token is frozen: once emitted, its temporal bounds are immutable.
    Extension is implemented by minting a NEW token and revoking the old
    (LeaseKernel.extend).  This preserves the linearity invariant that
    a single token represents a single logical access window.
    """
    token_id: str
    lease_name: str
    resource_ref: str
    acquired_at: datetime
    expires_at: datetime
    on_expire: str

    def envelope(self, now: datetime) -> LambdaEnvelope:
        """Current ΛD envelope — c decays to 0.0 when τ expires."""
        if now >= self.expires_at:
            return LambdaEnvelope(
                c=0.0, tau=now.isoformat(), rho="lease_kernel", delta="observed"
            )
        return LambdaEnvelope(
            c=1.0, tau=self.acquired_at.isoformat(),
            rho="lease_kernel", delta="axiomatic",
        )

    def remaining_seconds(self, now: datetime) -> float:
        delta = (self.expires_at - now).total_seconds()
        return max(0.0, delta)


# ═══════════════════════════════════════════════════════════════════
#  LEASE KERNEL
# ═══════════════════════════════════════════════════════════════════

Clock = Callable[[], datetime]
"""A pluggable wall-clock — defaults to `datetime.now(timezone.utc)` but
tests inject a controllable stub to verify τ-decay without wall-clock waits."""


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


class LeaseKernel:
    """
    In-process registry of active leases.

    Responsibilities
    ----------------
    • `acquire(ir_lease, ir_resource)` → LeaseToken.  Validates the
      resource's lifetime (affine/linear only) and mints a fresh token.
    • `use(token)` → verifies τ validity, raises LeaseExpiredError on
      post-expiry (CT-2 Anchor Breach).  Applies `on_expire` policy:
        - anchor_breach: raise
        - release:       silently return None (caller treats as void)
        - extend:        auto-renew, return the new token
    • `release(token)` → revoke a token before expiry.  Idempotent.
    • `sweep()` → background-style method that purges tokens whose τ
      has elapsed; returns the list of purged tokens for inspection.
    • `active()` → snapshot of non-expired tokens at `now`.
    """

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._tokens: dict[str, LeaseToken] = {}
        self._revoked: set[str] = set()
        self._clock: Clock = clock or _default_clock

    # ── Public API ───────────────────────────────────────────────

    def acquire(self, ir_lease: IRLease, ir_resource: IRResource) -> LeaseToken:
        if ir_resource.lifetime == "persistent":
            # Defense-in-depth — the type-checker already rejected this,
            # but the runtime enforces the invariant too.
            raise CallerBlameError(
                f"lease '{ir_lease.name}' cannot target persistent resource "
                f"'{ir_resource.name}' — persistent (!A) is unbounded, it has "
                f"no τ to decay."
            )
        if ir_lease.resource_ref != ir_resource.name:
            raise CalleeBlameError(
                f"acquire called with mismatched resource: lease.resource_ref="
                f"{ir_lease.resource_ref!r}, ir_resource.name={ir_resource.name!r}"
            )

        seconds = parse_duration(ir_lease.duration)
        now = self._clock()
        token = LeaseToken(
            token_id=f"lease-{uuid.uuid4().hex[:12]}",
            lease_name=ir_lease.name,
            resource_ref=ir_resource.name,
            acquired_at=now,
            expires_at=now + timedelta(seconds=seconds),
            on_expire=ir_lease.on_expire,
        )
        self._tokens[token.token_id] = token
        return token

    def use(self, token: LeaseToken) -> LeaseToken | None:
        """Verify the token is still valid, applying `on_expire` policy on decay.

        Returns:
          • the same `token` when it is still valid
          • a fresh `LeaseToken` when `on_expire='extend'` triggers renewal
          • `None` when `on_expire='release'` silently retires the lease

        Raises:
          • `LeaseExpiredError` (CT-2) when `on_expire='anchor_breach'` and
             the window has closed.
          • `CallerBlameError` (CT-2) when the token was revoked or is
             unknown to this kernel.
        """
        if token.token_id in self._revoked:
            raise CallerBlameError(
                f"lease token '{token.token_id}' was revoked "
                f"(lease='{token.lease_name}')"
            )
        if token.token_id not in self._tokens:
            raise CallerBlameError(
                f"unknown lease token '{token.token_id}' "
                f"(lease='{token.lease_name}') — did you forget to acquire?"
            )

        now = self._clock()
        if now < token.expires_at:
            return token

        # τ has expired — apply policy.
        if token.on_expire == "anchor_breach":
            raise LeaseExpiredError(
                f"lease '{token.lease_name}' on resource "
                f"'{token.resource_ref}' expired at {token.expires_at.isoformat()} "
                f"(Anchor Breach — Decision D2, CT-2)"
            )
        if token.on_expire == "release":
            self._tokens.pop(token.token_id, None)
            return None
        if token.on_expire == "extend":
            # Mint a replacement with the same Δt.  The old token is
            # revoked to preserve linearity of the lease identifier.
            duration = (token.expires_at - token.acquired_at).total_seconds()
            renewed = LeaseToken(
                token_id=f"lease-{uuid.uuid4().hex[:12]}",
                lease_name=token.lease_name,
                resource_ref=token.resource_ref,
                acquired_at=now,
                expires_at=now + timedelta(seconds=duration),
                on_expire=token.on_expire,
            )
            self._revoked.add(token.token_id)
            self._tokens.pop(token.token_id, None)
            self._tokens[renewed.token_id] = renewed
            return renewed

        raise CalleeBlameError(
            f"unknown on_expire policy '{token.on_expire}' "
            f"(token id='{token.token_id}')"
        )

    def release(self, token: LeaseToken) -> None:
        """Explicitly revoke a token. Idempotent."""
        self._revoked.add(token.token_id)
        self._tokens.pop(token.token_id, None)

    def sweep(self) -> list[LeaseToken]:
        """Purge tokens whose τ has elapsed. Returns the removed tokens."""
        now = self._clock()
        expired = [t for t in self._tokens.values() if now >= t.expires_at]
        for token in expired:
            self._tokens.pop(token.token_id, None)
        return expired

    def active(self) -> list[LeaseToken]:
        """Snapshot of currently-valid tokens."""
        now = self._clock()
        return [t for t in self._tokens.values() if now < t.expires_at]

    def __contains__(self, token_id: str) -> bool:
        return token_id in self._tokens


__all__ = [
    "Clock",
    "LeaseKernel",
    "LeaseToken",
    "parse_duration",
]
