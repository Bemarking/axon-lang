"""``axon-enterprise migrate ...`` — thin wrapper over Alembic.

Wraps ``alembic upgrade / downgrade / current / history`` so
operators get the same ``--help`` ergonomics as the rest of the
CLI and don't have to remember the Alembic CLI's shape. All
commands resolve ``sqlalchemy.url`` from ``AXON_DB_URL`` via the
Alembic env.py we ship.
"""

from __future__ import annotations

from pathlib import Path

import typer
from alembic import command
from alembic.config import Config

app = typer.Typer()


def _config() -> Config:
    repo_root = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    return cfg


@app.command("upgrade")
def upgrade(
    target: str = typer.Argument("head", help="Revision to upgrade to."),
) -> None:
    """Upgrade the schema to the given revision (default ``head``)."""
    command.upgrade(_config(), target)


@app.command("downgrade")
def downgrade(
    target: str = typer.Argument(..., help="Revision or relative e.g. -1"),
) -> None:
    """Roll back to the given revision."""
    command.downgrade(_config(), target)


@app.command("current")
def current() -> None:
    """Print the current head revision."""
    command.current(_config(), verbose=True)


@app.command("history")
def history() -> None:
    """Print the migration graph."""
    command.history(_config(), verbose=True)


@app.command("stamp")
def stamp(
    target: str = typer.Argument(..., help="Revision to stamp without running"),
) -> None:
    """Record a revision as applied without running migrations.

    Use when adopting the CLI against an existing database that was
    migrated out-of-band.
    """
    command.stamp(_config(), target)
