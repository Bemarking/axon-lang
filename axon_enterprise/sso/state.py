"""SsoStateService — short-lived state/nonce tracking across the SSO flow.

Every SSO login generates:

    state           URL-safe random (32+ bytes) shared with the IdP in
                    the authorization URL; returned by the IdP in the
                    callback. Prevents CSRF / response stealing.

    nonce           (OIDC only) URL-safe random embedded in the
                    authorization URL; must match the ``nonce`` claim
                    in the returned ID token. Prevents token replay
                    between sessions.

    code_verifier   (OIDC PKCE) Random secret; the authorization URL
                    carries only ``code_challenge = SHA-256(verifier)``.
                    On token exchange we send the raw ``verifier``;
                    any mismatch fails the exchange at the IdP.

Rows are TTL-bounded (10 min default) and single-use — the ``consumed_at``
column flips on first successful ``consume()``; a replay of the same
state raises ``SsoStateAlreadyConsumed`` so a stolen authorization
code is worth nothing.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.config import SsoSettings, get_settings
from axon_enterprise.sso.errors import (
    SsoStateAlreadyConsumed,
    SsoStateExpired,
    SsoStateInvalid,
)
from axon_enterprise.sso.models import SsoProviderType, SsoState

_logger: structlog.stdlib.BoundLogger = structlog.get_logger("axon_enterprise.sso.state")


@dataclass(frozen=True)
class StoredState:
    """What ``consume()`` returns for the caller to match against the IdP response."""

    state_id: UUID
    tenant_id: str
    provider_type: SsoProviderType
    state: str
    nonce: str | None
    code_verifier: str | None
    return_url: str | None
    issuer: str | None


@dataclass(frozen=True)
class SsoStateService:
    """Persistence-bound state tracker."""

    settings: SsoSettings

    @classmethod
    def default(cls) -> SsoStateService:
        return cls(settings=get_settings().sso)

    # ── Create ────────────────────────────────────────────────────────

    async def create(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        provider_type: SsoProviderType,
        nonce: str | None = None,
        code_verifier: str | None = None,
        return_url: str | None = None,
        issuer: str | None = None,
    ) -> StoredState:
        """Mint a fresh state row. Caller combines ``state`` into the auth URL."""
        state = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self.settings.state_ttl_seconds)

        row = SsoState(
            tenant_id=tenant_id,
            provider_type=provider_type.value,
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
            return_url=return_url,
            issuer=issuer,
            expires_at=expires_at,
        )
        db.add(row)
        await db.flush()
        return StoredState(
            state_id=row.state_id,
            tenant_id=tenant_id,
            provider_type=provider_type,
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
            return_url=return_url,
            issuer=issuer,
        )

    # ── Consume ───────────────────────────────────────────────────────

    async def consume(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        state: str,
    ) -> StoredState:
        """Look up and mark consumed. Raises on missing / expired / replayed."""
        row = await db.scalar(
            select(SsoState).where(
                SsoState.tenant_id == tenant_id, SsoState.state == state
            )
        )
        now = datetime.now(timezone.utc)
        if row is None:
            raise SsoStateInvalid(f"state={state!r}")
        if row.consumed_at is not None:
            _logger.warning(
                "sso_state_replay",
                tenant_id=tenant_id,
                state_id=str(row.state_id),
            )
            raise SsoStateAlreadyConsumed(str(row.state_id))
        if row.expires_at <= now:
            raise SsoStateExpired(str(row.state_id))

        row.consumed_at = now
        await db.flush()

        return StoredState(
            state_id=row.state_id,
            tenant_id=tenant_id,
            provider_type=SsoProviderType(row.provider_type),
            state=row.state,
            nonce=row.nonce,
            code_verifier=row.code_verifier,
            return_url=row.return_url,
            issuer=row.issuer,
        )

    # ── Housekeeping ──────────────────────────────────────────────────

    async def purge_expired(self, db: AsyncSession) -> int:
        """Delete rows past ``expires_at``. Safe to call from a cron job."""
        from sqlalchemy import delete

        now = datetime.now(timezone.utc)
        result = await db.execute(
            delete(SsoState).where(SsoState.expires_at <= now)
        )
        await db.flush()
        return int(result.rowcount or 0)
