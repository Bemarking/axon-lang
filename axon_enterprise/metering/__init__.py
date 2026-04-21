"""Metering + quota enforcement + invoicing — Fase 10.h.

Replaces the v1.0.0 ``MeteringCollector`` scaffolding (in-memory
list, ``organization_id`` instead of ``tenant_id``, billing
hard-coded to zero) with a real system:

- **Typed metric catalog** (``MetricType``) with stable unit labels.
- **PricingPlan** seeded per tenant — starter / pro / enterprise with
  ``hard_cap`` flag. Overage billed at per-unit rates.
- **UsageEvent** append-rich table with tenant scoping + RLS.
- **QuotaEnforcer**: per-minute rate limit (Redis / memory) +
  per-month quota (Postgres aggregate). Enforcement is real — 429
  on rate, 402 Payment Required semantics on hard-cap overflow.
- **InvoiceGenerator**: pure function taking a plan + aggregated
  usage, produces an ``Invoice`` row with itemised ``line_items``.
  Idempotent per (tenant_id, period).
- **StripeClient**: lazy import, optional — when disabled invoices
  stay in ``draft`` status for operator review.
"""

from axon_enterprise.metering.errors import (
    InvoiceAlreadyIssued,
    MeteringBackendError,
    MeteringError,
    PlanNotFound,
    QuotaExceeded,
    RateLimited,
    StripeIntegrationError,
    UsageRecordInvalid,
)
from axon_enterprise.metering.events import (
    MetricType,
    MetricUnit,
    UsageSample,
)
from axon_enterprise.metering.invoicing import (
    InvoiceGenerator,
    LineItem,
    PeriodUsage,
    aggregate_period,
)
from axon_enterprise.metering.limiter import (
    InMemoryRateLimiter,
    RateLimiter,
    RedisRateLimiter,
    build_rate_limiter,
)
from axon_enterprise.metering.models import (
    Invoice,
    InvoiceStatus,
    PricingPlan,
    TenantSubscription,
    UsageEvent,
)
from axon_enterprise.metering.pricing import (
    BUILT_IN_PLANS,
    BuiltInPlanSpec,
)
from axon_enterprise.metering.quota import (
    QuotaDecision,
    QuotaEnforcer,
)
from axon_enterprise.metering.service import MeteringService
from axon_enterprise.metering.stripe_client import StripeClient

__all__ = [
    "BUILT_IN_PLANS",
    "BuiltInPlanSpec",
    "InMemoryRateLimiter",
    "Invoice",
    "InvoiceAlreadyIssued",
    "InvoiceGenerator",
    "InvoiceStatus",
    "LineItem",
    "MeteringBackendError",
    "MeteringError",
    "MeteringService",
    "MetricType",
    "MetricUnit",
    "PeriodUsage",
    "PlanNotFound",
    "PricingPlan",
    "QuotaDecision",
    "QuotaEnforcer",
    "QuotaExceeded",
    "RateLimited",
    "RateLimiter",
    "RedisRateLimiter",
    "StripeClient",
    "StripeIntegrationError",
    "TenantSubscription",
    "UsageEvent",
    "UsageRecordInvalid",
    "UsageSample",
    "aggregate_period",
    "build_rate_limiter",
]
