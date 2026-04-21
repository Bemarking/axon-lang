"""Quota enforcer — rate limit + monthly allowance.

Two dimensions of enforcement:

1. **Rate limit** (per minute) — hot-path decision via the
   ``RateLimiter`` (Redis in prod). Rejects with ``RateLimited``.
2. **Monthly allowance** — sum of ``usage_events`` for the current
   billing period, compared against plan inclusions. When the plan
   is ``hard_cap``, over-allowance raises ``QuotaExceeded``. When
   the plan allows overage, the check returns a decision annotated
   with ``overage_quantity`` so callers can log an "approaching
   overage" warning without blocking.

The enforcer is invoked BEFORE recording the event. A typical
call-site pattern:

    decision = await quota.authorise(db, tenant_id, sample)
    # backend work happens here (flow execution, LLM call, ...)
    await metering.record(db, sample)

If the backend work fails after authorisation, the rate limiter's
counter has already incremented — fine, we overcount slightly on
failure paths. The Postgres aggregate only increments when
``record`` persists the event, so monthly billing stays accurate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.metering.errors import (
    PlanNotFound,
    QuotaExceeded,
)
from axon_enterprise.metering.events import MetricType, UsageSample
from axon_enterprise.metering.limiter import RateLimiter
from axon_enterprise.metering.models import (
    PricingPlan,
    TenantSubscription,
    UsageEvent,
)

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.metering.quota"
)


class QuotaDecision(NamedTuple):
    """Outcome of ``QuotaEnforcer.authorise``."""

    allowed: bool
    overage_quantity: float  # 0.0 when still inside included allowance
    current_usage: float
    period_limit: float
    unit: str


# Mapping from metric → plan allowance column. Kept here (not as a
# method on PricingPlan) so the mapping is greppable.
_METRIC_TO_ALLOWANCE: dict[MetricType, str] = {
    MetricType.FLOW_EXECUTION: "included_executions",
    MetricType.API_CALLS: "included_executions",
    MetricType.LLM_TOKENS_IN: "included_tokens",
    MetricType.LLM_TOKENS_OUT: "included_tokens",
    MetricType.STORAGE_BYTES: "included_storage_gib",
    MetricType.COMPUTE_TIME: "included_compute_seconds",
}

_METRIC_TO_RATE_LIMIT: dict[MetricType, str] = {
    MetricType.FLOW_EXECUTION: "rate_limit_rpm",
    MetricType.API_CALLS: "rate_limit_rpm",
    MetricType.LLM_TOKENS_IN: "rate_limit_tpm",
    MetricType.LLM_TOKENS_OUT: "rate_limit_tpm",
}


@dataclass
class QuotaEnforcer:
    """Combines rate limiter + monthly aggregate check."""

    rate_limiter: RateLimiter

    async def authorise(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        sample: UsageSample,
    ) -> QuotaDecision:
        """Gate the work this sample represents.

        Raises ``RateLimited`` on per-minute overflow, or
        ``QuotaExceeded`` on hard-cap monthly overflow. Otherwise
        returns a ``QuotaDecision`` annotated with any overage
        (plan allows overage) or ``overage_quantity=0.0`` (still
        inside the included allowance).
        """
        plan, sub = await _load_plan(db, tenant_id=tenant_id)

        # 1. Rate limit (if the metric has one).
        rate_attr = _METRIC_TO_RATE_LIMIT.get(sample.metric_type)
        if rate_attr is not None:
            limit = int(getattr(plan, rate_attr))
            # Rate limit tracks integer counts — round up sub-unit
            # quantities so a partial token bucket does not let
            # large requests through for free.
            quantity_int = max(1, int(sample.quantity))
            await self.rate_limiter.check_and_record(
                tenant_id=tenant_id,
                metric=sample.metric_type.value,
                quantity=quantity_int,
                limit_per_minute=limit,
            )

        # 2. Monthly allowance (only for metered types).
        alloc_attr = _METRIC_TO_ALLOWANCE.get(sample.metric_type)
        if alloc_attr is None:
            return QuotaDecision(
                allowed=True,
                overage_quantity=0.0,
                current_usage=0.0,
                period_limit=0.0,
                unit=sample.resolved_unit().value,
            )

        limit = float(getattr(plan, alloc_attr))
        current = await _sum_metric_for_period(
            db,
            tenant_id=tenant_id,
            metric_type=sample.metric_type,
            period_start=sub.current_period_start,
            period_end=sub.current_period_end,
        )
        projected = current + sample.quantity

        if projected <= limit:
            return QuotaDecision(
                allowed=True,
                overage_quantity=0.0,
                current_usage=current,
                period_limit=limit,
                unit=sample.resolved_unit().value,
            )

        # Over the included allowance.
        overage = projected - limit
        if plan.hard_cap:
            _logger.info(
                "quota_exceeded",
                tenant_id=tenant_id,
                plan_id=plan.plan_id,
                metric=sample.metric_type.value,
                limit=limit,
                requested=sample.quantity,
                current=current,
            )
            raise QuotaExceeded(
                metric=sample.metric_type.value,
                quantity=sample.quantity,
                limit=limit,
            )

        return QuotaDecision(
            allowed=True,
            overage_quantity=overage,
            current_usage=current,
            period_limit=limit,
            unit=sample.resolved_unit().value,
        )


# ── Helpers ─────────────────────────────────────────────────────────


async def _load_plan(
    db: AsyncSession, *, tenant_id: str
) -> tuple[PricingPlan, TenantSubscription]:
    sub = await db.get(TenantSubscription, tenant_id)
    if sub is None:
        raise PlanNotFound(tenant_id)
    plan = await db.get(PricingPlan, sub.plan_id)
    if plan is None:
        raise PlanNotFound(sub.plan_id)
    return plan, sub


async def _sum_metric_for_period(
    db: AsyncSession,
    *,
    tenant_id: str,
    metric_type: MetricType,
    period_start: datetime,
    period_end: datetime,
) -> float:
    from sqlalchemy import func as sql_func

    result = await db.execute(
        select(sql_func.coalesce(sql_func.sum(UsageEvent.quantity), 0.0))
        .where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.metric_type == metric_type.value,
            UsageEvent.recorded_at >= period_start,
            UsageEvent.recorded_at < period_end,
        )
    )
    return float(result.scalar_one() or 0.0)
