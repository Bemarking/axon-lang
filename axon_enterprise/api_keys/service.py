"""ApiKeyService — generate + verify + revoke.

Raw key shape: ``axk_<32-hex-uuid>``. The prefix ``axk_`` is stable
across all tenants; the 32 hex chars are a UUID4. Lookup indexes
the first 8 of those hex chars so the verify-time SELECT touches
at most one row per tenant (Argon2 verify is expensive — we run
it exactly once per request).

Creation contract
-----------------
``create()`` returns ``ApiKeyIssued`` carrying the raw key ONCE.
The caller (HTTP handler) echoes it into the response body with a
one-time warning; subsequent reads return only the metadata.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import NamedTuple
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.api_keys.errors import (
    ApiKeyExpired,
    ApiKeyInvalid,
    ApiKeyRevoked,
)
from axon_enterprise.api_keys.models import TenantApiKey
from axon_enterprise.identity.password import PasswordHasher

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.api_keys.service"
)


_PREFIX = "axk_"


class ApiKeyIssued(NamedTuple):
    """Returned from ``create`` — raw key exposed exactly once."""

    raw_key: str
    row: TenantApiKey


class VerifiedApiKey(NamedTuple):
    """Returned from ``verify`` — tenant + user context resolved."""

    api_key_id: UUID
    tenant_id: str
    created_by: UUID | None
    name: str


@dataclass
class ApiKeyService:
    """Typed API for the portal + verification paths."""

    hasher: PasswordHasher

    @classmethod
    def default(cls) -> ApiKeyService:
        return cls(hasher=PasswordHasher.default())

    # ── Create ────────────────────────────────────────────────────────

    async def create(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        name: str,
        created_by: UUID | None = None,
        expires_at: datetime | None = None,
    ) -> ApiKeyIssued:
        if not name.strip():
            raise ValueError("api key name must be non-empty")

        uid = uuid4()
        raw = f"{_PREFIX}{uid.hex}"
        prefix = uid.hex[:8]

        row = TenantApiKey(
            tenant_id=tenant_id,
            name=name.strip(),
            key_prefix=prefix,
            key_hash=self.hasher.hash(raw),
            hash_algo="argon2id",
            created_by=created_by,
            expires_at=expires_at,
        )
        db.add(row)
        await db.flush()
        _logger.info(
            "api_key_created",
            tenant_id=tenant_id,
            api_key_id=str(row.api_key_id),
            name=row.name,
        )
        return ApiKeyIssued(raw_key=raw, row=row)

    # ── Verify ────────────────────────────────────────────────────────

    async def verify(
        self,
        db: AsyncSession,
        *,
        raw_key: str,
        ip_address: str | None = None,
    ) -> VerifiedApiKey:
        """Resolve + authenticate a raw key. Raises on any failure path."""
        if not raw_key.startswith(_PREFIX) or len(raw_key) != len(_PREFIX) + 32:
            raise ApiKeyInvalid("malformed")

        hex_body = raw_key[len(_PREFIX) :]
        prefix = hex_body[:8]

        # Narrow by prefix; prefix+tenant_id is unique so at most one
        # row matches per tenant. We MUST verify against every tenant's
        # row whose prefix matches — in practice this is O(1-2) rows
        # because prefix is 32 bits of entropy.
        rows = list(
            (
                await db.execute(
                    select(TenantApiKey).where(TenantApiKey.key_prefix == prefix)
                )
            ).scalars()
        )
        now = datetime.now(timezone.utc)

        verified: TenantApiKey | None = None
        for candidate in rows:
            try:
                self.hasher.verify(candidate.key_hash, raw_key)
            except Exception:  # noqa: BLE001
                continue
            verified = candidate
            break

        if verified is None:
            raise ApiKeyInvalid("no match")
        if verified.revoked_at is not None:
            raise ApiKeyRevoked(str(verified.api_key_id))
        if verified.expires_at is not None and verified.expires_at <= now:
            raise ApiKeyExpired(str(verified.api_key_id))

        # Bookkeeping — fire-and-forget UPDATE.
        await db.execute(
            update(TenantApiKey)
            .where(TenantApiKey.api_key_id == verified.api_key_id)
            .values(last_used_at=now, last_used_ip=ip_address)
        )
        await db.flush()

        return VerifiedApiKey(
            api_key_id=verified.api_key_id,
            tenant_id=verified.tenant_id,
            created_by=verified.created_by,
            name=verified.name,
        )

    # ── List + Revoke ────────────────────────────────────────────────

    async def list_for_tenant(
        self, db: AsyncSession, *, tenant_id: str
    ) -> list[TenantApiKey]:
        res = await db.execute(
            select(TenantApiKey)
            .where(TenantApiKey.tenant_id == tenant_id)
            .order_by(TenantApiKey.created_at.desc())
        )
        return list(res.scalars())

    async def revoke(
        self,
        db: AsyncSession,
        *,
        api_key_id: UUID,
        tenant_id: str,
    ) -> None:
        result = await db.execute(
            update(TenantApiKey)
            .where(
                TenantApiKey.api_key_id == api_key_id,
                TenantApiKey.tenant_id == tenant_id,
                TenantApiKey.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
        if (result.rowcount or 0) == 0:
            raise ApiKeyInvalid("not found or already revoked")
        await db.flush()
        _logger.info("api_key_revoked", api_key_id=str(api_key_id))
