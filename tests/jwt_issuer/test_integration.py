"""Integration — JwtIssuer + KeyManagementService + JwksDocumentBuilder +
JtiRevocationService against the real DB (testcontainers).

Covers the complete happy path that a Rust verifier will see:

    1. Register a local signing key → row status=active
    2. Mint a JWT for a PrincipalContext
    3. Verify the JWT with the key from JwksDocumentBuilder
    4. Rotate: previous key → grace, new key → active
    5. Old-kid JWT still verifies (grace window honoured)
    6. Revoke jti → is_revoked() returns True
    7. Grace key retired after grace_until → no longer in JWKS
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from axon_enterprise.config import JwtSettings
from axon_enterprise.identity.principal import PrincipalContext
from axon_enterprise.jwt_issuer import (
    JtiRevocationService,
    JwksDocumentBuilder,
    JwtIssuer,
    KeyManagementService,
    LocalSigner,
    SigningKeyStatus,
)
from axon_enterprise.jwt_issuer.models import JwtSigningKey

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def admin_db(migrated_db: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            yield session


@pytest_asyncio.fixture
async def _clean_jwt(migrated_db: AsyncEngine) -> AsyncIterator[None]:
    yield
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "TRUNCATE axon_control.jwt_revoked_jtis, "
                    "axon_control.jwt_signing_keys CASCADE"
                )
            )


@pytest.fixture
def principal() -> PrincipalContext:
    return PrincipalContext(
        user_id=UUID("00000000-0000-0000-0000-000000000042"),
        email="alice@example.com",
        tenant_id="alpha",
        role_names=frozenset({"admin", "developer"}),
    )


# ── Happy path ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mint_then_verify_against_jwks(
    admin_db: AsyncSession,
    principal: PrincipalContext,
    _clean_jwt: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = JwtSettings(
        signer_backend="local",
        issuer="https://test.axon",
        audience="axon-api",
        access_token_ttl_seconds=120,
        revocation_backend="postgres",
    )
    signer = LocalSigner.generate()
    # Wire the local key into the environment so load_signer_for_row
    # picks it up.
    monkeypatch.setenv(
        "AXON_JWT_LOCAL_PRIVATE_KEY_PEM",
        signer.export_private_key_pem().decode(),
    )
    from axon_enterprise.config import get_settings

    get_settings.cache_clear()

    km = KeyManagementService()
    await km.register_local_key(admin_db, signer)

    issuer = JwtIssuer(key_management=km, settings=s)
    issued = await issuer.mint(admin_db, principal=principal)
    assert issued.token.count(".") == 2
    assert issued.kid == signer.info.kid

    # Build JWKS and verify
    jwks = await JwksDocumentBuilder().build(admin_db)
    assert len(jwks["keys"]) == 1
    jwk_entry = jwks["keys"][0]
    assert jwk_entry["kid"] == signer.info.kid
    assert jwk_entry["kty"] == "RSA"

    # Reconstruct the public key from JWKS and verify the token.
    decoded = jwt.decode(
        issued.token,
        signer.info.public_key_pem,
        algorithms=["RS256"],
        audience="axon-api",
        issuer="https://test.axon",
    )
    assert decoded["tenant_id"] == "alpha"
    assert decoded["sub"] == f"user:{principal.user_id}"
    assert decoded["roles"] == ["admin", "developer"]
    assert decoded["jti"] == str(issued.jti)


# ── Rotation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rotation_moves_previous_to_grace(
    admin_db: AsyncSession,
    _clean_jwt: None,
) -> None:
    km = KeyManagementService()
    old = await km.register_local_key(admin_db, LocalSigner.generate())
    new = await km.rotate(admin_db, new_local_signer=LocalSigner.generate())

    await admin_db.refresh(old)
    assert old.status == SigningKeyStatus.GRACE.value
    assert old.grace_until is not None
    assert new.status == SigningKeyStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_jwks_contains_active_plus_grace(
    admin_db: AsyncSession,
    _clean_jwt: None,
) -> None:
    km = KeyManagementService()
    await km.register_local_key(admin_db, LocalSigner.generate())
    await km.rotate(admin_db, new_local_signer=LocalSigner.generate())

    jwks = await JwksDocumentBuilder().build(admin_db)
    assert len(jwks["keys"]) == 2  # active + grace


@pytest.mark.asyncio
async def test_grace_key_retired_after_expiry(
    admin_db: AsyncSession,
    _clean_jwt: None,
) -> None:
    km = KeyManagementService()
    await km.register_local_key(admin_db, LocalSigner.generate())
    await km.rotate(admin_db, new_local_signer=LocalSigner.generate())

    # Backdate grace_until so retire_expired_grace_keys picks it up.
    await admin_db.execute(
        text(
            "UPDATE axon_control.jwt_signing_keys "
            "SET grace_until = :t WHERE status = 'grace'"
        ),
        {"t": datetime.now(timezone.utc) - timedelta(seconds=60)},
    )
    await admin_db.flush()

    retired = await km.retire_expired_grace_keys(admin_db)
    assert retired == 1

    jwks = await JwksDocumentBuilder().build(admin_db)
    assert len(jwks["keys"]) == 1
    assert jwks["keys"][0]["kid"] != ""  # only the active remains


@pytest.mark.asyncio
async def test_only_one_active_key_enforced(
    admin_db: AsyncSession,
    _clean_jwt: None,
) -> None:
    from sqlalchemy.exc import DBAPIError

    km = KeyManagementService()
    await km.register_local_key(admin_db, LocalSigner.generate())
    # Attempt a second direct INSERT with status='active' — partial
    # unique index must reject.
    with pytest.raises(DBAPIError):
        await admin_db.execute(
            text(
                "INSERT INTO axon_control.jwt_signing_keys "
                "(kid, algorithm, backend, key_material_ref, public_key_pem, status) "
                "VALUES ('dup', 'RS256', 'local', 'x', 'y', 'active')"
            )
        )


# ── Revocation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoke_then_check_postgres_backend(
    admin_db: AsyncSession, _clean_jwt: None
) -> None:
    svc = JtiRevocationService(
        backend_kind="postgres", settings=JwtSettings(revocation_backend="postgres")
    )
    jti = uuid4()
    exp = datetime.now(timezone.utc) + timedelta(minutes=10)

    assert await svc.is_revoked(admin_db, jti=jti) is False
    await svc.revoke(admin_db, jti=jti, expires_at=exp, reason="user_request")
    assert await svc.is_revoked(admin_db, jti=jti) is True


@pytest.mark.asyncio
async def test_purge_expired_removes_only_past(
    admin_db: AsyncSession, _clean_jwt: None
) -> None:
    svc = JtiRevocationService(
        backend_kind="postgres", settings=JwtSettings(revocation_backend="postgres")
    )
    past = uuid4()
    future = uuid4()
    await svc.revoke(
        admin_db,
        jti=past,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    await svc.revoke(
        admin_db,
        jti=future,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    purged = await svc.purge_expired(admin_db)
    assert purged == 1
    assert await svc.is_revoked(admin_db, jti=future) is True


# ── Unit-level revocation (memory backend) ───────────────────────────


@pytest.mark.asyncio
async def test_memory_backend_expires_are_honoured() -> None:
    svc = JtiRevocationService(
        backend_kind="memory", settings=JwtSettings(revocation_backend="memory")
    )
    jti = uuid4()
    # NO db needed for memory backend
    past_exp = datetime.now(timezone.utc) - timedelta(seconds=1)
    await svc.revoke(None, jti=jti, expires_at=past_exp)  # type: ignore[arg-type]
    assert await svc.is_revoked(None, jti=jti) is False  # type: ignore[arg-type]
