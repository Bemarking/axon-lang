"""Tenant-scoped RBAC service.

Replaces the in-memory v1.0.0 scaffolding. Everything flows through
an ``AsyncSession``; the service does not own its own DB handle and
the caller is responsible for opening a ``tenant_session()`` or
``admin_session()`` depending on the operation.

Responsibility split
--------------------

    Read operations (list roles, check permission, effective set)
        → tenant_session(ctx) — RLS filters by tenant

    Write operations (create role, grant permission, assign role)
        → admin_session() OR tenant_session(ctx) when the caller
          already holds ``role:create`` / ``role:assign`` — the
          service does not enforce the check itself; enforcement
          sits in ``rbac.enforce`` and the handlers that call us

    Global permissions catalog (list_permissions, get_permission)
        → admin_session() OR any session — no RLS on permissions

The hot path is ``check()`` which resolves effective permissions via
a recursive CTE in Postgres. Performance profile: single query, fully
indexed; cache invalidation complexity not warranted until metrics
show we need distributed caching (that lands with 10.i).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

import structlog
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError as SAIntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.rbac.errors import (
    BuiltInRoleProtected,
    PermissionDenied,
    PermissionNotFound,
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
    BUILT_IN_ROLE_NAMES,
    SYSTEM_PERMISSIONS,
    parse_permission,
)

_logger: structlog.stdlib.BoundLogger = structlog.get_logger("axon_enterprise.rbac.service")


# Recursive CTE that walks the role hierarchy upward from every role a
# user holds inside a tenant, then joins to the permission catalogue.
# ``UNION`` (not ``UNION ALL``) dedupes so a smuggled cycle terminates.
#
# Parameters:
#   :user_id    — UUID of the user
#   :tenant_id  — tenant slug
_EFFECTIVE_PERMISSIONS_SQL = text(
    """
    WITH RECURSIVE role_tree AS (
        SELECT r.role_id, r.parent_role_id
        FROM axon_control.roles r
        JOIN axon_control.user_roles ur USING (role_id)
        WHERE ur.user_id = :user_id
          AND ur.tenant_id = :tenant_id
          AND r.tenant_id = :tenant_id
        UNION
        SELECT r.role_id, r.parent_role_id
        FROM axon_control.roles r
        JOIN role_tree rt ON r.role_id = rt.parent_role_id
        WHERE r.tenant_id = :tenant_id
    )
    SELECT DISTINCT p.resource, p.action
    FROM role_tree rt
    JOIN axon_control.role_permissions rp ON rp.role_id = rt.role_id
    JOIN axon_control.permissions p ON p.permission_id = rp.permission_id
    WHERE rp.tenant_id = :tenant_id;
    """
)


@dataclass(frozen=True)
class RbacService:
    """Thin façade over RBAC persistence. Accepts an ``AsyncSession`` per call."""

    @classmethod
    def default(cls) -> RbacService:
        return cls()

    # ── Permission catalog ────────────────────────────────────────────

    async def list_permissions(self, db: AsyncSession) -> list[Permission]:
        res = await db.execute(select(Permission).order_by(Permission.resource, Permission.action))
        return list(res.scalars())

    async def get_permission(
        self, db: AsyncSession, *, resource: str, action: str
    ) -> Permission:
        row = await db.scalar(
            select(Permission).where(
                Permission.resource == resource,
                Permission.action == action,
            )
        )
        if row is None:
            raise PermissionNotFound(f"{resource}:{action}")
        return row

    # ── Roles ─────────────────────────────────────────────────────────

    async def create_role(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        name: str,
        description: str = "",
        parent_role_id: UUID | None = None,
        is_built_in: bool = False,
    ) -> Role:
        if parent_role_id is not None:
            await self._assert_no_cycle(
                db, tenant_id=tenant_id, role_id=None, parent_role_id=parent_role_id
            )

        role = Role(
            tenant_id=tenant_id,
            name=name,
            description=description,
            parent_role_id=parent_role_id,
            is_built_in=is_built_in,
        )
        db.add(role)
        try:
            await db.flush()
        except SAIntegrityError as exc:  # duplicate (tenant_id, name)
            raise RbacError from exc  # type: ignore[name-defined]
        return role

    async def get_role(self, db: AsyncSession, role_id: UUID) -> Role:
        row = await db.get(Role, role_id)
        if row is None:
            raise RoleNotFound(str(role_id))
        return row

    async def get_role_by_name(
        self, db: AsyncSession, *, tenant_id: str, name: str
    ) -> Role | None:
        return await db.scalar(
            select(Role).where(Role.tenant_id == tenant_id, Role.name == name)
        )

    async def list_roles(self, db: AsyncSession, *, tenant_id: str) -> list[Role]:
        res = await db.execute(
            select(Role).where(Role.tenant_id == tenant_id).order_by(Role.name)
        )
        return list(res.scalars())

    async def delete_role(self, db: AsyncSession, role_id: UUID) -> None:
        role = await self.get_role(db, role_id)
        if role.is_built_in:
            raise BuiltInRoleProtected(role.name)
        await db.delete(role)
        await db.flush()

    async def set_parent(
        self,
        db: AsyncSession,
        *,
        role_id: UUID,
        parent_role_id: UUID | None,
    ) -> Role:
        role = await self.get_role(db, role_id)
        if parent_role_id is not None:
            await self._assert_no_cycle(
                db,
                tenant_id=role.tenant_id,
                role_id=role_id,
                parent_role_id=parent_role_id,
            )
        role.parent_role_id = parent_role_id
        await db.flush()
        return role

    # ── Role → Permission ─────────────────────────────────────────────

    async def grant_permission(
        self,
        db: AsyncSession,
        *,
        role_id: UUID,
        resource: str,
        action: str,
        granted_by: UUID | None = None,
    ) -> None:
        role = await self.get_role(db, role_id)
        perm = await self.get_permission(db, resource=resource, action=action)
        link = RolePermission(
            role_id=role.role_id,
            permission_id=perm.permission_id,
            tenant_id=role.tenant_id,
            granted_by=granted_by,
        )
        db.add(link)
        try:
            await db.flush()
        except SAIntegrityError:
            # Already granted — idempotent.
            await db.rollback()
            # Re-open the surrounding tx for the caller. NOTE: callers
            # that need idempotency should invoke within their own
            # savepoint; this rollback simplifies the happy path.
            raise

    async def revoke_permission(
        self,
        db: AsyncSession,
        *,
        role_id: UUID,
        resource: str,
        action: str,
    ) -> None:
        perm = await self.get_permission(db, resource=resource, action=action)
        await db.execute(
            delete(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.permission_id == perm.permission_id,
            )
        )
        await db.flush()

    async def grant_permissions(
        self,
        db: AsyncSession,
        *,
        role_id: UUID,
        permission_keys: Iterable[str],
        granted_by: UUID | None = None,
    ) -> int:
        """Bulk grant — used by the tenant seeding flow.

        Silently skips (role_id, permission_id) pairs that already
        exist. Returns the number of NEW rows inserted.
        """
        role = await self.get_role(db, role_id)
        keys = list(permission_keys)
        if not keys:
            return 0

        existing_ids = set(
            (await db.execute(
                select(RolePermission.permission_id).where(
                    RolePermission.role_id == role_id
                )
            )).scalars()
        )

        inserted = 0
        for key in keys:
            resource, action = parse_permission(key)
            perm = await self.get_permission(db, resource=resource, action=action)
            if perm.permission_id in existing_ids:
                continue
            db.add(
                RolePermission(
                    role_id=role.role_id,
                    permission_id=perm.permission_id,
                    tenant_id=role.tenant_id,
                    granted_by=granted_by,
                )
            )
            existing_ids.add(perm.permission_id)
            inserted += 1
        await db.flush()
        return inserted

    # ── User ↔ Role ───────────────────────────────────────────────────

    async def assign_role(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        role_id: UUID,
        tenant_id: str,
        assigned_by: UUID | None = None,
    ) -> None:
        role = await self.get_role(db, role_id)
        if role.tenant_id != tenant_id:
            # Guard rail: a role is tenant-scoped; assigning it to a
            # user for a DIFFERENT tenant would bypass the isolation.
            raise RoleNotFound(str(role_id))
        link = UserRole(
            user_id=user_id,
            role_id=role_id,
            tenant_id=tenant_id,
            assigned_by=assigned_by,
        )
        db.add(link)
        try:
            await db.flush()
        except SAIntegrityError:
            # Already assigned — idempotent.
            await db.rollback()

    async def revoke_role(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        role_id: UUID,
        tenant_id: str,
    ) -> None:
        await db.execute(
            delete(UserRole).where(
                UserRole.user_id == user_id,
                UserRole.role_id == role_id,
                UserRole.tenant_id == tenant_id,
            )
        )
        await db.flush()

    async def list_user_roles(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        tenant_id: str,
    ) -> list[Role]:
        res = await db.execute(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.role_id)
            .where(
                UserRole.user_id == user_id,
                UserRole.tenant_id == tenant_id,
            )
            .order_by(Role.name)
        )
        return list(res.scalars())

    # ── Permission resolution (hot path) ──────────────────────────────

    async def effective_permissions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        tenant_id: str,
    ) -> set[tuple[str, str]]:
        """Return every ``(resource, action)`` pair reachable for the user.

        Walks the role hierarchy via a recursive CTE in Postgres. Cheap
        enough to invoke per-request for coarse checks; handlers can
        additionally cache the result on the ``PrincipalContext`` for
        the duration of a single request.
        """
        res = await db.execute(
            _EFFECTIVE_PERMISSIONS_SQL,
            {"user_id": user_id, "tenant_id": tenant_id},
        )
        return {(row[0], row[1]) for row in res.all()}

    async def check(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        tenant_id: str,
        permission: str,
    ) -> bool:
        resource, action = parse_permission(permission)
        effective = await self.effective_permissions(
            db, user_id=user_id, tenant_id=tenant_id
        )
        return (resource, action) in effective

    async def require(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        tenant_id: str,
        permission: str,
    ) -> None:
        """Raise ``PermissionDenied`` if the user lacks ``permission``."""
        if not await self.check(
            db, user_id=user_id, tenant_id=tenant_id, permission=permission
        ):
            _logger.info(
                "permission_denied",
                user_id=str(user_id),
                tenant_id=tenant_id,
                permission=permission,
            )
            raise PermissionDenied(permission)

    # ── Internals ─────────────────────────────────────────────────────

    async def _assert_no_cycle(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        role_id: UUID | None,
        parent_role_id: UUID,
    ) -> None:
        """Walk upward from ``parent_role_id`` and reject if we hit ``role_id``.

        ``role_id`` is None during creation (the new role has no id yet),
        in which case the only cycle-free parent chain is "any chain
        that terminates in a None parent". ``UNION`` semantics in the
        recursive CTE would still terminate on a smuggled cycle, but
        surfacing the error at write time gives operators a precise
        message.
        """
        visited: set[UUID] = {parent_role_id}
        current: UUID | None = parent_role_id

        while current is not None:
            parent_row = await db.scalar(
                select(Role.parent_role_id).where(
                    Role.role_id == current,
                    Role.tenant_id == tenant_id,
                )
            )
            if parent_row is None:
                return  # Chain terminated — no cycle.
            if role_id is not None and parent_row == role_id:
                raise RoleCycleError(
                    f"setting parent_role_id={parent_role_id} on role={role_id} "
                    "would create a hierarchy cycle"
                )
            if parent_row in visited:
                # Someone else created a cycle already; reject rather
                # than loop forever.
                raise RoleCycleError(
                    f"existing cycle detected while validating parent={parent_role_id}"
                )
            visited.add(parent_row)
            current = parent_row


# Needed for the ``SAIntegrityError`` fallthrough in create_role.
from axon_enterprise.rbac.errors import RbacError  # noqa: E402
