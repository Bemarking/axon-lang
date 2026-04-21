"""Built-in role seeding.

Creates the four canonical roles (``owner``, ``admin``, ``developer``,
``viewer``) inside a tenant and grants them the permissions defined
in ``permissions.BUILT_IN_ROLE_PERMISSIONS``.

Called by the tenant provisioning flow in 10.j (Admin API). Exposed
here as a stand-alone function because migrations + tests + the CLI
all need to invoke it.

Idempotency
-----------
The seeder checks for each role by ``(tenant_id, name)`` and only
creates what is missing. Re-running after adding a new permission to
the catalog top-level will also **backfill** any permissions that
the role should hold but doesn't yet — useful when bumping the
catalog without forcing every tenant to re-run a migration.
"""

from __future__ import annotations

from typing import NamedTuple
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.rbac.models import Role
from axon_enterprise.rbac.permissions import (
    BUILT_IN_ROLE_DESCRIPTIONS,
    BUILT_IN_ROLE_PERMISSIONS,
)
from axon_enterprise.rbac.service import RbacService

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.rbac.seed"
)


class SeededRoles(NamedTuple):
    """Return type of ``seed_builtin_roles`` — maps role name to its ID."""

    owner: UUID
    admin: UUID
    developer: UUID
    viewer: UUID

    def as_dict(self) -> dict[str, UUID]:
        return {
            "owner": self.owner,
            "admin": self.admin,
            "developer": self.developer,
            "viewer": self.viewer,
        }


async def seed_builtin_roles(
    db: AsyncSession,
    *,
    tenant_id: str,
    owner_user_id: UUID | None = None,
) -> SeededRoles:
    """Create (or top-up) the built-in roles for ``tenant_id``.

    When ``owner_user_id`` is supplied, that user is also assigned to
    the ``owner`` role — typical invocation from the tenant
    provisioning flow.

    Idempotent: safe to run against a tenant that already has some
    (or all) built-in roles. Missing permissions are granted; extra
    permissions on built-in roles are left alone so operators can
    tweak them without the seed re-resetting on every run.
    """
    rbac = RbacService()
    role_ids: dict[str, UUID] = {}

    for role_name, permission_keys in BUILT_IN_ROLE_PERMISSIONS.items():
        existing = await db.scalar(
            select(Role).where(Role.tenant_id == tenant_id, Role.name == role_name)
        )
        if existing is None:
            existing = await rbac.create_role(
                db,
                tenant_id=tenant_id,
                name=role_name,
                description=BUILT_IN_ROLE_DESCRIPTIONS[role_name],
                is_built_in=True,
            )
            _logger.info(
                "builtin_role_created",
                tenant_id=tenant_id,
                role_name=role_name,
            )

        inserted = await rbac.grant_permissions(
            db,
            role_id=existing.role_id,
            permission_keys=permission_keys,
        )
        if inserted:
            _logger.info(
                "builtin_role_permissions_backfilled",
                tenant_id=tenant_id,
                role_name=role_name,
                new_permissions=inserted,
            )

        role_ids[role_name] = existing.role_id

    if owner_user_id is not None:
        await rbac.assign_role(
            db,
            user_id=owner_user_id,
            role_id=role_ids["owner"],
            tenant_id=tenant_id,
        )
        _logger.info(
            "owner_role_assigned",
            tenant_id=tenant_id,
            user_id=str(owner_user_id),
        )

    return SeededRoles(
        owner=role_ids["owner"],
        admin=role_ids["admin"],
        developer=role_ids["developer"],
        viewer=role_ids["viewer"],
    )
