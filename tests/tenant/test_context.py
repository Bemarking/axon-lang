"""Unit tests for ``axon_enterprise.tenant.context``.

These tests run without Docker or Postgres — they exercise the
ContextVar-based propagation and the public helper surface.
"""

from __future__ import annotations

import asyncio

import pytest

from axon_enterprise.tenant import (
    CURRENT_TENANT,
    TenantContext,
    TenantPlan,
    current_tenant,
    current_tenant_or_none,
    require_tenant,
    set_current_tenant,
)


def test_default_tenant_is_enterprise_plan() -> None:
    ctx = TenantContext.default()
    assert ctx.tenant_id == "default"
    assert ctx.plan is TenantPlan.ENTERPRISE
    assert ctx.is_default() is True


def test_non_default_tenant_is_not_default() -> None:
    ctx = TenantContext(tenant_id="acme", plan=TenantPlan.PRO)
    assert ctx.is_default() is False


def test_tenant_plan_from_str_unknown_falls_back_to_starter() -> None:
    assert TenantPlan.from_str("gold") is TenantPlan.STARTER
    assert TenantPlan.from_str("PRO") is TenantPlan.PRO
    assert TenantPlan.from_str("enterprise") is TenantPlan.ENTERPRISE


def test_current_tenant_or_none_returns_none_when_unset() -> None:
    assert current_tenant_or_none() is None


def test_current_tenant_falls_back_to_default_when_unset() -> None:
    assert current_tenant().is_default()


def test_require_tenant_raises_when_unset() -> None:
    with pytest.raises(RuntimeError, match="No TenantContext"):
        require_tenant()


def test_set_current_tenant_populates_contextvar() -> None:
    ctx = TenantContext(tenant_id="acme", plan=TenantPlan.PRO)
    token = set_current_tenant(ctx)
    try:
        assert current_tenant_or_none() == ctx
        assert require_tenant() == ctx
    finally:
        CURRENT_TENANT.reset(token)
    assert current_tenant_or_none() is None


def test_async_task_inherits_tenant_from_parent() -> None:
    """Each asyncio task gets its own copy of the parent's context."""

    async def scenario() -> tuple[str, str | None]:
        ctx = TenantContext(tenant_id="alpha", plan=TenantPlan.ENTERPRISE)
        set_current_tenant(ctx)

        async def child() -> str:
            return require_tenant().tenant_id

        child_tid = await child()
        outer_tid = require_tenant().tenant_id
        return outer_tid, child_tid

    outer, child = asyncio.run(scenario())
    assert outer == "alpha"
    assert child == "alpha"


def test_sibling_tasks_do_not_leak_tenant_between_each_other() -> None:
    """Two concurrent tasks with different tenants must stay isolated."""

    async def scenario() -> tuple[str, str]:
        async def run_with(tenant_id: str, sleep_s: float) -> str:
            set_current_tenant(
                TenantContext(tenant_id=tenant_id, plan=TenantPlan.ENTERPRISE)
            )
            await asyncio.sleep(sleep_s)
            return require_tenant().tenant_id

        a, b = await asyncio.gather(
            run_with("alpha", 0.02),
            run_with("beta", 0.01),
        )
        return a, b

    a, b = asyncio.run(scenario())
    assert a == "alpha"
    assert b == "beta"
