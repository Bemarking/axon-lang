# Metering + Quota Enforcement — Operator Guide

Replaces the v1.0.0 ``MeteringCollector`` scaffolding (in-memory
list, ``organization_id`` placeholder, billing hard-coded to zero)
with a tenant-scoped, quota-enforcing, Stripe-integrable system.

## Data model

| Table | Purpose | RLS |
|---|---|---|
| ``pricing_plans`` | Global catalog — starter / pro / enterprise seeded by migration 008 | No RLS (global) |
| ``tenant_subscriptions`` | One row per tenant — binds to a plan + current billing period | tenant_isolation |
| ``usage_events`` | Append-rich per-tenant billable events | tenant_isolation |
| ``invoices`` | Finalised billing artefact with JSONB line items | tenant_isolation |

``invoices`` is UNIQUE on ``(tenant_id, period_start, period_end)`` —
the DB refuses double-billing for the same period.

## Built-in plans

| Plan | Base | Executions | Tokens | Storage | Compute | Rate limit | Hard cap |
|---|---|---|---|---|---|---|---|
| starter | $0/mo | 1,000 | 250k | 1 GiB | 1 hr | 30 rpm / 20k tpm | ✅ yes |
| pro | $49/mo | 50,000 | 5M | 25 GiB | 50 hrs | 300 rpm / 200k tpm | ❌ overage billed |
| enterprise | $499/mo | 1M | 100M | 500 GiB | 1000 hrs | 6000 rpm / 2M tpm | ❌ overage billed |

Overage pricing (in cents, per unit):

| Metric | Pro | Enterprise |
|---|---|---|
| Execution | 1¢ | 0¢ (negotiated) |
| 1k LLM tokens | 20¢ | 10¢ |
| GiB storage-month | 30¢ | 20¢ |
| Compute second | 0.03¢ | 0.02¢ |

Operators can override individual values via the Admin API (10.j) —
the ON CONFLICT DO NOTHING migration means seed values are applied
only on fresh DBs, not on redeploy.

## Quota enforcement

Every billable call-site invokes ``MeteringService.authorise`` before
starting the work:

```python
from axon_enterprise.metering import MeteringService, UsageSample, MetricType

metering = MeteringService.default()

sample = UsageSample(
    tenant_id=ctx.tenant_id,
    metric_type=MetricType.FLOW_EXECUTION,
    quantity=1,
    actor_user_id=principal.user_id,
    flow_id=flow.flow_id,
)

decision = await metering.authorise(db, sample)
# ... run the flow ...
await metering.record(db, sample)
```

``authorise`` performs two checks in order:

1. **Rate limit** via ``RateLimiter.check_and_record`` (Redis or
   in-memory). Raises ``RateLimited`` with ``retry_after_seconds``
   when the per-minute ceiling is hit.
2. **Monthly quota**: ``SUM(usage_events.quantity)`` for the metric
   in the current billing period + the requested ``quantity``. If
   the plan is ``hard_cap``, over-allowance raises ``QuotaExceeded``.
   Otherwise the decision carries ``overage_quantity > 0`` and the
   caller proceeds.

**Failure-path separation**: rate limit counters increment inside
``authorise`` and DO NOT decrement when the downstream work fails.
The monthly quota counter only increments after ``record`` persists
the event — so billing always reflects successful usage, while the
rate limiter slightly over-counts on failure paths (operator's
choice, keeps the limiter lock-free).

## Rate limiter

| Backend | When |
|---|---|
| Redis | Production — single atomic Lua round-trip, sliding window |
| In-memory | Dev / tests / single-replica — thread-safe dict |

Configured via ``AXON_METERING_RATE_LIMIT_BACKEND=redis|memory``.
Redis backend uses a sliding window with ``ZADD`` + ``ZRANGEBYSCORE``
and a 120-second TTL so counter data survives a restart without
outliving its relevance.

## Invoicing

``InvoiceGenerator`` is a pure function over a ``PricingPlan`` + a
``PeriodUsage`` aggregate. Output:

- One ``subscription.base`` line item (always, when base > 0)
- One line per metric with overage
- Each line carries ``quantity_total``, ``quantity_included``,
  ``quantity_overage``, ``unit_amount_cents``, ``amount_cents``,
  ``description``

```python
invoice = await metering.issue_invoice(
    db,
    tenant_id=ctx.tenant_id,
    period_start=period_start,
    period_end=period_end,
)
# invoice.status == 'draft' when Stripe disabled
# invoice.status == 'finalized' + stripe_invoice_id populated when enabled
```

Idempotency is enforced by ``UNIQUE (tenant_id, period_start,
period_end)`` — the batch can rerun safely. Collisions raise
``InvoiceAlreadyIssued``.

## Stripe integration

Disabled by default. Enable with:

```
AXON_METERING_STRIPE_ENABLED=true
AXON_METERING_STRIPE_API_KEY=sk_live_...
AXON_METERING_STRIPE_WEBHOOK_SECRET=whsec_...
AXON_METERING_STRIPE_API_VERSION=2024-12-18
```

Production validator refuses ``stripe_enabled=true`` without the
two secrets — fail-fast at startup.

``StripeClient.issue_invoice`` creates ``InvoiceItem`` rows per
``LineItem`` then ``Invoice.create`` + ``finalize_invoice``. Returns
the Stripe invoice id which is stored on our ``Invoice`` row.

``StripeClient.verify_webhook(payload, signature_header)`` wraps
``stripe.Webhook.construct_event`` — callers (10.j HTTP handler) route
on ``event["type"]``. Webhooks update the ``status`` column when
Stripe notifies of payment success / failure.

## Audit integration

``MeteringAuditEmitter`` is a Protocol; when passed to
``MeteringService.default(audit=...)`` the service emits:

- ``metering:usage_recorded`` on every ``record`` (10.g audit chain)
- ``metering:invoice_issued`` on every invoice (10.g audit chain)
- ``metering:quota_exceeded`` when the enforcer raises (structured log)
- ``metering:rate_limited`` when the limiter raises (structured log)

Default emitter is a no-op — the hash-chained writer lands when the
caller wires a ``MeteringAuditAdapter`` (added alongside the HTTP
layer in 10.j).

## Required environment

### Dev / test
```
AXON_METERING_RATE_LIMIT_BACKEND=memory
AXON_METERING_STRIPE_ENABLED=false
```

### Production
```
AXON_METERING_RATE_LIMIT_BACKEND=redis
AXON_METERING_RATE_LIMIT_REDIS_URL=rediss://user:pw@host:6380/0
AXON_METERING_STRIPE_ENABLED=true
AXON_METERING_STRIPE_API_KEY=<from-secrets-manager>
AXON_METERING_STRIPE_WEBHOOK_SECRET=<from-secrets-manager>
AXON_METERING_TAX_RATE_PERCENT=0.0
AXON_METERING_INVOICE_CURRENCY=USD
AXON_METERING_INVOICE_DUE_DAYS=15
```

## What comes next

- 10.i (Observability): Prometheus counters for
  ``axon_usage_events_total{tenant,metric}``,
  ``axon_quota_denials_total{tenant,reason}``,
  ``axon_rate_limits_total{tenant,metric}``
- 10.j (Admin API): HTTP handlers + the Stripe webhook route
- 10.k (Portal): usage dashboards + invoice PDFs
- 10.l (Compliance): invoice retention + billing-period cron jobs
