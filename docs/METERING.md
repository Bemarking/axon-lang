# Usage Metering & Billing

## Overview

Metering tracks usage metrics for billing and capacity planning.

## Metrics

### Flow Execution
- `flow:execution` — Count of flow executions

### LLM Usage
- `llm:tokens` — Tokens consumed (input + output)
- Tracked per provider (Anthropic, OpenAI, etc.)

### API Calls
- `api:calls` — Count of HTTP API calls

### Data Storage
- `data:storage` — GB of data stored

### Compute
- `compute:hours` — Compute hours used

## Usage

```python
from axon_enterprise.metering import MeteringCollector, MetricType
from uuid import UUID

collector = MeteringCollector()

# Record flow execution
collector.record_flow_execution(
    organization_id=org.id,
    flow_id=flow.id,
)

# Record LLM token usage
collector.record_llm_tokens(
    organization_id=org.id,
    tokens_in=1500,
    tokens_out=500,
    flow_id=flow.id,
)

# Custom metric
collector.record_metric(
    organization_id=org.id,
    metric_type=MetricType.DATA_STORAGE,
    value=2.5,  # 2.5 GB
    unit="GB",
)
```

## Billing

```python
from datetime import datetime, timedelta

# Create monthly billing record
period_start = datetime(2024, 1, 1)
period_end = datetime(2024, 1, 31)

record = collector.create_billing_record(
    organization_id=org.id,
    period_start=period_start,
    period_end=period_end,
)

# record.subtotal, record.tax, record.total
print(f"Invoice total: ${record.total:.2f}")
```

## Pricing Model

Example pricing:
- Flow execution: $0.001 per execution
- LLM tokens: $0.0001 per token
- API calls: $0.0001 per call (first 10k free)
- Data storage: $0.05 per GB per month
- Compute: $0.50 per compute hour

## Best Practices

- Record metrics immediately after operation
- Aggregate metrics daily for reporting
- Implement metering in critical paths (not sampling)
- Export metrics to data warehouse for analysis
- Monitor metric anomalies (usage spikes)
- Communicate pricing changes 30 days in advance
