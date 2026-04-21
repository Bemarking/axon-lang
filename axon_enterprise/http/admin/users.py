"""Admin user management — invite / list / deactivate."""

from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from axon_enterprise.db.session import admin_session
from axon_enterprise.http.pagination import OffsetPage, parse_pagination_params
from axon_enterprise.identity import AuthService
from axon_enterprise.identity.models import User, UserStatus
from axon_enterprise.identity.principal import require_principal
from axon_enterprise.rbac.errors import PermissionDenied

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.http.admin.users"
)


async def _create_user(request: Request) -> JSONResponse:
    _require_admin(require_principal())
    body = await request.json()
    email = str(body.get("email") or "").strip()
    password = str(body.get("password") or "")
    display_name = body.get("display_name")

    auth = AuthService.default()
    async with admin_session() as db:
        user = await auth.register(
            db,
            email=email,
            password=password,
            display_name=display_name,
        )
        return JSONResponse(
            {
                "user_id": str(user.user_id),
                "email": user.email,
                "display_name": user.display_name,
                "status": user.status,
            },
            status_code=201,
        )


async def _list_users(request: Request) -> JSONResponse:
    _require_admin(require_principal())
    params = dict(request.query_params)
    try:
        limit, offset, _ = parse_pagination_params(params)
    except ValueError as exc:
        return JSONResponse(
            {"error": {"code": "invalid_pagination", "message": str(exc)}},
            status_code=400,
        )

    async with admin_session() as db:
        from sqlalchemy import func as sql_func

        stmt = (
            select(User)
            .order_by(User.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list((await db.execute(stmt)).scalars())
        total_row = await db.execute(select(sql_func.count(User.user_id)))
        total = int(total_row.scalar_one())

        page = OffsetPage(items=rows, total=total, limit=limit, offset=offset)
        return JSONResponse(
            page.to_dict(
                lambda u: {
                    "user_id": str(u.user_id),
                    "email": u.email,
                    "display_name": u.display_name,
                    "status": u.status,
                    "email_verified": u.email_verified,
                    "last_login_at": u.last_login_at.isoformat()
                    if u.last_login_at
                    else None,
                }
            )
        )


async def _deactivate_user(request: Request) -> JSONResponse:
    _require_admin(require_principal())
    user_id_raw = request.path_params["user_id"]
    try:
        user_id = UUID(user_id_raw)
    except ValueError:
        return JSONResponse(
            {"error": {"code": "invalid_uuid", "message": user_id_raw}},
            status_code=400,
        )
    async with admin_session() as db:
        user = await db.get(User, user_id)
        if user is None:
            return JSONResponse(
                {"error": {"code": "not_found", "message": str(user_id)}},
                status_code=404,
            )
        user.status = UserStatus.SUSPENDED.value
        await db.flush()
    _logger.info("user_deactivated", user_id=str(user_id))
    return JSONResponse({"user_id": str(user_id), "status": "suspended"})


def _require_admin(principal) -> None:
    if "owner" not in principal.role_names and "admin" not in principal.role_names:
        raise PermissionDenied("user:update")


def routes() -> list[Route]:
    return [
        Route("/", _create_user, methods=["POST"]),
        Route("/", _list_users, methods=["GET"]),
        Route("/{user_id}", _deactivate_user, methods=["DELETE"]),
    ]
