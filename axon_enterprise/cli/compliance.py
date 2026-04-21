"""``axon-enterprise compliance ...`` — GDPR / CCPA / SOC 2 subcommands.

Operator surface area:

    compliance export SUBJECT_EMAIL --tenant TENANT
    compliance erase SUBJECT_EMAIL --tenant TENANT [--reason TEXT]
    compliance status REQUEST_ID
    compliance list-tickets --tenant TENANT
    compliance legal-hold apply SUBJECT_EMAIL --tenant TENANT --matter TEXT
    compliance legal-hold release HOLD_ID [--reason TEXT]
    compliance evidence-bundle --tenant TENANT --from DATE --to DATE
    compliance run-worker                # long-running process
"""

from __future__ import annotations

import asyncio
import json
import signal
from datetime import datetime, timezone
from uuid import UUID

import typer

from axon_enterprise.compliance import ComplianceService, ComplianceWorker
from axon_enterprise.compliance.legal_holds import LegalHoldService
from axon_enterprise.db.session import admin_session

app = typer.Typer()

legal_hold_app = typer.Typer()
app.add_typer(legal_hold_app, name="legal-hold", help="Litigation-hold management.")


@app.command("export")
def export(
    subject_email: str = typer.Argument(..., help="Subject's email address."),
    tenant: str = typer.Option(..., "--tenant", help="Tenant id."),
) -> None:
    """File a SAR export ticket + print the ticket id."""
    ticket = asyncio.run(_file_export(tenant=tenant, subject_email=subject_email))
    typer.echo(
        json.dumps(
            {
                "ticket_id": str(ticket.request_id),
                "scheduled_for": ticket.scheduled_for.isoformat(),
            },
            indent=2,
        )
    )


@app.command("erase")
def erase(
    subject_email: str = typer.Argument(..., help="Subject's email address."),
    tenant: str = typer.Option(..., "--tenant", help="Tenant id."),
    reason: str | None = typer.Option(None, "--reason"),
) -> None:
    """File a Right to Erasure ticket."""
    ticket = asyncio.run(
        _file_erasure(
            tenant=tenant, subject_email=subject_email, reason=reason
        )
    )
    typer.echo(
        json.dumps(
            {
                "ticket_id": str(ticket.request_id),
                "scheduled_for": ticket.scheduled_for.isoformat(),
            },
            indent=2,
        )
    )


@app.command("status")
def status(
    request_id: str = typer.Argument(..., help="Ticket id from export/erase."),
    tenant: str = typer.Option(..., "--tenant", help="Tenant id."),
) -> None:
    """Print the current status of a compliance ticket."""
    asyncio.run(_status(tenant=tenant, request_id=UUID(request_id)))


@app.command("list-tickets")
def list_tickets(
    tenant: str = typer.Option(..., "--tenant", help="Tenant id."),
    limit: int = typer.Option(50, help="Rows to show."),
) -> None:
    asyncio.run(_list_tickets(tenant=tenant, limit=limit))


@app.command("evidence-bundle")
def evidence_bundle(
    tenant: str = typer.Option(..., "--tenant"),
    from_date: str = typer.Option(..., "--from", help="ISO-8601 date."),
    to_date: str = typer.Option(..., "--to", help="ISO-8601 date."),
) -> None:
    """Generate a SOC 2 evidence bundle for a tenant / period."""
    start = _parse_period_bound(from_date)
    end = _parse_period_bound(to_date)
    result = asyncio.run(
        _evidence(tenant=tenant, period_start=start, period_end=end)
    )
    typer.echo(
        json.dumps(
            {
                "uri": result.uri,
                "sha256": result.sha256_hex,
                "size_bytes": result.size_bytes,
            },
            indent=2,
        )
    )


@app.command("run-worker")
def run_worker() -> None:
    """Long-running poller that drains the compliance_requests queue."""
    asyncio.run(_run_worker())


# ── legal-hold subcommands ──────────────────────────────────────────


@legal_hold_app.command("apply")
def legal_hold_apply(
    subject_email: str = typer.Argument(...),
    tenant: str = typer.Option(..., "--tenant"),
    matter: str = typer.Option(..., "--matter"),
) -> None:
    hold = asyncio.run(
        _legal_hold_apply(
            tenant=tenant, subject_email=subject_email, matter=matter
        )
    )
    typer.echo(
        json.dumps(
            {
                "hold_id": str(hold.hold_id),
                "subject_email": hold.subject_email,
                "applied_at": hold.applied_at.isoformat(),
            },
            indent=2,
        )
    )


@legal_hold_app.command("release")
def legal_hold_release(
    hold_id: str = typer.Argument(...),
    reason: str | None = typer.Option(None, "--reason"),
) -> None:
    asyncio.run(_legal_hold_release(hold_id=UUID(hold_id), reason=reason))
    typer.echo(json.dumps({"hold_id": hold_id, "released": True}, indent=2))


# ── Async implementations ──────────────────────────────────────────


async def _file_export(*, tenant: str, subject_email: str):
    svc = ComplianceService.default()
    async with admin_session() as db:
        return await svc.file_export(
            db, tenant_id=tenant, subject_email=subject_email
        )


async def _file_erasure(*, tenant: str, subject_email: str, reason: str | None):
    svc = ComplianceService.default()
    async with admin_session() as db:
        return await svc.file_erasure(
            db,
            tenant_id=tenant,
            subject_email=subject_email,
            reason=reason,
        )


async def _status(*, tenant: str, request_id: UUID) -> None:
    svc = ComplianceService.default()
    async with admin_session() as db:
        row = await svc.tickets.get(
            db, request_id=request_id, tenant_id=tenant
        )
    typer.echo(
        json.dumps(
            {
                "ticket_id": str(row.request_id),
                "kind": row.kind,
                "status": row.status,
                "subject_email": row.subject_email,
                "scheduled_for": row.scheduled_for.isoformat(),
                "completed_at": row.completed_at.isoformat()
                if row.completed_at
                else None,
                "artefact_uri": row.artefact_uri,
                "artefact_sha256": row.artefact_sha256,
                "error_message": row.error_message,
            },
            indent=2,
        )
    )


async def _list_tickets(*, tenant: str, limit: int) -> None:
    svc = ComplianceService.default()
    async with admin_session() as db:
        rows = await svc.tickets.list_for_tenant(
            db, tenant_id=tenant, limit=limit
        )
    typer.echo(
        json.dumps(
            [
                {
                    "ticket_id": str(r.request_id),
                    "kind": r.kind,
                    "status": r.status,
                    "subject_email": r.subject_email,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ],
            indent=2,
        )
    )


async def _evidence(*, tenant: str, period_start, period_end):
    svc = ComplianceService.default()
    async with admin_session() as db:
        return await svc.generate_evidence_bundle(
            db,
            tenant_id=tenant,
            period_start=period_start,
            period_end=period_end,
        )


async def _legal_hold_apply(*, tenant: str, subject_email: str, matter: str):
    svc = LegalHoldService.default()
    async with admin_session() as db:
        return await svc.apply(
            db,
            tenant_id=tenant,
            subject_email=subject_email,
            matter=matter,
        )


async def _legal_hold_release(*, hold_id: UUID, reason: str | None) -> None:
    svc = LegalHoldService.default()
    async with admin_session() as db:
        await svc.release(db, hold_id=hold_id, reason=reason)


async def _run_worker() -> None:
    worker = ComplianceWorker.default()
    stop = asyncio.Event()

    def _stop_handler(*_):
        stop.set()

    try:
        signal.signal(signal.SIGINT, _stop_handler)
        signal.signal(signal.SIGTERM, _stop_handler)
    except (ValueError, AttributeError):
        # Signals unavailable (Windows event loop, test harness).
        pass

    async def _ticker() -> None:
        while not stop.is_set():
            await worker.promote_due_purges()
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=worker.settings.worker_poll_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass

    await asyncio.gather(
        worker.run_forever(stop=stop),
        _ticker(),
    )


def _parse_period_bound(raw: str) -> datetime:
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise typer.BadParameter(f"expected ISO-8601 date/datetime: {raw!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
