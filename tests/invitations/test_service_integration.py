"""Integration tests for ``InvitationService``.

Covers:
    - invite creates a ``status='invited'`` membership with hashed token
    - accept flips ``status='active'`` + clears token hash
    - accept of a consumed token → ``InvitationNotFound`` (replay)
    - accept of an expired token → ``InvitationExpired``
    - invite on an already-active member → ``InvitationAlreadyAccepted``
    - revoke clears the pending token without activating
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from axon_enterprise.identity import (
    MembershipStatus,
    TenantMembership,
    User,
)
from axon_enterprise.invitations import (
    InvitationAlreadyAccepted,
    InvitationExpired,
    InvitationNotFound,
    InvitationService,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def session(migrated_db: AsyncEngine) -> AsyncIterator:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        yield s


async def _seed_user(session, email: str) -> User:
    user = User(email=email, display_name="Tester")
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_invite_creates_pending_membership_with_hashed_token(
    session,
) -> None:
    user = await _seed_user(session, f"user-{uuid4().hex[:6]}@example.com")
    svc = InvitationService()

    issued = await svc.invite(
        session, tenant_id="alpha", user_id=user.user_id
    )
    await session.commit()

    row = await session.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == "alpha",
            TenantMembership.user_id == user.user_id,
        )
    )
    assert row is not None
    assert row.status == MembershipStatus.INVITED.value
    assert row.invitation_token_hash is not None
    # Raw token must not leak into the stored hash bytes.
    assert issued.raw_token.encode("ascii") != bytes(row.invitation_token_hash)
    # SHA-256 = 32 bytes.
    assert len(bytes(row.invitation_token_hash)) == 32


@pytest.mark.asyncio
async def test_accept_consumes_token_and_activates(session) -> None:
    user = await _seed_user(session, f"accept-{uuid4().hex[:6]}@example.com")
    svc = InvitationService()
    issued = await svc.invite(
        session, tenant_id="alpha", user_id=user.user_id
    )
    await session.commit()

    accepted = await svc.accept(session, raw_token=issued.raw_token)
    await session.commit()

    assert accepted.status == MembershipStatus.ACTIVE.value
    assert accepted.invitation_token_hash is None
    assert accepted.invitation_expires_at is None
    assert accepted.joined_at is not None


@pytest.mark.asyncio
async def test_accept_rejects_replay(session) -> None:
    user = await _seed_user(session, f"replay-{uuid4().hex[:6]}@example.com")
    svc = InvitationService()
    issued = await svc.invite(
        session, tenant_id="alpha", user_id=user.user_id
    )
    await session.commit()
    await svc.accept(session, raw_token=issued.raw_token)
    await session.commit()

    with pytest.raises(InvitationNotFound):
        await svc.accept(session, raw_token=issued.raw_token)


@pytest.mark.asyncio
async def test_accept_rejects_expired(session) -> None:
    user = await _seed_user(session, f"expired-{uuid4().hex[:6]}@example.com")
    svc = InvitationService()
    issued = await svc.invite(
        session, tenant_id="alpha", user_id=user.user_id
    )
    row = await session.scalar(
        select(TenantMembership).where(
            TenantMembership.user_id == user.user_id,
            TenantMembership.tenant_id == "alpha",
        )
    )
    assert row is not None
    row.invitation_expires_at = datetime.now(timezone.utc) - timedelta(
        seconds=1
    )
    await session.commit()

    with pytest.raises(InvitationExpired):
        await svc.accept(session, raw_token=issued.raw_token)


@pytest.mark.asyncio
async def test_invite_on_active_member_raises(session) -> None:
    user = await _seed_user(session, f"active-{uuid4().hex[:6]}@example.com")
    svc = InvitationService()
    issued = await svc.invite(
        session, tenant_id="alpha", user_id=user.user_id
    )
    await session.commit()
    await svc.accept(session, raw_token=issued.raw_token)
    await session.commit()

    with pytest.raises(InvitationAlreadyAccepted):
        await svc.invite(
            session, tenant_id="alpha", user_id=user.user_id
        )


@pytest.mark.asyncio
async def test_revoke_clears_token_without_activating(session) -> None:
    user = await _seed_user(session, f"revoke-{uuid4().hex[:6]}@example.com")
    svc = InvitationService()
    issued = await svc.invite(
        session, tenant_id="alpha", user_id=user.user_id
    )
    await session.commit()

    await svc.revoke(
        session, tenant_id="alpha", user_id=user.user_id
    )
    await session.commit()

    row = await session.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == "alpha",
            TenantMembership.user_id == user.user_id,
        )
    )
    assert row is not None
    assert row.invitation_token_hash is None
    assert row.invitation_expires_at is None
    # Membership remains INVITED — revoke only cancels the token.
    assert row.status == MembershipStatus.INVITED.value

    with pytest.raises(InvitationNotFound):
        await svc.accept(session, raw_token=issued.raw_token)
