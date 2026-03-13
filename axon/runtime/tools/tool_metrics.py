"""
AXON Runtime — Tool Metrics & Feedback Loop (v0.11.0)
======================================================
Observability and quality feedback for tool executions.

``ToolMetrics`` records per-invocation data (timing, success,
attempt count).  ``ToolMetricsCollector`` aggregates observations
and provides a ``recommend()`` method that suggests the best
tool for a task based on historical performance.

Addresses weaknesses **W3** (no metrics/traceability) and
**W7** (no quality feedback loop).
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════════════
#  ToolMetrics — single observation
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class ToolMetrics:
    """Performance observation for a single tool execution.

    Attributes:
        tool_name:        Name of the tool executed.
        execution_time_ms: Wall-clock time in milliseconds.
        success:          Whether execution succeeded.
        is_stub:          Whether the tool was a stub implementation.
        result_size:      Approximate size of ``ToolResult.data`` (chars).
        attempt_count:    Number of attempts (1 = first try succeeded).
        timestamp:        Unix timestamp of the observation.
    """

    tool_name: str
    execution_time_ms: float
    success: bool
    is_stub: bool = False
    result_size: int = 0
    attempt_count: int = 1
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "success": self.success,
            "is_stub": self.is_stub,
            "result_size": self.result_size,
            "attempt_count": self.attempt_count,
            "timestamp": self.timestamp,
        }


# ═══════════════════════════════════════════════════════════════════
#  ToolMetricsCollector — aggregation & feedback loop
# ═══════════════════════════════════════════════════════════════════


@dataclass
class ToolMetricsCollector:
    """Accumulates tool metrics and provides aggregated insights.

    The ``recommend()`` method implements the **W7 feedback loop**:
    given a set of candidate tool names, it returns the one with
    the best historical performance (success rate × speed).

    Example::

        collector = ToolMetricsCollector()
        collector.record(ToolMetrics("WebSearch", 120.5, True))
        collector.record(ToolMetrics("WebSearch", 95.3, True))
        summary = collector.summary("WebSearch")
        # {'avg_time_ms': 107.9, 'success_rate': 1.0, ...}
    """

    _observations: dict[str, list[ToolMetrics]] = field(
        default_factory=dict,
    )

    # ── recording ─────────────────────────────────────────────

    def record(self, metric: ToolMetrics) -> None:
        """Record a tool execution observation."""
        if metric.tool_name not in self._observations:
            self._observations[metric.tool_name] = []
        self._observations[metric.tool_name].append(metric)

    # ── querying ──────────────────────────────────────────────

    def summary(self, tool_name: str | None = None) -> dict[str, Any]:
        """Return aggregated summary for a tool (or all tools).

        Args:
            tool_name: Specific tool name, or ``None`` for all tools.

        Returns:
            Dict with ``avg_time_ms``, ``success_rate``,
            ``total_executions``, ``avg_attempts``, ``stub_ratio``.
        """
        if tool_name:
            return self._summarize_single(tool_name)

        return {
            name: self._summarize_single(name)
            for name in sorted(self._observations.keys())
        }

    def recommend(
        self,
        candidates: list[str],
        *,
        task_hint: str = "",
    ) -> str | None:
        """Recommend the best tool from *candidates* based on history.

        Scoring: ``success_rate × (1 / avg_time_ms)``  Higher = better.

        This implements the **W7 feedback loop** — the system learns
        from past executions and recommends accordingly.

        Args:
            candidates: List of tool names to consider.
            task_hint:  Optional hint about the task (for future use).

        Returns:
            Tool name with best score, or ``None`` if no data.
        """
        best_name: str | None = None
        best_score: float = -1.0

        for name in candidates:
            if name not in self._observations:
                continue

            summary = self._summarize_single(name)
            success_rate = summary["success_rate"]
            avg_time = summary["avg_time_ms"]

            # Avoid division by zero
            if avg_time <= 0:
                avg_time = 1.0

            score = success_rate * (1000.0 / avg_time)

            if score > best_score:
                best_score = score
                best_name = name

        return best_name

    # ── serialization ─────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize all observations and summaries."""
        return {
            "tools": {
                name: {
                    "summary": self._summarize_single(name),
                    "observation_count": len(observations),
                }
                for name, observations in self._observations.items()
            },
            "total_observations": sum(
                len(v) for v in self._observations.values()
            ),
        }

    @property
    def tool_names(self) -> list[str]:
        """List of all tools that have been observed."""
        return sorted(self._observations.keys())

    # ── internals ─────────────────────────────────────────────

    def _summarize_single(self, tool_name: str) -> dict[str, Any]:
        """Aggregate stats for a single tool."""
        observations = self._observations.get(tool_name, [])

        if not observations:
            return {
                "avg_time_ms": 0.0,
                "success_rate": 0.0,
                "total_executions": 0,
                "avg_attempts": 0.0,
                "stub_ratio": 0.0,
            }

        times = [o.execution_time_ms for o in observations]
        successes = [o.success for o in observations]
        attempts = [o.attempt_count for o in observations]
        stubs = [o.is_stub for o in observations]

        return {
            "avg_time_ms": round(statistics.mean(times), 2),
            "success_rate": round(
                sum(1 for s in successes if s) / len(successes), 4
            ),
            "total_executions": len(observations),
            "avg_attempts": round(statistics.mean(attempts), 2),
            "stub_ratio": round(
                sum(1 for s in stubs if s) / len(stubs), 4
            ),
        }

    def __repr__(self) -> str:
        total = sum(len(v) for v in self._observations.values())
        return (
            f"ToolMetricsCollector("
            f"tools={len(self._observations)}, "
            f"observations={total})"
        )
