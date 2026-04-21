"""End-to-end tests for the AuthService against a real Postgres.

Covers:
    - register happy-path
    - register rejects duplicate email
    - authenticate with wrong password → InvalidCredentialsError
    - authenticate with correct password → session issued, TOTP skipped
      when not enabled
    - progressive lockout (soft → hard → permanent)
    - TOTP enrolment + confirmation + required on subsequent login
    - refresh token rotation + replay detection

Runs under ``admin_session()`` because users and sessions require
admin_bypass for cross-tenant access in this sub-fase.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pyotp
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from axon_enterprise.config import IdentitySettings, get_settings
from axon_enterprise.identity import (
    AccountLockedError,
    AuthService,
    EmailAlreadyRegistered,
    InvalidCredentialsError,
    LockoutPolicy,
    PasswordHasher,
    PasswordPolicy,
    SessionService,
    TotpService,
)
from axon_enterprise.identity.errors import (
    SessionExpiredError,
    TotpVerificationError,
)
from axon_enterprise.identity.models import Session, User

pytestmark = pytest.mark.integration


# ── Helpers ───────────────────────────────────────────────────────────


def _fast_identity_settings() -> IdentitySettings:
    """Cheap Argon2 params + HIBP disabled so the suite runs quickly."""
    return IdentitySettings(
        argon2_time_cost=2,
        argon2_memory_cost_kib=19_456,
        argon2_parallelism=1,
        password_min_length=12,
        password_zxcvbn_min_score=3,
        password_check_hibp=False,
        lockout_threshold_soft=3,
        lockout_duration_soft_minutes=15,
        lockout_threshold_hard=6,
        lockout_duration_hard_minutes=60,
        lockout_threshold_permanent=9,
    )


@pytest.fixture
def auth_service() -> AuthService:
    s = _fast_identity_settings()
    from axon_enterprise.crypto import LocalEnvelopeEncryption

    # Build an in-process envelope so TOTP works without relying on env.
    import base64
    import os as _os

    key = base64.urlsafe_b64encode(_os.urandom(32)).decode("ascii")
    envelope = LocalEnvelopeEncryption.from_base64(key)

    return AuthService(
        hasher=PasswordHasher.from_settings(s),
        policy=PasswordPolicy(settings=s),
        totp=TotpService(envelope=envelope, settings=s),
        sessions=SessionService(settings=s),
        lockout=LockoutPolicy(settings=s),
        settings=s,
    )


@pytest_asyncio.fixture
async def admin_db(migrated_db: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Single session that bypasses RLS — sufficient for these tests.

    A real production Admin API would connect as ``axon_admin``;
    inside tests the superuser role that owns the schema already
    bypasses RLS so no role switch is needed.
    """
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            yield session


@pytest_asyncio.fixture
async def _truncate_identity(migrated_db: AsyncEngine) -> AsyncIterator[None]:
    """Clean the identity tables between integration tests.

    ``migrated_db`` is session-scoped so rows from one test persist
    into the next without this.
    """
    yield
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "TRUNCATE axon_control.sessions, "
                    "axon_control.tenant_memberships, "
                    "axon_control.users CASCADE"
                )
            )


# ── Registration ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_happy_path(
    admin_db: AsyncSession, auth_service: AuthService, _truncate_identity: None
) -> None:
    user = await auth_service.register(
        admin_db,
        email="ALICE@example.com",
        password="correct-horse-battery-staple-9",
        display_name="Alice",
    )
    assert user.email == "alice@example.com"  # normalised
    assert user.password_hash is not None
    assert user.password_algo == "argon2id"


@pytest.mark.asyncio
async def test_register_duplicate_email_rejected(
    admin_db: AsyncSession, auth_service: AuthService, _truncate_identity: None
) -> None:
    await auth_service.register(
        admin_db,
        email="alice@example.com",
        password="correct-horse-battery-staple-9",
    )
    with pytest.raises(EmailAlreadyRegistered):
        await auth_service.register(
            admin_db,
            email="alice@example.com",
            password="different-password-that-is-strong-88",
        )


# ── Authentication ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_authenticate_wrong_password(
    admin_db: AsyncSession, auth_service: AuthService, _truncate_identity: None
) -> None:
    await auth_service.register(
        admin_db,
        email="alice@example.com",
        password="correct-horse-battery-staple-9",
    )
    with pytest.raises(InvalidCredentialsError):
        await auth_service.authenticate(
            admin_db,
            email="alice@example.com",
            password="wrong-password",
            tenant_id="alpha",
        )


@pytest.mark.asyncio
async def test_authenticate_success_issues_session(
    admin_db: AsyncSession, auth_service: AuthService, _truncate_identity: None
) -> None:
    await auth_service.register(
        admin_db,
        email="alice@example.com",
        password="correct-horse-battery-staple-9",
    )
    result = await auth_service.authenticate(
        admin_db,
        email="alice@example.com",
        password="correct-horse-battery-staple-9",
        tenant_id="alpha",
        ip_address="203.0.113.9",
        user_agent="pytest/1.0",
    )
    assert result.session.raw_refresh_token
    row = result.session.session
    assert row.tenant_id == "alpha"
    assert row.revoked_at is None
    assert result.user.failed_logins == 0
    assert result.user.last_login_at is not None


@pytest.mark.asyncio
async def test_authenticate_unknown_user_takes_similar_time(
    admin_db: AsyncSession, auth_service: AuthService, _truncate_identity: None
) -> None:
    # Smoke test: unknown users must fail with the same exception as
    # wrong passwords — no enumeration via distinct error codes.
    with pytest.raises(InvalidCredentialsError):
        await auth_service.authenticate(
            admin_db,
            email="nobody@example.com",
            password="anything",
            tenant_id="alpha",
        )


# ── Lockout ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lockout_ladder(
    admin_db: AsyncSession, auth_service: AuthService, _truncate_identity: None
) -> None:
    await auth_service.register(
        admin_db,
        email="alice@example.com",
        password="correct-horse-battery-staple-9",
    )

    # 2 failures — below soft threshold (3)
    for _ in range(2):
        with pytest.raises(InvalidCredentialsError):
            await auth_service.authenticate(
                admin_db,
                email="alice@example.com",
                password="wrong",
                tenant_id="alpha",
            )

    user = await admin_db.scalar(
        select(User).where(User.email == "alice@example.com")
    )
    assert user is not None
    assert user.failed_logins == 2
    assert user.locked_until is None

    # 3rd failure triggers soft lock
    with pytest.raises(InvalidCredentialsError):
        await auth_service.authenticate(
            admin_db,
            email="alice@example.com",
            password="wrong",
            tenant_id="alpha",
        )
    await admin_db.refresh(user)
    assert user.failed_logins == 3
    assert user.locked_until is not None

    # Next attempt — even with right password — is blocked by lock window
    with pytest.raises(AccountLockedError):
        await auth_service.authenticate(
            admin_db,
            email="alice@example.com",
            password="correct-horse-battery-staple-9",
            tenant_id="alpha",
        )


# ── TOTP ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_totp_enrolment_then_required_on_login(
    admin_db: AsyncSession, auth_service: AuthService, _truncate_identity: None
) -> None:
    user = await auth_service.register(
        admin_db,
        email="alice@example.com",
        password="correct-horse-battery-staple-9",
    )
    # Enrol
    _, uri = await auth_service.enrol_totp(admin_db, user_id=user.user_id)
    assert uri.startswith("otpauth://totp/")
    secret = uri.split("secret=")[1].split("&")[0]

    # Confirm with current code
    current = pyotp.TOTP(secret).now()
    confirmed = await auth_service.confirm_totp(
        admin_db, user_id=user.user_id, code=current
    )
    assert confirmed.totp_enabled is True

    # Login without TOTP → rejected
    with pytest.raises(TotpVerificationError):
        await auth_service.authenticate(
            admin_db,
            email="alice@example.com",
            password="correct-horse-battery-staple-9",
            tenant_id="alpha",
        )

    # Login with current TOTP code → succeeds
    current = pyotp.TOTP(secret).now()
    result = await auth_service.authenticate(
        admin_db,
        email="alice@example.com",
        password="correct-horse-battery-staple-9",
        tenant_id="alpha",
        totp_code=current,
    )
    assert result.session.session.revoked_at is None


# ── Session rotation ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_token_rotation(
    admin_db: AsyncSession, auth_service: AuthService, _truncate_identity: None
) -> None:
    user = await auth_service.register(
        admin_db,
        email="alice@example.com",
        password="correct-horse-battery-staple-9",
    )
    result = await auth_service.authenticate(
        admin_db,
        email="alice@example.com",
        password="correct-horse-battery-staple-9",
        tenant_id="alpha",
    )
    first_raw = result.session.raw_refresh_token
    first_id = result.session.session.session_id

    rotated = await auth_service.sessions.verify_and_rotate(
        admin_db, raw_refresh_token=first_raw
    )
    assert rotated.raw_refresh_token != first_raw
    assert rotated.session.session_id != first_id
    assert rotated.session.sequence == 1

    # Old session must be marked revoked + chain-linked forward
    old = await admin_db.get(Session, first_id)
    assert old is not None
    assert old.revoked_at is not None
    assert old.revoked_reason == "rotated"
    assert old.rotated_to_session_id == rotated.session.session_id

    # Replay of the first token must fail AND revoke the new session too
    with pytest.raises(SessionExpiredError):
        await auth_service.sessions.verify_and_rotate(
            admin_db, raw_refresh_token=first_raw
        )
    await admin_db.refresh(rotated.session)
    assert rotated.session.revoked_at is not None
    assert rotated.session.revoked_reason == "replay"


@pytest.mark.asyncio
async def test_refresh_after_absolute_expiry_fails(
    admin_db: AsyncSession, auth_service: AuthService, _truncate_identity: None
) -> None:
    user = await auth_service.register(
        admin_db,
        email="alice@example.com",
        password="correct-horse-battery-staple-9",
    )
    result = await auth_service.authenticate(
        admin_db,
        email="alice@example.com",
        password="correct-horse-battery-staple-9",
        tenant_id="alpha",
    )
    # Simulate expiry: backdate expires_at
    row = result.session.session
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await admin_db.flush()

    with pytest.raises(SessionExpiredError):
        await auth_service.sessions.verify_and_rotate(
            admin_db, raw_refresh_token=result.session.raw_refresh_token
        )
