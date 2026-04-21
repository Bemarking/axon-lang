"""Built-in plan definitions.

Seeded by migration 008 via ``INSERT ... ON CONFLICT DO NOTHING``
so operators can tune individual values via the Admin API without
the seed reverting on a redeploy.

Starter is the canonical hard-capped tier — suitable for free trials
and low-volume customers. Pro and Enterprise are overage-billed.

All monetary amounts are in USD cents unless otherwise noted.
``provider cost`` is in millicents (1/1000 USD) to track sub-cent
LLM pricing accurately.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BuiltInPlanSpec:
    """Snapshot of the canonical plans seeded at install time.

    Kept in code (not DB-only) so the test suite + CI + audit
    reviewers have a single place to compare against current
    ``pricing_plans`` rows.
    """

    plan_id: str
    display_name: str
    monthly_base_cents: int
    included_executions: int
    included_tokens: int
    included_storage_gib: int
    included_compute_seconds: int
    overage_per_execution_cents: int
    overage_per_1k_tokens_cents: int
    overage_per_gib_storage_cents: int
    overage_per_compute_second_millicents: int
    rate_limit_rpm: int
    rate_limit_tpm: int
    hard_cap: bool


BUILT_IN_PLANS: tuple[BuiltInPlanSpec, ...] = (
    BuiltInPlanSpec(
        plan_id="starter",
        display_name="Starter",
        monthly_base_cents=0,  # free trial
        included_executions=1_000,
        included_tokens=250_000,
        included_storage_gib=1,
        included_compute_seconds=3_600,
        overage_per_execution_cents=0,  # unused — hard_cap=True
        overage_per_1k_tokens_cents=0,
        overage_per_gib_storage_cents=0,
        overage_per_compute_second_millicents=0,
        rate_limit_rpm=30,
        rate_limit_tpm=20_000,
        hard_cap=True,
    ),
    BuiltInPlanSpec(
        plan_id="pro",
        display_name="Pro",
        monthly_base_cents=4_900,  # $49/mo
        included_executions=50_000,
        included_tokens=5_000_000,
        included_storage_gib=25,
        included_compute_seconds=180_000,  # 50 hours
        overage_per_execution_cents=1,  # $0.01 per execution
        overage_per_1k_tokens_cents=20,  # $0.002 per 1k tokens
        overage_per_gib_storage_cents=30,  # $0.30 per GiB-month
        overage_per_compute_second_millicents=30,  # $0.0003 per sec
        rate_limit_rpm=300,
        rate_limit_tpm=200_000,
        hard_cap=False,
    ),
    BuiltInPlanSpec(
        plan_id="enterprise",
        display_name="Enterprise",
        monthly_base_cents=49_900,  # $499/mo
        included_executions=1_000_000,
        included_tokens=100_000_000,
        included_storage_gib=500,
        included_compute_seconds=3_600_000,  # 1000 hours
        overage_per_execution_cents=0,  # negotiated — overage off by default
        overage_per_1k_tokens_cents=10,  # $0.001 per 1k tokens
        overage_per_gib_storage_cents=20,  # $0.20 per GiB-month
        overage_per_compute_second_millicents=20,
        rate_limit_rpm=6_000,
        rate_limit_tpm=2_000_000,
        hard_cap=False,
    ),
)


def plan_by_id(plan_id: str) -> BuiltInPlanSpec | None:
    """Lookup helper for tests + CLI."""
    for spec in BUILT_IN_PLANS:
        if spec.plan_id == plan_id:
            return spec
    return None
