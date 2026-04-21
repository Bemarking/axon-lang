"""Integration — ErasureService soft-delete + anonymize + legal-hold guard."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from axon_enterprise.compliance.erasure import ErasureService
from axon_enterprise.compliance.errors import LegalHoldActive
from axon_enterprise.compliance.legal_holds import LegalHoldService
from axon_enterprise.compliance.local_blob_store import LocalBlobStore
from axon_enterprise.config import ComplianceSettings
from axon_enterprise.identity.models import (
    MembershipStatus,
    Session,
    TenantMembership,
    User,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def session(migrated_db: AsyncEngine) -> AsyncIterator:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        yield s


def _service(tmp_path: Path) -> ErasureService:
    settings = ComplianceSettings(
        blob_local_path=tmp_path, erasure_soft_delete_days=0
    )
    return ErasureService.default(blob=LocalBlobStore(settings=settings))


@pytest.mark.asyncio
async def test_soft_delete_revokes_sessions_and_flips_membership(
    session, tmp_path: Path
) -> None:
    email = f"erase-{uuid4().hex[:6]}@example.com"
    user = User(email=email, display_name="To Erase")
    session.add(user)
    await session.flush()
    session.add(
        TenantMembership(
            tenant_id="alpha",
            user_id=user.user_id,
            status=MembershipStatus.ACTIVE.value,
        )
    )
    session.add(
        Session(
            session_id=uuid4(),
            tenant_id="alpha",
            user_id=user.user_id,
            refresh_token_hash=b"x" * 32,
            expires_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()

    svc = _service(tmp_path)
    request_id = uuid4()
    result = await svc.soft_delete(
        session,
        tenant_id="alpha",
        subject_email=email,
        requested_by=None,
        request_id=request_id,
    )
    await session.commit()

    assert result.sessions_revoked == 1
    membership = await session.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == "alpha",
            TenantMembership.user_id == user.user_id,
        )
    )
    assert membership is not None
    assert membership.status == MembershipStatus.ERASED_PENDING.value


@pytest.mark.asyncio
async def test_legal_hold_blocks_soft_delete(session, tmp_path: Path) -> None:
    email = f"hold-{uuid4().hex[:6]}@example.com"
    user = User(email=email)
    session.add(user)
    await session.flush()

    await LegalHoldService.default().apply(
        session,
        tenant_id="alpha",
        subject_email=email,
        matter="FTC investigation #2026-04",
    )
    await session.commit()

    svc = _service(tmp_path)
    with pytest.raises(LegalHoldActive):
        await svc.soft_delete(
            session,
            tenant_id="alpha",
            subject_email=email,
            requested_by=None,
            request_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_anonymize_scrubs_pii_and_writes_purge_report(
    session, tmp_path: Path
) -> None:
    email = f"anon-{uuid4().hex[:6]}@example.com"
    user = User(email=email, display_name="Will Anon", password_hash="$argon2id$abc")
    session.add(user)
    await session.flush()
    session.add(
        TenantMembership(
            tenant_id="alpha",
            user_id=user.user_id,
            status=MembershipStatus.ACTIVE.value,
        )
    )
    await session.commit()

    svc = _service(tmp_path)
    request_id = uuid4()
    result = await svc.anonymize(
        session,
        tenant_id="alpha",
        subject_email=email,
        request_id=request_id,
    )
    await session.commit()

    refreshed = await session.get(User, user.user_id)
    assert refreshed is not None
    assert refreshed.email != email
    assert refreshed.email.startswith("erased-") and refreshed.email.endswith("@axon.internal")
    assert refreshed.display_name == "[erased]"
    assert refreshed.password_hash is None

    membership = await session.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == "alpha",
            TenantMembership.user_id == user.user_id,
        )
    )
    assert membership is not None
    assert membership.status == MembershipStatus.ERASED.value

    # Purge report landed in the local blob store.
    assert result.size_bytes > 0
    assert result.uri.startswith("file://")
