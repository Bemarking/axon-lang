"""``axon-enterprise user ...`` — user lifecycle commands."""

from __future__ import annotations

import asyncio
import json
import sys
from uuid import UUID

import typer
from sqlalchemy import select

from axon_enterprise.db.session import admin_session
from axon_enterprise.identity import AuthService
from axon_enterprise.identity.models import User, UserStatus

app = typer.Typer()


@app.command("create")
def create(
    email: str = typer.Option(..., help="New user email."),
    display_name: str | None = typer.Option(None, help="Human-readable name."),
    password_from_stdin: bool = typer.Option(
        False,
        "--password-stdin",
        help="Read the password from stdin (never pass via --password).",
    ),
) -> None:
    """Register a user via AuthService.register. Password never goes on argv."""
    if not password_from_stdin:
        typer.secho(
            "Refusing to accept password from argv. Use --password-stdin.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)
    password = sys.stdin.readline().strip()
    if not password:
        typer.secho("No password supplied on stdin.", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    async def run() -> None:
        auth = AuthService.default()
        async with admin_session() as db:
            user = await auth.register(
                db,
                email=email,
                password=password,
                display_name=display_name,
            )
        typer.echo(
            json.dumps(
                {
                    "user_id": str(user.user_id),
                    "email": user.email,
                    "status": user.status,
                },
                indent=2,
            )
        )

    asyncio.run(run())


@app.command("list")
def list_users(
    status: str | None = typer.Option(None),
    limit: int = typer.Option(50, min=1, max=500),
) -> None:
    """Print every user matching the filter. Values are never logged."""

    async def run() -> None:
        async with admin_session() as db:
            stmt = select(User)
            if status:
                stmt = stmt.where(User.status == status)
            stmt = stmt.order_by(User.created_at.desc()).limit(limit)
            rows = list((await db.execute(stmt)).scalars())
            typer.echo(
                json.dumps(
                    [
                        {
                            "user_id": str(u.user_id),
                            "email": u.email,
                            "display_name": u.display_name,
                            "status": u.status,
                            "email_verified": u.email_verified,
                            "created_at": u.created_at.isoformat(),
                        }
                        for u in rows
                    ],
                    indent=2,
                )
            )

    asyncio.run(run())


@app.command("deactivate")
def deactivate(user_id: str = typer.Argument(..., help="UUID of the user.")) -> None:
    """Set the user's status to 'suspended'."""

    async def run() -> None:
        async with admin_session() as db:
            user = await db.get(User, UUID(user_id))
            if user is None:
                typer.secho("user not found", fg=typer.colors.RED)
                raise typer.Exit(code=1)
            user.status = UserStatus.SUSPENDED.value
            await db.flush()
        typer.secho(f"deactivated {user_id}", fg=typer.colors.YELLOW)

    asyncio.run(run())
