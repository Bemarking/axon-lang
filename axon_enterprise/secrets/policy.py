"""Key-name validation + path construction.

Enforces a conservative alphabet on secret keys so paths stay
readable in logs + IAM policies + CloudTrail events. Names are
lower-cased on entry; the Rust ``TenantSecretsClient`` expects the
exact canonical form.

The path convention is fixed in configuration:
``{path_prefix}/{tenant_id}/{key}``, default
``axon/tenants/<tenant>/<key>``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from axon_enterprise.config import SecretsSettings, get_settings
from axon_enterprise.secrets.errors import SecretKeyInvalid

# Keys reserved by the system — operators cannot create secrets with
# these names. Reserved to avoid collisions with future per-tenant
# metadata we may place alongside the user-facing secrets.
RESERVED_PREFIXES: frozenset[str] = frozenset({"axon_", "system_", "internal_"})


@dataclass(frozen=True)
class SecretsPolicy:
    """Key validator + path builder."""

    settings: SecretsSettings
    _pattern: re.Pattern[str]

    @classmethod
    def default(cls) -> SecretsPolicy:
        s = get_settings().secrets
        return cls(settings=s, _pattern=re.compile(s.key_pattern))

    @classmethod
    def from_settings(cls, settings: SecretsSettings) -> SecretsPolicy:
        return cls(settings=settings, _pattern=re.compile(settings.key_pattern))

    # ── Validation ────────────────────────────────────────────────────

    def normalise_and_validate_key(self, raw: str) -> str:
        """Return the canonical key or raise ``SecretKeyInvalid``."""
        if not isinstance(raw, str):
            raise SecretKeyInvalid("key must be a string")
        key = raw.strip().lower()
        if not self.settings.key_min_length <= len(key) <= self.settings.key_max_length:
            raise SecretKeyInvalid(
                f"key length must be in [{self.settings.key_min_length}, "
                f"{self.settings.key_max_length}]; got {len(key)}"
            )
        if not self._pattern.match(key):
            raise SecretKeyInvalid(
                f"key {key!r} does not match policy {self.settings.key_pattern!r}"
            )
        for prefix in RESERVED_PREFIXES:
            if key.startswith(prefix):
                raise SecretKeyInvalid(
                    f"key prefix {prefix!r} is reserved; choose another name"
                )
        return key

    def validate_tenant_id(self, tenant_id: str) -> str:
        """Defence-in-depth — reject tenant IDs that would mangle the path.

        The tenant_id is usually validated upstream (RLS + FK) but we
        double-check here because it is concatenated into a path that
        downstream services (AWS SM, CloudTrail) treat as opaque.
        """
        if not tenant_id or "/" in tenant_id or ".." in tenant_id:
            raise SecretKeyInvalid(f"invalid tenant_id {tenant_id!r}")
        return tenant_id

    # ── Path building ────────────────────────────────────────────────

    def build_path(self, tenant_id: str, key: str) -> str:
        """Return ``{prefix}/{tenant_id}/{key}`` for AWS Secrets Manager."""
        tid = self.validate_tenant_id(tenant_id)
        k = self.normalise_and_validate_key(key)
        return f"{self.settings.path_prefix}/{tid}/{k}"
