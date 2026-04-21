"""Unit tests for the pricing catalogue + in-memory rate limiter."""

from __future__ import annotations

import asyncio

import pytest

from axon_enterprise.metering import (
    BUILT_IN_PLANS,
    InMemoryRateLimiter,
    MetricType,
    RateLimited,
)
from axon_enterprise.metering.pricing import plan_by_id


# ── Pricing catalog ──────────────────────────────────────────────────


def test_three_builtin_plans_present() -> None:
    ids = {p.plan_id for p in BUILT_IN_PLANS}
    assert ids == {"starter", "pro", "enterprise"}


def test_starter_is_the_hard_cap_tier() -> None:
    starter = plan_by_id("starter")
    assert starter is not None
    assert starter.hard_cap is True
    assert starter.monthly_base_cents == 0  # free trial


def test_pro_and_enterprise_are_overage_billed() -> None:
    for pid in ("pro", "enterprise"):
        plan = plan_by_id(pid)
        assert plan is not None
        assert plan.hard_cap is False


def test_rate_limits_are_progressive() -> None:
    starter = plan_by_id("starter")
    pro = plan_by_id("pro")
    enterprise = plan_by_id("enterprise")
    assert starter is not None and pro is not None and enterprise is not None
    assert starter.rate_limit_rpm < pro.rate_limit_rpm < enterprise.rate_limit_rpm
    assert starter.rate_limit_tpm < pro.rate_limit_tpm < enterprise.rate_limit_tpm


def test_included_allowances_are_progressive() -> None:
    starter = plan_by_id("starter")
    pro = plan_by_id("pro")
    enterprise = plan_by_id("enterprise")
    assert starter is not None and pro is not None and enterprise is not None
    assert (
        starter.included_executions
        < pro.included_executions
        < enterprise.included_executions
    )
    assert starter.included_tokens < pro.included_tokens < enterprise.included_tokens


def test_metric_default_units_are_sensible() -> None:
    assert MetricType.FLOW_EXECUTION.default_unit().value == "count"
    assert MetricType.LLM_TOKENS_IN.default_unit().value == "tokens"
    assert MetricType.STORAGE_BYTES.default_unit().value == "gibibytes"


# ── In-memory rate limiter ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_allows_up_to_limit() -> None:
    rl = InMemoryRateLimiter()
    for _ in range(5):
        await rl.check_and_record(
            tenant_id="alpha",
            metric="flow.execution",
            quantity=1,
            limit_per_minute=5,
        )


@pytest.mark.asyncio
async def test_blocks_beyond_limit() -> None:
    rl = InMemoryRateLimiter()
    for _ in range(3):
        await rl.check_and_record(
            tenant_id="alpha",
            metric="flow.execution",
            quantity=1,
            limit_per_minute=3,
        )
    with pytest.raises(RateLimited) as exc:
        await rl.check_and_record(
            tenant_id="alpha",
            metric="flow.execution",
            quantity=1,
            limit_per_minute=3,
        )
    assert exc.value.metric == "flow.execution"
    assert exc.value.retry_after_seconds > 0


@pytest.mark.asyncio
async def test_isolated_per_tenant() -> None:
    rl = InMemoryRateLimiter()
    await rl.check_and_record(
        tenant_id="alpha", metric="flow.execution", quantity=1, limit_per_minute=1
    )
    # Different tenant → fresh bucket
    await rl.check_and_record(
        tenant_id="beta", metric="flow.execution", quantity=1, limit_per_minute=1
    )
    with pytest.raises(RateLimited):
        await rl.check_and_record(
            tenant_id="alpha",
            metric="flow.execution",
            quantity=1,
            limit_per_minute=1,
        )


@pytest.mark.asyncio
async def test_isolated_per_metric() -> None:
    rl = InMemoryRateLimiter()
    await rl.check_and_record(
        tenant_id="alpha", metric="flow.execution", quantity=1, limit_per_minute=1
    )
    # Different metric → fresh bucket
    await rl.check_and_record(
        tenant_id="alpha", metric="llm.tokens_in", quantity=1, limit_per_minute=1
    )


@pytest.mark.asyncio
async def test_quantity_accumulates_toward_limit() -> None:
    rl = InMemoryRateLimiter()
    await rl.check_and_record(
        tenant_id="alpha",
        metric="llm.tokens_in",
        quantity=500,
        limit_per_minute=1000,
    )
    await rl.check_and_record(
        tenant_id="alpha",
        metric="llm.tokens_in",
        quantity=400,
        limit_per_minute=1000,
    )
    with pytest.raises(RateLimited):
        await rl.check_and_record(
            tenant_id="alpha",
            metric="llm.tokens_in",
            quantity=200,
            limit_per_minute=1000,
        )


def test_rate_limited_carries_retry_hint() -> None:
    err = RateLimited(metric="flow.execution", retry_after_seconds=30)
    assert err.retry_after_seconds == 30
    assert err.metric == "flow.execution"
