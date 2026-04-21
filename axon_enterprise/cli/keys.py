"""``axon-enterprise keys ...`` — JWT signing key lifecycle."""

from __future__ import annotations

import asyncio
import json

import typer

from axon_enterprise.db.session import admin_session
from axon_enterprise.jwt_issuer import (
    JwksDocumentBuilder,
    KeyManagementService,
    LocalSigner,
)

app = typer.Typer()


@app.command("list")
def list_keys() -> None:
    """Print every verifiable signing key (active + grace)."""

    async def run() -> None:
        km = KeyManagementService()
        async with admin_session() as db:
            keys = await km.list_verifiable(db)
        typer.echo(
            json.dumps(
                [
                    {
                        "kid": k.kid,
                        "algorithm": k.algorithm,
                        "backend": k.backend,
                        "status": k.status,
                        "activated_at": k.activated_at.isoformat()
                        if k.activated_at
                        else None,
                        "grace_until": k.grace_until.isoformat()
                        if k.grace_until
                        else None,
                    }
                    for k in keys
                ],
                indent=2,
            )
        )

    asyncio.run(run())


@app.command("register-kms")
def register_kms(
    kms_arn: str = typer.Option(..., "--kms-arn", help="KMS key ARN or alias."),
) -> None:
    """Register a KMS key as ACTIVE (demotes the current active to grace)."""

    async def run() -> None:
        km = KeyManagementService()
        async with admin_session() as db:
            row = await km.register_kms_key(db, kms_key_arn=kms_arn)
        typer.secho(f"registered kid={row.kid} status={row.status}", fg=typer.colors.GREEN)

    asyncio.run(run())


@app.command("rotate")
def rotate(
    kms_arn: str | None = typer.Option(
        None,
        "--kms-arn",
        help=(
            "ARN of the NEW KMS key. If omitted, a local signer is generated "
            "(dev / single-node only — rejected by the production validator)."
        ),
    ),
) -> None:
    """Demote the current active to grace and install a new active."""

    async def run() -> None:
        km = KeyManagementService()
        async with admin_session() as db:
            if kms_arn:
                row = await km.rotate(db, new_kms_key_arn=kms_arn)
            else:
                row = await km.rotate(db, new_local_signer=LocalSigner.generate())
        typer.secho(f"rotated — new active kid={row.kid}", fg=typer.colors.GREEN)

    asyncio.run(run())


@app.command("retire-grace")
def retire_grace() -> None:
    """Retire grace keys past their ``grace_until``. Safe as a daily cron."""

    async def run() -> None:
        km = KeyManagementService()
        async with admin_session() as db:
            n = await km.retire_expired_grace_keys(db)
        typer.echo(f"retired {n} grace keys")

    asyncio.run(run())


@app.command("jwks")
def jwks() -> None:
    """Dump the current JWKS document — what ``/.well-known/jwks.json`` serves."""

    async def run() -> None:
        builder = JwksDocumentBuilder()
        async with admin_session() as db:
            doc = await builder.build(db)
        typer.echo(json.dumps(doc, indent=2))

    asyncio.run(run())
