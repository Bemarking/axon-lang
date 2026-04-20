"""Metering data collection service."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from axon_enterprise.metering.models import BillingRecord, MetricType, UsageMetric


class MeteringCollector:
    """Service for collecting and aggregating usage metrics."""

    def __init__(self):
        """Initialize metering collector."""
        self.metrics: list[UsageMetric] = []
        self.billing_records: list[BillingRecord] = []

    def record_metric(
        self,
        organization_id: UUID,
        metric_type: MetricType,
        value: float,
        unit: str = "",
        flow_id: Optional[UUID] = None,
        metadata: dict = None,
    ) -> UsageMetric:
        """Record a usage metric."""
        if metadata is None:
            metadata = {}

        metric = UsageMetric(
            organization_id=organization_id,
            metric_type=metric_type,
            value=value,
            unit=unit,
            flow_id=flow_id,
            metadata=metadata,
        )

        # TODO: Persist metric to database
        self.metrics.append(metric)
        return metric

    def record_flow_execution(self, organization_id: UUID, flow_id: UUID) -> UsageMetric:
        """Record a flow execution."""
        return self.record_metric(
            organization_id=organization_id,
            metric_type=MetricType.FLOW_EXECUTION,
            value=1.0,
            unit="executions",
            flow_id=flow_id,
        )

    def record_llm_tokens(self, organization_id: UUID, tokens_in: int, tokens_out: int, flow_id: Optional[UUID] = None) -> UsageMetric:
        """Record LLM token usage."""
        total_tokens = tokens_in + tokens_out
        return self.record_metric(
            organization_id=organization_id,
            metric_type=MetricType.LLM_TOKENS,
            value=total_tokens,
            unit="tokens",
            flow_id=flow_id,
            metadata={"tokens_in": tokens_in, "tokens_out": tokens_out},
        )

    def aggregate_metrics(self, organization_id: UUID, start_date: datetime, end_date: datetime) -> dict[MetricType, float]:
        """Aggregate metrics for a date range."""
        aggregated = {}

        for metric in self.metrics:
            if metric.organization_id != organization_id:
                continue
            if not (start_date <= metric.timestamp <= end_date):
                continue

            if metric.metric_type not in aggregated:
                aggregated[metric.metric_type] = 0.0

            aggregated[metric.metric_type] += metric.value

        return aggregated

    def create_billing_record(self, organization_id: UUID, period_start: datetime, period_end: datetime) -> BillingRecord:
        """Create a billing record for an organization."""
        metrics = self.aggregate_metrics(organization_id, period_start, period_end)

        # TODO: Calculate costs based on metrics and pricing plan
        subtotal = 0.0
        tax = subtotal * 0.08  # 8% tax rate (configurable)

        record = BillingRecord(
            organization_id=organization_id,
            period_start=period_start,
            period_end=period_end,
            metrics=metrics,
            subtotal=subtotal,
            tax=tax,
            total=subtotal + tax,
            status="pending",
        )

        # TODO: Persist record to database
        self.billing_records.append(record)
        return record

    def get_billing_record(self, record_id: UUID) -> Optional[BillingRecord]:
        """Retrieve a billing record."""
        for record in self.billing_records:
            if record.id == record_id:
                return record
        return None
