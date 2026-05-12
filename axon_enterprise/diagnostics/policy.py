"""§Fase 29.b — Vertical-aware DiagnosticPolicy.

D1 + D2 + D8 + D9 ratificadas 2026-05-12.

## What this module ships

Per-tenant :class:`DiagnosticPolicy` resolved from the tenant's
vertical. The policy bundles four orthogonal dials:

- ``strict_mode`` — fail fast on the first parser error, matches
  ``axon parse --strict`` from OSS Fase 28.
- ``telemetry_enabled`` — emit OTel + Prometheus + audit-log entry
  for every parser error (wired in 29.c).
- ``recovery_mode`` — opt into parser error-recovery (collect all
  errors per file, OSS Fase 28 baseline behavior).
- ``extra_keywords`` — vertical-specific glossary terms merged into
  the Levenshtein suggest dictionary (wired in 29.d).

## Closed catalog of verticals

:class:`TenantVertical` is a closed 4-variant enum:

==================== =====================================================
Variant              Default policy
==================== =====================================================
``GENERIC``          OSS Fase 28 surface unchanged (D9 backwards-compat).
                     strict=False, telemetry=False, recovery=True.
``HIPAA``            Healthcare tenants (45 CFR Parts 160/164 + GDPR Art.
                     25). strict=True per D1 risk posture; telemetry-on
                     per D2 audit trail.
``LEGAL``            Privileged communications + work-product doctrine
                     tenants (ABA Rule 1.6 + FRE 502). strict=True per D1;
                     telemetry-on per D2.
``FINTECH``          Banking / payments / AML tenants (BSA + OFAC +
                     MiFID II). recovery=True + telemetry-on per D1+D2 —
                     full diagnostic surface needed for audit trail.
==================== =====================================================

Adding a 5th vertical requires:

1. Adding the enum entry to :class:`TenantVertical`.
2. Adding the default policy in ``_VERTICAL_DEFAULTS`` (this file).
3. Adding the suggest dictionary in Fase 29.d.
4. Adding the audit/PR review reviewer to CODEOWNERS (per D7).

The compile-time pattern matching (every `if` branch + the
``_VERTICAL_DEFAULTS`` dict literal) breaks the build when a new
variant is added without updating every consumer — closed-catalog
discipline preserved.

## D-letter trace

- **D1 ratificada** — HIPAA + legal default-strict; fintech
  recovery + telemetry-on; generic unchanged.
- **D2 ratificada** — Telemetry sink reuses existing
  ``tenant_settings.telemetry_*`` toggles; no new config surface.
- **D5 ratificada** — Policy wraps ``axon parse`` invocations at the
  enterprise integration layer; axon-lang itself is unchanged.
- **D8 ratificada** — Per-tenant scoping verified by explicit
  isolation tests; vertical X never affects vertical Y.
- **D9 ratificada** — ``GENERIC`` tenants get the OSS Fase 28
  surface verbatim. The enterprise layer is invisible to them.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import StrEnum

from axon_enterprise.tenant.context import (
    TenantContext,
    current_tenant_or_none,
)

# ──────────────────────────────────────────────────────────────────
#  Closed vertical catalog
# ──────────────────────────────────────────────────────────────────


class TenantVertical(StrEnum):
    """Closed catalog of supported regulated verticals.

    Adding a variant requires updating ``_VERTICAL_DEFAULTS``,
    Fase 29.d suggest dictionaries, and CODEOWNERS per D7.
    """

    GENERIC = "generic"
    HIPAA = "hipaa"
    LEGAL = "legal"
    FINTECH = "fintech"

    @classmethod
    def from_str(cls, value: str | None) -> TenantVertical:
        """Parse with the OSS-friendly fallback shape mirroring
        :meth:`TenantPlan.from_str`: unknown / empty / None → GENERIC.

        Useful for boundary code (HTTP middleware, DB row decoders)
        that may see legacy data without a vertical column.
        """
        if not value:
            return cls.GENERIC
        try:
            return cls(value.lower())
        except ValueError:
            return cls.GENERIC


# ──────────────────────────────────────────────────────────────────
#  DiagnosticPolicy — resolved per-tenant
# ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DiagnosticPolicy:
    """Resolved diagnostic policy applied to a tenant's ``axon parse``
    invocations.

    Frozen + slots for the same reasons :class:`TenantContext` is —
    immutability prevents per-request mutation racing with the
    parser invocation, and slots avoid the per-instance ``__dict__``
    overhead in hot paths (every parser invocation resolves a
    policy).
    """

    vertical: TenantVertical
    strict_mode: bool
    telemetry_enabled: bool
    recovery_mode: bool
    extra_keywords: tuple[str, ...] = field(default_factory=tuple)

    def with_override(
        self,
        *,
        strict_mode: bool | None = None,
        telemetry_enabled: bool | None = None,
        recovery_mode: bool | None = None,
        extra_keywords: tuple[str, ...] | None = None,
    ) -> DiagnosticPolicy:
        """Return a new policy with the named fields overridden.

        Used by the per-tenant settings layer to honor explicit
        opt-outs (per D1 — HIPAA tenants can opt out of strict via
        ``diagnostic_policy.strict = false`` in tenant settings).
        Vertical is intentionally NOT overridable through this path —
        changing a tenant's vertical is a tenant-management operation,
        not a per-invocation override.
        """
        return DiagnosticPolicy(
            vertical=self.vertical,
            strict_mode=strict_mode if strict_mode is not None else self.strict_mode,
            telemetry_enabled=telemetry_enabled
            if telemetry_enabled is not None
            else self.telemetry_enabled,
            recovery_mode=recovery_mode if recovery_mode is not None else self.recovery_mode,
            extra_keywords=extra_keywords if extra_keywords is not None else self.extra_keywords,
        )

    def to_parse_args(self) -> list[str]:
        """Project the policy onto ``axon parse`` CLI flags.

        Returns the list of additional argv tokens the policy injects.
        Empty when the policy matches the OSS default (generic).

        D5 ratified — projection happens at the enterprise integration
        layer, not inside axon-lang. The flag set is exactly what OSS
        ``axon parse`` accepts; no new flag namespace.
        """
        args: list[str] = []
        if self.strict_mode:
            args.append("--strict")
        return args

    def matches_oss_default(self) -> bool:
        """True iff this policy is byte-equivalent to the OSS Fase 28
        default (generic vertical). D9 invariant pin.
        """
        return (
            self.vertical == TenantVertical.GENERIC
            and not self.strict_mode
            and not self.telemetry_enabled
            and self.recovery_mode
            and len(self.extra_keywords) == 0
        )


# ──────────────────────────────────────────────────────────────────
#  Per-vertical defaults (D1 + D2 ratificadas)
# ──────────────────────────────────────────────────────────────────


_VERTICAL_DEFAULTS: dict[TenantVertical, DiagnosticPolicy] = {
    TenantVertical.GENERIC: DiagnosticPolicy(
        vertical=TenantVertical.GENERIC,
        strict_mode=False,
        telemetry_enabled=False,
        recovery_mode=True,
    ),
    TenantVertical.HIPAA: DiagnosticPolicy(
        vertical=TenantVertical.HIPAA,
        strict_mode=True,
        telemetry_enabled=True,
        recovery_mode=False,
    ),
    TenantVertical.LEGAL: DiagnosticPolicy(
        vertical=TenantVertical.LEGAL,
        strict_mode=True,
        telemetry_enabled=True,
        recovery_mode=False,
    ),
    TenantVertical.FINTECH: DiagnosticPolicy(
        vertical=TenantVertical.FINTECH,
        strict_mode=False,
        telemetry_enabled=True,
        recovery_mode=True,
    ),
}


# Closed-catalog pin: every variant of TenantVertical MUST have a
# default policy registered above. Module-load-time assertion makes
# the contract a build-time invariant.
assert set(_VERTICAL_DEFAULTS.keys()) == set(TenantVertical), (
    "Every TenantVertical variant must have a _VERTICAL_DEFAULTS entry; "
    "missing: "
    f"{set(TenantVertical) - set(_VERTICAL_DEFAULTS.keys())}"
)


def resolve_policy_for_vertical(vertical: TenantVertical) -> DiagnosticPolicy:
    """Pure dispatch: vertical → default policy.

    Total over the closed :class:`TenantVertical` catalog; never
    panics. Forward-compat fallback: any unknown enum-style value
    (defensive, shouldn't reach here in practice) resolves to
    ``GENERIC``.
    """
    if vertical not in _VERTICAL_DEFAULTS:
        return _VERTICAL_DEFAULTS[TenantVertical.GENERIC]
    return _VERTICAL_DEFAULTS[vertical]


# ──────────────────────────────────────────────────────────────────
#  Tenant → vertical registry
# ──────────────────────────────────────────────────────────────────
#
# In-memory mapping from ``tenant_id`` → :class:`TenantVertical`.
# Production deployments wrap this with a DB-backed lookup; the
# in-memory shape exists for in-tree tests + bootstrap flows.
# Subsequent fases (or v1.15.x patches) can swap the implementation
# without changing the public API.

_VERTICAL_REGISTRY: dict[str, TenantVertical] = {}
_REGISTRY_LOCK = threading.RLock()


def set_tenant_vertical(tenant_id: str, vertical: TenantVertical) -> None:
    """Register the vertical for ``tenant_id``. Idempotent; last write
    wins.

    Thread-safe via an RLock; safe to call from any thread (HTTP
    handlers, background tasks, CLI tooling).
    """
    with _REGISTRY_LOCK:
        _VERTICAL_REGISTRY[tenant_id] = vertical


def get_tenant_vertical(tenant_id: str) -> TenantVertical:
    """Return the registered vertical for ``tenant_id``.

    Falls back to :attr:`TenantVertical.GENERIC` when no registration
    exists (D9 backwards-compat — unregistered tenants get the OSS
    surface unchanged).
    """
    with _REGISTRY_LOCK:
        return _VERTICAL_REGISTRY.get(tenant_id, TenantVertical.GENERIC)


def unset_tenant_vertical(tenant_id: str) -> None:
    """Remove the registration for ``tenant_id``. Idempotent — no
    error if the tenant was never registered.
    """
    with _REGISTRY_LOCK:
        _VERTICAL_REGISTRY.pop(tenant_id, None)


def clear_vertical_registry() -> None:
    """Drop every registration. Tests use this between cases; not
    intended for production code paths.
    """
    with _REGISTRY_LOCK:
        _VERTICAL_REGISTRY.clear()


def all_registered_tenants() -> dict[str, TenantVertical]:
    """Snapshot copy of the current registry. Useful for telemetry +
    diagnostic dashboards (Fase 29.e). Returns a defensive copy so
    callers can iterate without holding the lock.
    """
    with _REGISTRY_LOCK:
        return dict(_VERTICAL_REGISTRY)


# ──────────────────────────────────────────────────────────────────
#  Current-tenant resolution
# ──────────────────────────────────────────────────────────────────


def resolve_policy_for_current_tenant() -> DiagnosticPolicy:
    """Resolve the diagnostic policy for the active
    :class:`TenantContext`.

    D9 backwards-compat: falls back to GENERIC when no tenant context
    is set OR when the tenant has no registered vertical. Generic
    tenants receive the OSS Fase 28 surface verbatim.
    """
    ctx = current_tenant_or_none()
    if ctx is None:
        return resolve_policy_for_vertical(TenantVertical.GENERIC)
    vertical = get_tenant_vertical(ctx.tenant_id)
    return resolve_policy_for_vertical(vertical)


def resolve_policy_for_tenant_context(ctx: TenantContext) -> DiagnosticPolicy:
    """Resolve the policy for an explicit :class:`TenantContext`.

    Useful for code paths that have a tenant context but haven't yet
    installed it via :func:`set_current_tenant` (e.g. batch workers
    iterating over tenants).
    """
    vertical = get_tenant_vertical(ctx.tenant_id)
    return resolve_policy_for_vertical(vertical)
