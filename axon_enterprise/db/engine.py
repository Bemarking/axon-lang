"""Async SQLAlchemy engine(s) + pool tuning + per-session server-side safeguards.

Why two engines?
    Production deployments route reads to a replica when ``db.read_url`` is
    set. ``create_read_engine()`` returns the primary as a fallback so
    single-instance Postgres (staging, local) keeps working without code
    changes.

Slow-query logging, statement timeouts, lock timeouts, and
idle-in-transaction timeouts are applied **per connection** on checkout
via the ``connect`` event. This is the only place these values live so
the rest of the codebase never needs to think about them.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import structlog
from sqlalchemy import event, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from axon_enterprise.config import DatabaseSettings, get_settings

_logger: structlog.stdlib.BoundLogger = structlog.get_logger("axon_enterprise.db.engine")
_stdlib_logger = logging.getLogger("axon_enterprise.db.slowquery")


# Caches — one engine per URL. ``dispose_all_engines()`` releases them on shutdown.
_engines: dict[str, AsyncEngine] = {}


def _build_connect_args(settings: DatabaseSettings) -> dict[str, Any]:
    """Assemble asyncpg connect kwargs (SSL, command timeout, etc.)."""
    args: dict[str, Any] = {
        "server_settings": {
            "application_name": settings.application_name,
            # These Postgres GUCs apply to every new connection in the pool.
            "statement_timeout": str(settings.statement_timeout_ms),
            "idle_in_transaction_session_timeout": str(
                settings.idle_in_transaction_timeout_ms
            ),
            "lock_timeout": str(settings.lock_timeout_ms),
        },
    }

    # SSL: asyncpg accepts either a string mode or an ssl.SSLContext.
    # We always pass a string so the driver builds the context itself,
    # honouring ``ssl_root_cert`` via PGSSLROOTCERT env var when set.
    if settings.ssl_mode != "disable":
        args["ssl"] = settings.ssl_mode

    return args


def _attach_slow_query_listener(engine: AsyncEngine, threshold_ms: int) -> None:
    """Log (and keep the structured event ready for a metrics sink) queries >= threshold."""

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        context._axon_t0 = time.perf_counter()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        t0 = getattr(context, "_axon_t0", None)
        if t0 is None:
            return
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if elapsed_ms >= threshold_ms:
            # Keep the statement preview short — full SQL ends up in pg logs.
            _logger.warning(
                "slow_query",
                elapsed_ms=round(elapsed_ms, 2),
                threshold_ms=threshold_ms,
                statement_preview=statement.splitlines()[0][:160] if statement else "",
            )


def _configure_engine(engine: AsyncEngine, settings: DatabaseSettings) -> AsyncEngine:
    """Wire post-creation hooks (slow-query, future metrics)."""
    if settings.slow_query_ms > 0:
        _attach_slow_query_listener(engine, settings.slow_query_ms)
    return engine


def _make_engine(url: str, settings: DatabaseSettings) -> AsyncEngine:
    """Create a configured ``AsyncEngine`` for the given URL."""
    engine = create_async_engine(
        url,
        echo=settings.echo_sql,
        echo_pool=settings.echo_pool,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_seconds,
        pool_recycle=settings.pool_recycle_seconds,
        pool_pre_ping=settings.pool_pre_ping,
        future=True,
        connect_args=_build_connect_args(settings),
    )
    return _configure_engine(engine, settings)


# ── Public factory functions ───────────────────────────────────────────


def create_primary_engine() -> AsyncEngine:
    """Build (or return cached) the primary read-write engine."""
    s = get_settings()
    url = s.db.url.get_secret_value()
    if url not in _engines:
        _engines[url] = _make_engine(url, s.db)
        _logger.info(
            "engine_created",
            role="primary",
            dsn_host=URL.create_from_url_string(url).host if hasattr(URL, "create_from_url_string") else None,
            pool_size=s.db.pool_size,
            max_overflow=s.db.max_overflow,
        )
    return _engines[url]


def create_read_engine() -> AsyncEngine:
    """Build (or return cached) the read replica engine.

    Falls back to the primary when ``db.read_url`` is unset so
    single-instance deployments work without code changes.
    """
    s = get_settings()
    if s.db.read_url is None:
        return create_primary_engine()
    url = s.db.read_url.get_secret_value()
    if url not in _engines:
        _engines[url] = _make_engine(url, s.db)
        _logger.info("engine_created", role="read_replica")
    return _engines[url]


def get_primary_engine() -> AsyncEngine:
    """Accessor used by the session factory."""
    return create_primary_engine()


def get_read_engine() -> AsyncEngine:
    """Accessor used by read-only session contexts."""
    return create_read_engine()


async def dispose_all_engines() -> None:
    """Close pools on application shutdown. Safe to call multiple times."""
    for url, engine in list(_engines.items()):
        await engine.dispose()
        _engines.pop(url, None)
    _logger.info("engines_disposed", count=len(_engines))


# ── Session factories ──────────────────────────────────────────────────
#
# Exposed at module level so other modules can construct sessions without
# re-reading settings. The ``tenant_session`` / ``admin_session`` /
# ``read_session`` context managers in ``db.session`` are the canonical
# way to use them.

primary_session_factory: async_sessionmaker | None = None
read_session_factory: async_sessionmaker | None = None


def get_primary_session_factory() -> async_sessionmaker:
    """Lazy singleton for the write session maker."""
    global primary_session_factory
    if primary_session_factory is None:
        primary_session_factory = async_sessionmaker(
            bind=get_primary_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return primary_session_factory


def get_read_session_factory() -> async_sessionmaker:
    """Lazy singleton for the read-only session maker."""
    global read_session_factory
    if read_session_factory is None:
        read_session_factory = async_sessionmaker(
            bind=get_read_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return read_session_factory


async def healthcheck() -> bool:
    """SELECT 1 on the primary. Used by ``/healthz`` and readiness probes."""
    engine = get_primary_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        return result.scalar_one() == 1
