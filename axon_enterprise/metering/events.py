"""Metric catalog + typed usage sample shape.

``MetricType`` is a closed enum. Each entry is paired with a stable
``MetricUnit`` so aggregation + invoicing layers never guess.
Adding a metric requires a migration that updates
``pricing_plans`` + tests so the catalog stays in sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID


class MetricUnit(StrEnum):
    """Wire-stable unit tag. Aggregator sums within the same unit only."""

    COUNT = "count"          # whole events (flow executions, API calls)
    TOKENS = "tokens"        # LLM tokens (in + out collapsed)
    KILOBYTES = "kibibytes"  # binary KiB
    GIGABYTES = "gibibytes"  # binary GiB (storage, egress)
    COMPUTE_SECONDS = "compute_seconds"
    MILLICENTS = "millicents"  # pass-through provider cost in 1/1000 USD


class MetricType(StrEnum):
    """Closed enum — extension via migration."""

    FLOW_EXECUTION = "flow.execution"
    FLOW_DEPLOYED = "flow.deployed"

    LLM_TOKENS_IN = "llm.tokens_in"
    LLM_TOKENS_OUT = "llm.tokens_out"

    STORAGE_BYTES = "storage.bytes"
    EGRESS_BYTES = "egress.bytes"

    API_CALLS = "api.calls"
    COMPUTE_TIME = "compute.time"

    PROVIDER_COST = "provider.cost_passthrough"

    def default_unit(self) -> MetricUnit:
        return _METRIC_DEFAULT_UNIT[self]


_METRIC_DEFAULT_UNIT: dict[MetricType, MetricUnit] = {
    MetricType.FLOW_EXECUTION: MetricUnit.COUNT,
    MetricType.FLOW_DEPLOYED: MetricUnit.COUNT,
    MetricType.LLM_TOKENS_IN: MetricUnit.TOKENS,
    MetricType.LLM_TOKENS_OUT: MetricUnit.TOKENS,
    MetricType.STORAGE_BYTES: MetricUnit.GIGABYTES,
    MetricType.EGRESS_BYTES: MetricUnit.GIGABYTES,
    MetricType.API_CALLS: MetricUnit.COUNT,
    MetricType.COMPUTE_TIME: MetricUnit.COMPUTE_SECONDS,
    MetricType.PROVIDER_COST: MetricUnit.MILLICENTS,
}


@dataclass(frozen=True, slots=True)
class UsageSample:
    """What callers hand to ``MeteringService.record``."""

    tenant_id: str
    metric_type: MetricType
    quantity: float
    unit: MetricUnit | None = None
    flow_id: UUID | None = None
    provider: str | None = None
    actor_user_id: UUID | None = None
    recorded_at: datetime | None = None
    metadata: dict[str, Any] | None = None

    def resolved_unit(self) -> MetricUnit:
        return self.unit or self.metric_type.default_unit()

    def resolved_timestamp(self) -> datetime:
        return self.recorded_at or datetime.now(timezone.utc)
