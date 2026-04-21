"""Integration tests for SsoConfigurationService + SsoStateService + RLS."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from axon_enterprise.config import SsoSettings
from axon_enterprise.crypto import LocalEnvelopeEncryption
from axon_enterprise.sso import (
    SsoConfigurationNotFound,
    SsoProviderType,
    SsoStateAlreadyConsumed,
    SsoStateExpired,
    SsoStateInvalid,
)
from axon_enterprise.sso.configurations import SsoConfigurationService
from axon_enterprise.sso.state import SsoStateService

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def admin_db(migrated_db: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            yield session


@pytest_asyncio.fixture
async def _clean_sso(migrated_db: AsyncEngine) -> AsyncIterator[None]:
    yield
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "TRUNCATE axon_control.sso_assertion_seen, "
                    "axon_control.sso_states, "
                    "axon_control.sso_configurations CASCADE"
                )
            )


@pytest.fixture
def local_envelope() -> LocalEnvelopeEncryption:
    import base64
    import os as _os

    key = base64.urlsafe_b64encode(_os.urandom(32)).decode("ascii")
    return LocalEnvelopeEncryption.from_base64(key)


# ── Configuration envelope round-trip ─────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_then_get_returns_decrypted_payload(
    admin_db: AsyncSession,
    local_envelope: LocalEnvelopeEncryption,
    _clean_sso: None,
) -> None:
    svc = SsoConfigurationService(envelope=local_envelope)
    payload = {
        "issuer": "https://idp.example.com",
        "client_id": "client-abc",
        "client_secret": "shhh-secret",
        "redirect_uri": "https://auth.example.com/cb",
    }
    await svc.upsert(
        admin_db,
        tenant_id="alpha",
        provider_type=SsoProviderType.OIDC,
        payload=payload,
        attribute_map={"email": "email"},
    )

    resolved = await svc.get(
        admin_db, tenant_id="alpha", provider_type=SsoProviderType.OIDC
    )
    assert resolved.payload == payload
    assert resolved.attribute_map == {"email": "email"}


@pytest.mark.asyncio
async def test_ciphertext_not_stored_in_plaintext(
    admin_db: AsyncSession,
    local_envelope: LocalEnvelopeEncryption,
    _clean_sso: None,
) -> None:
    svc = SsoConfigurationService(envelope=local_envelope)
    await svc.upsert(
        admin_db,
        tenant_id="alpha",
        provider_type=SsoProviderType.OIDC,
        payload={
            "issuer": "https://x",
            "client_id": "c",
            "client_secret": "SUPER-SECRET-TOKEN-XYZ",
            "redirect_uri": "https://cb",
        },
    )
    # Verify the secret does NOT appear in the raw row bytes.
    row = (
        await admin_db.execute(
            text(
                "SELECT config_encrypted FROM axon_control.sso_configurations "
                "WHERE tenant_id = 'alpha'"
            )
        )
    ).scalar_one()
    assert b"SUPER-SECRET-TOKEN-XYZ" not in bytes(row)


@pytest.mark.asyncio
async def test_get_raises_when_not_configured(
    admin_db: AsyncSession,
    local_envelope: LocalEnvelopeEncryption,
    _clean_sso: None,
) -> None:
    svc = SsoConfigurationService(envelope=local_envelope)
    with pytest.raises(SsoConfigurationNotFound):
        await svc.get(
            admin_db, tenant_id="alpha", provider_type=SsoProviderType.OIDC
        )


# ── State lifecycle ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_state_create_then_consume(
    admin_db: AsyncSession, _clean_sso: None
) -> None:
    svc = SsoStateService(settings=SsoSettings(state_ttl_seconds=600))
    stored = await svc.create(
        admin_db,
        tenant_id="alpha",
        provider_type=SsoProviderType.OIDC,
        nonce="noncy",
        code_verifier="verrr",
    )
    consumed = await svc.consume(
        admin_db, tenant_id="alpha", state=stored.state
    )
    assert consumed.nonce == "noncy"
    assert consumed.code_verifier == "verrr"


@pytest.mark.asyncio
async def test_state_replay_rejected(
    admin_db: AsyncSession, _clean_sso: None
) -> None:
    svc = SsoStateService(settings=SsoSettings(state_ttl_seconds=600))
    stored = await svc.create(
        admin_db,
        tenant_id="alpha",
        provider_type=SsoProviderType.OIDC,
    )
    await svc.consume(admin_db, tenant_id="alpha", state=stored.state)
    with pytest.raises(SsoStateAlreadyConsumed):
        await svc.consume(admin_db, tenant_id="alpha", state=stored.state)


@pytest.mark.asyncio
async def test_state_unknown_rejected(
    admin_db: AsyncSession, _clean_sso: None
) -> None:
    svc = SsoStateService(settings=SsoSettings(state_ttl_seconds=600))
    with pytest.raises(SsoStateInvalid):
        await svc.consume(admin_db, tenant_id="alpha", state="never-issued")


@pytest.mark.asyncio
async def test_state_expired_rejected(
    admin_db: AsyncSession, _clean_sso: None
) -> None:
    svc = SsoStateService(settings=SsoSettings(state_ttl_seconds=600))
    stored = await svc.create(
        admin_db,
        tenant_id="alpha",
        provider_type=SsoProviderType.OIDC,
    )
    # Backdate expires_at so consume fails with Expired, not Consumed.
    await admin_db.execute(
        text(
            "UPDATE axon_control.sso_states "
            "SET expires_at = :exp WHERE state = :s"
        ),
        {"exp": datetime.now(timezone.utc) - timedelta(seconds=60), "s": stored.state},
    )
    await admin_db.flush()
    with pytest.raises(SsoStateExpired):
        await svc.consume(admin_db, tenant_id="alpha", state=stored.state)


# ── Cross-tenant isolation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_configurations_isolated_cross_tenant(
    admin_db: AsyncSession,
    local_envelope: LocalEnvelopeEncryption,
    _clean_sso: None,
) -> None:
    svc = SsoConfigurationService(envelope=local_envelope)
    payload = {
        "issuer": "https://idp.x",
        "client_id": "c",
        "client_secret": "s",
        "redirect_uri": "https://cb",
    }
    await svc.upsert(
        admin_db,
        tenant_id="alpha",
        provider_type=SsoProviderType.OIDC,
        payload=payload,
    )

    async with admin_db.begin_nested():
        await admin_db.execute(
            text("SELECT set_config('axon.current_tenant', 'beta', true)")
        )
        count = (
            await admin_db.execute(
                text("SELECT COUNT(*) FROM axon_control.sso_configurations")
            )
        ).scalar_one()
        assert count == 0  # beta sees nothing
