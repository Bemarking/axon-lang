"""Async-compatible Alembic environment for axon-enterprise.

Responsibilities:
    - Load the database URL from ``Settings`` so it matches runtime.
    - Attach the control-plane metadata (``METADATA``) so autogenerate
      sees every Python-owned model.
    - Run migrations inside an async engine so we use the same asyncpg
      driver as the app — one less thing to keep in sync.
    - Filter out objects under the ``public`` schema; those belong to
      the Rust data plane and are managed by its own migration set
      (``axon-rs/migrations/``).
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Make the package importable when Alembic is run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from axon_enterprise.config import get_settings  # noqa: E402
from axon_enterprise.db.base import METADATA  # noqa: E402

# Alembic config object; logging configured from alembic.ini sections.
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the URL from Settings so AXON_DB_URL is the single source of truth.
_settings = get_settings()
config.set_main_option("sqlalchemy.url", _settings.db.url.get_secret_value())

target_metadata = METADATA

# The schema where alembic_version lives. Keeping it inside the
# control-plane schema isolates migration state from the Rust tables.
VERSION_TABLE_SCHEMA = _settings.db.control_schema


def include_object(
    object: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Filter objects so autogenerate ignores tables owned by the Rust plane.

    The Rust migration suite owns ``public.*``. We assert those tables
    exist (baseline migration) but never emit DDL for them.
    """
    if type_ == "table":
        schema = getattr(object, "schema", None) or "public"
        if schema == "public":
            return False
    return True


def _context_kwargs(**extra: Any) -> dict[str, Any]:
    """Common ``context.configure`` kwargs used by both offline and online."""
    return {
        "target_metadata": target_metadata,
        "include_schemas": True,
        "include_object": include_object,
        "version_table_schema": VERSION_TABLE_SCHEMA,
        # Treat server_default changes and column-type changes as meaningful
        # differences during autogenerate.
        "compare_server_default": True,
        "compare_type": True,
        # transaction_per_migration=True so a failing migration doesn't
        # leave a partially-applied state; Alembic wraps EACH migration
        # in its own transaction (and we never run DDL outside a tx).
        "transaction_per_migration": True,
        **extra,
    }


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to a DB.

    Useful for code review: ``alembic upgrade head --sql > pending.sql``.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_context_kwargs(),
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, **_context_kwargs())
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live DB using asyncpg."""
    section = config.get_section(config.config_ini_section, {}) or {}
    # NullPool: Alembic opens one connection and holds it until the end;
    # a connection pool would recycle mid-migration and lose GUCs.
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
