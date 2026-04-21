"""``/api/v1/tenant/api-keys/*`` — M2M key self-service."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from axon_enterprise.api_keys import ApiKeyService
from axon_enterprise.db.session import tenant_session
from axon_enterprise.identity.principal import require_principal
from axon_enterprise.rbac.errors import PermissionDenied


async def _create(request: Request) -> JSONResponse:
    principal = require_principal()
    _require_manage(principal)
    body = await request.json()
    name = str(body.get("name") or "").strip()
    expires_raw = body.get("expires_at")
    expires_at: datetime | None = None
    if expires_raw:
        try:
            expires_at = datetime.fromisoformat(str(expires_raw))
        except ValueError:
            return JSONResponse(
                {"error": {"code": "invalid_input", "message": "bad expires_at"}},
                status_code=400,
            )
    if not name:
        return JSONResponse(
            {"error": {"code": "invalid_input", "message": "name required"}},
            status_code=400,
        )

    svc = ApiKeyService.default()
    async with tenant_session() as db:
        issued = await svc.create(
            db,
            tenant_id=principal.tenant_id,
            name=name,
            created_by=principal.user_id,
            expires_at=expires_at,
        )
    return JSONResponse(
        {
            "api_key_id": str(issued.row.api_key_id),
            "name": issued.row.name,
            "key_prefix": issued.row.key_prefix,
            "raw_key": issued.raw_key,  # ONLY time the raw key is ever returned
            "expires_at": issued.row.expires_at.isoformat()
            if issued.row.expires_at
            else None,
        },
        status_code=201,
    )


async def _list(request: Request) -> JSONResponse:
    principal = require_principal()
    svc = ApiKeyService.default()
    async with tenant_session() as db:
        rows = await svc.list_for_tenant(db, tenant_id=principal.tenant_id)
    return JSONResponse(
        {
            "items": [
                {
                    "api_key_id": str(r.api_key_id),
                    "name": r.name,
                    "key_prefix": r.key_prefix,
                    "created_at": r.created_at.isoformat(),
                    "last_used_at": r.last_used_at.isoformat()
                    if r.last_used_at
                    else None,
                    "expires_at": r.expires_at.isoformat()
                    if r.expires_at
                    else None,
                    "revoked_at": r.revoked_at.isoformat()
                    if r.revoked_at
                    else None,
                }
                for r in rows
            ]
        }
    )


async def _revoke(request: Request) -> JSONResponse:
    principal = require_principal()
    _require_manage(principal)
    raw = request.path_params["api_key_id"]
    try:
        api_key_id = UUID(raw)
    except ValueError:
        return JSONResponse({"error": {"code": "invalid_uuid"}}, status_code=400)

    svc = ApiKeyService.default()
    async with tenant_session() as db:
        await svc.revoke(db, api_key_id=api_key_id, tenant_id=principal.tenant_id)
    return JSONResponse({"api_key_id": str(api_key_id), "status": "revoked"})


def _require_manage(principal) -> None:
    if (
        "owner" not in principal.role_names
        and "admin" not in principal.role_names
    ):
        raise PermissionDenied("api_key:manage")


def routes() -> list[Route]:
    return [
        Route("/", _create, methods=["POST"]),
        Route("/", _list, methods=["GET"]),
        Route("/{api_key_id}", _revoke, methods=["DELETE"]),
    ]
