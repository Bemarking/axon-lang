"""
AXON Runtime — Store Metrics & Observability
===============================================
Structured metrics and logging for ``axonstore`` operations.

Provides:
  - Operation counters (per-operation, per-store)
  - Latency histograms (p50/p95/p99)
  - Error tracking with categorization
  - Structured log emission
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  METRICS COLLECTOR
# ═══════════════════════════════════════════════════════════════════


@dataclass
class OperationMetric:
    """Metrics for a single operation type."""
    count: int = 0
    error_count: int = 0
    total_duration_ms: float = 0.0
    min_duration_ms: float = float("inf")
    max_duration_ms: float = 0.0
    _durations: list[float] = field(default_factory=list, repr=False)

    def record(self, duration_ms: float, error: bool = False) -> None:
        """Record a single operation execution."""
        self.count += 1
        if error:
            self.error_count += 1
        self.total_duration_ms += duration_ms
        if duration_ms < self.min_duration_ms:
            self.min_duration_ms = duration_ms
        if duration_ms > self.max_duration_ms:
            self.max_duration_ms = duration_ms
        # Keep last 1000 durations for percentile calculation
        self._durations.append(duration_ms)
        if len(self._durations) > 1000:
            self._durations = self._durations[-1000:]

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / self.count if self.count else 0.0

    def percentile(self, p: float) -> float:
        """Calculate the p-th percentile of recorded durations."""
        if not self._durations:
            return 0.0
        sorted_d = sorted(self._durations)
        idx = int(len(sorted_d) * p / 100.0)
        idx = min(idx, len(sorted_d) - 1)
        return sorted_d[idx]

    @property
    def error_rate(self) -> float:
        return self.error_count / self.count if self.count else 0.0


class StoreMetrics:
    """Centralized metrics collector for all store operations.

    Thread-safe (for single-threaded async) — records operation
    counts, latencies, and errors per store + operation type.
    """

    def __init__(self) -> None:
        # Nested: store_name → operation → OperationMetric
        self._metrics: dict[str, dict[str, OperationMetric]] = defaultdict(
            lambda: defaultdict(OperationMetric)
        )
        self._global = OperationMetric()
        self._start_time = time.monotonic()

    def record(
        self,
        store_name: str,
        operation: str,
        duration_ms: float,
        error: bool = False,
    ) -> None:
        """Record an operation execution."""
        self._metrics[store_name][operation].record(duration_ms, error)
        self._global.record(duration_ms, error)

        if error:
            logger.warning(
                "axonstore.op.error",
                extra={
                    "store": store_name,
                    "operation": operation,
                    "duration_ms": round(duration_ms, 2),
                },
            )
        else:
            logger.debug(
                "axonstore.op.ok",
                extra={
                    "store": store_name,
                    "operation": operation,
                    "duration_ms": round(duration_ms, 2),
                },
            )

    @asynccontextmanager
    async def track(
        self, store_name: str, operation: str,
    ) -> AsyncGenerator[None, None]:
        """Context manager to automatically track operation timing."""
        start = time.perf_counter()
        error = False
        try:
            yield
        except Exception:
            error = True
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self.record(store_name, operation, duration_ms, error)

    def snapshot(self) -> dict[str, Any]:
        """Return a snapshot of all metrics."""
        uptime = time.monotonic() - self._start_time
        result: dict[str, Any] = {
            "uptime_seconds": round(uptime, 1),
            "global": {
                "total_ops": self._global.count,
                "total_errors": self._global.error_count,
                "error_rate": round(self._global.error_rate, 4),
                "avg_duration_ms": round(self._global.avg_duration_ms, 2),
                "p50_ms": round(self._global.percentile(50), 2),
                "p95_ms": round(self._global.percentile(95), 2),
                "p99_ms": round(self._global.percentile(99), 2),
            },
            "stores": {},
        }
        for store_name, ops in self._metrics.items():
            store_data: dict[str, Any] = {}
            for op_name, metric in ops.items():
                store_data[op_name] = {
                    "count": metric.count,
                    "errors": metric.error_count,
                    "avg_ms": round(metric.avg_duration_ms, 2),
                    "p95_ms": round(metric.percentile(95), 2),
                }
            result["stores"][store_name] = store_data
        return result

    def reset(self) -> None:
        """Reset all metrics."""
        self._metrics.clear()
        self._global = OperationMetric()
        self._start_time = time.monotonic()
