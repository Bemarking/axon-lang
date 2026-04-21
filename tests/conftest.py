"""Top-level test fixtures for axon-enterprise.

Three classes of tests are supported here:

- **unit** (default): no Docker, no Postgres, no network. Exercises
  pure-Python logic (TenantContext propagation, settings validation,
  RLS SQL shape, password hashing, TOTP, envelope crypto).

- **integration** (``-m integration``): spins up an ephemeral Postgres
  via testcontainers, applies the Rust M1 baseline (``public.tenants``)
  and the Python Alembic chain, and exercises real queries + RLS.

- **slow** (``-m slow``): for load / large-data paths.

Integration tests are skipped automatically when Docker is unavailable.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio


# ── Docker availability gate ──────────────────────────────────────────


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip integration tests when Docker is unreachable."""
    docker_available = shutil.which("docker") is not None and (
        os.environ.get("DOCKER_HOST") is not None
        or Path("/var/run/docker.sock").exists()
        or os.name == "nt"  # on Windows assume Docker Desktop is handling it
    )
    if docker_available:
        return
    skip_marker = pytest.mark.skip(reason="Docker unavailable; integration tests skipped")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _reset_current_tenant() -> Iterator[None]:
    """Clear the TenantContext ContextVar between tests so state never leaks."""
    from axon_enterprise.tenant import CURRENT_TENANT

    token = CURRENT_TENANT.set(None)
    try:
        yield
    finally:
        CURRENT_TENANT.reset(token)


# ── Session-scoped MonkeyPatch ────────────────────────────────────────


@pytest.fixture(scope="session")
def monkeypatch_session() -> Iterator[pytest.MonkeyPatch]:
    """Session-scoped MonkeyPatch (pytest ships a function-scoped one)."""
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


# ── Postgres container (integration-only) ─────────────────────────────
#
# The container and the migrated engine live at session scope so the
# (~2s) cold start is amortised across the whole integration suite.


@pytest.fixture(scope="session")
def _postgres_container():  # type: ignore[no-untyped-def]
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        image="postgres:16-alpine",
        username="axon_test",
        password="axon_test",
        dbname="axon_enterprise_test",
        port=5432,
    ) as container:
        yield container


@pytest.fixture(scope="session")
def postgres_url(_postgres_container) -> str:  # type: ignore[no-untyped-def]
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
    """Point the app's settings at the container + ensure envelope has a key."""
    import base64
    import os as _os

    from axon_enterprise.config import get_settings

    monkeypatch_session.setenv("AXON_ENV", "test")
    monkeypatch_session.setenv("AXON_DB__URL", postgres_url)
    monkeypatch_session.setenv("AXON_DB__SSL_MODE", "disable")
    monkeypatch_session.setenv("AXON_DB__ECHO_SQL", "false")
    # Envelope: local backend with a generated key so TotpService works.
    key_b64 = base64.urlsafe_b64encode(_os.urandom(32)).decode("ascii")
    monkeypatch_session.setenv("AXON_ENVELOPE__BACKEND", "local")
    monkeypatch_session.setenv("AXON_ENVELOPE__LOCAL_KEY", key_b64)
    get_settings.cache_clear()


# ── Rust data-plane fixture (public.tenants stand-in) ─────────────────

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


@pytest_asyncio.fixture(scope="session")
async def migrated_db(
    postgres_url: str,
    project_root: Path,
):
    """Seed Rust fixture + run ``alembic upgrade head``, yield an engine."""
    from alembic import command
    from alembic.config import Config as AlembicConfig
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    sync_url = postgres_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")

    # Seed Rust fixture
    seed_engine = create_async_engine(postgres_url, future=True)
    try:
        async with seed_engine.begin() as conn:
            for stmt in _RUST_DATA_PLANE_FIXTURE_SQL.strip().split(";"):
                s = stmt.strip()
                if s:
                    await conn.execute(text(s))
    finally:
        await seed_engine.dispose()

    # Alembic upgrade
    cfg = AlembicConfig(str(project_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", sync_url)
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    await asyncio.to_thread(command.upgrade, cfg, "head")

    engine = create_async_engine(postgres_url, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(migrated_db) -> AsyncIterator:  # type: ignore[no-untyped-def]
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        yield session
