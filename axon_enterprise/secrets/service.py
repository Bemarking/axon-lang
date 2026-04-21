"""SecretsService — orchestrates backend calls + metadata persistence + audit.

Every mutation is a two-step operation:

    1. Backend call (AWS SM) — source of truth for the value.
    2. Postgres metadata update — our view of "what keys exist"
       plus the audit trail.

When the backend call succeeds but the Postgres update fails the
operator sees a partial state (value exists in AWS SM without a
metadata row). The recovery path is simple: re-running ``put`` is
idempotent (AWS SM appends a version), and a reconciliation job
(future, 10.l) syncs orphaned backend entries back into Postgres.

All operations emit an audit event via ``SecretsAuditEmitter``. The
default implementation logs structured events; 10.g swaps in the
hash-chained writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import NamedTuple, Protocol
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.config import SecretsSettings, get_settings
from axon_enterprise.secrets.backend import SecretsBackend
from axon_enterprise.secrets.errors import (
    SecretAlreadyScheduledForDeletion,
    SecretNotFound,
)
from axon_enterprise.secrets.in_memory_backend import InMemoryBackend
from axon_enterprise.secrets.models import SecretStatus, TenantSecret
from axon_enterprise.secrets.policy import SecretsPolicy
from axon_enterprise.secrets.value import SecretValue

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.secrets.service"
)


# ── Audit emitter (stub until 10.g) ──────────────────────────────────


class SecretsAuditEmitter(Protocol):
    """Fase 10.g will wire the hash-chained audit writer; until then a
    structured-log emitter satisfies the interface."""

    async def emit(
        self,
        *,
        tenant_id: str,
        user_id: UUID | None,
        event_type: str,
        key: str,
        fingerprint: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None: ...


@dataclass
class LoggingAuditEmitter:
    """Default structured-log emitter. Will be replaced in 10.g."""

    async def emit(
        self,
        *,
        tenant_id: str,
        user_id: UUID | None,
        event_type: str,
        key: str,
        fingerprint: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        _logger.info(
            "audit_secret_event",
            tenant_id=tenant_id,
            user_id=str(user_id) if user_id else None,
            event_type=event_type,
            key=key,
            fingerprint=fingerprint,
            details=details or {},
        )


# ── Return types ─────────────────────────────────────────────────────


class SecretReveal(NamedTuple):
    """Returned by ``reveal_secret`` — value wrapped, metadata exposed."""

    value: SecretValue
    key: str
    version_id: str
    last_accessed_at: datetime


@dataclass(frozen=True, slots=True)
class SecretListing:
    """Summary row for ``list_secrets`` — values never included."""

    key: str
    description: str
    status: SecretStatus
    version_id: str
    last_rotated_at: datetime | None
    last_accessed_at: datetime | None
    accessed_count: int
    created_at: datetime


# ── Service ───────────────────────────────────────────────────────────


@dataclass
class SecretsService:
    """CRUD + audit for tenant-scoped secrets."""

    backend: SecretsBackend
    policy: SecretsPolicy
    audit: SecretsAuditEmitter
    settings: SecretsSettings

    @classmethod
    def default(cls) -> SecretsService:
        s = get_settings().secrets
        backend: SecretsBackend
        if s.backend == "aws_sm":
            from axon_enterprise.secrets.aws_sm_backend import AwsSmBackend

            backend = AwsSmBackend.from_settings()
        else:
            backend = InMemoryBackend()
        return cls(
            backend=backend,
            policy=SecretsPolicy.default(),
            audit=LoggingAuditEmitter(),
            settings=s,
        )

    # ── Write (create or replace) ─────────────────────────────────────

    async def put_secret(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        key: str,
        value: SecretValue,
        user_id: UUID | None = None,
        description: str | None = None,
    ) -> TenantSecret:
        """Create on first call or append a new version on subsequent calls."""
        canonical_key = self.policy.normalise_and_validate_key(key)
        path = self.policy.build_path(tenant_id, canonical_key)

        row = await self._find_row(db, tenant_id=tenant_id, key=canonical_key)
        if row is not None and row.status == SecretStatus.DELETED_PENDING.value:
            raise SecretAlreadyScheduledForDeletion(canonical_key)

        entry = await self.backend.put(path, value, description=description)

        now = datetime.now(timezone.utc)
        event = "secret:update"
        if row is None:
            row = TenantSecret(
                tenant_id=tenant_id,
                key=canonical_key,
                backend=self.settings.backend,
                storage_path=path,
                storage_arn=entry.arn,
                current_version=entry.version_id,
                description=description or "",
                status=SecretStatus.ACTIVE.value,
                created_by=user_id,
            )
            db.add(row)
            event = "secret:create"
        else:
            row.storage_arn = entry.arn
            row.current_version = entry.version_id
            if description is not None:
                row.description = description
            row.last_rotated_by = user_id
            row.last_rotated_at = now
        await db.flush()

        await self.audit.emit(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type=event,
            key=canonical_key,
            fingerprint=value.fingerprint,
            details={"version_id": entry.version_id, "size_bytes": value.length},
        )
        return row

    # ── Read ──────────────────────────────────────────────────────────

    async def reveal_secret(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        key: str,
        user_id: UUID | None = None,
    ) -> SecretReveal:
        """Fetch the current value + bump the access counter."""
        canonical_key = self.policy.normalise_and_validate_key(key)
        row = await self._require_active_row(
            db, tenant_id=tenant_id, key=canonical_key
        )

        value, entry = await self.backend.get(row.storage_path)

        now = datetime.now(timezone.utc)
        row.last_accessed_at = now
        row.accessed_count = (row.accessed_count or 0) + 1
        await db.flush()

        if self.settings.audit_on_read:
            await self.audit.emit(
                tenant_id=tenant_id,
                user_id=user_id,
                event_type="secret:read",
                key=canonical_key,
                fingerprint=value.fingerprint,
                details={"version_id": entry.version_id},
            )
        return SecretReveal(
            value=value,
            key=canonical_key,
            version_id=entry.version_id,
            last_accessed_at=now,
        )

    async def list_secrets(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
    ) -> list[SecretListing]:
        """Return metadata for every active secret of the tenant."""
        res = await db.execute(
            select(TenantSecret)
            .where(
                TenantSecret.tenant_id == tenant_id,
                TenantSecret.status != SecretStatus.DELETED.value,
            )
            .order_by(TenantSecret.key)
        )
        return [
            SecretListing(
                key=r.key,
                description=r.description,
                status=SecretStatus(r.status),
                version_id=r.current_version,
                last_rotated_at=r.last_rotated_at,
                last_accessed_at=r.last_accessed_at,
                accessed_count=r.accessed_count,
                created_at=r.created_at,
            )
            for r in res.scalars()
        ]

    # ── Rotate ────────────────────────────────────────────────────────

    async def rotate_secret(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        key: str,
        new_value: SecretValue,
        user_id: UUID | None = None,
    ) -> TenantSecret:
        """New AWS SM version; AWSPREVIOUS is demoted automatically."""
        canonical_key = self.policy.normalise_and_validate_key(key)
        row = await self._require_active_row(
            db, tenant_id=tenant_id, key=canonical_key
        )
        entry = await self.backend.rotate(row.storage_path, new_value)

        now = datetime.now(timezone.utc)
        row.current_version = entry.version_id
        row.last_rotated_by = user_id
        row.last_rotated_at = now
        await db.flush()

        await self.audit.emit(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type="secret:rotate",
            key=canonical_key,
            fingerprint=new_value.fingerprint,
            details={"version_id": entry.version_id},
        )
        return row

    # ── Delete ────────────────────────────────────────────────────────

    async def schedule_deletion(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        key: str,
        user_id: UUID | None = None,
    ) -> TenantSecret:
        """Soft-delete with the configured recovery window."""
        canonical_key = self.policy.normalise_and_validate_key(key)
        row = await self._require_active_row(
            db, tenant_id=tenant_id, key=canonical_key
        )
        await self.backend.delete(
            row.storage_path,
            recovery_window_days=self.settings.deletion_recovery_window_days,
        )
        now = datetime.now(timezone.utc)
        row.status = SecretStatus.DELETED_PENDING.value
        # Mirror AWS SM's recovery window.
        from datetime import timedelta

        row.deleted_pending_until = now + timedelta(
            days=self.settings.deletion_recovery_window_days
        )
        await db.flush()

        await self.audit.emit(
            tenant_id=tenant_id,
            user_id=user_id,
            event_type="secret:delete_scheduled",
            key=canonical_key,
            details={
                "recovery_window_days": self.settings.deletion_recovery_window_days
            },
        )
        return row

    # ── Internals ─────────────────────────────────────────────────────

    async def _find_row(
        self, db: AsyncSession, *, tenant_id: str, key: str
    ) -> TenantSecret | None:
        return await db.scalar(
            select(TenantSecret).where(
                TenantSecret.tenant_id == tenant_id,
                TenantSecret.key == key,
            )
        )

    async def _require_active_row(
        self, db: AsyncSession, *, tenant_id: str, key: str
    ) -> TenantSecret:
        row = await self._find_row(db, tenant_id=tenant_id, key=key)
        if row is None or row.status == SecretStatus.DELETED.value:
            raise SecretNotFound(key)
        return row
