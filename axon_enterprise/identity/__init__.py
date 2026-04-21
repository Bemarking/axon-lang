"""Identity core — users, passwords, TOTP, sessions, lockout.

Fase 10.b. Provides the authentication primitives that later sub-fases
compose into full login flows (SSO → 10.d, JWT issuance → 10.e,
tenant self-service → 10.k).
"""

from axon_enterprise.identity.auth import AuthService
from axon_enterprise.identity.errors import (
    AccountLockedError,
    AuthenticationError,
    EmailAlreadyRegistered,
    InvalidCredentialsError,
    PasswordPolicyViolation,
    SessionExpiredError,
    TotpNotEnabledError,
    TotpVerificationError,
)
from axon_enterprise.identity.lockout import LockoutDecision, LockoutPolicy
from axon_enterprise.identity.models import (
    MembershipStatus,
    Session,
    SessionStatus,
    TenantMembership,
    User,
    UserStatus,
)
from axon_enterprise.identity.password import PasswordHasher
from axon_enterprise.identity.principal import (
    CURRENT_PRINCIPAL,
    PrincipalContext,
    current_principal_or_none,
    require_principal,
    set_current_principal,
)
from axon_enterprise.identity.password_policy import (
    PasswordPolicy,
    PasswordPolicyViolation as PolicyViolation,
)
from axon_enterprise.identity.sessions import SessionService, issued_session_token
from axon_enterprise.identity.totp import TotpService

__all__ = [
    "AccountLockedError",
    "AuthService",
    "AuthenticationError",
    "CURRENT_PRINCIPAL",
    "EmailAlreadyRegistered",
    "InvalidCredentialsError",
    "LockoutDecision",
    "LockoutPolicy",
    "MembershipStatus",
    "PasswordHasher",
    "PasswordPolicy",
    "PasswordPolicyViolation",
    "PolicyViolation",
    "PrincipalContext",
    "Session",
    "SessionExpiredError",
    "SessionService",
    "SessionStatus",
    "TenantMembership",
    "TotpNotEnabledError",
    "TotpService",
    "TotpVerificationError",
    "User",
    "UserStatus",
    "current_principal_or_none",
    "issued_session_token",
    "require_principal",
    "set_current_principal",
]
