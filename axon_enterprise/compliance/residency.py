"""Data-residency enforcement middleware + helpers.

Every tenant declares a ``data_region`` (matching one of the
deployment regions Terraform provisions). A request arriving at a
server whose ``compliance.server_region`` does NOT match the
tenant's declared region is mis-routed — we 308-redirect to the
correct regional hostname when ``residency_redirect_base`` is
configured, otherwise respond 421 Misdirected Request.

The middleware runs AFTER ``AuthMiddleware`` because it needs
``principal.tenant_id``; it looks up ``axon_admin.tenants.data_region``
lazily via an admin_session (cached in-process per tenant for 60
seconds to keep the hot path fast).

An audit event ``compliance:residency_violation`` is emitted for
each mis-routed request so operators can see if a particular
region is receiving traffic it shouldn't.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import structlog
from sqlalchemy import text
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from axon_enterprise.audit.events import AuditEventType
from axon_enterprise.audit.service import AuditService, AuditWriteRequest
from axon_enterprise.config import ComplianceSettings, get_settings
from axon_enterprise.db.session import admin_session
from axon_enterprise.identity.principal import current_principal_or_none

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.compliance.residency"
)


@dataclass
class _RegionCacheEntry:
    region: str
    fetched_at: float


@dataclass
class TenantRegionCache:
    """Lookup ``tenants.data_region`` with a short in-process TTL."""

    ttl_seconds: float = 60.0
    _entries: dict[str, _RegionCacheEntry] = field(default_factory=dict)

    async def region_for(self, tenant_id: str) -> str | None:
        entry = self._entries.get(tenant_id)
        now = time.monotonic()
        if entry is not None and (now - entry.fetched_at) < self.ttl_seconds:
            return entry.region or None
        async with admin_session() as db:
            region = await db.scalar(
                text(
                    "SELECT data_region FROM axon_admin.tenants "
                    "WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        resolved = str(region) if region else ""
        self._entries[tenant_id] = _RegionCacheEntry(
            region=resolved, fetched_at=now
        )
        return resolved or None


class DataResidencyMiddleware:
    """Rejects / redirects requests whose tenant region ≠ server region.

    Constructed via Starlette's ``add_middleware(DataResidencyMiddleware)``.
    All configuration comes from ``get_settings().compliance``.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        cache: TenantRegionCache | None = None,
    ) -> None:
        self.app: ASGIApp = app
        self.settings: ComplianceSettings = get_settings().compliance
        self.cache = cache or TenantRegionCache()

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        principal = current_principal_or_none()
        if principal is None:
            # Public routes (login, webhooks) don't know the tenant
            # yet — they are always allowed; the tenant-scoped
            # handlers downstream set the principal after auth.
            await self.app(scope, receive, send)
            return

        tenant_region = await self.cache.region_for(principal.tenant_id)
        server_region = self.settings.server_region
        if not tenant_region or tenant_region == server_region:
            await self.app(scope, receive, send)
            return

        # Mis-routed — emit audit + redirect or reject.
        await self._record_violation(
            tenant_id=principal.tenant_id,
            actor_user_id=principal.user_id,
            tenant_region=tenant_region,
        )

        if self.settings.residency_redirect_base:
            redirect_to = self._build_redirect_url(
                base=self.settings.residency_redirect_base,
                region=tenant_region,
                path=scope.get("path", "/"),
                raw_query=scope.get("query_string", b""),
            )
            await _send_redirect(send, redirect_to)
        else:
            await _send_misdirected(send, tenant_region=tenant_region)

    async def _record_violation(
        self,
        *,
        tenant_id: str,
        actor_user_id,
        tenant_region: str,
    ) -> None:
        try:
            audit = AuditService()
            async with admin_session() as db:
                await audit.record(
                    db,
                    AuditWriteRequest(
                        tenant_id=tenant_id,
                        event_type=AuditEventType.COMPLIANCE_RESIDENCY_VIOLATION,
                        resource_type="tenant",
                        resource_id=tenant_id,
                        action="residency_redirect",
                        actor_user_id=actor_user_id,
                        status="denied",
                        details={
                            "server_region": self.settings.server_region,
                            "tenant_region": tenant_region,
                        },
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            # Never fail the request because audit failed — log and
            # press on with the redirect/reject.
            _logger.warning(
                "compliance_residency_audit_failed",
                tenant_id=tenant_id,
                error=str(exc),
            )

    def _build_redirect_url(
        self,
        *,
        base: str,
        region: str,
        path: str,
        raw_query: bytes,
    ) -> str:
        host = base.format(region=region).rstrip("/")
        query = (
            "?" + raw_query.decode("ascii") if raw_query else ""
        )
        return f"{host}{path}{query}"


async def _send_redirect(send: Send, location: str) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 308,
            "headers": [
                (b"location", location.encode("ascii")),
                (b"content-type", b"application/json"),
            ],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": b'{"error":{"code":"compliance.residency_redirect"}}',
        }
    )


async def _send_misdirected(send: Send, *, tenant_region: str) -> None:
    body = (
        '{"error":{"code":"compliance.residency_violation",'
        f'"tenant_region":"{tenant_region}"}}'
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 421,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})
