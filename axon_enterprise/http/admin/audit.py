"""Admin audit access — verify chain + list events cross-tenant."""

from __future__ import annotations

import base64
from datetime import datetime

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from axon_enterprise.audit import AuditEventType, AuditService
from axon_enterprise.db.session import admin_session
from axon_enterprise.http.pagination import parse_pagination_params
from axon_enterprise.identity.principal import require_principal
from axon_enterprise.rbac.errors import PermissionDenied


async def _verify_chain(request: Request) -> JSONResponse:
    _require_admin(require_principal())
    tenant_id = request.path_params["tenant_id"]
    svc = AuditService()
    async with admin_session() as db:
        report = await svc.verify_chain(db, tenant_id=tenant_id)
    return JSONResponse(
        {
            "tenant_id": report.tenant_id,
            "ok": report.ok,
            "checked": report.checked,
            "broken_at": report.broken_at,
            "reason": report.reason,
        }
    )


async def _list_events(request: Request) -> JSONResponse:
    _require_admin(require_principal())
    tenant_id = request.path_params["tenant_id"]
    params = dict(request.query_params)
    try:
        limit, _, _ = parse_pagination_params(params, default_limit=100, max_limit=1000)
    except ValueError as exc:
        return JSONResponse(
            {"error": {"code": "invalid_pagination", "message": str(exc)}},
            status_code=400,
        )

    event_types: list[AuditEventType] = []
    raw_types = params.get("event_type")
    if raw_types:
        for raw in raw_types.split(","):
            try:
                event_types.append(AuditEventType(raw.strip()))
            except ValueError:
                return JSONResponse(
                    {
                        "error": {
                            "code": "unknown_event_type",
                            "message": raw,
                        }
                    },
                    status_code=400,
                )

    since = _parse_iso(params.get("since"))
    until = _parse_iso(params.get("until"))

    svc = AuditService()
    async with admin_session() as db:
        events = await svc.list_events(
            db,
            tenant_id=tenant_id,
            event_types=event_types or None,
            since=since,
            until=until,
            limit=limit,
        )
    return JSONResponse(
        {
            "items": [_serialise_event(e) for e in events],
            "count": len(events),
        }
    )


def _serialise_event(event) -> dict:
    return {
        "event_id": str(event.event_id),
        "tenant_id": event.tenant_id,
        "sequence_number": event.sequence_number,
        "event_type": event.event_type,
        "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
        "actor_email": event.actor_email,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "action": event.action,
        "status": event.status,
        "ip_address": event.ip_address,
        "user_agent": event.user_agent,
        "details": event.details,
        "prev_hash": base64.urlsafe_b64encode(bytes(event.prev_hash))
        .rstrip(b"=")
        .decode("ascii"),
        "event_hash": base64.urlsafe_b64encode(bytes(event.event_hash))
        .rstrip(b"=")
        .decode("ascii"),
        "created_at": event.created_at.isoformat(),
    }


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _require_admin(principal) -> None:
    if principal.tenant_id != "default" and "owner" not in principal.role_names:
        raise PermissionDenied("admin audit access")


def routes() -> list[Route]:
    return [
        Route(
            "/{tenant_id}/verify", _verify_chain, methods=["POST"]
        ),
        Route("/{tenant_id}/events", _list_events, methods=["GET"]),
    ]
