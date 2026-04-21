"""RBAC-layer errors."""

from __future__ import annotations

from axon_enterprise.identity.errors import IdentityError


class RbacError(IdentityError):
    """Base class for RBAC errors."""

    code = "rbac.error"


class PermissionDenied(RbacError):
    """The principal lacks the required permission.

    Clients see a 403 with the permission string so UIs can render a
    precise message. We consider the permission identifier safe to
    reveal because the action name is derivable from the request path.
    """

    code = "rbac.permission_denied"
    reveal_to_client = True

    def __init__(self, permission: str) -> None:
        self.permission = permission
        super().__init__(f"permission denied: {permission}")


class RoleCycleError(RbacError):
    """Creating / updating a role would introduce a cycle in the hierarchy."""

    code = "rbac.role_cycle"
    reveal_to_client = True


class RoleNotFound(RbacError):
    code = "rbac.role_not_found"
    reveal_to_client = True


class PermissionNotFound(RbacError):
    code = "rbac.permission_not_found"
    reveal_to_client = True


class BuiltInRoleProtected(RbacError):
    """Built-in roles (``owner``, ``admin``, ...) cannot be deleted or renamed."""

    code = "rbac.builtin_role_protected"
    reveal_to_client = True


class InvalidPermissionString(RbacError):
    """``permission`` argument is not in ``resource:action`` form."""

    code = "rbac.invalid_permission_string"
    reveal_to_client = True
