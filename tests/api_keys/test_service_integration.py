"""Integration tests for ``ApiKeyService`` against a real Postgres.

Covers:
    - create → raw key surfaces exactly once with the ``axk_`` prefix
    - create → only the Argon2id hash is persisted
    - verify happy-path returns tenant + created_by
    - verify rejects mangled input
    - verify rejects revoked key (``ApiKeyRevoked``)
    - verify rejects expired key (``ApiKeyExpired``)
    - list_for_tenant is tenant-scoped + ordered newest-first
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from axon_enterprise.api_keys import (
    ApiKeyExpired,
    ApiKeyInvalid,
    ApiKeyRevoked,
    ApiKeyService,
)
from axon_enterprise.config import IdentitySettings
from axon_enterprise.identity.password import PasswordHasher

pytestmark = pytest.mark.integration


def _fast_hasher() -> PasswordHasher:
    return PasswordHasher(
        settings=IdentitySettings(
            argon2_time_cost=2,
            argon2_memory_cost_kib=19_456,
            argon2_parallelism=1,
            password_min_length=12,
            password_zxcvbn_min_score=0,
            password_check_hibp=False,
        )
    )


@pytest_asyncio.fixture
async def svc() -> ApiKeyService:
    return ApiKeyService(hasher=_fast_hasher())


@pytest_asyncio.fixture
async def session(migrated_db: AsyncEngine) -> AsyncIterator:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as s:
        yield s


@pytest.mark.asyncio
async def test_create_returns_raw_key_exactly_once(svc, session) -> None:
    issued = await svc.create(session, tenant_id="alpha", name="ci-pipeline")
    await session.commit()

    assert issued.raw_key.startswith("axk_")
    assert len(issued.raw_key) == len("axk_") + 32
    # The DB row stores only the Argon2 hash + prefix, never the raw key.
    assert issued.row.key_hash.startswith("$argon2id$")
    assert issued.raw_key not in issued.row.key_hash
    assert issued.row.key_prefix == issued.raw_key[len("axk_") :][:8]
    assert issued.row.tenant_id == "alpha"


@pytest.mark.asyncio
async def test_verify_happy_path(svc, session) -> None:
    issued = await svc.create(session, tenant_id="alpha", name="ci")
    await session.commit()

    resolved = await svc.verify(session, raw_key=issued.raw_key)
    assert resolved.tenant_id == "alpha"
    assert resolved.api_key_id == issued.row.api_key_id
    assert resolved.name == "ci"


@pytest.mark.asyncio
async def test_verify_rejects_malformed(svc, session) -> None:
    with pytest.raises(ApiKeyInvalid):
        await svc.verify(session, raw_key="not-an-axon-key")


@pytest.mark.asyncio
async def test_verify_rejects_revoked(svc, session) -> None:
    issued = await svc.create(session, tenant_id="alpha", name="ci")
    await session.commit()
    await svc.revoke(
        session, api_key_id=issued.row.api_key_id, tenant_id="alpha"
    )
    await session.commit()

    with pytest.raises(ApiKeyRevoked):
        await svc.verify(session, raw_key=issued.raw_key)


@pytest.mark.asyncio
async def test_verify_rejects_expired(svc, session) -> None:
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    issued = await svc.create(
        session, tenant_id="alpha", name="short-lived", expires_at=past
    )
    await session.commit()

    with pytest.raises(ApiKeyExpired):
        await svc.verify(session, raw_key=issued.raw_key)


@pytest.mark.asyncio
async def test_list_for_tenant_scoped_and_ordered(svc, session) -> None:
    a1 = await svc.create(session, tenant_id="alpha", name="one")
    a2 = await svc.create(session, tenant_id="alpha", name="two")
    b1 = await svc.create(session, tenant_id="beta", name="other")
    await session.commit()

    alpha = await svc.list_for_tenant(session, tenant_id="alpha")
    alpha_ids = {r.api_key_id for r in alpha}
    assert alpha_ids == {a1.row.api_key_id, a2.row.api_key_id}
    assert b1.row.api_key_id not in alpha_ids

    beta = await svc.list_for_tenant(session, tenant_id="beta")
    assert [r.api_key_id for r in beta] == [b1.row.api_key_id]


@pytest.mark.asyncio
async def test_revoke_twice_raises(svc, session) -> None:
    issued = await svc.create(session, tenant_id="alpha", name="x")
    await session.commit()
    await svc.revoke(
        session, api_key_id=issued.row.api_key_id, tenant_id="alpha"
    )
    await session.commit()
    with pytest.raises(ApiKeyInvalid):
        await svc.revoke(
            session, api_key_id=issued.row.api_key_id, tenant_id="alpha"
        )
