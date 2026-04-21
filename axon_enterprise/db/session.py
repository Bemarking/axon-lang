"""Session context managers with tenant-aware GUC injection.

Three flavours:

    tenant_session(ctx)   — read/write scoped to a single tenant via RLS.
                            Emits ``SET LOCAL axon.current_tenant = :id``
                            before yielding, matching the Rust runtime.

    admin_session()       — read/write WITHOUT a tenant GUC. Requires the
                            caller to be connected as a role tagged
                            ``BYPASSRLS`` (``axon_admin``). Used by the
                            Admin API, migrations, and audit verification.

    read_session(ctx)     — read-only, routed to the replica when
                            configured. Same GUC behaviour as
                            ``tenant_session``.

Every context manager is a single transaction:

    - ``commit()`` on clean exit
    - ``rollback()`` on exception
    - ``SET LOCAL`` scopes the GUC to the transaction, so the pool-
      recycled connection carries no stale tenant state on next use

This matches the Rust ``db_pool.rs`` behaviour which also applies
``SET LOCAL axon.current_tenant`` at the start of each transaction.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, NewType

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.config import get_settings
from axon_enterprise.db.base import set_tenant_guc_sql
from axon_enterprise.db.engine import (
    get_primary_session_factory,
    get_read_session_factory,
)
from axon_enterprise.tenant import (
    TenantContext,
    current_tenant_or_none,
    require_tenant,
)

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.db.session"
)


# Typed aliases so downstream signatures document intent at the call site.
TenantSession = NewType("TenantSession", AsyncSession)
AdminSession = NewType("AdminSession", AsyncSession)


async def _apply_tenant_guc(session: AsyncSession, tenant_id: str) -> None:
    """Emit ``SET LOCAL axon.current_tenant = :id`` on the active tx."""
    guc = get_settings().rls_guc_name
    await session.execute(set_tenant_guc_sql(guc, tenant_id))


@asynccontextmanager
async def tenant_session(
    ctx: TenantContext | None = None,
) -> AsyncIterator[TenantSession]:
    """Open a tenant-scoped read/write session.

    When ``ctx`` is omitted, the active ``ContextVar`` is used (matches
    Rust's ``current_tenant_id()`` pattern). If the ContextVar is unset
    this raises ``RuntimeError`` — silent fallback to ``"default"`` is
    not allowed for mutating operations.

    Usage
    -----

        async with tenant_session() as session:
            session.add(User(...))
            # commit happens on __aexit__

    """
    ctx = ctx or require_tenant()
    factory = get_primary_session_factory()
    session = factory()
    try:
        async with session.begin():
            await _apply_tenant_guc(session, ctx.tenant_id)
            yield session  # type: ignore[misc]
    except Exception:
        # session.begin() context manager already rolled back; we log and
        # re-raise so observability sees the tenant that caused the error.
        _logger.warning(
            "tenant_session_rollback",
            tenant_id=ctx.tenant_id,
            request_id=ctx.request_id,
        )
        raise
    finally:
        await session.close()


@asynccontextmanager
async def read_session(
    ctx: TenantContext | None = None,
) -> AsyncIterator[TenantSession]:
    """Open a tenant-scoped read-only session (routes to replica when configured).

    The GUC is still set so RLS filters apply. Writes are technically
    possible since Postgres doesn't tag sessions as read-only here, but
    the connection routes through the replica engine which is typically
    read-only at the infra layer.
    """
    ctx = ctx or require_tenant()
    factory = get_read_session_factory()
    session = factory()
    try:
        async with session.begin():
            await _apply_tenant_guc(session, ctx.tenant_id)
            yield session  # type: ignore[misc]
    finally:
        await session.close()


@asynccontextmanager
async def admin_session() -> AsyncIterator[AdminSession]:
    """Open a cross-tenant session for admin operations.

    No GUC is set. The connecting role should be ``axon_admin`` (tagged
    ``BYPASSRLS``) so tenant policies are skipped; the provisioning
    scripts in ``infrastructure/aws/iam`` grant this role to the Admin
    API's service account only.

    Always emits an audit event via the caller — admin access is
    privileged and MUST be accounted for. See ``axon_enterprise.audit``
    (Fase 10.g).
    """
    factory = get_primary_session_factory()
    session = factory()
    try:
        async with session.begin():
            yield session  # type: ignore[misc]
    finally:
        await session.close()


# ── FastAPI / Starlette helpers ───────────────────────────────────────


async def get_request_session() -> AsyncIterator[TenantSession]:
    """FastAPI-style dependency that yields a tenant-scoped session.

    The tenant is resolved from the active ``ContextVar`` — it is the
    responsibility of upstream middleware (``TenantExtractor``, Fase
    10.b) to set it before handlers run. When the middleware is not
    installed this dependency raises to avoid silent cross-tenant
    writes.
    """
    ctx = current_tenant_or_none()
    if ctx is None:
        raise RuntimeError(
            "No TenantContext; upstream TenantExtractor middleware must run first."
        )
    async with tenant_session(ctx) as session:
        yield session
