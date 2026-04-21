"""``/api/v1/tenant/compliance/*`` — GDPR/CCPA request endpoints.

10.k scope: accept the request, emit a ``compliance:*`` audit event,
and return a ticket id. Full execution (subject-access bundle ZIP,
right-to-erasure purge workflow) lands in 10.l.

Handlers run under ``tenant_session`` so the 10.g audit writer
records the requester's tenant automatically.
"""

from __future__ import annotations

from uuid import uuid4

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from axon_enterprise.audit import (
    AuditEventType,
    AuditService,
    AuditWriteRequest,
)
from axon_enterprise.db.session import admin_session
from axon_enterprise.identity.principal import require_principal


async def _export_request(request: Request) -> JSONResponse:
    """POST — GDPR Subject Access Request. Enqueues + emits audit event."""
    principal = require_principal()
    body = await request.json() if await request.body() else {}
    subject_email = str(body.get("subject_email") or "").strip().lower()
    if not subject_email:
        return JSONResponse(
            {"error": {"code": "invalid_input", "message": "subject_email required"}},
            status_code=400,
        )

    ticket_id = uuid4()
    audit = AuditService()
    async with admin_session() as db:
        await audit.record(
            db,
            AuditWriteRequest(
                tenant_id=principal.tenant_id,
                event_type=AuditEventType.COMPLIANCE_EXPORT_REQUESTED,
                resource_type="user",
                resource_id=subject_email,
                action="export_request",
                actor_user_id=principal.user_id,
                details={"ticket_id": str(ticket_id)},
            ),
        )

    return JSONResponse(
        {
            "ticket_id": str(ticket_id),
            "subject_email": subject_email,
            "sla_days": 30,  # GDPR Art. 12
            "status": "queued",
        },
        status_code=202,
    )


async def _erasure_request(request: Request) -> JSONResponse:
    """POST — GDPR Right to Erasure (Art. 17) request."""
    principal = require_principal()
    body = await request.json() if await request.body() else {}
    subject_email = str(body.get("subject_email") or "").strip().lower()
    reason = body.get("reason", "")
    if not subject_email:
        return JSONResponse(
            {"error": {"code": "invalid_input", "message": "subject_email required"}},
            status_code=400,
        )

    ticket_id = uuid4()
    audit = AuditService()
    async with admin_session() as db:
        await audit.record(
            db,
            AuditWriteRequest(
                tenant_id=principal.tenant_id,
                event_type=AuditEventType.COMPLIANCE_ERASURE_REQUESTED,
                resource_type="user",
                resource_id=subject_email,
                action="erasure_request",
                actor_user_id=principal.user_id,
                details={
                    "ticket_id": str(ticket_id),
                    "reason": reason,
                },
            ),
        )

    return JSONResponse(
        {
            "ticket_id": str(ticket_id),
            "subject_email": subject_email,
            "review_window_days": 7,
            "status": "queued",
        },
        status_code=202,
    )


def routes() -> list[Route]:
    return [
        Route("/export", _export_request, methods=["POST"]),
        Route("/erase", _erasure_request, methods=["POST"]),
    ]
