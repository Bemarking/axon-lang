"""``axon-enterprise audit ...`` — audit chain verification."""

from __future__ import annotations

import asyncio
import json

import typer
from sqlalchemy import text

from axon_enterprise.audit import AuditService
from axon_enterprise.db.session import admin_session

app = typer.Typer()


@app.command("verify")
def verify(
    tenant_id: str | None = typer.Option(
        None,
        help=(
            "Tenant to verify. Pass none to walk every tenant in the DB — "
            "typical cron invocation."
        ),
    ),
    exit_nonzero_on_break: bool = typer.Option(
        True,
        "--exit-nonzero/--exit-zero",
        help="Return non-zero when any chain is broken (scripts + cron).",
    ),
) -> None:
    """Recompute hashes for every event; report divergences."""

    async def run() -> None:
        svc = AuditService()
        async with admin_session() as db:
            if tenant_id:
                tenants = [tenant_id]
            else:
                rows = (
                    await db.execute(text("SELECT tenant_id FROM axon_admin.tenants"))
                ).all()
                tenants = [r[0] for r in rows]

            reports = []
            broken_any = False
            for tid in tenants:
                report = await svc.verify_chain(db, tenant_id=tid)
                reports.append(
                    {
                        "tenant_id": report.tenant_id,
                        "ok": report.ok,
                        "checked": report.checked,
                        "broken_at": report.broken_at,
                        "reason": report.reason,
                    }
                )
                if not report.ok:
                    broken_any = True

        typer.echo(json.dumps(reports, indent=2))
        if broken_any and exit_nonzero_on_break:
            raise typer.Exit(code=1)

    asyncio.run(run())
