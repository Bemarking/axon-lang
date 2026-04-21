"""MeteringService — records usage + enforces quotas + issues invoices.

Composes the pieces:

    - ``QuotaEnforcer`` — gate + rate limit before work starts
    - ``InvoiceGenerator`` — pure conversion from aggregates to
      itemised line items
    - ``StripeClient`` — optional push to the billing provider
    - ``RateLimiter`` — hot-path per-minute counter

Every operation can emit to the 10.g audit log through a caller-
provided adapter; when no adapter is given the service logs
structured events and callers miss the hash chain (operator's
choice, not a library default).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.config import MeteringSettings, get_settings
from axon_enterprise.metering.errors import (
    InvoiceAlreadyIssued,
    PlanNotFound,
    UsageRecordInvalid,
)
from axon_enterprise.metering.events import MetricType, UsageSample
from axon_enterprise.metering.invoicing import (
    InvoiceGenerator,
    aggregate_period,
)
from axon_enterprise.metering.limiter import RateLimiter, build_rate_limiter
from axon_enterprise.metering.models import (
    Invoice,
    InvoiceStatus,
    PricingPlan,
    TenantSubscription,
    UsageEvent,
)
from axon_enterprise.metering.quota import QuotaDecision, QuotaEnforcer
from axon_enterprise.metering.stripe_client import StripeClient

_logger: structlog.stdlib.BoundLogger = structlog.get_logger(
    "axon_enterprise.metering.service"
)


class MeteringAuditEmitter(Protocol):
    """Minimal interface for audit integration (wired via 10.g adapters)."""

    async def emit_usage_recorded(
        self,
        *,
        tenant_id: str,
        metric_type: str,
        quantity: float,
        actor_user_id: UUID | None,
    ) -> None: ...

    async def emit_invoice_issued(
        self,
        *,
        tenant_id: str,
        invoice_id: UUID,
        total_cents: int,
        stripe_invoice_id: str | None,
    ) -> None: ...


@dataclass
class _NoopAuditEmitter:
    async def emit_usage_recorded(self, **kwargs) -> None:
        pass

    async def emit_invoice_issued(self, **kwargs) -> None:
        pass


@dataclass
class MeteringService:
    """High-level façade: record, authorise, issue."""

    rate_limiter: RateLimiter
    quota: QuotaEnforcer
    invoice_generator: InvoiceGenerator
    stripe: StripeClient
    audit: MeteringAuditEmitter
    settings: MeteringSettings

    @classmethod
    def default(
        cls, audit: MeteringAuditEmitter | None = None
    ) -> MeteringService:
        s = get_settings().metering
        limiter = build_rate_limiter(s)
        return cls(
            rate_limiter=limiter,
            quota=QuotaEnforcer(rate_limiter=limiter),
            invoice_generator=InvoiceGenerator(
                tax_rate_percent=s.tax_rate_percent,
                tax_label=s.tax_label,
                currency=s.invoice_currency,
            ),
            stripe=StripeClient(settings=s),
            audit=audit or _NoopAuditEmitter(),
            settings=s,
        )

    # ── Record ────────────────────────────────────────────────────────

    async def record(
        self, db: AsyncSession, sample: UsageSample
    ) -> UsageEvent:
        """Persist a usage event. Does NOT enforce quotas (see ``authorise``)."""
        _validate(sample)
        row = UsageEvent(
            tenant_id=sample.tenant_id,
            metric_type=sample.metric_type.value,
            unit=sample.resolved_unit().value,
            quantity=float(sample.quantity),
            actor_user_id=sample.actor_user_id,
            flow_id=sample.flow_id,
            provider=sample.provider,
            details=dict(sample.metadata or {}),
            recorded_at=sample.resolved_timestamp(),
        )
        db.add(row)
        await db.flush()
        await self.audit.emit_usage_recorded(
            tenant_id=sample.tenant_id,
            metric_type=sample.metric_type.value,
            quantity=sample.quantity,
            actor_user_id=sample.actor_user_id,
        )
        return row

    async def authorise(
        self, db: AsyncSession, sample: UsageSample
    ) -> QuotaDecision:
        """Gate the work. Raises RateLimited / QuotaExceeded when denied."""
        return await self.quota.authorise(
            db, tenant_id=sample.tenant_id, sample=sample
        )

    async def authorise_and_record(
        self, db: AsyncSession, sample: UsageSample
    ) -> tuple[QuotaDecision, UsageEvent]:
        """Convenience: authorise first, then persist on approval."""
        decision = await self.authorise(db, sample)
        event = await self.record(db, sample)
        return decision, event

    # ── Aggregation ───────────────────────────────────────────────────

    async def current_period_usage(
        self, db: AsyncSession, *, tenant_id: str
    ) -> dict[MetricType, float]:
        sub = await _require_subscription(db, tenant_id=tenant_id)
        usage = await aggregate_period(
            db,
            tenant_id=tenant_id,
            period_start=sub.current_period_start,
            period_end=sub.current_period_end,
        )
        return dict(usage.totals)

    # ── Invoice ───────────────────────────────────────────────────────

    async def issue_invoice(
        self,
        db: AsyncSession,
        *,
        tenant_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> Invoice:
        """Generate + persist the invoice for a closed period.

        Idempotent — a second call with the same ``(tenant, period)``
        raises ``InvoiceAlreadyIssued`` so callers can safely retry
        batch jobs without double-billing.
        """
        existing = await db.scalar(
            select(Invoice).where(
                Invoice.tenant_id == tenant_id,
                Invoice.period_start == period_start,
                Invoice.period_end == period_end,
            )
        )
        if existing is not None:
            raise InvoiceAlreadyIssued(
                f"{tenant_id} {period_start.isoformat()} → "
                f"{period_end.isoformat()}"
            )

        plan, sub = await _load_plan_row(db, tenant_id=tenant_id)
        usage = await aggregate_period(
            db,
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
        )
        line_items, subtotal, tax, total = self.invoice_generator.build(
            plan=plan, usage=usage
        )

        now = datetime.now(timezone.utc)
        invoice = Invoice(
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
            currency=self.settings.invoice_currency,
            line_items=[li.to_jsonable() for li in line_items],
            subtotal_cents=subtotal,
            tax_cents=tax,
            total_cents=total,
            status=InvoiceStatus.DRAFT.value,
            issued_at=now,
        )
        db.add(invoice)
        await db.flush()

        # Push to Stripe when configured; otherwise leave as draft.
        if self.stripe.enabled and sub.stripe_customer_id:
            try:
                stripe_id = self.stripe.issue_invoice(
                    customer_id=sub.stripe_customer_id,
                    currency=self.settings.invoice_currency,
                    description=(
                        f"{plan.display_name} {period_start.date()} "
                        f"→ {period_end.date()}"
                    ),
                    line_items=line_items,
                    due_days=self.settings.invoice_due_days,
                )
                invoice.stripe_invoice_id = stripe_id
                invoice.status = InvoiceStatus.FINALIZED.value
                await db.flush()
            except Exception:
                invoice.status = InvoiceStatus.FAILED.value
                await db.flush()
                raise

        await self.audit.emit_invoice_issued(
            tenant_id=tenant_id,
            invoice_id=invoice.invoice_id,
            total_cents=total,
            stripe_invoice_id=invoice.stripe_invoice_id,
        )
        return invoice


# ── Internals ──────────────────────────────────────────────────────


def _validate(sample: UsageSample) -> None:
    if not sample.tenant_id:
        raise UsageRecordInvalid("tenant_id is required")
    if sample.quantity < 0:
        raise UsageRecordInvalid("quantity must be non-negative")


async def _require_subscription(
    db: AsyncSession, *, tenant_id: str
) -> TenantSubscription:
    sub = await db.get(TenantSubscription, tenant_id)
    if sub is None:
        raise PlanNotFound(tenant_id)
    return sub


async def _load_plan_row(
    db: AsyncSession, *, tenant_id: str
) -> tuple[PricingPlan, TenantSubscription]:
    sub = await _require_subscription(db, tenant_id=tenant_id)
    plan = await db.get(PricingPlan, sub.plan_id)
    if plan is None:
        raise PlanNotFound(sub.plan_id)
    return plan, sub
