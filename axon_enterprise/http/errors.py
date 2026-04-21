"""Error-to-HTTP mapping.

Every typed error in the service layer carries a ``code`` and a
``reveal_to_client`` flag. This module translates those into a
JSON response with a stable shape:

    {
        "error": {
            "code": "rbac.permission_denied",
            "message": "permission denied: secret:write"
        }
    }

When ``reveal_to_client`` is False (credential / signature errors)
the message collapses to a generic ``"Authentication required"`` or
``"Request could not be processed"`` so observers can't enumerate
which step failed.

HTTP status mapping is explicit per error class so 402 vs 403 vs
429 semantics stay correct for downstream automation (clients
observing rate limits need 429 specifically; quota-exhausted
tenants get 402 Payment Required).
"""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from axon_enterprise.identity.errors import (
    AccountLockedError,
    AuthenticationError,
    EmailAlreadyRegistered,
    IdentityError,
    InvalidCredentialsError,
    PasswordPolicyViolation,
    SessionExpiredError,
    TotpNotEnabledError,
    TotpVerificationError,
)
from axon_enterprise.metering.errors import QuotaExceeded, RateLimited
from axon_enterprise.rbac.errors import (
    InvalidPermissionString,
    PermissionDenied,
    RoleCycleError,
    RoleNotFound,
)
from axon_enterprise.secrets.errors import (
    SecretKeyInvalid,
    SecretNotFound,
    SecretValueTooLarge,
)
from axon_enterprise.sso.errors import (
    SsoConfigurationInvalid,
    SsoConfigurationNotFound,
    SsoError,
    SsoProviderDisabled,
    SsoStateExpired,
    SsoStateInvalid,
)


# Maps each concrete error class to the HTTP status we emit.
_STATUS_MAP: dict[type, int] = {
    # 400
    PasswordPolicyViolation: 400,
    InvalidPermissionString: 400,
    SecretKeyInvalid: 400,
    SsoConfigurationInvalid: 400,
    SecretValueTooLarge: 413,
    # 401
    AuthenticationError: 401,
    InvalidCredentialsError: 401,
    SessionExpiredError: 401,
    TotpVerificationError: 401,
    TotpNotEnabledError: 401,
    # 402 Payment Required — quota exhausted on hard_cap plans
    QuotaExceeded: 402,
    # 403
    PermissionDenied: 403,
    AccountLockedError: 403,
    SsoProviderDisabled: 403,
    # 404
    SecretNotFound: 404,
    RoleNotFound: 404,
    SsoConfigurationNotFound: 404,
    # 409
    EmailAlreadyRegistered: 409,
    RoleCycleError: 409,
    # 410 — state expired
    SsoStateExpired: 410,
    # 422
    SsoStateInvalid: 422,
    # 429
    RateLimited: 429,
}


def error_response_for(exc: BaseException) -> tuple[int, dict[str, Any]]:
    """Return ``(status_code, body_dict)`` for a typed error.

    Unknown exception types → 500 + opaque body. The middleware
    logs the full stack before translating.
    """
    if not isinstance(exc, IdentityError):
        return 500, {
            "error": {
                "code": "internal",
                "message": "Internal server error",
            }
        }

    status = _STATUS_MAP.get(type(exc), 400)
    if exc.reveal_to_client:
        message = str(exc) or exc.code
    else:
        # Collapse to a family-level message — never reveal which step failed.
        message = _GENERIC_MESSAGES.get(status, "Request rejected")

    body: dict[str, Any] = {
        "error": {
            "code": exc.code,
            "message": message,
        }
    }

    # RateLimited carries Retry-After info that the client needs to
    # honour sensibly.
    if isinstance(exc, RateLimited):
        body["error"]["retry_after_seconds"] = exc.retry_after_seconds

    if isinstance(exc, QuotaExceeded):
        body["error"]["metric"] = exc.metric
        body["error"]["limit"] = exc.limit

    return status, body


_GENERIC_MESSAGES: dict[int, str] = {
    401: "Authentication required",
    403: "Permission denied",
    422: "Invalid request",
}


def json_error(exc: BaseException) -> JSONResponse:
    """Build the final ``JSONResponse`` for a typed error."""
    status, body = error_response_for(exc)
    headers: dict[str, str] = {}
    if isinstance(exc, RateLimited):
        headers["Retry-After"] = str(exc.retry_after_seconds)
    return JSONResponse(body, status_code=status, headers=headers)


async def _identity_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return json_error(exc)


async def _catchall_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Logged by the caller (via structlog processor); keep the
    # client-facing body opaque.
    return json_error(exc)


def install_error_handlers(app: Starlette) -> None:
    """Register handlers for every typed error class + a 500 fallback."""
    for err_cls in _STATUS_MAP.keys():
        app.add_exception_handler(err_cls, _identity_error_handler)
    # Base classes — catch subclasses we didn't register explicitly.
    app.add_exception_handler(IdentityError, _identity_error_handler)
    app.add_exception_handler(SsoError, _identity_error_handler)
    # Last-resort 500.
    app.add_exception_handler(Exception, _catchall_error_handler)
