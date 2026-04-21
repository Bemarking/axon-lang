"""metering — pricing_plans + tenant_subscriptions + usage_events + invoices

Seeds the three built-in plans (starter / pro / enterprise) via
``INSERT ... ON CONFLICT DO NOTHING`` so operator tuning via the
Admin API survives redeploys.

All tenant-scoped tables carry ``tenant_isolation + admin_bypass``
RLS. ``pricing_plans`` is global (no RLS) — the catalogue is
shared across tenants.

Revision ID: 008
Revises: 007
Create Date: 2026-04-21 07:00:00+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from axon_enterprise.db.rls_policies import full_policy_set_sql
from axon_enterprise.metering.pricing import BUILT_IN_PLANS

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── pricing_plans (global) ────────────────────────────────────────
    op.create_table(
        "pricing_plans",
        sa.Column("plan_id", sa.String(32), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "monthly_base_cents", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "included_executions",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "included_tokens", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "included_storage_gib",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "included_compute_seconds",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "overage_per_execution_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "overage_per_1k_tokens_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "overage_per_gib_storage_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "overage_per_compute_second_millicents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "rate_limit_rpm", sa.Integer(), nullable=False, server_default="60"
        ),
        sa.Column(
            "rate_limit_tpm",
            sa.BigInteger(),
            nullable=False,
            server_default="100000",
        ),
        sa.Column(
            "hard_cap", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="axon_control",
    )

    # Seed built-in plans via a single bulk insert. Deterministic order.
    for spec in sorted(BUILT_IN_PLANS, key=lambda p: p.plan_id):
        op.execute(
            sa.text(
                """
                INSERT INTO axon_control.pricing_plans (
                    plan_id, display_name, monthly_base_cents,
                    included_executions, included_tokens,
                    included_storage_gib, included_compute_seconds,
                    overage_per_execution_cents, overage_per_1k_tokens_cents,
                    overage_per_gib_storage_cents,
                    overage_per_compute_second_millicents,
                    rate_limit_rpm, rate_limit_tpm, hard_cap
                ) VALUES (
                    :plan_id, :display_name, :monthly_base_cents,
                    :included_executions, :included_tokens,
                    :included_storage_gib, :included_compute_seconds,
                    :overage_per_execution_cents, :overage_per_1k_tokens_cents,
                    :overage_per_gib_storage_cents,
                    :overage_per_compute_second_millicents,
                    :rate_limit_rpm, :rate_limit_tpm, :hard_cap
                ) ON CONFLICT (plan_id) DO NOTHING
                """
            ).bindparams(
                plan_id=spec.plan_id,
                display_name=spec.display_name,
                monthly_base_cents=spec.monthly_base_cents,
                included_executions=spec.included_executions,
                included_tokens=spec.included_tokens,
                included_storage_gib=spec.included_storage_gib,
                included_compute_seconds=spec.included_compute_seconds,
                overage_per_execution_cents=spec.overage_per_execution_cents,
                overage_per_1k_tokens_cents=spec.overage_per_1k_tokens_cents,
                overage_per_gib_storage_cents=spec.overage_per_gib_storage_cents,
                overage_per_compute_second_millicents=(
                    spec.overage_per_compute_second_millicents
                ),
                rate_limit_rpm=spec.rate_limit_rpm,
                rate_limit_tpm=spec.rate_limit_tpm,
                hard_cap=spec.hard_cap,
            )
        )

    # ── tenant_subscriptions ──────────────────────────────────────────
    op.create_table(
        "tenant_subscriptions",
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey(
                "public.tenants.tenant_id",
                ondelete="CASCADE",
                onupdate="CASCADE",
                name="fk_tenant_subscriptions_tenant_id_tenants",
            ),
            primary_key=True,
        ),
        sa.Column(
            "plan_id",
            sa.String(32),
            sa.ForeignKey(
                "axon_control.pricing_plans.plan_id",
                ondelete="RESTRICT",
                onupdate="CASCADE",
                name="fk_tenant_subscriptions_plan_id_pricing_plans",
            ),
            nullable=False,
        ),
        sa.Column(
            "current_period_start", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "current_period_end", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("stripe_customer_id", sa.Text(), nullable=True),
        sa.Column("stripe_subscription_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="axon_control",
    )
    op.create_index(
        "ix_tenant_subscriptions_plan_id",
        "tenant_subscriptions",
        ["plan_id"],
        schema="axon_control",
    )
    for stmt in full_policy_set_sql(
        table="tenant_subscriptions", schema="axon_control"
    ):
        op.execute(stmt)

    # ── usage_events ──────────────────────────────────────────────────
    op.create_table(
        "usage_events",
        sa.Column(
            "usage_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey(
                "public.tenants.tenant_id",
                ondelete="RESTRICT",
                onupdate="CASCADE",
                name="fk_usage_events_tenant_id_tenants",
            ),
            nullable=False,
        ),
        sa.Column("metric_type", sa.String(64), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column(
            "actor_user_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_usage_events_quantity_nonneg"),
        schema="axon_control",
    )
    op.create_index(
        "ix_usage_events_tenant_id",
        "usage_events",
        ["tenant_id"],
        schema="axon_control",
    )
    op.create_index(
        "ix_usage_events_tenant_id_recorded_at",
        "usage_events",
        ["tenant_id", "recorded_at"],
        schema="axon_control",
    )
    op.create_index(
        "ix_usage_events_tenant_id_metric_type_recorded_at",
        "usage_events",
        ["tenant_id", "metric_type", "recorded_at"],
        schema="axon_control",
    )
    for stmt in full_policy_set_sql(table="usage_events", schema="axon_control"):
        op.execute(stmt)

    # ── invoices ──────────────────────────────────────────────────────
    op.create_table(
        "invoices",
        sa.Column(
            "invoice_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            sa.String(64),
            sa.ForeignKey(
                "public.tenants.tenant_id",
                ondelete="RESTRICT",
                onupdate="CASCADE",
                name="fk_invoices_tenant_id_tenants",
            ),
            nullable=False,
        ),
        sa.Column(
            "period_start", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "period_end", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "currency", sa.String(3), nullable=False, server_default="USD"
        ),
        sa.Column(
            "line_items",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("subtotal_cents", sa.Integer(), nullable=False),
        sa.Column(
            "tax_cents", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("total_cents", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("stripe_invoice_id", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('draft','finalized','paid','void','failed')",
            name="ck_invoices_status",
        ),
        sa.CheckConstraint(
            "period_end > period_start",
            name="ck_invoices_period_order",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "period_start",
            "period_end",
            name="uq_invoices_tenant_id_period",
        ),
        schema="axon_control",
    )
    op.create_index(
        "ix_invoices_tenant_id_status_issued_at",
        "invoices",
        ["tenant_id", "status", "issued_at"],
        schema="axon_control",
    )
    for stmt in full_policy_set_sql(table="invoices", schema="axon_control"):
        op.execute(stmt)


def downgrade() -> None:
    op.drop_table("invoices", schema="axon_control")
    op.drop_table("usage_events", schema="axon_control")
    op.drop_table("tenant_subscriptions", schema="axon_control")
    op.drop_table("pricing_plans", schema="axon_control")
