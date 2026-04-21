"""System permission catalog — the closed set of (resource, action) pairs.

Permissions are a **global** catalog shared across tenants. Granting a
permission to a role happens per-tenant via ``role_permissions`` (also
tenant-scoped). The catalog itself is seeded once by migration 003 and
audited for changes via Alembic review.

To add a permission:

    1. Append a tuple to ``SYSTEM_PERMISSIONS``.
    2. Add an Alembic revision that ``INSERT ... ON CONFLICT DO NOTHING``
       the new permission, and updates the relevant built-in roles
       (``owner`` gets it automatically; others by explicit decision).
    3. Call sites that must enforce the new permission use
       ``rbac.require_permission("resource:action")``.

Adopter-agnostic note
---------------------
The resource set reflects the *minimum* shape every Axon Enterprise
deployment needs. Tenants with their own domain resources (e.g.
"invoice:read") can extend the catalog by inserting rows in a
migration local to the tenant's fork — the schema allows it via
``is_system = FALSE``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PermissionDef:
    """Catalog entry describing a single permission."""

    resource: str
    action: str
    description: str

    @property
    def key(self) -> str:
        return f"{self.resource}:{self.action}"


# ── Canonical catalog ─────────────────────────────────────────────────
#
# Ordering matters only for migration diffs; ordering them by resource
# keeps the seed SQL stable across reviewers.

SYSTEM_PERMISSIONS: tuple[PermissionDef, ...] = (
    # Tenant management
    PermissionDef("tenant", "read", "View tenant information and settings"),
    PermissionDef("tenant", "update", "Modify tenant metadata and settings"),
    PermissionDef("tenant", "delete", "Schedule deletion of the tenant"),
    PermissionDef("tenant", "suspend", "Suspend tenant operations"),
    # User management
    PermissionDef("user", "invite", "Invite a user to the tenant"),
    PermissionDef("user", "read", "View user profile and membership"),
    PermissionDef("user", "update", "Modify a user's profile"),
    PermissionDef("user", "deactivate", "Revoke a user's access"),
    PermissionDef("user", "impersonate", "Impersonate a user (support only)"),
    # Role management
    PermissionDef("role", "create", "Create a custom role within this tenant"),
    PermissionDef("role", "read", "View role definitions and assignments"),
    PermissionDef("role", "update", "Modify a custom role"),
    PermissionDef("role", "delete", "Delete a custom role"),
    PermissionDef("role", "assign", "Assign or revoke a role from a user"),
    # Flow lifecycle
    PermissionDef("flow", "create", "Author a new flow"),
    PermissionDef("flow", "read", "View flow definitions and execution history"),
    PermissionDef("flow", "update", "Modify an existing flow"),
    PermissionDef("flow", "delete", "Delete a flow"),
    PermissionDef("flow", "execute", "Execute a flow on demand"),
    PermissionDef("flow", "deploy", "Promote a flow to a deployed state"),
    # Tenant secrets (Fase 10.f)
    PermissionDef("secret", "list", "List secret keys (values not shown)"),
    PermissionDef("secret", "read", "Reveal a secret's current value"),
    PermissionDef("secret", "write", "Create or update a secret"),
    PermissionDef("secret", "delete", "Schedule a secret for deletion"),
    PermissionDef("secret", "rotate", "Rotate a secret to a new version"),
    # Audit
    PermissionDef("audit", "read", "Read audit events"),
    PermissionDef("audit", "export", "Export audit logs (JSONL / ZIP bundles)"),
    # Metering + billing
    PermissionDef("metering", "read", "Read usage metrics and overage status"),
    PermissionDef("metering", "export_invoice", "Download issued invoices"),
    # Observability
    PermissionDef("observability", "read_metrics", "View Prometheus / OTLP metrics"),
    PermissionDef("observability", "read_logs", "View structured logs"),
    PermissionDef("observability", "read_traces", "View distributed traces"),
)


PERMISSION_KEY_SET: frozenset[str] = frozenset(p.key for p in SYSTEM_PERMISSIONS)


def parse_permission(permission: str) -> tuple[str, str]:
    """Split ``'resource:action'`` into a ``(resource, action)`` tuple.

    Raises ``InvalidPermissionString`` if the format is wrong. The
    string IS validated against the catalog so typos surface here
    instead of silently never matching any permission.
    """
    from axon_enterprise.rbac.errors import InvalidPermissionString

    if permission.count(":") != 1:
        raise InvalidPermissionString(
            f"permission must be 'resource:action', got {permission!r}"
        )
    resource, action = permission.split(":", 1)
    resource, action = resource.strip(), action.strip()
    if not resource or not action:
        raise InvalidPermissionString(
            f"permission has empty resource or action: {permission!r}"
        )
    if f"{resource}:{action}" not in PERMISSION_KEY_SET:
        raise InvalidPermissionString(
            f"{permission!r} is not in the system catalog; "
            "add it via a migration before enforcing it"
        )
    return resource, action


# ── Built-in role definitions ─────────────────────────────────────────
#
# Seeded per-tenant on tenant creation (via RbacService.seed_builtin_roles).
# The mapping is role_name → iterable of permission keys.
#
# Policy:
#
#   owner     — every permission in the catalog (one per tenant, cannot
#               be revoked from the tenant's original owner user)
#   admin     — operational admin, cannot delete or suspend the tenant
#               and cannot impersonate users
#   developer — everything flow-shaped plus read access to meta,
#               metering, observability, and audit
#   viewer    — read-only, cannot mutate anything
#
# ``owner`` is intentionally treated as "all" rather than an enum wildcard:
# enumerating the permissions explicitly makes role audits deterministic
# and survives catalog additions (owner gets new permissions on migration).

BUILT_IN_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "owner": [p.key for p in SYSTEM_PERMISSIONS],
    "admin": [
        p.key
        for p in SYSTEM_PERMISSIONS
        if p.key
        not in {
            "tenant:delete",
            "tenant:suspend",
            "user:impersonate",
        }
    ],
    "developer": [
        "flow:create",
        "flow:read",
        "flow:update",
        "flow:delete",
        "flow:execute",
        "flow:deploy",
        "secret:list",
        "secret:read",
        "audit:read",
        "metering:read",
        "observability:read_metrics",
        "observability:read_logs",
        "observability:read_traces",
        "role:read",
        "user:read",
        "tenant:read",
    ],
    "viewer": [p.key for p in SYSTEM_PERMISSIONS if p.action.startswith("read")],
}


BUILT_IN_ROLE_DESCRIPTIONS: dict[str, str] = {
    "owner": "Full control over the tenant (all permissions).",
    "admin": "Operational administrator (all except delete/suspend/impersonate).",
    "developer": "Flow authoring + execution + read access to audit / metering.",
    "viewer": "Read-only access to every non-sensitive resource.",
}


BUILT_IN_ROLE_NAMES: frozenset[str] = frozenset(BUILT_IN_ROLE_PERMISSIONS.keys())
