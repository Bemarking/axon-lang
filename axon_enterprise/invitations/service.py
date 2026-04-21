"""InvitationService — magic-link lifecycle over ``tenant_memberships``.

No new table. We store:

    invitation_token_hash: BYTEA  = SHA-256(raw_token)
    invitation_expires_at: TIMESTAMPTZ

in ``tenant_memberships``. On accept, both columns are cleared +
``status`` flips to 'active'. Replay of the same token → miss on
``invitation_token_hash`` lookup → ``InvitationNotFound``.

Default TTL: 72 hours. Short enough that lost emails force
operators to re-invite; long enough to survive a long weekend.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import NamedTuple
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.identity import MembershipStatus, TenantMembership
from axon_enterprise.invitations.errors import (
    InvitationAlreadyAccepted,
    InvitationExpired,
    InvitationNotFound,
)

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.invitations.service"
)


class InvitationIssued(NamedTuple):
    tenant_id: str
    user_id: UUID
    raw_token: str
    expires_at: datetime


@dataclass
class InvitationService:
    """Issue + redeem + consume magic-link invitations."""

    ttl_hours: int = 72

    # ── Issue ─────────────────────────────────────────────────────────

    async def invite(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        user_id: UUID,
        invited_by: UUID | None = None,
    ) -> InvitationIssued:
        """Upsert the membership + mint a magic-link token."""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=self.ttl_hours)
        raw = secrets.token_urlsafe(32)
        digest = hashlib.sha256(raw.encode("ascii")).digest()

        existing = await db.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.user_id == user_id,
            )
        )
        if existing is None:
            row = TenantMembership(
                tenant_id=tenant_id,
                user_id=user_id,
                status=MembershipStatus.INVITED.value,
                invited_by=invited_by,
                invitation_token_hash=digest,
                invitation_expires_at=expires,
            )
            db.add(row)
        elif existing.status == MembershipStatus.ACTIVE.value:
            # User is already a member — no-op token; caller surfaces
            # InvitationAlreadyAccepted to the portal so they stop
            # showing an "invite pending" banner.
            raise InvitationAlreadyAccepted(str(user_id))
        else:
            existing.invitation_token_hash = digest
            existing.invitation_expires_at = expires
            existing.invited_by = invited_by

        await db.flush()
        _logger.info(
            "invitation_issued",
            tenant_id=tenant_id,
            user_id=str(user_id),
            expires_at=expires.isoformat(),
        )
        return InvitationIssued(
            tenant_id=tenant_id,
            user_id=user_id,
            raw_token=raw,
            expires_at=expires,
        )

    # ── Accept ────────────────────────────────────────────────────────

    async def accept(
        self,
        db: AsyncSession,
        *,
        raw_token: str,
    ) -> TenantMembership:
        """Verify + consume the token. Raises on any failure path."""
        digest = hashlib.sha256(raw_token.encode("ascii")).digest()
        row = await db.scalar(
            select(TenantMembership).where(
                TenantMembership.invitation_token_hash == digest
            )
        )
        if row is None:
            raise InvitationNotFound("token not recognised")
        now = datetime.now(timezone.utc)
        if (
            row.invitation_expires_at is None
            or row.invitation_expires_at <= now
        ):
            raise InvitationExpired(str(row.user_id))

        row.status = MembershipStatus.ACTIVE.value
        row.joined_at = now
        row.invitation_token_hash = None
        row.invitation_expires_at = None
        await db.flush()
        _logger.info(
            "invitation_accepted",
            tenant_id=row.tenant_id,
            user_id=str(row.user_id),
        )
        return row

    # ── Revoke / cleanup ──────────────────────────────────────────────

    async def revoke(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        user_id: UUID,
    ) -> None:
        """Clear a pending invite without flipping to active."""
        await db.execute(
            update(TenantMembership)
            .where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.user_id == user_id,
                TenantMembership.status == MembershipStatus.INVITED.value,
            )
            .values(
                invitation_token_hash=None,
                invitation_expires_at=None,
            )
        )
        await db.flush()
