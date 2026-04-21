"""``/api/v1/tenant/compliance/*`` — GDPR/CCPA request endpoints.

10.l scope: accept the request, enqueue a ticket, emit the
``compliance:*`` audit event, return 202 + ``ticket_id``. The
``ComplianceWorker`` running as its own Deployment picks the
ticket up, builds the bundle (SAR) or runs the soft-delete +
anonymize flow (erasure), and parks the result in the blob store.

Clients poll ``GET /api/v1/tenant/compliance/{request_id}`` for
status + (when complete) a presigned download URL.

Handlers run under ``tenant_session`` so audit writes inherit the
caller's tenant via the 10.g adapter.
"""

from __future__ import annotations

from uuid import UUID

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from axon_enterprise.compliance import (
    ComplianceRequestNotFound,
    ComplianceService,
    LegalHoldActive,
)
from axon_enterprise.compliance.s3_blob_store import build_blob_store
from axon_enterprise.config import get_settings
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

    svc = ComplianceService.default()
    async with admin_session() as db:
        ticket = await svc.file_export(
            db,
            tenant_id=principal.tenant_id,
            subject_email=subject_email,
            requested_by=principal.user_id,
        )
    return JSONResponse(
        {
            "ticket_id": str(ticket.request_id),
            "request_id": str(ticket.request_id),
            "subject_email": subject_email,
            "sla_days": get_settings().compliance.erasure_anonymize_sla_days,
            "status": "queued",
        },
        status_code=202,
    )


async def _erasure_request(request: Request) -> JSONResponse:
    """POST — GDPR Right to Erasure (Art. 17) request."""
    principal = require_principal()
    body = await request.json() if await request.body() else {}
    subject_email = str(body.get("subject_email") or "").strip().lower()
    reason = body.get("reason")
    if not subject_email:
        return JSONResponse(
            {"error": {"code": "invalid_input", "message": "subject_email required"}},
            status_code=400,
        )

    svc = ComplianceService.default()
    async with admin_session() as db:
        try:
            ticket = await svc.file_erasure(
                db,
                tenant_id=principal.tenant_id,
                subject_email=subject_email,
                reason=reason,
                requested_by=principal.user_id,
            )
        except LegalHoldActive as exc:
            return JSONResponse(
                {
                    "error": {
                        "code": "compliance.legal_hold_active",
                        "message": str(exc),
                    }
                },
                status_code=409,
            )

    settings = get_settings().compliance
    return JSONResponse(
        {
            "ticket_id": str(ticket.request_id),
            "request_id": str(ticket.request_id),
            "subject_email": subject_email,
            "soft_delete_window_days": settings.erasure_soft_delete_days,
            "sla_days": settings.erasure_anonymize_sla_days,
            "status": "queued",
        },
        status_code=202,
    )


async def _ticket_status(request: Request) -> JSONResponse:
    """GET — status + artefact link for a single ticket."""
    principal = require_principal()
    raw = request.path_params["request_id"]
    try:
        request_id = UUID(raw)
    except ValueError:
        return JSONResponse(
            {"error": {"code": "invalid_uuid"}}, status_code=400
        )

    tickets = ComplianceService.default().tickets
    async with admin_session() as db:
        try:
            row = await tickets.get(
                db, request_id=request_id, tenant_id=principal.tenant_id
            )
        except ComplianceRequestNotFound:
            return JSONResponse(
                {"error": {"code": "compliance.request_not_found"}},
                status_code=404,
            )

    download_url: str | None = None
    if row.status == "completed" and row.artefact_uri:
        blob = build_blob_store()
        settings = get_settings().compliance
        # artefact_uri is the raw URI; derive the blob key by
        # stripping the store-specific prefix.
        key = _key_from_uri(row.artefact_uri)
        if key is not None:
            download_url = await blob.signed_url(
                key=key, ttl_seconds=settings.blob_signed_url_ttl_seconds
            )

    return JSONResponse(
        {
            "ticket_id": str(row.request_id),
            "kind": row.kind,
            "status": row.status,
            "subject_email": row.subject_email,
            "scheduled_for": row.scheduled_for.isoformat(),
            "claimed_at": row.claimed_at.isoformat()
            if row.claimed_at
            else None,
            "completed_at": row.completed_at.isoformat()
            if row.completed_at
            else None,
            "artefact_sha256": row.artefact_sha256,
            "artefact_size_bytes": row.artefact_size_bytes,
            "download_url": download_url,
            "error_message": row.error_message,
        }
    )


async def _list_tickets(request: Request) -> JSONResponse:
    """GET — list tickets filed against the caller's tenant."""
    principal = require_principal()
    tickets = ComplianceService.default().tickets
    async with admin_session() as db:
        rows = await tickets.list_for_tenant(
            db, tenant_id=principal.tenant_id, limit=100
        )
    return JSONResponse(
        {
            "items": [
                {
                    "ticket_id": str(r.request_id),
                    "kind": r.kind,
                    "status": r.status,
                    "subject_email": r.subject_email,
                    "created_at": r.created_at.isoformat(),
                    "completed_at": r.completed_at.isoformat()
                    if r.completed_at
                    else None,
                }
                for r in rows
            ]
        }
    )


def _key_from_uri(uri: str) -> str | None:
    """Recover the blob key from the artefact URI.

    The LocalBlobStore returns ``file:///.../compliance/<key>``;
    S3 returns ``s3://<bucket>/<prefix>/<key>``. Extract the
    trailing path component set we stored against.
    """
    if uri.startswith("s3://"):
        parts = uri[len("s3://") :].split("/", 1)
        if len(parts) != 2:
            return None
        settings = get_settings().compliance
        prefix = (settings.blob_s3_prefix or "").strip("/")
        key = parts[1]
        if prefix and key.startswith(prefix + "/"):
            key = key[len(prefix) + 1 :]
        return key
    if uri.startswith("file://"):
        settings = get_settings().compliance
        root = settings.blob_local_path.as_uri().rstrip("/")
        if uri.startswith(root + "/"):
            return uri[len(root) + 1 :]
    return None


def routes() -> list[Route]:
    return [
        Route("/export", _export_request, methods=["POST"]),
        Route("/erase", _erasure_request, methods=["POST"]),
        Route("/", _list_tickets, methods=["GET"]),
        Route("/{request_id}", _ticket_status, methods=["GET"]),
    ]
