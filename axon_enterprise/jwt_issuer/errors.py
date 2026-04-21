"""JWT-issuer error hierarchy."""

from __future__ import annotations

from axon_enterprise.identity.errors import IdentityError


class JwtIssuerError(IdentityError):
    """Base for JWT issuer errors."""

    code = "jwt.error"


class NoActiveSigningKey(JwtIssuerError):
    """The signing key set has no row in ``status='active'``."""

    code = "jwt.no_active_key"
    reveal_to_client = False


class JwtKeyNotFound(JwtIssuerError):
    code = "jwt.key_not_found"
    reveal_to_client = False


class JwtSigningFailed(JwtIssuerError):
    """The backend refused to sign — KMS rate-limit, IAM denial, etc."""

    code = "jwt.signing_failed"
    reveal_to_client = False


class JwtBackendError(JwtIssuerError):
    """Catch-all for opaque backend failures (Redis down, etc.)."""

    code = "jwt.backend_error"
    reveal_to_client = False


class JwtRevoked(JwtIssuerError):
    """The token's ``jti`` is on the revocation list."""

    code = "jwt.revoked"
    reveal_to_client = True
