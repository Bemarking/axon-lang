"""``axon-enterprise tenant ...`` subcommands."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import typer
from sqlalchemy import text

from axon_enterprise.db.session import admin_session
from axon_enterprise.metering.models import PricingPlan, TenantSubscription
from axon_enterprise.rbac import seed_builtin_roles

app = typer.Typer()


@app.command("create")
def create(
    slug: str = typer.Option(..., help="URL-safe unique identifier for the tenant."),
    name: str = typer.Option(..., help="Human-readable display name."),
    plan: str = typer.Option("starter", help="Pricing plan id."),
    owner_user_id: str | None = typer.Option(
        None,
        help="User UUID to assign the built-in 'owner' role to.",
    ),
) -> None:
    """Provision a new tenant row + RBAC roles + subscription."""

    async def run() -> None:
        async with admin_session() as db:
            existing = (
                await db.execute(
                    text(
                        "SELECT 1 FROM axon_admin.tenants WHERE tenant_id = :s"
                    ),
                    {"s": slug},
                )
            ).scalar()
            if existing:
                typer.secho(
                    f"tenant {slug!r} already exists", fg=typer.colors.RED
                )
                raise typer.Exit(code=1)
            plan_row = await db.get(PricingPlan, plan)
            if plan_row is None:
                typer.secho(
                    f"plan {plan!r} not found", fg=typer.colors.RED
                )
                raise typer.Exit(code=1)

            await db.execute(
                text(
                    "INSERT INTO axon_admin.tenants "
                    "(tenant_id, name, plan, status) VALUES (:s, :n, :p, 'active')"
                ),
                {"s": slug, "n": name, "p": plan},
            )

            owner_uuid = UUID(owner_user_id) if owner_user_id else None
            seeded = await seed_builtin_roles(
                db, tenant_id=slug, owner_user_id=owner_uuid
            )

            now = datetime.now(timezone.utc)
            db.add(
                TenantSubscription(
                    tenant_id=slug,
                    plan_id=plan,
                    current_period_start=now,
                    current_period_end=now + timedelta(days=30),
                )
            )
            await db.flush()

        typer.echo(
            json.dumps(
                {
                    "tenant_id": slug,
                    "plan_id": plan,
                    "roles": {k: str(v) for k, v in seeded.as_dict().items()},
                },
                indent=2,
            )
        )

    asyncio.run(run())


@app.command("list")
def list_tenants(
    status: str | None = typer.Option(None, help="Filter by status."),
    limit: int = typer.Option(50, min=1, max=500),
) -> None:
    """Print every tenant matching the filter."""

    async def run() -> None:
        async with admin_session() as db:
            sql = (
                "SELECT tenant_id, name, plan, status, created_at "
                "FROM axon_admin.tenants "
                + ("WHERE status = :status " if status else "")
                + "ORDER BY created_at DESC LIMIT :limit"
            )
            bind = {"limit": limit}
            if status:
                bind["status"] = status
            rows = (await db.execute(text(sql), bind)).mappings().all()
            typer.echo(
                json.dumps(
                    [
                        {
                            "tenant_id": r["tenant_id"],
                            "name": r["name"],
                            "plan": r["plan"],
                            "status": r["status"],
                            "created_at": r["created_at"].isoformat(),
                        }
                        for r in rows
                    ],
                    indent=2,
                )
            )

    asyncio.run(run())


@app.command("suspend")
def suspend(
    slug: str = typer.Argument(..., help="Tenant to suspend."),
    reason: str = typer.Option("", help="Audit-log reason."),
) -> None:
    """Flag the tenant as suspended — blocks new writes via the Rust plane."""

    async def run() -> None:
        async with admin_session() as db:
            updated = await db.execute(
                text(
                    "UPDATE axon_admin.tenants SET status='suspended' "
                    "WHERE tenant_id=:s AND status != 'deleted' RETURNING tenant_id"
                ),
                {"s": slug},
            )
            if updated.first() is None:
                typer.secho(f"tenant {slug!r} not found", fg=typer.colors.RED)
                raise typer.Exit(code=1)
        typer.secho(
            f"suspended {slug} (reason: {reason or 'n/a'})", fg=typer.colors.YELLOW
        )

    asyncio.run(run())


@app.command("resume")
def resume(slug: str = typer.Argument(..., help="Tenant to reactivate.")) -> None:
    """Flip a suspended tenant back to active."""

    async def run() -> None:
        async with admin_session() as db:
            updated = await db.execute(
                text(
                    "UPDATE axon_admin.tenants SET status='active' "
                    "WHERE tenant_id=:s AND status='suspended' RETURNING tenant_id"
                ),
                {"s": slug},
            )
            if updated.first() is None:
                typer.secho(
                    f"tenant {slug!r} not suspended", fg=typer.colors.RED
                )
                raise typer.Exit(code=1)
        typer.secho(f"resumed {slug}", fg=typer.colors.GREEN)

    asyncio.run(run())
