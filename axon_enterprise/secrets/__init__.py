"""Per-tenant secret management — Fase 10.f.

Stores the sensitive strings (API keys, webhook signing secrets,
OAuth client secrets for downstream providers) that each tenant's
flows need at runtime. Values live in AWS Secrets Manager under
``axon/tenants/{tenant_id}/{key}``; only metadata (arn, version,
creator, timestamps, description) is persisted in Postgres.

Design anchors
--------------
- Values are NEVER written to the DB; only the path/ARN is stored.
- Values are NEVER logged. ``SecretValue`` redacts itself in repr,
  str, structlog, and exception traces.
- Every read/write/delete/rotate emits an audit event (10.g wires
  the hash-chained log; stub emits structured logs in 10.f).
- Path convention matches axon-rs/src/tenant_secrets.rs (§M3) so
  the Rust runtime reads the same paths without any translation.

Public surface
--------------
    SecretsService          orchestrates CRUD + audit
    SecretsBackend (Protocol)
      - AwsSmBackend        production
      - InMemoryBackend     dev / tests
    TenantSecret            ORM row (metadata only)
    SecretValue             opaque wrapper
    SecretsPolicy           key-name validation + path building
    Errors                  typed, reveal-to-client matrix
"""

from axon_enterprise.secrets.aws_sm_backend import AwsSmBackend
from axon_enterprise.secrets.backend import SecretStoreEntry, SecretsBackend
from axon_enterprise.secrets.errors import (
    SecretKeyInvalid,
    SecretNotFound,
    SecretsBackendError,
    SecretsError,
    SecretValueTooLarge,
)
from axon_enterprise.secrets.in_memory_backend import InMemoryBackend
from axon_enterprise.secrets.models import SecretStatus, TenantSecret
from axon_enterprise.secrets.policy import SecretsPolicy
from axon_enterprise.secrets.service import (
    SecretListing,
    SecretReveal,
    SecretsAuditEmitter,
    SecretsService,
)
from axon_enterprise.secrets.value import SecretValue

__all__ = [
    "AwsSmBackend",
    "InMemoryBackend",
    "SecretKeyInvalid",
    "SecretListing",
    "SecretNotFound",
    "SecretReveal",
    "SecretStatus",
    "SecretStoreEntry",
    "SecretValue",
    "SecretValueTooLarge",
    "SecretsAuditEmitter",
    "SecretsBackend",
    "SecretsBackendError",
    "SecretsError",
    "SecretsPolicy",
    "SecretsService",
    "TenantSecret",
]
