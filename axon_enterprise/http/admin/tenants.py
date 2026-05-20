"""Admin tenant CRUD."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, text
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from axon_enterprise.db.session import admin_session
from axon_enterprise.http.pagination import OffsetPage, parse_pagination_params
from axon_enterprise.identity.principal import require_principal
from axon_enterprise.metering.models import PricingPlan, TenantSubscription
from axon_enterprise.rbac import seed_builtin_roles

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.http.admin.tenants"
)


async def _create_tenant(request: Request) -> JSONResponse:
    """POST /admin/tenants — provisions tenant row + RBAC roles + subscription."""
    principal = require_principal()
    if "tenant:update" not in principal.role_names and "owner" not in principal.role_names:
        # Coarse admin gate — the operator who calls this must belong to
        # the control-plane admin tenant (typically 'default').
        from axon_enterprise.rbac.errors import PermissionDenied

        raise PermissionDenied("tenant:create")

    body = await request.json()
    slug = str(body.get("slug") or "").strip().lower()
    name = str(body.get("name") or "").strip()
    plan_id = str(body.get("plan_id") or "starter")
    owner_user_id_raw = body.get("owner_user_id")

    if not slug or not name:
        return JSONResponse(
            {"error": {"code": "invalid_input", "message": "slug + name required"}},
            status_code=400,
        )

    async with admin_session() as db:
        # Does a tenant by this slug already exist?
        existing = await db.execute(
            text("SELECT tenant_id FROM axon_admin.tenants WHERE tenant_id = :s"),
            {"s": slug},
        )
        if existing.scalar() is not None:
            return JSONResponse(
                {"error": {"code": "tenant_exists", "message": slug}},
                status_code=409,
            )
        plan = await db.get(PricingPlan, plan_id)
        if plan is None:
            return JSONResponse(
                {"error": {"code": "plan_not_found", "message": plan_id}},
                status_code=404,
            )

        # Create the tenants row (in public schema — owned by the Rust plane).
        await db.execute(
            text(
                "INSERT INTO axon_admin.tenants (tenant_id, name, plan, status) "
                "VALUES (:s, :n, :p, 'active')"
            ),
            {"s": slug, "n": name, "p": plan_id},
        )
        # Seed RBAC built-in roles.
        from uuid import UUID

        owner_uuid = UUID(owner_user_id_raw) if owner_user_id_raw else None
        seeded = await seed_builtin_roles(db, tenant_id=slug, owner_user_id=owner_uuid)

        # Create subscription with initial 30-day billing period.
        now = datetime.now(timezone.utc)
        db.add(
            TenantSubscription(
                tenant_id=slug,
                plan_id=plan_id,
                current_period_start=now,
                current_period_end=now + timedelta(days=30),
            )
        )
        await db.flush()

        _logger.info(
            "tenant_created",
            tenant_id=slug,
            plan_id=plan_id,
            owner_user_id=str(owner_uuid) if owner_uuid else None,
        )
        return JSONResponse(
            {
                "tenant_id": slug,
                "name": name,
                "plan_id": plan_id,
                "status": "active",
                "roles": seeded.as_dict() | {},
            },
            status_code=201,
        )


async def _list_tenants(request: Request) -> JSONResponse:
    """GET /admin/tenants — paginated list with filters."""
    principal = require_principal()
    _require_admin(principal)

    params = dict(request.query_params)
    try:
        limit, offset, _ = parse_pagination_params(params)
    except ValueError as exc:
        return JSONResponse(
            {"error": {"code": "invalid_pagination", "message": str(exc)}},
            status_code=400,
        )
    status_filter = params.get("status")

    async with admin_session() as db:
        stmt = text(
            "SELECT tenant_id, name, plan, status, created_at "
            "FROM axon_admin.tenants "
            + ("WHERE status = :status " if status_filter else "")
            + "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        )
        bind = {"limit": limit, "offset": offset}
        if status_filter:
            bind["status"] = status_filter
        rows = (await db.execute(stmt, bind)).mappings().all()

        count_stmt = text(
            "SELECT COUNT(*) FROM axon_admin.tenants "
            + ("WHERE status = :status" if status_filter else "")
        )
        total = (await db.execute(count_stmt, bind)).scalar_one()

        page = OffsetPage(
            items=list(rows), total=int(total), limit=limit, offset=offset
        )
        return JSONResponse(
            page.to_dict(
                lambda r: {
                    "tenant_id": r["tenant_id"],
                    "name": r["name"],
                    "plan_id": r["plan"],
                    "status": r["status"],
                    "created_at": r["created_at"].isoformat(),
                }
            )
        )


async def _get_tenant(request: Request) -> JSONResponse:
    principal = require_principal()
    _require_admin(principal)
    tenant_id = request.path_params["tenant_id"]
    async with admin_session() as db:
        row = (
            await db.execute(
                text(
                    "SELECT tenant_id, name, plan, status, created_at "
                    "FROM axon_admin.tenants WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).mappings().first()
        if row is None:
            return JSONResponse(
                {"error": {"code": "not_found", "message": tenant_id}},
                status_code=404,
            )
        return JSONResponse(
            {
                "tenant_id": row["tenant_id"],
                "name": row["name"],
                "plan_id": row["plan"],
                "status": row["status"],
                "created_at": row["created_at"].isoformat(),
            }
        )


async def _suspend_tenant(request: Request) -> Response:
    principal = require_principal()
    _require_admin(principal)
    tenant_id = request.path_params["tenant_id"]
    body = await request.json() if await request.body() else {}
    reason = body.get("reason", "")
    async with admin_session() as db:
        updated = await db.execute(
            text(
                "UPDATE axon_admin.tenants SET status = 'suspended' "
                "WHERE tenant_id = :t AND status != 'deleted' "
                "RETURNING tenant_id"
            ),
            {"t": tenant_id},
        )
        if updated.first() is None:
            return JSONResponse(
                {"error": {"code": "not_found", "message": tenant_id}},
                status_code=404,
            )
    _logger.info("tenant_suspended", tenant_id=tenant_id, reason=reason)
    return JSONResponse({"tenant_id": tenant_id, "status": "suspended"})


async def _resume_tenant(request: Request) -> Response:
    principal = require_principal()
    _require_admin(principal)
    tenant_id = request.path_params["tenant_id"]
    async with admin_session() as db:
        updated = await db.execute(
            text(
                "UPDATE axon_admin.tenants SET status = 'active' "
                "WHERE tenant_id = :t AND status = 'suspended' "
                "RETURNING tenant_id"
            ),
            {"t": tenant_id},
        )
        if updated.first() is None:
            return JSONResponse(
                {"error": {"code": "not_suspended", "message": tenant_id}},
                status_code=409,
            )
    _logger.info("tenant_resumed", tenant_id=tenant_id)
    return JSONResponse({"tenant_id": tenant_id, "status": "active"})


def _require_admin(principal) -> None:
    """Coarse gate — caller must belong to the control-plane admin tenant."""
    from axon_enterprise.rbac.errors import PermissionDenied

    if principal.tenant_id != "default" and "owner" not in principal.role_names:
        raise PermissionDenied("admin tenant membership required")


def routes() -> list[Route]:
    return [
        Route("/", _create_tenant, methods=["POST"]),
        Route("/", _list_tenants, methods=["GET"]),
        Route("/{tenant_id}", _get_tenant, methods=["GET"]),
        Route("/{tenant_id}/suspend", _suspend_tenant, methods=["POST"]),
        Route("/{tenant_id}/resume", _resume_tenant, methods=["POST"]),
    ]
