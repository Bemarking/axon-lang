"""Identity-layer exception hierarchy.

Every raised error carries a stable string code so HTTP handlers can
map them to well-defined response payloads and audit events can be
filtered deterministically. The ``reveal_to_client`` flag on each
exception indicates whether the error message is safe to return
verbatim to an unauthenticated caller or whether it must be collapsed
into a generic "invalid credentials" response to avoid enumeration.
"""

from __future__ import annotations

from datetime import datetime


class IdentityError(Exception):
    """Base class for identity-layer errors."""

    code: str = "identity.error"
    #: When False, HTTP handlers should collapse this into a generic
    #: "invalid credentials" to deny attackers confirmation.
    reveal_to_client: bool = True

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or self.code)
        if code is not None:
            self.code = code


class AuthenticationError(IdentityError):
    """Parent of login-path errors. Exposed as 401 by handlers."""

    code = "auth.failed"
    reveal_to_client = False


class InvalidCredentialsError(AuthenticationError):
    code = "auth.invalid_credentials"
    reveal_to_client = False


class AccountLockedError(AuthenticationError):
    """Account is locked; ``locked_until`` tells the client when to retry."""

    code = "auth.locked"
    reveal_to_client = True  # The specific "when" is safe to reveal

    def __init__(self, locked_until: datetime | None) -> None:
        self.locked_until = locked_until
        msg = (
            f"Account is locked until {locked_until.isoformat()}"
            if locked_until
            else "Account is permanently locked; contact an administrator"
        )
        super().__init__(msg)


class SessionExpiredError(AuthenticationError):
    code = "auth.session_expired"
    reveal_to_client = True


class TotpNotEnabledError(AuthenticationError):
    code = "auth.totp_not_enabled"
    reveal_to_client = True


class TotpVerificationError(AuthenticationError):
    code = "auth.totp_invalid"
    reveal_to_client = False


class PasswordPolicyViolation(IdentityError):
    """Raised at registration / rotation when policy rejects the password."""

    code = "auth.password_policy"
    reveal_to_client = True

    def __init__(self, violations: list[str]) -> None:
        self.violations = list(violations)
        super().__init__("; ".join(violations))


class EmailAlreadyRegistered(IdentityError):
    code = "auth.email_taken"
    reveal_to_client = False  # avoid user enumeration
