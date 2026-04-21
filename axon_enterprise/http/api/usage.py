"""``/api/v1/tenant/usage`` + ``/invoices`` — read-only dashboards."""

from __future__ import annotations

from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from axon_enterprise.db.session import tenant_session
from axon_enterprise.identity.principal import require_principal
from axon_enterprise.metering import MeteringService
from axon_enterprise.metering.models import Invoice


async def _current_usage(request: Request) -> JSONResponse:
    principal = require_principal()
    svc = MeteringService.default()
    async with tenant_session() as db:
        totals = await svc.current_period_usage(db, tenant_id=principal.tenant_id)
    return JSONResponse(
        {
            "tenant_id": principal.tenant_id,
            "totals": {m.value: q for m, q in totals.items()},
        }
    )


async def _list_invoices(request: Request) -> JSONResponse:
    principal = require_principal()
    async with tenant_session() as db:
        rows = list(
            (
                await db.execute(
                    select(Invoice)
                    .where(Invoice.tenant_id == principal.tenant_id)
                    .order_by(Invoice.period_start.desc())
                )
            ).scalars()
        )
    return JSONResponse(
        {
            "items": [
                {
                    "invoice_id": str(r.invoice_id),
                    "period_start": r.period_start.isoformat(),
                    "period_end": r.period_end.isoformat(),
                    "currency": r.currency,
                    "subtotal_cents": r.subtotal_cents,
                    "tax_cents": r.tax_cents,
                    "total_cents": r.total_cents,
                    "status": r.status,
                    "stripe_invoice_id": r.stripe_invoice_id,
                    "issued_at": r.issued_at.isoformat()
                    if r.issued_at
                    else None,
                    "paid_at": r.paid_at.isoformat() if r.paid_at else None,
                    "line_items": r.line_items,
                }
                for r in rows
            ]
        }
    )


def routes() -> list[Route]:
    return [
        Route("/", _current_usage, methods=["GET"]),
        Route("/invoices", _list_invoices, methods=["GET"]),
    ]
