"""AXON APX - Observability, Audit, and Compliance (Phase 5)."""

from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
import json
import time
from typing import Any, Generator


class APXEventType(str, Enum):
    """Canonical APX audit event types."""

    REGISTRY_REGISTER = "registry_register"
    REGISTRY_RESOLVE = "registry_resolve"
    RUNTIME_RESOLVE = "runtime_resolve"
    PCC_VERIFICATION = "pcc_verification"
    MEC_VALIDATION = "mec_validation"
    QUARANTINE_ACTION = "quarantine_action"
    CONTRACT_VIOLATION = "contract_violation"
    FFI_DEGRADATION = "ffi_degradation"
    BLAME_FAULT = "blame_fault"


class APXComplianceError(Exception):
    """Raised when APX compliance gates are not satisfied."""


@dataclass(frozen=True)
class APXCompliancePolicy:
    """Compliance thresholds for operational gating."""

    require_full_pcc_success: bool = True
    max_mec_failures: int = 0
    max_blame_faults: int = 0
    max_contract_violations: int = 0
    max_quarantine_actions: int | None = None


@dataclass(frozen=True)
class APXAuditEvent:
    """Single immutable APX audit record."""

    event_type: APXEventType
    timestamp: float
    component: str
    operation: str
    status: str
    package_key: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "component": self.component,
            "operation": self.operation,
            "status": self.status,
        }
        if self.package_key:
            result["package_key"] = self.package_key
        if self.details:
            result["details"] = self.details
        return result


@dataclass
class APXOperationMetric:
    """Metric aggregate for one operation."""

    count: int = 0
    errors: int = 0
    total_duration_ms: float = 0.0
    max_duration_ms: float = 0.0

    def record(self, duration_ms: float, error: bool = False) -> None:
        self.count += 1
        if error:
            self.errors += 1
        self.total_duration_ms += duration_ms
        if duration_ms > self.max_duration_ms:
            self.max_duration_ms = duration_ms

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / self.count if self.count else 0.0


class APXObservability:
    """Collects APX audit trail, metrics, and compliance snapshots."""

    def __init__(self, component: str = "apx") -> None:
        self.component = component
        self._events: list[APXAuditEvent] = []
        self._metrics: dict[str, APXOperationMetric] = defaultdict(APXOperationMetric)
        self._decisions: Counter[str] = Counter()
        self._start_time = time.monotonic()

    @property
    def events(self) -> list[APXAuditEvent]:
        return list(self._events)

    def recent_events(
        self,
        limit: int = 50,
        event_type: APXEventType | None = None,
    ) -> list[APXAuditEvent]:
        """Return latest events, optionally filtered by type."""
        if limit < 1:
            return []

        if event_type is None:
            return self._events[-limit:]

        filtered = [event for event in self._events if event.event_type == event_type]
        return filtered[-limit:]

    def emit(
        self,
        event_type: APXEventType,
        operation: str,
        status: str,
        package_key: str = "",
        **details: Any,
    ) -> APXAuditEvent:
        event = APXAuditEvent(
            event_type=event_type,
            timestamp=time.time(),
            component=self.component,
            operation=operation,
            status=status,
            package_key=package_key,
            details=details,
        )
        self._events.append(event)
        if "decision" in details:
            self._decisions[str(details["decision"]).lower()] += 1
        return event

    @contextmanager
    def track(self, operation: str) -> Generator[None, None, None]:
        start = time.perf_counter()
        error = False
        try:
            yield
        except Exception:
            error = True
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            self._metrics[operation].record(duration_ms, error=error)

    def snapshot(self) -> dict[str, Any]:
        uptime = time.monotonic() - self._start_time
        metrics: dict[str, Any] = {}
        for op, metric in self._metrics.items():
            metrics[op] = {
                "count": metric.count,
                "errors": metric.errors,
                "avg_ms": round(metric.avg_duration_ms, 2),
                "max_ms": round(metric.max_duration_ms, 2),
            }

        return {
            "component": self.component,
            "uptime_seconds": round(uptime, 1),
            "event_count": len(self._events),
            "decision_distribution": dict(self._decisions),
            "metrics": metrics,
        }

    def compliance_report(self) -> dict[str, Any]:
        counters: Counter[str] = Counter(e.event_type.value for e in self._events)
        pcc_checks = counters[APXEventType.PCC_VERIFICATION.value]
        pcc_ok = sum(
            1
            for e in self._events
            if e.event_type == APXEventType.PCC_VERIFICATION and e.status == "ok"
        )
        pcc_rate = (pcc_ok / pcc_checks) if pcc_checks else 1.0

        report = {
            "component": self.component,
            "total_events": len(self._events),
            "pcc_checks": pcc_checks,
            "pcc_success_rate": round(pcc_rate, 4),
            "mec_failures": counters[APXEventType.MEC_VALIDATION.value],
            "ffi_degradations": counters[APXEventType.FFI_DEGRADATION.value],
            "blame_faults": counters[APXEventType.BLAME_FAULT.value],
            "quarantine_actions": counters[APXEventType.QUARANTINE_ACTION.value],
            "contract_violations": counters[APXEventType.CONTRACT_VIOLATION.value],
            "decision_distribution": dict(self._decisions),
        }

        report["compliant"] = (
            report["pcc_success_rate"] >= 1.0
            and report["mec_failures"] == 0
            and report["blame_faults"] == 0
        )
        return report

    def evaluate_compliance(self, policy: APXCompliancePolicy | None = None) -> dict[str, Any]:
        """Evaluate a compliance report against configurable gates."""
        active_policy = policy or APXCompliancePolicy()
        report = self.compliance_report()

        violations: list[str] = []
        if active_policy.require_full_pcc_success and report["pcc_success_rate"] < 1.0:
            violations.append("pcc_success_rate_below_1.0")
        if report["mec_failures"] > active_policy.max_mec_failures:
            violations.append("mec_failures_exceeded")
        if report["blame_faults"] > active_policy.max_blame_faults:
            violations.append("blame_faults_exceeded")
        if report["contract_violations"] > active_policy.max_contract_violations:
            violations.append("contract_violations_exceeded")
        if (
            active_policy.max_quarantine_actions is not None
            and report["quarantine_actions"] > active_policy.max_quarantine_actions
        ):
            violations.append("quarantine_actions_exceeded")

        return {
            "policy": {
                "require_full_pcc_success": active_policy.require_full_pcc_success,
                "max_mec_failures": active_policy.max_mec_failures,
                "max_blame_faults": active_policy.max_blame_faults,
                "max_contract_violations": active_policy.max_contract_violations,
                "max_quarantine_actions": active_policy.max_quarantine_actions,
            },
            "report": report,
            "gate_passed": len(violations) == 0,
            "violations": violations,
        }

    def assert_compliance(self, policy: APXCompliancePolicy | None = None) -> None:
        """Raise a structured error when compliance gates fail."""
        evaluated = self.evaluate_compliance(policy)
        if evaluated["gate_passed"]:
            return

        raise APXComplianceError(
            "APX compliance gate failed: " + ", ".join(evaluated["violations"])
        )

    def export_events(self, format: str = "json") -> str:
        """Export events for audit persistence.

        Supported formats:
        - json: JSON array
        - jsonl: one JSON event per line
        """
        normalized = format.lower().strip()
        payload = [event.to_dict() for event in self._events]

        if normalized == "json":
            return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
        if normalized == "jsonl":
            return "\n".join(
                json.dumps(event, ensure_ascii=True, separators=(",", ":"))
                for event in payload
            )

        raise ValueError("unsupported export format; use json or jsonl")
