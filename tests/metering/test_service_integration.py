"""Integration — MeteringService end-to-end against real Postgres."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from axon_enterprise.config import MeteringSettings
from axon_enterprise.metering import (
    InMemoryRateLimiter,
    InvoiceAlreadyIssued,
    InvoiceGenerator,
    InvoiceStatus,
    MeteringService,
    MetricType,
    PlanNotFound,
    QuotaExceeded,
    StripeClient,
    UsageSample,
)
from axon_enterprise.metering.models import PricingPlan, TenantSubscription
from axon_enterprise.metering.quota import QuotaEnforcer

pytestmark = pytest.mark.integration


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def admin_db(migrated_db: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            yield session


@pytest_asyncio.fixture
async def _clean_metering(migrated_db: AsyncEngine) -> AsyncIterator[None]:
    yield
    factory = async_sessionmaker(bind=migrated_db, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "TRUNCATE axon_control.invoices, "
                    "axon_control.usage_events, "
                    "axon_control.tenant_subscriptions CASCADE"
                )
            )


@pytest.fixture
def metering() -> MeteringService:
    settings = MeteringSettings(
        rate_limit_backend="memory",
        stripe_enabled=False,
        tax_rate_percent=0.0,
        invoice_currency="USD",
    )
    limiter = InMemoryRateLimiter()
    return MeteringService(
        rate_limiter=limiter,
        quota=QuotaEnforcer(rate_limiter=limiter),
        invoice_generator=InvoiceGenerator(currency="USD"),
        stripe=StripeClient(settings=settings),
        audit=MeteringService.default().audit,  # _NoopAuditEmitter
        settings=settings,
    )


async def _subscribe(
    db: AsyncSession, *, tenant_id: str, plan_id: str
) -> TenantSubscription:
    now = datetime.now(timezone.utc)
    sub = TenantSubscription(
        tenant_id=tenant_id,
        plan_id=plan_id,
        current_period_start=now - timedelta(days=1),
        current_period_end=now + timedelta(days=29),
    )
    db.add(sub)
    await db.flush()
    return sub


# ── Seeded plans ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_built_in_plans_seeded_by_migration(
    admin_db: AsyncSession, _clean_metering: None
) -> None:
    row = await admin_db.get(PricingPlan, "starter")
    assert row is not None
    assert row.hard_cap is True
    row_pro = await admin_db.get(PricingPlan, "pro")
    assert row_pro is not None
    assert row_pro.monthly_base_cents == 4_900


# ── Record + aggregate ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_persists_usage_event(
    admin_db: AsyncSession,
    metering: MeteringService,
    _clean_metering: None,
) -> None:
    await _subscribe(admin_db, tenant_id="alpha", plan_id="pro")
    sample = UsageSample(
        tenant_id="alpha",
        metric_type=MetricType.FLOW_EXECUTION,
        quantity=1,
    )
    event = await metering.record(admin_db, sample)
    assert event.tenant_id == "alpha"
    assert event.metric_type == "flow.execution"
    assert event.quantity == 1.0


@pytest.mark.asyncio
async def test_current_period_usage_aggregates(
    admin_db: AsyncSession,
    metering: MeteringService,
    _clean_metering: None,
) -> None:
    await _subscribe(admin_db, tenant_id="alpha", plan_id="pro")
    for _ in range(5):
        await metering.record(
            admin_db,
            UsageSample(
                tenant_id="alpha",
                metric_type=MetricType.FLOW_EXECUTION,
                quantity=1,
            ),
        )
    await metering.record(
        admin_db,
        UsageSample(
            tenant_id="alpha",
            metric_type=MetricType.LLM_TOKENS_IN,
            quantity=200,
        ),
    )

    totals = await metering.current_period_usage(admin_db, tenant_id="alpha")
    assert totals[MetricType.FLOW_EXECUTION] == 5.0
    assert totals[MetricType.LLM_TOKENS_IN] == 200.0


# ── Quota enforcement ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_starter_hard_caps_over_allowance(
    admin_db: AsyncSession,
    metering: MeteringService,
    _clean_metering: None,
) -> None:
    """Starter has included_executions=1000 and hard_cap=True."""
    await _subscribe(admin_db, tenant_id="alpha", plan_id="starter")

    # Pre-fill usage up to the included allowance.
    for _ in range(10):
        await metering.record(
            admin_db,
            UsageSample(
                tenant_id="alpha",
                metric_type=MetricType.FLOW_EXECUTION,
                quantity=100,
            ),
        )
    # Total = 1000. Next sample would push over.
    with pytest.raises(QuotaExceeded) as exc:
        await metering.authorise(
            admin_db,
            UsageSample(
                tenant_id="alpha",
                metric_type=MetricType.FLOW_EXECUTION,
                quantity=1,
            ),
        )
    assert exc.value.metric == "flow.execution"


@pytest.mark.asyncio
async def test_pro_allows_overage(
    admin_db: AsyncSession,
    metering: MeteringService,
    _clean_metering: None,
) -> None:
    """Pro has hard_cap=False — overage billed instead of rejected."""
    await _subscribe(admin_db, tenant_id="alpha", plan_id="pro")

    # Record exactly the included allowance, then try one more.
    await metering.record(
        admin_db,
        UsageSample(
            tenant_id="alpha",
            metric_type=MetricType.FLOW_EXECUTION,
            quantity=50_000,
        ),
    )
    decision = await metering.authorise(
        admin_db,
        UsageSample(
            tenant_id="alpha",
            metric_type=MetricType.FLOW_EXECUTION,
            quantity=100,
        ),
    )
    assert decision.allowed is True
    assert decision.overage_quantity == 100.0


@pytest.mark.asyncio
async def test_plan_not_found_without_subscription(
    admin_db: AsyncSession,
    metering: MeteringService,
    _clean_metering: None,
) -> None:
    with pytest.raises(PlanNotFound):
        await metering.authorise(
            admin_db,
            UsageSample(
                tenant_id="alpha",
                metric_type=MetricType.FLOW_EXECUTION,
                quantity=1,
            ),
        )


# ── Invoicing ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_issue_invoice_for_period_with_overage(
    admin_db: AsyncSession,
    metering: MeteringService,
    _clean_metering: None,
) -> None:
    """Issue an invoice for pro tenant with execution overage."""
    sub = await _subscribe(admin_db, tenant_id="alpha", plan_id="pro")

    # 50_001 executions = 1 overage * 1c
    await admin_db.execute(
        text(
            "INSERT INTO axon_control.usage_events "
            "(tenant_id, metric_type, unit, quantity, recorded_at) "
            "VALUES ('alpha', 'flow.execution', 'count', 50001, :ts)"
        ),
        {"ts": sub.current_period_start + timedelta(hours=1)},
    )
    await admin_db.flush()

    invoice = await metering.issue_invoice(
        admin_db,
        tenant_id="alpha",
        period_start=sub.current_period_start,
        period_end=sub.current_period_end,
    )
    assert invoice.status == InvoiceStatus.DRAFT.value
    assert invoice.subtotal_cents == 4_900 + 1  # base + 1c overage
    assert invoice.total_cents == invoice.subtotal_cents


@pytest.mark.asyncio
async def test_issue_invoice_is_idempotent(
    admin_db: AsyncSession,
    metering: MeteringService,
    _clean_metering: None,
) -> None:
    sub = await _subscribe(admin_db, tenant_id="alpha", plan_id="pro")
    await metering.issue_invoice(
        admin_db,
        tenant_id="alpha",
        period_start=sub.current_period_start,
        period_end=sub.current_period_end,
    )
    with pytest.raises(InvoiceAlreadyIssued):
        await metering.issue_invoice(
            admin_db,
            tenant_id="alpha",
            period_start=sub.current_period_start,
            period_end=sub.current_period_end,
        )


# ── Tenant RLS isolation ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_usage_events_isolated_cross_tenant(
    admin_db: AsyncSession,
    metering: MeteringService,
    _clean_metering: None,
) -> None:
    await _subscribe(admin_db, tenant_id="alpha", plan_id="pro")
    await metering.record(
        admin_db,
        UsageSample(
            tenant_id="alpha",
            metric_type=MetricType.FLOW_EXECUTION,
            quantity=1,
        ),
    )
    async with admin_db.begin_nested():
        await admin_db.execute(
            text("SELECT set_config('axon.current_tenant', 'beta', true)")
        )
        count = (
            await admin_db.execute(
                text("SELECT COUNT(*) FROM axon_control.usage_events")
            )
        ).scalar_one()
        assert count == 0
