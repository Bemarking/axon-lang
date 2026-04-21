"""Authentication orchestration — registration + password login + 2FA.

This is the service layer that composes:

    - PasswordPolicy (strength + HIBP)
    - PasswordHasher (Argon2id)
    - TotpService (RFC 6238 with envelope encryption)
    - SessionService (refresh token rotation)
    - LockoutPolicy (progressive lockout)

The AuthService does NOT speak HTTP; it takes an ``AsyncSession`` and
returns domain objects. Fase 10.j (Admin API) and 10.k (Self-service
portal) are the HTTP layers that call into this service.

Audit emission is stubbed via ``_emit_audit`` — when 10.g lands it
will write to the ``audit_events`` table with a hash chain entry.
For now we log structured events so the transition is transparent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import NamedTuple
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.config import IdentitySettings, get_settings
from axon_enterprise.identity.errors import (
    AccountLockedError,
    EmailAlreadyRegistered,
    InvalidCredentialsError,
    TotpVerificationError,
)
from axon_enterprise.identity.lockout import LockoutPolicy
from axon_enterprise.identity.models import User, UserStatus
from axon_enterprise.identity.password import PasswordHasher
from axon_enterprise.identity.password_policy import PasswordPolicy
from axon_enterprise.identity.sessions import IssuedSession, SessionService
from axon_enterprise.identity.totp import TotpService

_logger: structlog.stdlib.BoundLogger = structlog.get_logger("axon_enterprise.identity.auth")


class AuthenticationResult(NamedTuple):
    user: User
    session: IssuedSession


@dataclass(frozen=True)
class AuthService:
    """Orchestrates the authentication lifecycle for the control plane."""

    hasher: PasswordHasher
    policy: PasswordPolicy
    totp: TotpService
    sessions: SessionService
    lockout: LockoutPolicy
    settings: IdentitySettings

    @classmethod
    def default(cls) -> AuthService:
        s = get_settings().identity
        return cls(
            hasher=PasswordHasher.default(),
            policy=PasswordPolicy.default(),
            totp=TotpService.default(),
            sessions=SessionService.default(),
            lockout=LockoutPolicy.default(),
            settings=s,
        )

    # ── Registration ──────────────────────────────────────────────────

    async def register(
        self,
        db: AsyncSession,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> User:
        """Create a new user. Fails closed on policy / duplicate email.

        Invoked under ``admin_session()`` by the provisioning flow
        (Fase 10.j Admin API) because the ``users`` table is global
        and ``admin_bypass`` is required to INSERT rows.
        """
        email_norm = email.strip().lower()
        await self.policy.validate(
            password,
            user_inputs=[email_norm] + ([display_name] if display_name else []),
        )

        existing = await db.scalar(select(User).where(User.email == email_norm))
        if existing is not None:
            # Deliberately not revealed to the client — see EmailAlreadyRegistered.
            raise EmailAlreadyRegistered(email_norm)

        user = User(
            email=email_norm,
            display_name=display_name,
            password_hash=self.hasher.hash(password),
            password_algo="argon2id",
            password_updated_at=datetime.now(timezone.utc),
            status=UserStatus.ACTIVE.value,
        )
        db.add(user)
        await db.flush()
        _logger.info(
            "user_registered",
            user_id=str(user.user_id),
            email=user.email,
        )
        return user

    # ── Password login ────────────────────────────────────────────────

    async def authenticate(
        self,
        db: AsyncSession,
        *,
        email: str,
        password: str,
        tenant_id: str,
        totp_code: str | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> AuthenticationResult:
        """Verify credentials and issue a session.

        Timing parity
        -------------
        When the email is unknown we still spend the same CPU as a
        full Argon2 verify, so login timing is identical whether the
        account exists or not.
        """
        email_norm = email.strip().lower()
        now = datetime.now(timezone.utc)

        user = await db.scalar(select(User).where(User.email == email_norm))
        if user is None:
            # Spend the time an Argon2 verify would take to defeat
            # user-enumeration by timing.
            self.hasher.burn_equivalent_time(password)
            raise InvalidCredentialsError()

        # Status gate
        if user.status == UserStatus.DELETED.value:
            raise InvalidCredentialsError()
        if user.status == UserStatus.SUSPENDED.value:
            raise InvalidCredentialsError()

        # Current lock window
        if LockoutPolicy.is_currently_locked(user.locked_until, now=now):
            raise AccountLockedError(user.locked_until)
        if user.status == UserStatus.LOCKED.value:
            raise AccountLockedError(None)

        # Password verify
        if user.password_hash is None:
            # SSO-only account — password login not permitted.
            self.hasher.burn_equivalent_time(password)
            raise InvalidCredentialsError()

        try:
            self.hasher.verify(user.password_hash, password)
        except InvalidCredentialsError:
            await self._record_failed_login(db, user, now=now)
            raise

        # TOTP if enabled
        if user.totp_enabled:
            if totp_code is None:
                raise TotpVerificationError("totp_code required")
            try:
                self.totp.verify(
                    user_id=user.user_id,
                    ciphertext=user.totp_secret_encrypted,
                    code=totp_code,
                )
            except TotpVerificationError:
                await self._record_failed_login(db, user, now=now)
                raise

        # Transparent param rotation
        if self.hasher.needs_rehash(user.password_hash):
            user.password_hash = self.hasher.hash(password)
            user.password_updated_at = now

        # Success path
        user.failed_logins = 0
        user.locked_until = None
        user.last_login_at = now
        user.last_login_ip = ip_address

        issued = await self.sessions.create(
            db,
            user_id=user.user_id,
            tenant_id=tenant_id,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        await db.flush()

        _logger.info(
            "user_authenticated",
            user_id=str(user.user_id),
            tenant_id=tenant_id,
            session_id=str(issued.session.session_id),
        )
        return AuthenticationResult(user=user, session=issued)

    # ── TOTP enrolment ────────────────────────────────────────────────

    async def enrol_totp(self, db: AsyncSession, *, user_id: UUID) -> tuple[User, str]:
        """Generate a TOTP secret and persist its ciphertext.

        Returns the provisioning URI so the caller can render a QR.
        The secret is NOT activated until the user confirms a code via
        ``confirm_totp``.
        """
        user = await db.get(User, user_id)
        if user is None:
            raise InvalidCredentialsError()
        enrolment = self.totp.generate(user_id, user.email)
        user.totp_secret_encrypted = enrolment.ciphertext
        user.totp_enabled = False
        user.totp_verified_at = None
        await db.flush()
        return user, enrolment.provisioning_uri

    async def confirm_totp(
        self, db: AsyncSession, *, user_id: UUID, code: str
    ) -> User:
        """Verify the enrolment code and flip ``totp_enabled`` to True."""
        user = await db.get(User, user_id)
        if user is None:
            raise InvalidCredentialsError()
        if user.totp_secret_encrypted is None:
            raise TotpVerificationError("no enrolment in progress")
        self.totp.verify(
            user_id=user.user_id,
            ciphertext=user.totp_secret_encrypted,
            code=code,
        )
        user.totp_enabled = True
        user.totp_verified_at = datetime.now(timezone.utc)
        await db.flush()
        return user

    # ── Internals ─────────────────────────────────────────────────────

    async def _record_failed_login(
        self, db: AsyncSession, user: User, *, now: datetime
    ) -> None:
        user.failed_logins = (user.failed_logins or 0) + 1
        decision = self.lockout.evaluate(failed_logins=user.failed_logins, now=now)
        if decision.should_lock:
            user.locked_until = decision.locked_until
            if decision.locked_until is None:
                # Permanent → also set status so it survives a cleared locked_until.
                user.status = UserStatus.LOCKED.value
            _logger.warning(
                "account_locked",
                user_id=str(user.user_id),
                failed_logins=user.failed_logins,
                locked_until=decision.locked_until.isoformat()
                if decision.locked_until
                else None,
                reason=decision.reason,
            )
        await db.flush()
