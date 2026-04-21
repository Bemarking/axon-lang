"""``/webhooks/stripe`` — inbound Stripe billing event sink.

The endpoint is PUBLIC at the AuthMiddleware layer — authentication
is re-implemented via ``Stripe-Signature`` HMAC verification
against the shared webhook secret. Without a valid signature the
handler returns 400 and records nothing.

Event routing
-------------
We intentionally handle a small, well-defined set of events:

    invoice.finalized         → Invoice.status := FINALIZED
    invoice.paid              → Invoice.status := PAID + paid_at
    invoice.payment_failed    → Invoice.status := FAILED
    invoice.voided            → Invoice.status := VOID

Unknown types are acknowledged with 204 so Stripe stops retrying,
but otherwise ignored — if we later decide to consume a new event,
adding the branch here is the only change needed.

Idempotency
-----------
Stripe guarantees at-least-once delivery. ``event["id"]`` is the
client-side dedupe key. We don't persist a dedupe table in this
phase (the state transitions are idempotent — ``PAID`` → ``PAID``
is a no-op), but 10.l adds a ``processed_webhooks`` row to close
the loop on side-effecting handlers like ``invoice.voided``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from axon_enterprise.db.session import admin_session
from axon_enterprise.metering.errors import StripeIntegrationError
from axon_enterprise.metering.models import Invoice, InvoiceStatus
from axon_enterprise.metering.stripe_client import StripeClient

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.http.webhooks.stripe"
)


async def _receive(request: Request) -> Response:
    """Verify signature, route event, return 204/400/500."""
    signature = request.headers.get("Stripe-Signature") or ""
    payload = await request.body()

    client = StripeClient.from_settings()
    try:
        event = client.verify_webhook(
            payload=payload, signature_header=signature
        )
    except StripeIntegrationError as exc:
        _logger.warning("stripe_webhook_signature_rejected", error=str(exc))
        return JSONResponse(
            {"error": {"code": "webhook.signature", "message": str(exc)}},
            status_code=400,
        )

    event_id = str(event.get("id") or "")
    event_type = str(event.get("type") or "")
    data_object = (event.get("data") or {}).get("object") or {}

    _logger.info(
        "stripe_webhook_received",
        event_id=event_id,
        event_type=event_type,
    )

    async with admin_session() as db:
        handled = await _route(db, event_type=event_type, data=data_object)

    if not handled:
        return Response(status_code=204)
    return JSONResponse(
        {"event_id": event_id, "event_type": event_type, "handled": True}
    )


async def _route(db, *, event_type: str, data: dict) -> bool:
    """Dispatch known event types to their state transition."""
    stripe_invoice_id = str(data.get("id") or "")
    if not stripe_invoice_id or not event_type.startswith("invoice."):
        return False

    row = await db.scalar(
        select(Invoice).where(Invoice.stripe_invoice_id == stripe_invoice_id)
    )
    if row is None:
        _logger.info(
            "stripe_webhook_invoice_unknown",
            stripe_invoice_id=stripe_invoice_id,
            event_type=event_type,
        )
        return False

    now = datetime.now(timezone.utc)
    match event_type:
        case "invoice.finalized":
            row.status = InvoiceStatus.FINALIZED.value
        case "invoice.paid":
            row.status = InvoiceStatus.PAID.value
            row.paid_at = now
        case "invoice.payment_failed":
            row.status = InvoiceStatus.FAILED.value
        case "invoice.voided":
            row.status = InvoiceStatus.VOID.value
        case _:
            return False
    await db.flush()
    _logger.info(
        "stripe_webhook_invoice_updated",
        invoice_id=str(row.invoice_id),
        stripe_invoice_id=stripe_invoice_id,
        status=row.status,
    )
    return True


def routes() -> list[Route]:
    return [Route("/", _receive, methods=["POST"])]
