"""
HashiCorp Vault integration: opt-in via AXON_IT_VAULT=1.

Requires env vars:
    VAULT_ADDR   — e.g. http://127.0.0.1:8200
    VAULT_TOKEN  — token with KV v2 read permission
    AXON_IT_VAULT_PATH  — path to a pre-seeded secret (e.g. "axon/ci/smoke")
"""

from __future__ import annotations

import os

import pytest

from .conftest import skip_unless_vault


@skip_unless_vault
class TestVaultProviderIntegration:

    def test_fetch_and_wrap_in_secret(self):
        from axon.runtime.esk import VaultProvider, secret_from_provider

        addr = os.environ.get("VAULT_ADDR")
        token = os.environ.get("VAULT_TOKEN")
        path = os.environ.get("AXON_IT_VAULT_PATH", "axon/ci/smoke")
        assert addr and token, "VAULT_ADDR + VAULT_TOKEN required"

        provider = VaultProvider(url=addr, token=token)
        secret = secret_from_provider(provider, path)
        # no-materialize invariant survives the provider fetch
        assert "redacted" in repr(secret).lower()
        # reveal inside audited scope
        payload = secret.reveal(accessor="ci_smoke", purpose="verify_fetch")
        assert payload is not None
        # audit trail recorded
        assert len(secret.audit_trail) == 1
