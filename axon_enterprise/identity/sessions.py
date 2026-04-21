"""Session issuance + refresh-token rotation.

Refresh tokens are 64 random bytes (``secrets.token_bytes``) rendered
as URL-safe base64 so the wire representation is ASCII. Only the
SHA-256 of the token is persisted — loss of the DB does not reveal
the refresh secrets.

Rotation discipline: every successful ``verify_and_rotate`` mints a
new token and marks the previous session row ``revoked`` with reason
``"rotated"``. Presenting an already-rotated token is treated as a
potential replay attempt: the service revokes the entire rotation
chain for that user + tenant and raises ``SessionExpiredError`` so
the client is forced to re-authenticate.

Expiration:

    absolute        = created_at + session_absolute_ttl_days
    inactivity      = last_used_at + session_inactivity_ttl_hours
    expires_at      = min(absolute, inactivity)  (recomputed on each refresh)

Stored ``expires_at`` reflects the absolute TTL; inactivity is
enforced dynamically at verify time because ``last_used_at`` moves.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.config import IdentitySettings, get_settings
from axon_enterprise.identity.errors import SessionExpiredError
from axon_enterprise.identity.models import Session, SessionStatus


class IssuedSession(NamedTuple):
    """What the caller gets after ``create`` / ``verify_and_rotate``."""

    session: Session
    raw_refresh_token: str  # only returned once; client must store it


# Back-compat alias used in ``identity.__init__`` exports.
issued_session_token = IssuedSession


@dataclass(frozen=True)
class SessionService:
    """Persistence-bound session issuance + rotation."""

    settings: IdentitySettings

    @classmethod
    def default(cls) -> SessionService:
        return cls(settings=get_settings().identity)

    # ── Token helpers ─────────────────────────────────────────────────

    def _mint_raw_token(self) -> str:
        return secrets.token_urlsafe(self.settings.session_refresh_token_bytes)

    @staticmethod
    def hash_token(raw: str) -> bytes:
        """Deterministic SHA-256 of the raw token for indexed lookup.

        SHA-256 (not HMAC) because the stored hash doesn't need the
        secret-key property: an attacker with the hash still can't
        forge a token (needs a 64-byte preimage).
        """
        return hashlib.sha256(raw.encode("utf-8")).digest()

    # ── Create ────────────────────────────────────────────────────────

    async def create(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        tenant_id: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> IssuedSession:
        """Mint a fresh session for ``(user_id, tenant_id)``.

        Caller is responsible for having set the tenant GUC before
        invoking — i.e. use ``tenant_session(ctx)`` or equivalent.
        """
        raw = self._mint_raw_token()
        now = datetime.now(timezone.utc)
        absolute_exp = now + timedelta(days=self.settings.session_absolute_ttl_days)

        row = Session(
            user_id=user_id,
            tenant_id=tenant_id,
            refresh_token_hash=self.hash_token(raw),
            user_agent=user_agent,
            ip_address=ip_address,
            expires_at=absolute_exp,
            last_used_at=now,
        )
        db.add(row)
        await db.flush()
        return IssuedSession(session=row, raw_refresh_token=raw)

    # ── Verify + rotate ───────────────────────────────────────────────

    async def verify_and_rotate(
        self,
        db: AsyncSession,
        *,
        raw_refresh_token: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> IssuedSession:
        """Validate ``raw_refresh_token``, rotate, return new session.

        Raises ``SessionExpiredError`` on any failure path — the client
        response must be identical regardless of the cause to avoid
        enumeration.
        """
        now = datetime.now(timezone.utc)
        hashed = self.hash_token(raw_refresh_token)

        row = await db.scalar(
            select(Session).where(Session.refresh_token_hash == hashed)
        )
        if row is None:
            raise SessionExpiredError()
        if row.revoked_at is not None:
            # Replay detection: someone is using an already-rotated
            # token. Revoke every live session for the user so the
            # attacker plus the legitimate client are both forced to
            # re-authenticate.
            await self._revoke_all_for_user(
                db, user_id=row.user_id, tenant_id=row.tenant_id, reason="replay"
            )
            raise SessionExpiredError()

        # Absolute expiry
        if row.expires_at <= now:
            await self._revoke(db, row, reason="expired_absolute", now=now)
            raise SessionExpiredError()

        # Inactivity expiry
        inactivity_cutoff = row.last_used_at + timedelta(
            hours=self.settings.session_inactivity_ttl_hours
        )
        if inactivity_cutoff <= now:
            await self._revoke(db, row, reason="expired_inactivity", now=now)
            raise SessionExpiredError()

        # Mint successor
        new_raw = self._mint_raw_token()
        successor = Session(
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            refresh_token_hash=self.hash_token(new_raw),
            user_agent=user_agent or row.user_agent,
            ip_address=ip_address or row.ip_address,
            # Preserve absolute expiry — rotation does NOT extend max life.
            expires_at=row.expires_at,
            last_used_at=now,
            sequence=row.sequence + 1,
        )
        db.add(successor)
        await db.flush()

        # Revoke predecessor, link the chain.
        row.revoked_at = now
        row.revoked_reason = "rotated"
        row.rotated_to_session_id = successor.session_id
        await db.flush()

        return IssuedSession(session=successor, raw_refresh_token=new_raw)

    # ── Revoke ────────────────────────────────────────────────────────

    async def revoke(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        reason: str = "user_request",
    ) -> None:
        row = await db.get(Session, session_id)
        if row is None or row.revoked_at is not None:
            return
        await self._revoke(db, row, reason=reason)

    async def revoke_all_for_user(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        tenant_id: str,
        reason: str = "user_request",
    ) -> int:
        return await self._revoke_all_for_user(
            db, user_id=user_id, tenant_id=tenant_id, reason=reason
        )

    # ── Internals ─────────────────────────────────────────────────────

    async def _revoke(
        self,
        db: AsyncSession,
        row: Session,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> None:
        row.revoked_at = now or datetime.now(timezone.utc)
        row.revoked_reason = reason
        await db.flush()

    async def _revoke_all_for_user(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        tenant_id: str,
        reason: str,
    ) -> int:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            update(Session)
            .where(
                Session.user_id == user_id,
                Session.tenant_id == tenant_id,
                Session.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoked_reason=reason)
        )
        return int(result.rowcount or 0)

    # ── Read helpers ──────────────────────────────────────────────────

    @staticmethod
    def derive_status(row: Session, *, now: datetime | None = None) -> SessionStatus:
        """Compute the effective status of a session row."""
        now = now or datetime.now(timezone.utc)
        if row.revoked_at is not None:
            return SessionStatus.REVOKED
        if row.expires_at <= now:
            return SessionStatus.EXPIRED
        return SessionStatus.ACTIVE
