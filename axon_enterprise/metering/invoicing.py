"""Invoice generation — pure functions + service wrapper.

Given a ``PricingPlan`` + aggregated usage for a billing period,
``InvoiceGenerator`` produces a deterministic set of ``LineItem``
objects that serialise verbatim into ``invoices.line_items`` (JSONB).

Overage math is explicit per metric so operators reading an
invoice can explain every cent to a customer. When the plan is
``hard_cap=True``, any over-allowance has already been rejected by
the ``QuotaEnforcer``, so invoicing sees only in-allowance usage.

Idempotency
-----------
The writer (``MeteringService.issue_invoice``) checks for an
existing row at ``(tenant_id, period_start, period_end)`` before
creating — the UNIQUE constraint on that triple enforces the same
invariant at the DB. Callers that re-run the invoice batch see a
``InvoiceAlreadyIssued`` error and skip.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from axon_enterprise.metering.events import MetricType
from axon_enterprise.metering.models import PricingPlan, UsageEvent


@dataclass(frozen=True, slots=True)
class LineItem:
    """Single billable row in an invoice. Serialised to JSONB."""

    metric_type: str
    unit: str
    quantity_total: float
    quantity_included: float
    quantity_overage: float
    unit_amount_cents: int
    amount_cents: int
    description: str

    def to_jsonable(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PeriodUsage:
    """Per-metric totals for a single billing period."""

    tenant_id: str
    period_start: datetime
    period_end: datetime
    totals: dict[MetricType, float] = field(default_factory=dict)


@dataclass
class InvoiceGenerator:
    """Pure converter from plan + aggregates to line items + totals.

    Emits the fixed-fee base line item first, followed by one line
    per metric that has billable usage. Unit amounts are normalised
    to cents per unit (rounded up) — avoids sub-cent deltas across
    invoices.
    """

    tax_rate_percent: float = 0.0
    tax_label: str = "VAT"
    currency: str = "USD"

    def build(
        self,
        *,
        plan: PricingPlan,
        usage: PeriodUsage,
    ) -> tuple[list[LineItem], int, int, int]:
        """Return (line_items, subtotal_cents, tax_cents, total_cents)."""
        items: list[LineItem] = []

        if plan.monthly_base_cents > 0:
            items.append(
                LineItem(
                    metric_type="subscription.base",
                    unit="months",
                    quantity_total=1.0,
                    quantity_included=1.0,
                    quantity_overage=0.0,
                    unit_amount_cents=plan.monthly_base_cents,
                    amount_cents=plan.monthly_base_cents,
                    description=f"{plan.display_name} — monthly base fee",
                )
            )

        # For each billable metric we compute overage = max(0, total - included).
        for metric, total in sorted(usage.totals.items(), key=lambda x: x[0].value):
            line = _line_for_metric(metric=metric, total=total, plan=plan)
            if line is not None:
                items.append(line)

        subtotal = sum(i.amount_cents for i in items)
        tax = int(round(subtotal * (self.tax_rate_percent / 100.0)))
        total = subtotal + tax
        return items, subtotal, tax, total


def _line_for_metric(
    *,
    metric: MetricType,
    total: float,
    plan: PricingPlan,
) -> LineItem | None:
    """Return a LineItem when the metric has overage; otherwise None."""
    if metric in (MetricType.FLOW_EXECUTION, MetricType.API_CALLS):
        included = float(plan.included_executions)
        overage = max(0.0, total - included)
        if overage == 0.0:
            return None
        per_unit = plan.overage_per_execution_cents
        amount = int(math.ceil(overage * per_unit))
        return LineItem(
            metric_type=metric.value,
            unit="count",
            quantity_total=total,
            quantity_included=min(total, included),
            quantity_overage=overage,
            unit_amount_cents=per_unit,
            amount_cents=amount,
            description=f"{metric.value} overage ({int(overage)} events)",
        )
    if metric in (MetricType.LLM_TOKENS_IN, MetricType.LLM_TOKENS_OUT):
        # Included tokens is a pool shared across in + out; callers
        # pass totals per metric and we collapse downstream. Here we
        # per-metric-overage so the line items are itemised.
        included = float(plan.included_tokens) / 2.0  # conservative split
        overage = max(0.0, total - included)
        if overage == 0.0:
            return None
        per_1k = plan.overage_per_1k_tokens_cents
        amount = int(math.ceil(overage / 1000.0 * per_1k))
        return LineItem(
            metric_type=metric.value,
            unit="tokens",
            quantity_total=total,
            quantity_included=min(total, included),
            quantity_overage=overage,
            unit_amount_cents=per_1k,
            amount_cents=amount,
            description=f"{metric.value} overage ({int(overage)} tokens)",
        )
    if metric is MetricType.STORAGE_BYTES:
        # Totals arrive in GiB already (UsageSample carries unit).
        included = float(plan.included_storage_gib)
        overage = max(0.0, total - included)
        if overage == 0.0:
            return None
        per_gib = plan.overage_per_gib_storage_cents
        amount = int(math.ceil(overage * per_gib))
        return LineItem(
            metric_type=metric.value,
            unit="gibibytes",
            quantity_total=total,
            quantity_included=min(total, included),
            quantity_overage=overage,
            unit_amount_cents=per_gib,
            amount_cents=amount,
            description=f"storage overage ({overage:.2f} GiB-month)",
        )
    if metric is MetricType.COMPUTE_TIME:
        included = float(plan.included_compute_seconds)
        overage = max(0.0, total - included)
        if overage == 0.0:
            return None
        per_sec_mc = plan.overage_per_compute_second_millicents
        # Convert millicents to cents (round up to the nearest cent).
        amount = int(math.ceil(overage * per_sec_mc / 1000.0))
        return LineItem(
            metric_type=metric.value,
            unit="compute_seconds",
            quantity_total=total,
            quantity_included=min(total, included),
            quantity_overage=overage,
            unit_amount_cents=per_sec_mc,
            amount_cents=amount,
            description=f"compute overage ({int(overage)} seconds)",
        )
    # PROVIDER_COST, EGRESS_BYTES and others pass through as
    # observability-only for now — 10.l may introduce billable forms.
    return None


async def aggregate_period(
    db: AsyncSession,
    *,
    tenant_id: str,
    period_start: datetime,
    period_end: datetime,
) -> PeriodUsage:
    """Sum every metric for the tenant inside ``[period_start, period_end)``."""
    from sqlalchemy import func as sql_func

    result = await db.execute(
        select(
            UsageEvent.metric_type, sql_func.sum(UsageEvent.quantity)
        )
        .where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.recorded_at >= period_start,
            UsageEvent.recorded_at < period_end,
        )
        .group_by(UsageEvent.metric_type)
    )
    totals: dict[MetricType, float] = {}
    for metric_type, summed in result.all():
        try:
            totals[MetricType(metric_type)] = float(summed or 0.0)
        except ValueError:
            # Unknown metric type — skip silently. Would only
            # happen if a migration added a new metric that this
            # code does not know about.
            continue
    return PeriodUsage(
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
        totals=totals,
    )
