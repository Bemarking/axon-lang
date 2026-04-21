"""Integration tests for the Alembic migration chain.

- ``upgrade head`` leaves the schema in the expected shape.
- ``downgrade base`` reverses the baseline cleanly.
- Re-running ``upgrade head`` is idempotent on an already-migrated DB.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


def _cfg(postgres_url: str, project_root: Path) -> AlembicConfig:
    sync_url = postgres_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    cfg = AlembicConfig(str(project_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", sync_url)
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    return cfg


async def _schema_exists(engine: AsyncEngine, schema: str) -> bool:
    async with engine.connect() as conn:
        row = await conn.execute(
            text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"),
            {"s": schema},
        )
        return row.scalar() is not None


async def _role_exists(engine: AsyncEngine, role: str) -> bool:
    async with engine.connect() as conn:
        row = await conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"),
            {"r": role},
        )
        return row.scalar() is not None


async def _function_exists(engine: AsyncEngine, qualified_name: str) -> bool:
    schema, name = qualified_name.split(".")
    async with engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT 1 FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = :s AND p.proname = :n"
            ),
            {"s": schema, "n": name},
        )
        return row.scalar() is not None


@pytest.mark.asyncio
async def test_baseline_creates_schema_role_function(
    migrated_db: AsyncEngine,
) -> None:
    assert await _schema_exists(migrated_db, "axon_control")
    assert await _role_exists(migrated_db, "axon_admin")
    assert await _function_exists(migrated_db, "axon_control.set_tenant")


@pytest.mark.asyncio
async def test_alembic_version_table_is_in_control_schema(
    migrated_db: AsyncEngine,
) -> None:
    async with migrated_db.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT table_schema FROM information_schema.tables "
                "WHERE table_name = 'alembic_version'"
            )
        )
        assert row.scalar_one() == "axon_control"


@pytest.mark.asyncio
async def test_upgrade_is_idempotent(
    migrated_db: AsyncEngine,
    postgres_url: str,
    project_root: Path,
) -> None:
    # Running upgrade again on an already-migrated DB must be a no-op.
    cfg = _cfg(postgres_url, project_root)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    # Still intact:
    assert await _schema_exists(migrated_db, "axon_control")


@pytest.mark.asyncio
async def test_downgrade_then_upgrade_roundtrip(
    migrated_db: AsyncEngine,
    postgres_url: str,
    project_root: Path,
) -> None:
    cfg = _cfg(postgres_url, project_root)

    # Downgrade to base.
    await asyncio.to_thread(command.downgrade, cfg, "base")
    assert not await _schema_exists(migrated_db, "axon_control")

    # Upgrade back. ``migrated_db`` fixture will be re-seeded in the next
    # test automatically; we leave HEAD in place for subsequent tests.
    await asyncio.to_thread(command.upgrade, cfg, "head")
    assert await _schema_exists(migrated_db, "axon_control")
    assert await _function_exists(migrated_db, "axon_control.set_tenant")
