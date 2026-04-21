"""Integration test fixtures: ephemeral Postgres + Alembic upgrade.

The Docker daemon must be reachable (tests are auto-skipped otherwise).
Container lifecycle is session-scoped so the (~2s) cold start is
amortised across the whole integration suite.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from testcontainers.postgres import PostgresContainer

# ── SQL applied before Alembic to simulate the Rust M1 / M2 baseline ────
#
# The real Rust migration is axon-rs/migrations/003_add_tenants.sql
# (Fase M1). We apply a shape-compatible subset here so the Python
# Alembic baseline can assert `public.tenants` exists without requiring
# the Rust tooling to run first.

_RUST_DATA_PLANE_FIXTURE_SQL = """
CREATE TABLE IF NOT EXISTS public.tenants (
    tenant_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    plan        TEXT NOT NULL DEFAULT 'starter',
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO public.tenants (tenant_id, name, plan) VALUES
    ('default', 'Default Tenant', 'enterprise'),
    ('alpha',   'Alpha Tenant',   'enterprise'),
    ('beta',    'Beta Tenant',    'enterprise')
ON CONFLICT (tenant_id) DO NOTHING;
"""


@pytest.fixture(scope="session")
def _postgres_container() -> Iterator[PostgresContainer]:
    """Start an ephemeral Postgres 16 container for the session."""
    with PostgresContainer(
        image="postgres:16-alpine",
        username="axon_test",
        password="axon_test",
        dbname="axon_enterprise_test",
        port=5432,
    ) as container:
        yield container


@pytest.fixture(scope="session")
def postgres_url(_postgres_container: PostgresContainer) -> str:
    """Assemble the asyncpg URL pointing at the ephemeral container."""
    host = _postgres_container.get_container_host_ip()
    port = _postgres_container.get_exposed_port(5432)
    user = _postgres_container.username
    pw = _postgres_container.password
    db = _postgres_container.dbname
    return f"postgresql+asyncpg://{user}:{pw}@{host}:{port}/{db}"


@pytest.fixture(scope="session", autouse=True)
def _set_axon_db_env(
    postgres_url: str,
    monkeypatch_session: pytest.MonkeyPatch,
) -> None:
    """Point the app's settings at the container for the duration of the session."""
    from axon_enterprise.config import get_settings

    monkeypatch_session.setenv("AXON_ENV", "test")
    monkeypatch_session.setenv("AXON_DB__URL", postgres_url)
    monkeypatch_session.setenv("AXON_DB__SSL_MODE", "disable")
    monkeypatch_session.setenv("AXON_DB__ECHO_SQL", "false")
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def monkeypatch_session() -> Iterator[pytest.MonkeyPatch]:
    """Session-scoped MonkeyPatch (pytest ships a function-scoped one)."""
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


async def _apply_rust_fixture(engine: AsyncEngine) -> None:
    """Seed ``public.tenants`` before Alembic runs its baseline."""
    async with engine.begin() as conn:
        # split on semicolons — simple enough for the fixture DDL.
        for stmt in _RUST_DATA_PLANE_FIXTURE_SQL.strip().split(";"):
            s = stmt.strip()
            if s:
                await conn.execute(text(s))


def _alembic_config(postgres_url: str, project_root: Path) -> AlembicConfig:
    cfg = AlembicConfig(str(project_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", postgres_url)
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    return cfg


@pytest_asyncio.fixture(scope="session")
async def migrated_db(
    postgres_url: str,
    project_root: Path,
) -> AsyncIterator[AsyncEngine]:
    """Seed Rust fixture + run ``alembic upgrade head``, yield a live engine."""
    # Use a sync URL for Alembic (simpler path) — derive from the asyncpg URL.
    sync_url = postgres_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")

    # Seed Rust fixture via a temporary async engine.
    seed_engine = create_async_engine(postgres_url, future=True)
    try:
        await _apply_rust_fixture(seed_engine)
    finally:
        await seed_engine.dispose()

    # Run Alembic upgrade against the sync URL (Alembic env.py resolves via
    # get_settings() but we override here so the runner doesn't spin up an
    # async loop inside pytest-asyncio).
    cfg = _alembic_config(sync_url, project_root)
    await asyncio.to_thread(command.upgrade, cfg, "head")

    # Return an async engine the tests can use.
    engine = create_async_engine(postgres_url, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(migrated_db: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Plain async session bound to the migrated DB (no tenant GUC set)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        yield session
