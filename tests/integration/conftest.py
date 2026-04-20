"""Shared fixtures + gating helpers for AXON integration tests."""

from __future__ import annotations

import os

import pytest


def _env_enabled(var: str) -> bool:
    """True if the env var is set to a truthy value."""
    value = os.environ.get(var, "")
    return value.lower() not in ("", "0", "false", "no", "off")


def skip_unless_env(var: str):
    """Decorator: skip a test class/function unless `var` is set."""
    return pytest.mark.skipif(
        not _env_enabled(var),
        reason=f"integration test skipped — set {var}=1 to enable",
    )


# ── Concrete gates (one per integration target) ───────────────────

skip_unless_docker = skip_unless_env("AXON_IT_DOCKER")
skip_unless_terraform = skip_unless_env("AXON_IT_TERRAFORM")
skip_unless_aws = skip_unless_env("AXON_IT_AWS")
skip_unless_kubernetes = skip_unless_env("AXON_IT_KUBERNETES")
skip_unless_vault = skip_unless_env("AXON_IT_VAULT")
skip_unless_azure_kv = skip_unless_env("AXON_IT_AZURE_KEYVAULT")
skip_unless_pq = skip_unless_env("AXON_IT_PQ")
skip_unless_fhe = skip_unless_env("AXON_IT_FHE")


@pytest.fixture
def dry_run_handler():
    from axon.runtime.handlers.dry_run import DryRunHandler
    return DryRunHandler()
