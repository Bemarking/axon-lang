"""Metrics collection and aggregation for advanced observability."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Metric:
    """A single metric measurement."""

    name: str
    value: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    tags: dict[str, str] = field(default_factory=dict)
    labels: dict[str, Any] = field(default_factory=dict)


class MetricsCollector:
    """Collects and aggregates metrics for observability."""

    def __init__(self):
        """Initialize metrics collector."""
        self.metrics: list[Metric] = []
        self.counters: dict[str, int] = {}
        self.gauges: dict[str, float] = {}
        self.histograms: dict[str, list[float]] = {}

    def counter(self, name: str, value: int = 1, tags: dict[str, str] = None) -> None:
        """Increment a counter metric."""
        if tags is None:
            tags = {}

        if name not in self.counters:
            self.counters[name] = 0

        self.counters[name] += value

        # TODO: Send to metrics backend (Prometheus, DataDog, etc.)

    def gauge(self, name: str, value: float, tags: dict[str, str] = None) -> None:
        """Set a gauge metric."""
        if tags is None:
            tags = {}

        self.gauges[name] = value

        # TODO: Send to metrics backend

    def histogram(self, name: str, value: float, tags: dict[str, str] = None) -> None:
        """Record a histogram metric."""
        if tags is None:
            tags = {}

        if name not in self.histograms:
            self.histograms[name] = []

        self.histograms[name].append(value)

        # TODO: Send to metrics backend

    def record_metric(self, metric: Metric) -> None:
        """Record a custom metric."""
        self.metrics.append(metric)

        # TODO: Send to metrics backend

    def record_flow_latency(self, flow_name: str, latency_ms: float) -> None:
        """Record flow execution latency."""
        self.histogram(
            "flow:latency_ms",
            latency_ms,
            tags={"flow": flow_name},
        )

    def record_llm_latency(self, provider: str, latency_ms: float) -> None:
        """Record LLM API latency."""
        self.histogram(
            "llm:latency_ms",
            latency_ms,
            tags={"provider": provider},
        )

    def record_error(self, error_type: str, tags: dict[str, str] = None) -> None:
        """Record an error occurrence."""
        if tags is None:
            tags = {}

        tags["error_type"] = error_type

        self.counter("error:count", value=1, tags=tags)

    def get_counter(self, name: str) -> int:
        """Get counter value."""
        return self.counters.get(name, 0)

    def get_gauge(self, name: str) -> float:
        """Get gauge value."""
        return self.gauges.get(name, 0.0)

    def get_histogram(self, name: str) -> list[float]:
        """Get histogram values."""
        return self.histograms.get(name, [])
