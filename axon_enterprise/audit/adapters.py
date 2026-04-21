"""Adapters that plug ``AuditService`` into the Protocol-based emitters
already wired into upstream services (SecretsService in 10.f, and the
RBAC / SSO equivalents added when 10.j wires HTTP handlers).

The emitters exposed in each module are:

    - ``SecretsAuditEmitter`` (10.f)
    - future: ``RbacAuditEmitter`` (used by 10.c service when wired)
    - future: ``SsoAuditEmitter`` (used by 10.d service when wired)

Each adapter translates a module-specific ``emit()`` signature into
an ``AuditWriteRequest`` + ``AuditService.record``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.audit.events import AuditEventType
from axon_enterprise.audit.service import AuditService, AuditWriteRequest

# Map between the informal ``secret:create`` / ``secret:update`` / ...
# strings used by ``SecretsService`` today and the canonical
# ``AuditEventType`` values. Keeping the mapping explicit lets us
# extend the Secrets service with new events without breaking old
# log consumers.
_SECRET_EVENT_MAP: dict[str, AuditEventType] = {
    "secret:create": AuditEventType.SECRET_CREATED,
    "secret:update": AuditEventType.SECRET_UPDATED,
    "secret:read": AuditEventType.SECRET_READ,
    "secret:rotate": AuditEventType.SECRET_ROTATED,
    "secret:delete_scheduled": AuditEventType.SECRET_DELETE_SCHEDULED,
}


@dataclass
class SecretsAuditAdapter:
    """Drop-in for ``SecretsAuditEmitter``.

    Satisfies the Protocol by implementing ``emit``. The owning caller
    passes the active ``AsyncSession`` when constructing the adapter
    because ``AuditService.record`` needs one.
    """

    service: AuditService
    db: AsyncSession

    async def emit(
        self,
        *,
        tenant_id: str,
        user_id: UUID | None,
        event_type: str,
        key: str,
        fingerprint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        canonical = _SECRET_EVENT_MAP.get(event_type)
        if canonical is None:
            raise ValueError(
                f"SecretsAuditAdapter: unmapped event_type {event_type!r}. "
                "Extend _SECRET_EVENT_MAP in audit.adapters."
            )
        body: dict[str, Any] = {"fingerprint": fingerprint, **(details or {})}
        action = canonical.value.split(":", 1)[1]
        await self.service.record(
            self.db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=canonical,
                resource_type="secret",
                resource_id=key,
                action=action,
                actor_user_id=user_id,
                details=body,
            ),
        )


@dataclass
class RbacAuditAdapter:
    """Adapter for RBAC service events.

    10.c's ``RbacService`` currently only logs ``permission_denied``
    events via structlog. This adapter surfaces a uniform ``emit``
    the service can start calling once 10.j wires the HTTP layer.
    """

    service: AuditService
    db: AsyncSession

    async def emit_role_created(
        self,
        *,
        tenant_id: str,
        actor_user_id: UUID | None,
        role_id: UUID,
        role_name: str,
    ) -> None:
        await self.service.record(
            self.db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=AuditEventType.RBAC_ROLE_CREATED,
                resource_type="role",
                resource_id=str(role_id),
                action="create",
                actor_user_id=actor_user_id,
                details={"role_name": role_name},
            ),
        )

    async def emit_permission_granted(
        self,
        *,
        tenant_id: str,
        actor_user_id: UUID | None,
        role_id: UUID,
        permission: str,
    ) -> None:
        await self.service.record(
            self.db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=AuditEventType.RBAC_PERMISSION_GRANTED,
                resource_type="role",
                resource_id=str(role_id),
                action="grant_permission",
                actor_user_id=actor_user_id,
                details={"permission": permission},
            ),
        )

    async def emit_permission_denied(
        self,
        *,
        tenant_id: str,
        actor_user_id: UUID | None,
        permission: str,
    ) -> None:
        await self.service.record(
            self.db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=AuditEventType.RBAC_PERMISSION_DENIED,
                resource_type="permission",
                resource_id=permission,
                action="deny",
                actor_user_id=actor_user_id,
                status="denied",
            ),
        )


@dataclass
class SsoAuditAdapter:
    """Adapter for SSO events — config mutation, login, user provisioning."""

    service: AuditService
    db: AsyncSession

    async def emit_config_changed(
        self,
        *,
        tenant_id: str,
        actor_user_id: UUID | None,
        provider_type: str,
        operation: str,  # 'create' | 'update' | 'delete'
    ) -> None:
        mapping = {
            "create": AuditEventType.SSO_CONFIG_CREATED,
            "update": AuditEventType.SSO_CONFIG_UPDATED,
            "delete": AuditEventType.SSO_CONFIG_DELETED,
        }
        canonical = mapping.get(operation)
        if canonical is None:
            raise ValueError(f"unknown SSO config operation {operation!r}")
        await self.service.record(
            self.db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=canonical,
                resource_type="sso_configuration",
                resource_id=provider_type,
                action=operation,
                actor_user_id=actor_user_id,
            ),
        )

    async def emit_login(
        self,
        *,
        tenant_id: str,
        actor_user_id: UUID,
        actor_email: str,
        provider_type: str,
        is_new_user: bool,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        await self.service.record(
            self.db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=AuditEventType.SSO_LOGIN_SUCCESS,
                resource_type="user",
                resource_id=str(actor_user_id),
                action="login",
                actor_user_id=actor_user_id,
                actor_email=actor_email,
                ip_address=ip_address,
                user_agent=user_agent,
                details={
                    "provider_type": provider_type,
                    "is_new_user": is_new_user,
                },
            ),
        )

    async def emit_assertion_replay(
        self,
        *,
        tenant_id: str,
        assertion_id: str,
    ) -> None:
        await self.service.record(
            self.db,
            AuditWriteRequest(
                tenant_id=tenant_id,
                event_type=AuditEventType.SSO_ASSERTION_REPLAY,
                resource_type="saml_assertion",
                resource_id=assertion_id,
                action="replay_attempt",
                status="denied",
            ),
        )
