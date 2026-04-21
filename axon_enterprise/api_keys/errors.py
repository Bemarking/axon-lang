"""API-key error hierarchy."""

from __future__ import annotations

from axon_enterprise.identity.errors import IdentityError


class ApiKeysError(IdentityError):
    """Base class for API-key errors."""

    code = "api_key.error"


class ApiKeyInvalid(ApiKeysError):
    """Caller presented something that isn't a recognisable axk_ key or
    fails the Argon2id verification against any stored hash."""

    code = "api_key.invalid"
    reveal_to_client = False


class ApiKeyRevoked(ApiKeysError):
    code = "api_key.revoked"
    reveal_to_client = False


class ApiKeyExpired(ApiKeysError):
    code = "api_key.expired"
    reveal_to_client = False
