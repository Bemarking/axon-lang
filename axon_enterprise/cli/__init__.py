"""Operator CLI — ``axon-enterprise <subcommand>``.

Typer-based so ``--help`` is auto-generated and type annotations
double as shell validation. Every subcommand operates on the same
Postgres + services the HTTP layer uses — no second code path for
operator tooling.

Exposed by the entry point declared in ``pyproject.toml``:
``axon-enterprise = "axon_enterprise.cli:entrypoint"``.
"""

from axon_enterprise.cli.app import app, entrypoint

__all__ = ["app", "entrypoint"]
