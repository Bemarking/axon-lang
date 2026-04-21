"""SSO (Single Sign-On) — Fase 10.d.

Replaces the v1.0.0 scaffolding (``return None`` for every method)
with production-grade OIDC + SAML implementations backed by
signature verification, PKCE, state+nonce replay defence, per-tenant
envelope-encrypted configuration, and auto-provisioning with rate
limiting.

Public surface:

    SsoService           — orchestrator (initiate / complete)
    OidcProvider         — OIDC flow with discovery + JWKS cache
    SamlProvider         — SAML via python3-saml (lazy import)
    SsoConfigurationService — envelope-encrypted CRUD for IdP configs
    SsoStateService      — short-lived state/nonce persistence
    SsoProviderType      — 'oidc' | 'saml' enum
    Models               — SsoConfiguration, SsoState, SsoAssertionSeen

Errors are in :mod:`axon_enterprise.sso.errors` and all inherit from
``IdentityError`` so a single HTTP error middleware catches them.
"""

from axon_enterprise.sso.configurations import (
    ResolvedSsoConfiguration,
    SsoConfigurationService,
)
from axon_enterprise.sso.errors import (
    OidcDiscoveryError,
    OidcEmailNotVerified,
    OidcIdTokenInvalid,
    OidcNonceMismatch,
    OidcPkceMismatch,
    OidcTokenExchangeError,
    SamlAssertionReplay,
    SamlResponseInvalid,
    SsoConfigurationInvalid,
    SsoConfigurationNotFound,
    SsoError,
    SsoProviderDisabled,
    SsoRateLimited,
    SsoStateAlreadyConsumed,
    SsoStateExpired,
    SsoStateInvalid,
    SsoTenantMismatch,
)
from axon_enterprise.sso.mapper import (
    MappedIdentity,
    map_oidc_identity,
    map_saml_identity,
    resolve_axon_roles,
)
from axon_enterprise.sso.models import (
    SsoAssertionSeen,
    SsoConfiguration,
    SsoProviderType,
    SsoState,
)
from axon_enterprise.sso.oidc import InitiateResult as OidcInitiateResult
from axon_enterprise.sso.oidc import OidcProvider
from axon_enterprise.sso.oidc_discovery import OidcDiscoverer, OidcMetadata
from axon_enterprise.sso.oidc_id_token import (
    ACCEPTED_ALGS,
    IdTokenValidator,
    ValidatedIdToken,
)
from axon_enterprise.sso.oidc_jwks import JwksClient, PublicKeyEntry
from axon_enterprise.sso.oidc_pkce import (
    compute_code_challenge,
    generate_code_verifier,
    verify_pair,
)
from axon_enterprise.sso.rate_limit import InMemoryRateLimiter
from axon_enterprise.sso.saml import (
    SamlAssertion,
    SamlInitiateResult,
    SamlProvider,
    purge_assertion_seen,
)
from axon_enterprise.sso.saml_metadata import SpMetadataInput, build_sp_metadata_xml
from axon_enterprise.sso.service import SsoLoginResult, SsoService
from axon_enterprise.sso.state import SsoStateService, StoredState

__all__ = [
    "ACCEPTED_ALGS",
    "IdTokenValidator",
    "InMemoryRateLimiter",
    "JwksClient",
    "MappedIdentity",
    "OidcDiscoverer",
    "OidcDiscoveryError",
    "OidcEmailNotVerified",
    "OidcIdTokenInvalid",
    "OidcInitiateResult",
    "OidcMetadata",
    "OidcNonceMismatch",
    "OidcPkceMismatch",
    "OidcProvider",
    "OidcTokenExchangeError",
    "PublicKeyEntry",
    "ResolvedSsoConfiguration",
    "SamlAssertion",
    "SamlAssertionReplay",
    "SamlInitiateResult",
    "SamlProvider",
    "SamlResponseInvalid",
    "SpMetadataInput",
    "SsoAssertionSeen",
    "SsoConfiguration",
    "SsoConfigurationInvalid",
    "SsoConfigurationNotFound",
    "SsoConfigurationService",
    "SsoError",
    "SsoLoginResult",
    "SsoProviderDisabled",
    "SsoProviderType",
    "SsoRateLimited",
    "SsoService",
    "SsoState",
    "SsoStateAlreadyConsumed",
    "SsoStateExpired",
    "SsoStateInvalid",
    "SsoStateService",
    "SsoTenantMismatch",
    "StoredState",
    "ValidatedIdToken",
    "build_sp_metadata_xml",
    "compute_code_challenge",
    "generate_code_verifier",
    "map_oidc_identity",
    "map_saml_identity",
    "purge_assertion_seen",
    "resolve_axon_roles",
    "verify_pair",
]
