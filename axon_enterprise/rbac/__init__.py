"""RBAC Production-Grade — Fase 10.c.

Replaces the in-memory v1.0.0 scaffolding with a persistent, tenant-
scoped, hierarchical model enforced in Postgres via a recursive CTE.

Public surface:

    RbacService          — all persistence-bound operations
    Role / Permission    — ORM models
    RolePermission /     — M2M join models (denormalised tenant_id
    UserRole               for direct RLS policies)
    SYSTEM_PERMISSIONS   — 32-entry catalogue seeded by migration 003
    BUILT_IN_ROLE_*      — owner / admin / developer / viewer definitions
    seed_builtin_roles   — per-tenant idempotent seeder
    require_permission   — handler decorator
    PermissionDenied     — raised on deny (403)
"""

from axon_enterprise.rbac.enforce import (
    check_permission,
    require_permission,
    require_permission_active,
)
from axon_enterprise.rbac.errors import (
    BuiltInRoleProtected,
    InvalidPermissionString,
    PermissionDenied,
    PermissionNotFound,
    RbacError,
    RoleCycleError,
    RoleNotFound,
)
from axon_enterprise.rbac.models import (
    Permission,
    Role,
    RolePermission,
    UserRole,
)
from axon_enterprise.rbac.permissions import (
    BUILT_IN_ROLE_DESCRIPTIONS,
    BUILT_IN_ROLE_NAMES,
    BUILT_IN_ROLE_PERMISSIONS,
    PERMISSION_KEY_SET,
    SYSTEM_PERMISSIONS,
    PermissionDef,
    parse_permission,
)
from axon_enterprise.rbac.seed import SeededRoles, seed_builtin_roles
from axon_enterprise.rbac.service import RbacService

__all__ = [
    "BUILT_IN_ROLE_DESCRIPTIONS",
    "BUILT_IN_ROLE_NAMES",
    "BUILT_IN_ROLE_PERMISSIONS",
    "BuiltInRoleProtected",
    "InvalidPermissionString",
    "PERMISSION_KEY_SET",
    "Permission",
    "PermissionDef",
    "PermissionDenied",
    "PermissionNotFound",
    "RbacError",
    "RbacService",
    "Role",
    "RoleCycleError",
    "RoleNotFound",
    "RolePermission",
    "SYSTEM_PERMISSIONS",
    "SeededRoles",
    "UserRole",
    "check_permission",
    "parse_permission",
    "require_permission",
    "require_permission_active",
    "seed_builtin_roles",
]
