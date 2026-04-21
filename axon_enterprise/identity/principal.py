"""Principal context — authenticated user + active tenant propagated via ContextVar.

Complements ``tenant.context`` which carries ``TenantContext``. This
module adds ``PrincipalContext`` which carries the authenticated user
identity plus their resolved role names within the active tenant.

Both ContextVars are set by upstream middleware:

- ``TenantExtractor`` (Rust-side + Python duplicate in 10.e) populates
  ``CURRENT_TENANT`` from the request.
- JWT/session middleware populates ``CURRENT_PRINCIPAL`` after the
  token is verified (full JWT verification lands in 10.e).

RBAC enforcement (``rbac.enforce.require_permission``) reads from
both ContextVars; handler code never threads these values manually.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PrincipalContext:
    """The authenticated actor for the current request / task."""

    user_id: UUID
    email: str
    tenant_id: str
    # Role names inside the active tenant — denormalised from the
    # JWT/session so enforcement does not have to hit the DB for
    # coarse checks. For fine checks, ``RbacService.check`` resolves
    # effective permissions via the recursive CTE.
    role_names: frozenset[str] = field(default_factory=frozenset)
    # Session identifier for audit trail correlation.
    session_id: UUID | None = None

    def has_role(self, name: str) -> bool:
        return name in self.role_names


CURRENT_PRINCIPAL: contextvars.ContextVar[PrincipalContext | None] = (
    contextvars.ContextVar("axon.current_principal", default=None)
)


def current_principal_or_none() -> PrincipalContext | None:
    return CURRENT_PRINCIPAL.get()


def require_principal() -> PrincipalContext:
    """Return the principal or raise — use in tenant-mutating code paths."""
    p = CURRENT_PRINCIPAL.get()
    if p is None:
        raise RuntimeError(
            "No PrincipalContext set for this task. "
            "Upstream authentication middleware must call set_current_principal()."
        )
    return p


def set_current_principal(
    principal: PrincipalContext,
) -> contextvars.Token[PrincipalContext | None]:
    return CURRENT_PRINCIPAL.set(principal)
