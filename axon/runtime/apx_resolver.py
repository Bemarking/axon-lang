"""
AXON Runtime - APX Resolver (Phase 3)

Runtime resolver for APX epistemic dependencies.

Implements:
- MEC/PCC verification for imported dependency packages
- Policy-driven resolution (warn, quarantine, block)
- Mandatory FFI degradation to believe+tainted
- Indy blame semantics at APX boundary (caller/server)
- Violation strategies: raise, retry(n), fallback, warn
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from axon.engine.apx import EpistemicGraph, EpistemicLevel, EpistemicPageRank
from axon.engine.apx.observability import APXCompliancePolicy, APXEventType, APXObservability
from axon.runtime.runtime_errors import AxonRuntimeError, ErrorContext
from axon.runtime.tools.blame import BlameFault, BlameLabel


class APXResolutionError(AxonRuntimeError):
    """Raised when APX dependency resolution fails hard."""

    level: int = 9


class APXDecision(str, Enum):
    """Resolver decision states."""

    RESOLVED = "resolved"
    WARNED = "warned"
    QUARANTINED = "quarantined"
    BLOCKED = "blocked"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class APXPolicy:
    """Runtime APX policy derived from import metadata."""

    min_epr: float = 0.0
    on_low_rank: str = "warn"  # warn | quarantine | block
    trust_floor: str = "uncertainty"
    ffi_mode: str = "taint"  # taint | sanitize | strict
    require_pcc: bool = False
    retry_attempts: int = 0

    @staticmethod
    def from_dict(data: dict[str, Any] | None) -> APXPolicy:
        if not data:
            return APXPolicy()

        return APXPolicy(
            min_epr=float(data.get("min_epr", 0.0)),
            on_low_rank=str(data.get("on_low_rank", "warn")),
            trust_floor=str(data.get("trust_floor", "uncertainty")),
            ffi_mode=str(data.get("ffi_mode", "taint")),
            require_pcc=bool(data.get("require_pcc", False)),
            retry_attempts=int(data.get("retry_attempts", 0)),
        )


@dataclass(frozen=True)
class APXTaintedValue:
    """Mandatory degraded value after crossing APX FFI boundary."""

    value: Any
    epistemic_mode: str = "believe"
    tainted: bool = True
    source: str = "apx_ffi"

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "epistemic_mode": self.epistemic_mode,
            "tainted": self.tainted,
            "source": self.source,
        }


@dataclass
class APXResolutionResult:
    """Final result of APX resolution."""

    package_id: str
    decision: APXDecision
    score: float
    level: EpistemicLevel
    warnings: list[str] = field(default_factory=list)
    faults: list[BlameFault] = field(default_factory=list)
    degraded_payload: APXTaintedValue | None = None


@dataclass(frozen=True)
class APXContract:
    """Contract tuple C = (name, P, Q, I, sigma)."""

    name: str
    precondition: Callable[[dict[str, Any]], bool] | None = None
    postcondition: Callable[[Any], bool] | None = None
    invariant: Callable[[dict[str, Any], Any], bool] | None = None
    on_violation: str = "raise"  # raise | retry | fallback | warn
    fallback_value: Any = None


class APXBlameMonitor:
    """Indy blame monitor at APX boundaries."""

    def __init__(self) -> None:
        self._faults: list[BlameFault] = []

    @property
    def faults(self) -> list[BlameFault]:
        return list(self._faults)

    def check_precondition(
        self,
        package_id: str,
        args: dict[str, Any],
        predicate: Callable[[dict[str, Any]], bool] | None,
    ) -> BlameFault | None:
        if predicate is None:
            return None
        if predicate(args):
            return None

        fault = BlameFault(
            label=BlameLabel.CALLER,
            boundary="precondition",
            tool_name=package_id,
            expected_type="precondition(args)=True",
            actual_type="precondition(args)=False",
            actual_value=args,
            message=f"APX precondition violated for '{package_id}'",
        )
        self._faults.append(fault)
        return fault

    def check_postcondition(
        self,
        package_id: str,
        result: Any,
        predicate: Callable[[Any], bool] | None,
    ) -> BlameFault | None:
        if predicate is None:
            return None
        if predicate(result):
            return None

        fault = BlameFault(
            label=BlameLabel.SERVER,
            boundary="postcondition",
            tool_name=package_id,
            expected_type="postcondition(result)=True",
            actual_type="postcondition(result)=False",
            actual_value=result,
            message=f"APX postcondition violated for '{package_id}'",
        )
        self._faults.append(fault)
        return fault


class APXResolver:
    """Policy-driven APX dependency resolver."""

    _TRUST_MAP = {
        "uncertainty": EpistemicLevel.UNCERTAINTY,
        "speculation": EpistemicLevel.SPECULATION,
        "opinion": EpistemicLevel.OPINION,
        "factual_claim": EpistemicLevel.FACTUAL_CLAIM,
        "cited_fact": EpistemicLevel.CITED_FACT,
        "corroborated_fact": EpistemicLevel.CORROBORATED_FACT,
    }

    def __init__(
        self,
        ranking: EpistemicPageRank | None = None,
        observability: APXObservability | None = None,
    ) -> None:
        self._ranking = ranking or EpistemicPageRank()
        self._monitor = APXBlameMonitor()
        self.observability = observability or APXObservability(component="apx.runtime")

    @property
    def faults(self) -> list[BlameFault]:
        return self._monitor.faults

    def compliance_report(self) -> dict[str, Any]:
        """Return current runtime compliance report."""
        return self.observability.compliance_report()

    def assert_compliance(self, policy: APXCompliancePolicy | None = None) -> None:
        """Raise if runtime compliance gates are violated."""
        self.observability.assert_compliance(policy)

    def resolve(
        self,
        graph: EpistemicGraph,
        package_id: str,
        policy: APXPolicy,
        provided_pcc_hash: str | None = None,
        ffi_payload: Any = None,
    ) -> APXResolutionResult:
        """Resolve one package under APX runtime policy."""
        with self.observability.track("resolve"):
            violations = graph.validate_all()
            if violations:
                self.observability.emit(
                    APXEventType.MEC_VALIDATION,
                    operation="resolve",
                    status="failed",
                    package_key=package_id,
                    violations="; ".join(violations),
                )
                raise APXResolutionError(
                    "APX graph invariants violated",
                    context=ErrorContext(details="; ".join(violations)),
                )

            node = graph.get_node(package_id)
            if node is None:
                raise APXResolutionError(
                    f"APX package '{package_id}' not found",
                    context=ErrorContext(details="unknown package id"),
                )

            # MEC/PCC checks
            if not node.contract.is_valid():
                self.observability.emit(
                    APXEventType.MEC_VALIDATION,
                    operation="resolve",
                    status="failed",
                    package_key=package_id,
                )
                return self._decision_from_violation(
                    package_id=package_id,
                    level=node.level,
                    score=0.0,
                    policy=policy,
                    message="MEC validation failed",
                )

            if policy.require_pcc:
                pcc_ok = provided_pcc_hash == node.contract.certificate_hash
                self.observability.emit(
                    APXEventType.PCC_VERIFICATION,
                    operation="resolve",
                    status="ok" if pcc_ok else "failed",
                    package_key=package_id,
                )
                if not pcc_ok:
                    return self._decision_from_violation(
                        package_id=package_id,
                        level=node.level,
                        score=0.0,
                        policy=policy,
                        message="PCC verification failed",
                    )

            # Trust floor check
            floor = self._TRUST_MAP.get(policy.trust_floor.lower(), EpistemicLevel.UNCERTAINTY)
            if node.level < floor:
                return self._decision_from_violation(
                    package_id=package_id,
                    level=node.level,
                    score=0.0,
                    policy=policy,
                    message=f"trust floor violation: required {floor.name}",
                )

            # EPR policy check
            scores = self._ranking.compute(graph)
            score = scores.get(package_id, 0.0)
            if score < policy.min_epr:
                return self._decision_from_violation(
                    package_id=package_id,
                    level=node.level,
                    score=score,
                    policy=policy,
                    message=(
                        f"low EPR score {score:.4f} < min_epr {policy.min_epr:.4f}"
                    ),
                )

            degraded = self._cross_ffi(ffi_payload, mode=policy.ffi_mode)
            result = APXResolutionResult(
                package_id=package_id,
                decision=APXDecision.RESOLVED,
                score=score,
                level=node.level,
                warnings=[],
                faults=self._monitor.faults,
                degraded_payload=degraded,
            )
            self.observability.emit(
                APXEventType.RUNTIME_RESOLVE,
                operation="resolve",
                status="ok",
                package_key=package_id,
                decision=result.decision.value,
                score=round(score, 6),
            )
            return result

    def execute_with_contract(
        self,
        package_id: str,
        args: dict[str, Any],
        call: Callable[[dict[str, Any]], Any],
        contract: APXContract,
        retries: int = 0,
    ) -> Any:
        """Execute call with denotational contract semantics and strategy handling."""

        def _once() -> tuple[Any, str | None]:
            pre_fault = self._monitor.check_precondition(package_id, args, contract.precondition)
            if pre_fault is not None:
                self.observability.emit(
                    APXEventType.BLAME_FAULT,
                    operation="execute_with_contract",
                    status="failed",
                    package_key=package_id,
                    blame=pre_fault.label.value,
                    boundary=pre_fault.boundary,
                )
                return None, pre_fault.message

            result = call(args)

            post_fault = self._monitor.check_postcondition(package_id, result, contract.postcondition)
            if post_fault is not None:
                self.observability.emit(
                    APXEventType.BLAME_FAULT,
                    operation="execute_with_contract",
                    status="failed",
                    package_key=package_id,
                    blame=post_fault.label.value,
                    boundary=post_fault.boundary,
                )
                return None, post_fault.message

            if contract.invariant is not None and not contract.invariant(args, result):
                self.observability.emit(
                    APXEventType.CONTRACT_VIOLATION,
                    operation="execute_with_contract",
                    status="failed",
                    package_key=package_id,
                    reason="invariant",
                )
                return None, f"APX invariant violated for '{package_id}'"

            return result, None

        attempts = max(0, retries)
        result, err = _once()
        if err is None:
            return result

        return self._resolve_contract_failure(
            package_id=package_id,
            contract=contract,
            attempts=attempts,
            once=_once,
            initial_error=err,
        )

    def _resolve_contract_failure(
        self,
        package_id: str,
        contract: APXContract,
        attempts: int,
        once: Callable[[], tuple[Any, str | None]],
        initial_error: str | None,
    ) -> Any:
        strategy = contract.on_violation.lower()
        if strategy == "retry":
            last_error = initial_error
            for _ in range(attempts):
                result, err = once()
                if err is None:
                    return result
                last_error = err
            self.observability.emit(
                APXEventType.CONTRACT_VIOLATION,
                operation="execute_with_contract",
                status="failed",
                package_key=package_id,
                strategy="retry",
            )
            raise APXResolutionError(
                "APX contract retry exhausted",
                context=ErrorContext(details=last_error or "unknown contract failure"),
            )

        if strategy == "fallback":
            self.observability.emit(
                APXEventType.CONTRACT_VIOLATION,
                operation="execute_with_contract",
                status="warn",
                package_key=package_id,
                strategy="fallback",
            )
            return contract.fallback_value

        if strategy == "warn":
            self.observability.emit(
                APXEventType.CONTRACT_VIOLATION,
                operation="execute_with_contract",
                status="warn",
                package_key=package_id,
                strategy="warn",
            )
            return {"warning": initial_error, "fallback": contract.fallback_value}

        # default: raise
        self.observability.emit(
            APXEventType.CONTRACT_VIOLATION,
            operation="execute_with_contract",
            status="failed",
            package_key=package_id,
            strategy="raise",
        )
        raise APXResolutionError(
            "APX contract violation",
            context=ErrorContext(details=initial_error or "unknown contract failure"),
        )

    def _decision_from_violation(
        self,
        package_id: str,
        level: EpistemicLevel,
        score: float,
        policy: APXPolicy,
        message: str,
    ) -> APXResolutionResult:
        action = policy.on_low_rank.lower()

        if action == "warn":
            result = APXResolutionResult(
                package_id=package_id,
                decision=APXDecision.WARNED,
                score=score,
                level=level,
                warnings=[message],
                faults=self._monitor.faults,
            )
            self.observability.emit(
                APXEventType.RUNTIME_RESOLVE,
                operation="resolve",
                status="warn",
                package_key=package_id,
                decision=result.decision.value,
                score=round(score, 6),
                reason=message,
            )
            return result

        if action == "quarantine":
            result = APXResolutionResult(
                package_id=package_id,
                decision=APXDecision.QUARANTINED,
                score=score,
                level=level,
                warnings=[message],
                faults=self._monitor.faults,
            )
            self.observability.emit(
                APXEventType.QUARANTINE_ACTION,
                operation="resolve",
                status="ok",
                package_key=package_id,
                decision=result.decision.value,
                reason=message,
            )
            return result

        if action == "block":
            raise APXResolutionError(
                "APX dependency blocked by policy",
                context=ErrorContext(details=message),
            )

        raise APXResolutionError(
            "Unknown APX policy action",
            context=ErrorContext(details=f"on_low_rank={policy.on_low_rank}"),
        )

    def _cross_ffi(self, payload: Any, mode: str = "taint") -> APXTaintedValue:
        """Mandatory degradation: τ_externo -> τ_axon<believe+tainted>."""
        normalized_mode = mode.lower()
        if normalized_mode not in {"taint", "sanitize", "strict"}:
            normalized_mode = "taint"

        if normalized_mode == "sanitize" and isinstance(payload, dict):
            scrubbed = {
                key: value
                for key, value in payload.items()
                if not str(key).lower().endswith(("token", "secret", "password"))
            }
            self.observability.emit(
                APXEventType.FFI_DEGRADATION,
                operation="cross_ffi",
                status="ok",
                mode=normalized_mode,
            )
            return APXTaintedValue(value=scrubbed)

        if normalized_mode == "strict" and payload is None:
            self.observability.emit(
                APXEventType.FFI_DEGRADATION,
                operation="cross_ffi",
                status="ok",
                mode=normalized_mode,
            )
            return APXTaintedValue(value={"strict": "empty-payload"})

        self.observability.emit(
            APXEventType.FFI_DEGRADATION,
            operation="cross_ffi",
            status="ok",
            mode=normalized_mode,
        )
        return APXTaintedValue(value=payload)
