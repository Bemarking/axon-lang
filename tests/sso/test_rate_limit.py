"""Unit tests for the auto-provisioning rate limiter."""

from __future__ import annotations

import pytest

from axon_enterprise.config import SsoSettings
from axon_enterprise.sso.errors import SsoRateLimited
from axon_enterprise.sso.rate_limit import InMemoryRateLimiter


def _limiter(rate: int) -> InMemoryRateLimiter:
    return InMemoryRateLimiter(
        settings=SsoSettings(auto_provision_rate_limit_per_minute=rate)
    )


def test_allows_up_to_limit() -> None:
    rl = _limiter(3)
    for _ in range(3):
        rl.check_and_record(tenant_id="alpha", provider_type="oidc")


def test_blocks_beyond_limit() -> None:
    rl = _limiter(2)
    rl.check_and_record(tenant_id="alpha", provider_type="oidc")
    rl.check_and_record(tenant_id="alpha", provider_type="oidc")
    with pytest.raises(SsoRateLimited):
        rl.check_and_record(tenant_id="alpha", provider_type="oidc")


def test_isolated_per_tenant() -> None:
    rl = _limiter(1)
    rl.check_and_record(tenant_id="alpha", provider_type="oidc")
    # Different tenant starts fresh
    rl.check_and_record(tenant_id="beta", provider_type="oidc")
    with pytest.raises(SsoRateLimited):
        rl.check_and_record(tenant_id="alpha", provider_type="oidc")


def test_isolated_per_provider() -> None:
    rl = _limiter(1)
    rl.check_and_record(tenant_id="alpha", provider_type="oidc")
    # SAML has its own bucket
    rl.check_and_record(tenant_id="alpha", provider_type="saml")
    with pytest.raises(SsoRateLimited):
        rl.check_and_record(tenant_id="alpha", provider_type="oidc")


def test_reset_clears_state() -> None:
    rl = _limiter(1)
    rl.check_and_record(tenant_id="alpha", provider_type="oidc")
    rl.reset()
    rl.check_and_record(tenant_id="alpha", provider_type="oidc")  # fresh


def test_mapper_resolves_axon_roles_preserves_first_seen_order() -> None:
    from axon_enterprise.sso.mapper import MappedIdentity, resolve_axon_roles

    mapped = MappedIdentity(
        email="a@x.z",
        display_name=None,
        external_subject="sub",
        raw_claims={},
        groups=("okta-engineers", "okta-leaders", "okta-engineers"),
    )
    role_map = {"okta-engineers": "developer", "okta-leaders": "admin"}
    roles = resolve_axon_roles(mapped, role_map=role_map)
    assert roles == ["developer", "admin"]


def test_mapper_ignores_unmapped_groups() -> None:
    from axon_enterprise.sso.mapper import MappedIdentity, resolve_axon_roles

    mapped = MappedIdentity(
        email="a@x.z",
        display_name=None,
        external_subject="sub",
        raw_claims={},
        groups=("okta-engineers", "okta-random-group"),
    )
    role_map = {"okta-engineers": "developer"}
    roles = resolve_axon_roles(mapped, role_map=role_map)
    assert roles == ["developer"]
