"""Top-level test fixtures for axon-enterprise.

Three classes of tests are supported here:

- **unit** (default): no Docker, no Postgres, no network. Exercises
  pure-Python logic (TenantContext propagation, settings validation,
  RLS SQL shape).

- **integration** (``-m integration``): spins up an ephemeral Postgres
  via testcontainers, applies the Rust M1 baseline (``public.tenants``)
  and the Python Alembic chain, and exercises real queries + RLS.

- **slow** (``-m slow``): for load / large-data paths.

Integration tests are skipped automatically when Docker is unavailable.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip integration tests when Docker is unreachable."""
    docker_available = shutil.which("docker") is not None and (
        os.environ.get("DOCKER_HOST") is not None
        or Path("/var/run/docker.sock").exists()
        or os.name == "nt"  # on Windows assume Docker Desktop is handling it
    )
    if docker_available:
        return
    skip_marker = pytest.mark.skip(reason="Docker unavailable; integration tests skipped")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _reset_current_tenant() -> Iterator[None]:
    """Clear the TenantContext ContextVar between tests so state never leaks."""
    from axon_enterprise.tenant import CURRENT_TENANT

    token = CURRENT_TENANT.set(None)
    try:
        yield
    finally:
        CURRENT_TENANT.reset(token)
