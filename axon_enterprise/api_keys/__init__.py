"""M2M API keys — Fase 10.k.

Tenant-scoped API keys for machine-to-machine integrations that
can't drive the interactive OIDC/SAML flows. Design anchors:

- **UUID opaque key** with a stable ``axk_`` prefix for grep + log
  scanning. The raw key is emitted exactly once on creation; only
  the Argon2id hash is stored.
- **Tenant-scoped** via RLS on ``tenant_api_keys``. Cross-tenant
  reuse is impossible — a key carries its tenant binding at verify
  time so a forged uuid that happens to collide verifies against
  the wrong tenant and fails the hash check.
- **Metadata fields** cover the typical portal requirements: name,
  created_by, last_used_at, expires_at, revoked_at. Never the
  plaintext.
- **Verification**: lookup by the first 8 hex chars of the key
  (indexed prefix — collision-free at realistic sizes) + Argon2id
  verify against the stored hash. Constant-time comparison built
  into ``argon2-cffi``.
"""

from axon_enterprise.api_keys.errors import (
    ApiKeyExpired,
    ApiKeyInvalid,
    ApiKeyRevoked,
    ApiKeysError,
)
from axon_enterprise.api_keys.models import TenantApiKey
from axon_enterprise.api_keys.service import (
    ApiKeyIssued,
    ApiKeyService,
    VerifiedApiKey,
)

__all__ = [
    "ApiKeyExpired",
    "ApiKeyInvalid",
    "ApiKeyIssued",
    "ApiKeyRevoked",
    "ApiKeyService",
    "ApiKeysError",
    "TenantApiKey",
    "VerifiedApiKey",
]
