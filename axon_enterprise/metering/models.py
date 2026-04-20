"""Metering and billing data models."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class MetricType(str, Enum):
    """Types of usage metrics."""

    FLOW_EXECUTION = "flow:execution"
    LLM_TOKENS = "llm:tokens"  # tokens consumed
    API_CALLS = "api:calls"
    DATA_STORAGE = "data:storage"  # GB stored
    COMPUTE_HOURS = "compute:hours"


@dataclass
class UsageMetric:
    """A single usage metric."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID = uuid4()
    metric_type: MetricType = MetricType.FLOW_EXECUTION
    value: float = 0.0  # quantity
    unit: str = ""  # e.g., "executions", "tokens", "GB", "hours"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    flow_id: Optional[UUID] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "metric_type": self.metric_type.value,
            "value": self.value,
            "unit": self.unit,
            "timestamp": self.timestamp.isoformat(),
            "flow_id": str(self.flow_id) if self.flow_id else None,
            "metadata": self.metadata,
        }


@dataclass
class BillingRecord:
    """A billing record for an organization."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID = uuid4()
    period_start: datetime = field(default_factory=datetime.utcnow)
    period_end: datetime = field(default_factory=datetime.utcnow)
    metrics: dict[MetricType, float] = field(default_factory=dict)  # metric type -> total value
    subtotal: float = 0.0  # Before tax
    tax: float = 0.0
    total: float = 0.0
    status: str = "pending"  # "pending", "sent", "paid"
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "metrics": {k.value: v for k, v in self.metrics.items()},
            "subtotal": self.subtotal,
            "tax": self.tax,
            "total": self.total,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }
