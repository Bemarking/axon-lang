"""Top-level Typer app + subcommand registration."""

from __future__ import annotations

import typer

from axon_enterprise.cli.audit import app as audit_app
from axon_enterprise.cli.compliance import app as compliance_app
from axon_enterprise.cli.keys import app as keys_app
from axon_enterprise.cli.migrate import app as migrate_app
from axon_enterprise.cli.tenant import app as tenant_app
from axon_enterprise.cli.user import app as user_app

app = typer.Typer(
    name="axon-enterprise",
    help="Operator CLI for the Axon Enterprise control plane.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.add_typer(tenant_app, name="tenant", help="Tenant lifecycle commands.")
app.add_typer(user_app, name="user", help="User management commands.")
app.add_typer(keys_app, name="keys", help="JWT signing key lifecycle.")
app.add_typer(audit_app, name="audit", help="Audit chain verification + queries.")
app.add_typer(
    compliance_app, name="compliance", help="GDPR/CCPA/SOC 2 tooling."
)
app.add_typer(migrate_app, name="migrate", help="Alembic wrapper.")


def entrypoint() -> None:
    """``console_scripts`` target for ``pyproject.toml``."""
    app()


if __name__ == "__main__":  # pragma: no cover
    entrypoint()
