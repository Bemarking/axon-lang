"""``/api/v1/tenant/users/*`` — tenant-admin user management."""

from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import select, text
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from axon_enterprise.db.session import admin_session, tenant_session
from axon_enterprise.identity import (
    MembershipStatus,
    TenantMembership,
    User,
)
from axon_enterprise.identity.principal import require_principal
from axon_enterprise.invitations import InvitationService
from axon_enterprise.rbac import RbacService
from axon_enterprise.rbac.errors import PermissionDenied

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.http.api.tenant_users"
)


async def _invite(request: Request) -> JSONResponse:
    """POST — invite a new or existing user to the tenant."""
    principal = require_principal()
    _require_user_invite(principal)

    body = await request.json()
    email = str(body.get("email") or "").strip().lower()
    display_name = body.get("display_name")
    role_name = body.get("role_name", "viewer")
    if not email:
        return JSONResponse({"error": {"code": "invalid_input"}}, status_code=400)

    invitations = InvitationService()
    rbac = RbacService()

    async with admin_session() as db:
        # Upsert the user row (create when new — no password yet).
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, display_name=display_name)
            db.add(user)
            await db.flush()

        issued = await invitations.invite(
            db,
            tenant_id=principal.tenant_id,
            user_id=user.user_id,
            invited_by=principal.user_id,
        )

        # Assign the requested role (if it exists in this tenant).
        role = await rbac.get_role_by_name(
            db, tenant_id=principal.tenant_id, name=str(role_name)
        )
        if role is not None:
            await rbac.assign_role(
                db,
                user_id=user.user_id,
                role_id=role.role_id,
                tenant_id=principal.tenant_id,
                assigned_by=principal.user_id,
            )

    return JSONResponse(
        {
            "user_id": str(user.user_id),
            "email": user.email,
            "invitation_token": issued.raw_token,
            "invitation_expires_at": issued.expires_at.isoformat(),
            "assigned_role": role_name if role is not None else None,
        },
        status_code=201,
    )


async def _list_members(request: Request) -> JSONResponse:
    """GET — list members of the caller's tenant (paginated)."""
    principal = require_principal()
    async with tenant_session() as db:
        memberships = list(
            (
                await db.execute(
                    select(TenantMembership).where(
                        TenantMembership.tenant_id == principal.tenant_id
                    )
                )
            ).scalars()
        )
    # Fetch user rows via admin_session (users is admin_bypass-only).
    user_ids = [m.user_id for m in memberships]
    users: dict[UUID, User] = {}
    if user_ids:
        async with admin_session() as db:
            for u in (
                (
                    await db.execute(
                        select(User).where(User.user_id.in_(user_ids))
                    )
                ).scalars()
            ):
                users[u.user_id] = u

    payload = []
    for m in memberships:
        u = users.get(m.user_id)
        payload.append(
            {
                "user_id": str(m.user_id),
                "email": u.email if u else None,
                "display_name": u.display_name if u else None,
                "status": m.status,
                "joined_at": m.joined_at.isoformat() if m.joined_at else None,
            }
        )
    return JSONResponse({"items": payload})


async def _deactivate(request: Request) -> JSONResponse:
    """DELETE — remove the user's membership in the caller's tenant."""
    principal = require_principal()
    _require_user_invite(principal)
    raw = request.path_params["user_id"]
    try:
        user_id = UUID(raw)
    except ValueError:
        return JSONResponse({"error": {"code": "invalid_uuid"}}, status_code=400)

    async with tenant_session() as db:
        await db.execute(
            text(
                "UPDATE axon_control.tenant_memberships "
                "SET status = 'suspended' "
                "WHERE tenant_id = :t AND user_id = :u"
            ),
            {"t": principal.tenant_id, "u": user_id},
        )
    _logger.info(
        "tenant_user_deactivated",
        tenant_id=principal.tenant_id,
        user_id=str(user_id),
    )
    return JSONResponse({"user_id": str(user_id), "status": "suspended"})


async def _update_roles(request: Request) -> JSONResponse:
    """PATCH — replace the user's role assignments in the caller's tenant."""
    principal = require_principal()
    _require_user_invite(principal)
    raw = request.path_params["user_id"]
    try:
        user_id = UUID(raw)
    except ValueError:
        return JSONResponse({"error": {"code": "invalid_uuid"}}, status_code=400)

    body = await request.json()
    role_names = body.get("role_names") or []
    if not isinstance(role_names, list):
        return JSONResponse(
            {"error": {"code": "invalid_input", "message": "role_names must be a list"}},
            status_code=400,
        )

    rbac = RbacService()
    async with admin_session() as db:
        # Wipe existing assignments then re-add the requested set.
        await db.execute(
            text(
                "DELETE FROM axon_control.user_roles "
                "WHERE user_id = :u AND tenant_id = :t"
            ),
            {"u": user_id, "t": principal.tenant_id},
        )
        assigned: list[str] = []
        for name in role_names:
            role = await rbac.get_role_by_name(
                db, tenant_id=principal.tenant_id, name=str(name)
            )
            if role is None:
                continue
            await rbac.assign_role(
                db,
                user_id=user_id,
                role_id=role.role_id,
                tenant_id=principal.tenant_id,
                assigned_by=principal.user_id,
            )
            assigned.append(str(name))

    return JSONResponse({"user_id": str(user_id), "roles": assigned})


def _require_user_invite(principal) -> None:
    if (
        "owner" not in principal.role_names
        and "admin" not in principal.role_names
    ):
        raise PermissionDenied("user:invite")


def routes() -> list[Route]:
    return [
        Route("/invite", _invite, methods=["POST"]),
        Route("/", _list_members, methods=["GET"]),
        Route("/{user_id}", _deactivate, methods=["DELETE"]),
        Route("/{user_id}/roles", _update_roles, methods=["PATCH"]),
    ]
