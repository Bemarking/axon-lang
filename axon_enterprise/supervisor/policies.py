"""
on_stuck policy dispatcher (Fase 16.g).

Maps the AST-level `on_stuck:` declaration on a `daemon Foo { ... }`
to a runtime restart strategy. The OSS supervisor only honors
`restart` and `noop`; this module dispatches the full vocabulary:

    restart   — current behavior, restart with intensity gate
    hibernate — serialize state, do NOT restart (operator wakes it)
    escalate  — emit alert, do NOT restart
    retry     — restart with separate retry budget
    forge     — Poincaré creative-synthesis recovery (gated/experimental)
    noop      — terminal stop, no further action

Each policy is implemented as an awaitable handler that returns one
of the OSS-recognized strings (`restart` or `noop`). The supervisor's
`resolve_on_stuck` hook routes through `PolicyDispatcher.dispatch`
which delegates to the registered handler.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol


class OnStuckPolicy(str, enum.Enum):
    """Closed catalogue of on_stuck policy strings."""

    RESTART = "restart"
    HIBERNATE = "hibernate"
    ESCALATE = "escalate"
    RETRY = "retry"
    FORGE = "forge"
    NOOP = "noop"

    @classmethod
    def parse(cls, raw: str) -> "OnStuckPolicy":
        """Parse a string into a policy enum, defaulting to RESTART
        on unknown values to preserve liveness."""
        try:
            return cls(raw)
        except ValueError:
            return cls.RESTART


# Resolution result: a string the OSS supervisor understands.
# The dispatcher's job is to perform whatever side effects the policy
# requires (snapshot, alert, etc.) then return the string.
_OSSResolution = str


class _PolicyHandler(Protocol):
    async def __call__(
        self,
        daemon_name: str,
        exc: BaseException,
    ) -> _OSSResolution: ...


@dataclass
class PolicyContext:
    """Side-channel handles that policy handlers may use.

    Filled by `EnterpriseSupervisorHooks` at construction time. Each
    field is optional — handlers should degrade gracefully if a given
    side channel isn't wired (e.g., audit_sink is None in unit tests).
    """

    snapshot_fn: Callable[[str], Awaitable[bytes | None]] | None = None
    alert_fn: Callable[[str, str], Awaitable[None]] | None = None
    audit_fn: Callable[[str, dict], Awaitable[None]] | None = None
    forge_fn: Callable[[str, BaseException], Awaitable[None]] | None = None


class PolicyDispatcher:
    """Routes a daemon-name + on_stuck_policy + exception triple to
    one of the OSS-recognized resolutions (`restart` or `noop`),
    performing side effects along the way.

    Extensible: register a custom handler with `register_policy(...)`
    if you need bespoke recovery logic for a tenant or daemon class.
    """

    def __init__(self, *, ctx: PolicyContext) -> None:
        self._ctx = ctx
        self._handlers: dict[OnStuckPolicy, _PolicyHandler] = {
            OnStuckPolicy.RESTART: self._handle_restart,
            OnStuckPolicy.HIBERNATE: self._handle_hibernate,
            OnStuckPolicy.ESCALATE: self._handle_escalate,
            OnStuckPolicy.RETRY: self._handle_retry,
            OnStuckPolicy.FORGE: self._handle_forge,
            OnStuckPolicy.NOOP: self._handle_noop,
        }

    def register_policy(
        self, policy: OnStuckPolicy, handler: _PolicyHandler,
    ) -> None:
        """Override the default handler for a given policy."""
        self._handlers[policy] = handler

    async def dispatch(
        self,
        daemon_name: str,
        policy_str: str,
        exc: BaseException,
    ) -> _OSSResolution:
        """Look up and invoke the handler for `policy_str`. Unknown
        policies fall back to RESTART. Handler exceptions also fall
        back to RESTART (defensive — never let a policy bug take down
        the supervisor)."""
        policy = OnStuckPolicy.parse(policy_str)
        handler = self._handlers.get(policy, self._handle_restart)
        try:
            return await handler(daemon_name, exc)
        except Exception:
            return OnStuckPolicy.RESTART.value

    # ── Default handlers ───────────────────────────────────────────

    async def _handle_restart(
        self, daemon_name: str, exc: BaseException,
    ) -> _OSSResolution:
        """RESTART — current behavior; let the supervisor restart
        with its intensity gate."""
        return OnStuckPolicy.RESTART.value

    async def _handle_hibernate(
        self, daemon_name: str, exc: BaseException,
    ) -> _OSSResolution:
        """HIBERNATE — snapshot state, do NOT restart. Operator wakes
        the daemon manually via the control plane."""
        if self._ctx.snapshot_fn is not None:
            try:
                await self._ctx.snapshot_fn(daemon_name)
            except Exception:
                pass
        if self._ctx.audit_fn is not None:
            try:
                await self._ctx.audit_fn(
                    "daemon_hibernated",
                    {"daemon": daemon_name, "exc": type(exc).__name__},
                )
            except Exception:
                pass
        return OnStuckPolicy.NOOP.value

    async def _handle_escalate(
        self, daemon_name: str, exc: BaseException,
    ) -> _OSSResolution:
        """ESCALATE — fire an alert, do NOT restart. Suitable for
        daemons where automated recovery is unsafe (e.g., billing
        reconciliation that may have corrupted state)."""
        if self._ctx.alert_fn is not None:
            try:
                await self._ctx.alert_fn(
                    daemon_name,
                    f"Daemon escalated after crash: {type(exc).__name__}: {exc}",
                )
            except Exception:
                pass
        if self._ctx.audit_fn is not None:
            try:
                await self._ctx.audit_fn(
                    "daemon_escalated",
                    {"daemon": daemon_name, "exc": type(exc).__name__},
                )
            except Exception:
                pass
        return OnStuckPolicy.NOOP.value

    async def _handle_retry(
        self, daemon_name: str, exc: BaseException,
    ) -> _OSSResolution:
        """RETRY — bypass the standard intensity cap up to a separate
        retry budget. The supervisor's intensity gate is unchanged
        (this dispatcher cannot extend it from here); the retry
        semantic is implemented by `EnterpriseSupervisorHooks` via a
        separate counter consulted in `on_intensity_exceeded`."""
        return OnStuckPolicy.RESTART.value

    async def _handle_forge(
        self, daemon_name: str, exc: BaseException,
    ) -> _OSSResolution:
        """FORGE — Poincaré creative-synthesis recovery. EXPERIMENTAL
        and gated behind `enterprise.experimental.forge_recovery`.

        If a forge_fn is wired, invoke it. Otherwise fall back to
        RESTART with backoff.
        """
        if self._ctx.forge_fn is not None:
            try:
                await self._ctx.forge_fn(daemon_name, exc)
            except Exception:
                pass
        return OnStuckPolicy.RESTART.value

    async def _handle_noop(
        self, daemon_name: str, exc: BaseException,
    ) -> _OSSResolution:
        """NOOP — terminal stop; mark the daemon as done."""
        if self._ctx.audit_fn is not None:
            try:
                await self._ctx.audit_fn(
                    "daemon_terminal_noop",
                    {"daemon": daemon_name, "exc": type(exc).__name__},
                )
            except Exception:
                pass
        return OnStuckPolicy.NOOP.value
