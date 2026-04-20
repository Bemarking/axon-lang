"""RBAC data models: Role, Permission, and RoleHierarchy."""

from dataclasses import dataclass, field
from typing import Set
from uuid import UUID, uuid4


@dataclass
class Permission:
    """A single permission (e.g., 'flow:deploy', 'metrics:read')."""

    id: UUID = field(default_factory=uuid4)
    name: str = ""  # e.g., "flow:deploy", "metrics:read", "audit:view"
    description: str = ""
    resource: str = ""  # e.g., "flow", "metrics", "audit"
    action: str = ""  # e.g., "deploy", "read", "view"

    def __hash__(self) -> int:
        return hash(self.id)


@dataclass
class Role:
    """A role that holds a set of permissions."""

    id: UUID = field(default_factory=uuid4)
    name: str = ""  # e.g., "admin", "developer", "viewer"
    description: str = ""
    permissions: Set[Permission] = field(default_factory=set)
    is_built_in: bool = False  # System roles (admin, viewer) cannot be deleted

    def __hash__(self) -> int:
        return hash(self.id)

    def has_permission(self, permission: Permission) -> bool:
        """Check if this role has a specific permission."""
        return permission in self.permissions

    def add_permission(self, permission: Permission) -> None:
        """Grant a permission to this role."""
        self.permissions.add(permission)

    def remove_permission(self, permission: Permission) -> None:
        """Revoke a permission from this role."""
        self.permissions.discard(permission)


@dataclass
class RoleHierarchy:
    """Manages role inheritance and hierarchy (e.g., admin > developer > viewer)."""

    parent_role: Role
    child_roles: Set[Role] = field(default_factory=set)

    def add_child_role(self, role: Role) -> None:
        """Add a child role that inherits from parent."""
        self.child_roles.add(role)

    def remove_child_role(self, role: Role) -> None:
        """Remove a child role from hierarchy."""
        self.child_roles.discard(role)

    def get_inherited_permissions(self, role: Role) -> Set[Permission]:
        """Get all permissions for a role including inherited ones."""
        permissions = set(role.permissions)
        # Add parent permissions
        if self.parent_role == role:
            return permissions
        # TODO: Recursively add parent permissions
        return permissions
