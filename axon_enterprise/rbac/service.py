"""RBAC service for managing roles, permissions, and access control."""

from typing import Optional, Set
from uuid import UUID

from axon_enterprise.rbac.models import Permission, Role, RoleHierarchy


class RBACService:
    """Service for managing role-based access control."""

    def __init__(self):
        """Initialize RBAC service with built-in roles."""
        self.roles: dict[UUID, Role] = {}
        self.permissions: dict[UUID, Permission] = {}
        self.hierarchies: dict[UUID, RoleHierarchy] = {}
        self._init_builtin_roles()

    def _init_builtin_roles(self) -> None:
        """Create built-in roles: admin, developer, viewer."""
        # Admin: all permissions
        admin = Role(name="admin", description="Full system access", is_built_in=True)
        self.roles[admin.id] = admin

        # Developer: deploy, execute, read metrics
        developer = Role(name="developer", description="Deploy and execute flows", is_built_in=True)
        self.roles[developer.id] = developer

        # Viewer: read-only access
        viewer = Role(name="viewer", description="Read-only access", is_built_in=True)
        self.roles[viewer.id] = viewer

    def create_role(self, name: str, description: str = "") -> Role:
        """Create a new custom role."""
        role = Role(name=name, description=description, is_built_in=False)
        self.roles[role.id] = role
        return role

    def get_role(self, role_id: UUID) -> Optional[Role]:
        """Retrieve a role by ID."""
        return self.roles.get(role_id)

    def get_role_by_name(self, name: str) -> Optional[Role]:
        """Retrieve a role by name."""
        for role in self.roles.values():
            if role.name == name:
                return role
        return None

    def delete_role(self, role_id: UUID) -> bool:
        """Delete a custom role (cannot delete built-in roles)."""
        role = self.roles.get(role_id)
        if role and not role.is_built_in:
            del self.roles[role_id]
            return True
        return False

    def create_permission(self, resource: str, action: str, description: str = "") -> Permission:
        """Create a new permission."""
        perm = Permission(
            name=f"{resource}:{action}",
            resource=resource,
            action=action,
            description=description,
        )
        self.permissions[perm.id] = perm
        return perm

    def grant_permission(self, role_id: UUID, permission_id: UUID) -> bool:
        """Grant a permission to a role."""
        role = self.roles.get(role_id)
        perm = self.permissions.get(permission_id)
        if role and perm:
            role.add_permission(perm)
            return True
        return False

    def revoke_permission(self, role_id: UUID, permission_id: UUID) -> bool:
        """Revoke a permission from a role."""
        role = self.roles.get(role_id)
        perm = self.permissions.get(permission_id)
        if role and perm:
            role.remove_permission(perm)
            return True
        return False

    def check_permission(self, role_id: UUID, permission_id: UUID) -> bool:
        """Check if a role has a specific permission."""
        role = self.roles.get(role_id)
        perm = self.permissions.get(permission_id)
        if role and perm:
            return role.has_permission(perm)
        return False
