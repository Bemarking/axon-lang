"""
Compliance-aware restart hooks (Fase 16.n).

Before restarting any daemon the supervisor consults this module to
check whether the daemon's legal basis (`@legal_basis: GDPR.Art6.Consent`,
`HIPAA.164_502`, etc.) is still valid. If consent was revoked or the
basis expired between crash and restart, the supervisor refuses to
restart and emits a compliance violation event instead — the daemon
stays down until either:

  * a fresh consent is recorded, OR
  * the operator explicitly overrides the gate (audit-logged).

The check is a thin facade over `axon_enterprise.compliance.service`,
which holds the closed catalog of regulatory authorisations + an
adapter for fresh-status lookup (Postgres-backed in production).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol


class _ComplianceChecker(Protocol):
    """Adapter-shaped interface to the enterprise compliance module.

    Production deployments pass an instance backed by Postgres + the
    legal-basis catalog (per-tenant, per-daemon legal-basis lookup).
    """

    async def is_basis_valid(
        self, tenant_id: str, basis_slug: str,
    ) -> bool: ...


@dataclass
class ComplianceGate:
    """Restart-time compliance gate.

    Constructed once per supervisor; consulted by
    `EnterpriseSupervisorHooks.on_daemon_restart`. If `allow_restart`
    returns False, the supervisor's restart cascade is short-circuited
    via the `noop` resolution.
    """

    checker: _ComplianceChecker
    # Resolves daemon name → list[basis_slug] (or empty list if the
    # daemon isn't legally constrained).
    basis_resolver: Callable[[str], list[str]]
    tenant_resolver: Callable[[str], str]

    async def allow_restart(self, daemon_name: str) -> bool:
        """Return True iff every legal basis required by the daemon
        is currently valid for the resolved tenant."""
        try:
            tenant_id = self.tenant_resolver(daemon_name)
        except Exception:
            return True  # default-allow if resolver is broken
        try:
            slugs = self.basis_resolver(daemon_name)
        except Exception:
            return True
        if not slugs:
            return True
        for basis in slugs:
            try:
                ok = await self.checker.is_basis_valid(tenant_id, basis)
            except Exception:
                # Default-allow on lookup failure so a flaky compliance
                # service can't take down all daemons. The operator
                # alert path lives in observability.
                ok = True
            if not ok:
                return False
        return True


class _AlwaysValidChecker:
    """Default `_ComplianceChecker` impl for tests + adopters who
    don't want compliance gating. Always returns True."""

    async def is_basis_valid(self, tenant_id: str, basis_slug: str) -> bool:
        return True


def default_compliance_gate() -> ComplianceGate:
    """No-op gate — every restart allowed. Suitable for tests + the
    OSS-ish enterprise install where compliance gating is disabled."""
    return ComplianceGate(
        checker=_AlwaysValidChecker(),
        basis_resolver=lambda _: [],
        tenant_resolver=lambda _: "_global",
    )
