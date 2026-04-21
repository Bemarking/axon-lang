"""TenantContext + async-task-local propagation.

The design intentionally mirrors ``axon-rs/src/tenant.rs``:

- ``TenantContext`` is the Python equivalent of ``TenantContext`` in Rust.
- ``CURRENT_TENANT`` is a ``contextvars.ContextVar`` analogous to Rust's
  ``tokio::task_local!`` ``CURRENT_TENANT_ID``.
- Downstream code (DB session, audit logger, metering) reads the current
  tenant through ``current_tenant()`` without requiring an explicit
  parameter to propagate through every function call.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from enum import StrEnum


class TenantPlan(StrEnum):
    """Plan tier. Must match ``TenantPlan`` in axon-rs exactly (lowercase)."""

    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"

    @classmethod
    def from_str(cls, value: str) -> TenantPlan:
        """Parse with the same fallback as Rust: unknown → Starter."""
        try:
            return cls(value.lower())
        except ValueError:
            return cls.STARTER


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Resolved tenant identity for the current request / task."""

    tenant_id: str
    plan: TenantPlan = TenantPlan.ENTERPRISE
    # Request correlation. Optional on purpose: set by middleware, useful
    # when emitting audit events, metrics, and structured logs.
    request_id: str | None = field(default=None)

    @classmethod
    def default(cls) -> TenantContext:
        """Open-source / single-tenant fallback, matching Rust's ``default_tenant()``."""
        return cls(tenant_id="default", plan=TenantPlan.ENTERPRISE)

    def is_default(self) -> bool:
        return self.tenant_id == "default"


# ── Task-local propagation ─────────────────────────────────────────────

CURRENT_TENANT: contextvars.ContextVar[TenantContext | None] = contextvars.ContextVar(
    "axon.current_tenant",
    default=None,
)


def current_tenant_or_none() -> TenantContext | None:
    """Return the active ``TenantContext`` or ``None`` if unset.

    Use this at the boundary between user-facing code and background tasks
    where an unset tenant is acceptable (e.g. system-wide metrics).
    """
    return CURRENT_TENANT.get()


def current_tenant() -> TenantContext:
    """Return the active ``TenantContext`` or fall back to the default tenant.

    Matches the Rust helper ``current_tenant_id()`` which falls back to
    ``"default"`` when called outside a scoped request context. Use this in
    code paths where ``"default"`` is a safe choice (CLI, migrations, tests).
    """
    ctx = CURRENT_TENANT.get()
    return ctx if ctx is not None else TenantContext.default()


def require_tenant() -> TenantContext:
    """Return the active ``TenantContext`` or raise ``RuntimeError``.

    Use this in code paths where an unset tenant is a programming error —
    any handler that reads or writes tenant-scoped data (users, secrets,
    audit). Raising early prevents silent writes to the wrong tenant.
    """
    ctx = CURRENT_TENANT.get()
    if ctx is None:
        raise RuntimeError(
            "No TenantContext set for this task. "
            "Upstream middleware (TenantExtractor) must call set_current_tenant() "
            "before any tenant-scoped operation."
        )
    return ctx


def set_current_tenant(ctx: TenantContext) -> contextvars.Token[TenantContext | None]:
    """Install a ``TenantContext`` for the current async task.

    Returns the ``Token`` from ``ContextVar.set`` so callers can reset it on
    teardown:

        token = set_current_tenant(ctx)
        try:
            ...
        finally:
            CURRENT_TENANT.reset(token)
    """
    return CURRENT_TENANT.set(ctx)
