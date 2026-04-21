"""Tenant identity and request-scoped propagation.

Mirrors the semantics of ``axon-rs/src/tenant.rs`` so the Python control
plane and the Rust data plane share a single mental model:

- ``TenantContext`` carries ``tenant_id`` and plan tier.
- A ``ContextVar`` propagates the active tenant through async tasks —
  the Python analogue of Rust's ``tokio::task_local!``.
- ``require_tenant()`` raises when called without a context so mistakes
  surface at call sites instead of silently writing to the wrong tenant.
"""

from axon_enterprise.tenant.context import (
    CURRENT_TENANT,
    TenantContext,
    TenantPlan,
    current_tenant,
    current_tenant_or_none,
    require_tenant,
    set_current_tenant,
)

__all__ = [
    "CURRENT_TENANT",
    "TenantContext",
    "TenantPlan",
    "current_tenant",
    "current_tenant_or_none",
    "require_tenant",
    "set_current_tenant",
]
