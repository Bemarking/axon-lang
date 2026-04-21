"""SSO error hierarchy.

Separate from identity errors because SSO-specific failure modes have
their own observability + audit-event shape. All inherit from
``IdentityError`` so a single HTTP error middleware catches both.
"""

from __future__ import annotations

from axon_enterprise.identity.errors import IdentityError


class SsoError(IdentityError):
    """Base for SSO errors."""

    code = "sso.error"


# ── Configuration ─────────────────────────────────────────────────────


class SsoConfigurationNotFound(SsoError):
    code = "sso.not_configured"
    reveal_to_client = True


class SsoConfigurationInvalid(SsoError):
    code = "sso.config_invalid"
    reveal_to_client = True


class SsoProviderDisabled(SsoError):
    code = "sso.provider_disabled"
    reveal_to_client = True


# ── Flow / State ──────────────────────────────────────────────────────


class SsoStateInvalid(SsoError):
    """The returned ``state`` does not match any live outstanding request."""

    code = "sso.state_invalid"
    reveal_to_client = False


class SsoStateExpired(SsoError):
    code = "sso.state_expired"
    reveal_to_client = True


class SsoStateAlreadyConsumed(SsoError):
    code = "sso.state_replayed"
    reveal_to_client = False


# ── OIDC ──────────────────────────────────────────────────────────────


class OidcDiscoveryError(SsoError):
    code = "sso.oidc.discovery"
    reveal_to_client = False


class OidcTokenExchangeError(SsoError):
    code = "sso.oidc.token_exchange"
    reveal_to_client = False


class OidcIdTokenInvalid(SsoError):
    """ID token signature / claims validation failure."""

    code = "sso.oidc.id_token_invalid"
    reveal_to_client = False


class OidcNonceMismatch(SsoError):
    code = "sso.oidc.nonce_mismatch"
    reveal_to_client = False


class OidcPkceMismatch(SsoError):
    code = "sso.oidc.pkce_mismatch"
    reveal_to_client = False


class OidcEmailNotVerified(SsoError):
    code = "sso.oidc.email_not_verified"
    reveal_to_client = True


# ── SAML ──────────────────────────────────────────────────────────────


class SamlResponseInvalid(SsoError):
    """Response signature / destination / InResponseTo / window check failed."""

    code = "sso.saml.response_invalid"
    reveal_to_client = False


class SamlAssertionReplay(SsoError):
    """Seen this assertion ID before — block replay."""

    code = "sso.saml.assertion_replay"
    reveal_to_client = False


# ── Auto-provisioning ────────────────────────────────────────────────


class SsoRateLimited(SsoError):
    """Per-IdP provisioning rate limit exceeded."""

    code = "sso.rate_limited"
    reveal_to_client = True


class SsoTenantMismatch(SsoError):
    """The IdP returned a subject bound to a different tenant than expected."""

    code = "sso.tenant_mismatch"
    reveal_to_client = False
