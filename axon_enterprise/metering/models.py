"""ORM for metering / pricing / invoicing.

    pricing_plans          global — seeded via migration with built-in
                           tiers; operators may add custom plans via
                           the Admin API (10.j)
    tenant_subscriptions   per-tenant row binding a tenant to a plan;
                           tracks billing period + Stripe customer id
    usage_events           append-rich per-tenant table — every billable
                           event lands here, aggregated on invoice day
    invoices               finalised billing artefact with JSONB
                           ``line_items``; Stripe-issuable rows carry
                           ``stripe_invoice_id`` after sync
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from axon_enterprise.db.base import Base, TimestampMixin


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    FINALIZED = "finalized"
    PAID = "paid"
    VOID = "void"
    FAILED = "failed"


# ── pricing_plans (global) ──────────────────────────────────────────


class PricingPlan(TimestampMixin, Base):
    """Price card for a subscription tier. Global, not tenant-scoped."""

    __tablename__ = "pricing_plans"

    plan_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)

    monthly_base_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    # Per-plan quotas. ``None`` (stored as -1 sentinel) means unlimited.
    included_executions: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    included_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    included_storage_gib: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    included_compute_seconds: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )

    overage_per_execution_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    overage_per_1k_tokens_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    overage_per_gib_storage_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    overage_per_compute_second_millicents: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    rate_limit_rpm: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="60"
    )
    rate_limit_tpm: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default="100000",
        comment="Tokens per minute hard-coded ceiling, protects against runaway prompts.",
    )

    hard_cap: Mapped[bool] = mapped_column(
        nullable=False,
        server_default="false",
        comment=(
            "When True, quotas are hard ceilings — exceeding raises "
            "QuotaExceeded. When False, overage is billed."
        ),
    )
    active: Mapped[bool] = mapped_column(
        nullable=False, server_default="true"
    )


# ── tenant_subscriptions ────────────────────────────────────────────


class TenantSubscription(TimestampMixin, Base):
    """One row per tenant — binds the tenant to a plan + billing period."""

    __tablename__ = "tenant_subscriptions"

    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "axon_admin.tenants.tenant_id",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        primary_key=True,
    )
    plan_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(
            "axon_control.pricing_plans.plan_id",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    current_period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    current_period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    stripe_customer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── usage_events (per-tenant) ───────────────────────────────────────


class UsageEvent(Base):
    """One row per billable event. High-volume table — append-only.

    Tenant-scoped RLS applies. No UPDATE trigger (only audit_events is
    strictly append-only at the DB level); usage events are aggregated
    and rarely mutated, but correction paths (out-of-band) may need
    UPDATE access via admin_bypass.
    """

    __tablename__ = "usage_events"

    usage_id: Mapped[UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "axon_admin.tenants.tenant_id",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    metric_type: Mapped[str] = mapped_column(String(64), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)

    actor_user_id: Mapped[UUID | None] = mapped_column(nullable=True)
    flow_id: Mapped[UUID | None] = mapped_column(nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)

    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index(
            "ix_usage_events_tenant_id_recorded_at",
            "tenant_id",
            "recorded_at",
        ),
        Index(
            "ix_usage_events_tenant_id_metric_type_recorded_at",
            "tenant_id",
            "metric_type",
            "recorded_at",
        ),
    )


# ── invoices ───────────────────────────────────────────────────────


class Invoice(TimestampMixin, Base):
    """Finalised billing artefact. One per (tenant, period)."""

    __tablename__ = "invoices"

    invoice_id: Mapped[UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "axon_admin.tenants.tenant_id",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        nullable=False,
    )

    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="USD"
    )

    line_items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )

    subtotal_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=InvoiceStatus.DRAFT.value,
    )

    stripe_invoice_id: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )

    issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "period_start",
            "period_end",
            name="uq_invoices_tenant_id_period",
        ),
        Index(
            "ix_invoices_tenant_id_status_issued_at",
            "tenant_id",
            "status",
            "issued_at",
        ),
    )
