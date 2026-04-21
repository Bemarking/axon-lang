"""Unit tests for the pure ``InvoiceGenerator``."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from axon_enterprise.metering import (
    InvoiceGenerator,
    MetricType,
    PeriodUsage,
)
from axon_enterprise.metering.models import PricingPlan


def _plan(**overrides) -> PricingPlan:
    defaults = dict(
        plan_id="pro",
        display_name="Pro",
        monthly_base_cents=4_900,
        included_executions=100,
        included_tokens=10_000,
        included_storage_gib=10,
        included_compute_seconds=3_600,
        overage_per_execution_cents=1,
        overage_per_1k_tokens_cents=20,
        overage_per_gib_storage_cents=30,
        overage_per_compute_second_millicents=30,
        rate_limit_rpm=300,
        rate_limit_tpm=200_000,
        hard_cap=False,
        active=True,
    )
    defaults.update(overrides)
    return PricingPlan(**defaults)


def _usage(**metrics) -> PeriodUsage:
    return PeriodUsage(
        tenant_id="alpha",
        period_start=datetime(2026, 4, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 5, 1, tzinfo=timezone.utc),
        totals={MetricType(k): float(v) for k, v in metrics.items()},
    )


def test_base_fee_line_item_present() -> None:
    gen = InvoiceGenerator()
    items, subtotal, tax, total = gen.build(plan=_plan(), usage=_usage())
    assert items[0].metric_type == "subscription.base"
    assert items[0].amount_cents == 4_900
    assert subtotal == 4_900
    assert tax == 0
    assert total == 4_900


def test_no_overage_no_metric_lines() -> None:
    gen = InvoiceGenerator()
    items, _, _, _ = gen.build(
        plan=_plan(),
        usage=_usage(**{"flow.execution": 50}),  # within included 100
    )
    assert len(items) == 1  # only base fee
    assert items[0].metric_type == "subscription.base"


def test_execution_overage_charged() -> None:
    gen = InvoiceGenerator()
    items, subtotal, _, total = gen.build(
        plan=_plan(),
        usage=_usage(**{"flow.execution": 150}),  # 50 over the 100 included
    )
    # Base + overage line
    assert len(items) == 2
    overage = items[1]
    assert overage.metric_type == "flow.execution"
    assert overage.quantity_overage == 50.0
    assert overage.amount_cents == 50  # 50 * 1 cent
    assert subtotal == 4_900 + 50
    assert total == subtotal


def test_tax_applied_when_rate_set() -> None:
    gen = InvoiceGenerator(tax_rate_percent=10.0)
    items, subtotal, tax, total = gen.build(
        plan=_plan(), usage=_usage()
    )
    assert subtotal == 4_900
    assert tax == 490  # 10% of 4900
    assert total == 5_390


def test_tokens_overage_billed_per_1k() -> None:
    gen = InvoiceGenerator()
    # include_tokens=10_000 split → included_per_metric=5000.
    # tokens_in=8000 → overage=3000 → 3 * 20c = 60c.
    items, subtotal, _, _ = gen.build(
        plan=_plan(), usage=_usage(**{"llm.tokens_in": 8000})
    )
    tokens_line = [i for i in items if i.metric_type == "llm.tokens_in"]
    assert len(tokens_line) == 1
    assert tokens_line[0].quantity_overage == 3000.0
    assert tokens_line[0].amount_cents == 60
    assert subtotal == 4_900 + 60


def test_storage_overage_rounds_up() -> None:
    gen = InvoiceGenerator()
    items, _, _, _ = gen.build(
        plan=_plan(), usage=_usage(**{"storage.bytes": 12.3})
    )
    line = [i for i in items if i.metric_type == "storage.bytes"]
    assert len(line) == 1
    # 12.3 - 10 included = 2.3 GiB overage; per_gib=30c → ceil(2.3 * 30) = 69c
    assert line[0].amount_cents == 69


def test_compute_overage_converts_millicents_to_cents() -> None:
    gen = InvoiceGenerator()
    # included_compute_seconds=3600, usage=7200 → overage=3600s
    # per_second=30 millicents → 3600 * 30 / 1000 = 108 cents
    items, _, _, _ = gen.build(
        plan=_plan(), usage=_usage(**{"compute.time": 7_200})
    )
    line = [i for i in items if i.metric_type == "compute.time"]
    assert len(line) == 1
    assert line[0].amount_cents == 108


def test_line_items_ordered_by_metric() -> None:
    gen = InvoiceGenerator()
    items, _, _, _ = gen.build(
        plan=_plan(),
        usage=_usage(
            **{
                "flow.execution": 150,
                "llm.tokens_in": 8_000,
                "storage.bytes": 15,
            }
        ),
    )
    # Base first, then sorted by metric_type alphabetically
    assert items[0].metric_type == "subscription.base"
    metrics = [i.metric_type for i in items[1:]]
    assert metrics == sorted(metrics)


def test_line_item_serialises_to_jsonable_dict() -> None:
    gen = InvoiceGenerator()
    items, _, _, _ = gen.build(
        plan=_plan(), usage=_usage(**{"flow.execution": 200})
    )
    jsonable = items[1].to_jsonable()
    assert isinstance(jsonable, dict)
    assert jsonable["metric_type"] == "flow.execution"
    assert jsonable["quantity_overage"] == 100.0
    assert jsonable["amount_cents"] == 100
