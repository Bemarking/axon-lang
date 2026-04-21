"""Secrets-layer error hierarchy."""

from __future__ import annotations

from axon_enterprise.identity.errors import IdentityError


class SecretsError(IdentityError):
    """Base class for secrets errors."""

    code = "secret.error"


class SecretKeyInvalid(SecretsError):
    """The requested key does not satisfy the naming policy."""

    code = "secret.key_invalid"
    reveal_to_client = True


class SecretNotFound(SecretsError):
    """No tenant_secrets row for ``(tenant_id, key)`` — or row was soft-deleted."""

    code = "secret.not_found"
    reveal_to_client = True


class SecretValueTooLarge(SecretsError):
    """Value exceeds the 64 KiB AWS Secrets Manager payload limit."""

    code = "secret.value_too_large"
    reveal_to_client = True


class SecretsBackendError(SecretsError):
    """Opaque upstream failure — AWS SM 5xx, IAM denial, etc."""

    code = "secret.backend_error"
    reveal_to_client = False


class SecretAlreadyScheduledForDeletion(SecretsError):
    """Caller tried to mutate a secret that is pending deletion."""

    code = "secret.scheduled_for_deletion"
    reveal_to_client = True
