"""
AXON Runtime — Error Hierarchy
================================
All runtime errors for AXON program execution.

Eight severity levels, from least to most critical:

    Level 1: ValidationError           — output type does not match declaration
    Level 2: ConfidenceError           — confidence score below configured floor
    Level 3: AnchorBreachError         — hard constraint anchor violated
    Level 4: RefineExhaustedError      — max refine/retry attempts exhausted
    Level 5: ModelCallError            — LLM API call failed
    Level 6: ExecutionTimeoutError     — execution exceeded time limit
    Level 7: AgentBudgetExhaustedError — agent resource budget exhausted
    Level 8: AgentStuckError           — agent stuck, no progress possible

Every runtime error carries structured context through ``ErrorContext``
for precise diagnostics and tracer integration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════════════
#  ERROR CONTEXT — structured diagnostic payload
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ErrorContext:
    """Structured context attached to every runtime error.

    Provides enough information for the Tracer to produce a
    meaningful diagnostic entry without requiring the caller
    to format error messages manually.
    """

    step_name: str = ""
    flow_name: str = ""
    attempt: int = 0
    expected_type: str = ""
    actual_value: Any = None
    anchor_name: str = ""
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        result: dict[str, Any] = {}
        if self.step_name:
            result["step_name"] = self.step_name
        if self.flow_name:
            result["flow_name"] = self.flow_name
        if self.attempt:
            result["attempt"] = self.attempt
        if self.expected_type:
            result["expected_type"] = self.expected_type
        if self.actual_value is not None:
            result["actual_value"] = repr(self.actual_value)
        if self.anchor_name:
            result["anchor_name"] = self.anchor_name
        if self.details:
            result["details"] = self.details
        return result


# ═══════════════════════════════════════════════════════════════════
#  BASE RUNTIME ERROR
# ═══════════════════════════════════════════════════════════════════


class AxonRuntimeError(Exception):
    """Base class for all AXON runtime errors.

    Attributes:
        message:  Human-readable description of the failure.
        context:  Structured diagnostic payload.
        level:    Severity level (1–6).
    """

    level: int = 5

    def __init__(
        self,
        message: str,
        context: ErrorContext | None = None,
    ) -> None:
        self.message = message
        self.context = context or ErrorContext()
        super().__init__(self._format())

    def _format(self) -> str:
        parts = [f"[L{self.level}] {self.__class__.__name__}: {self.message}"]
        if self.context.step_name:
            parts.append(f"  step: {self.context.step_name}")
        if self.context.flow_name:
            parts.append(f"  flow: {self.context.flow_name}")
        if self.context.attempt:
            parts.append(f"  attempt: {self.context.attempt}")
        if self.context.details:
            parts.append(f"  details: {self.context.details}")
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "error_type": self.__class__.__name__,
            "level": self.level,
            "message": self.message,
            "context": self.context.to_dict(),
        }


# ═══════════════════════════════════════════════════════════════════
#  LEVEL 1 — VALIDATION ERROR
# ═══════════════════════════════════════════════════════════════════


class ValidationError(AxonRuntimeError):
    """Output type does not match the declared semantic type.

    Raised by the SemanticValidator when a step's output
    fails type checking against its declaration.

    Example:
        Step declares ``-> FactualClaim`` but the model
        produced content classified as ``Opinion``.
    """

    level: int = 1


# ═══════════════════════════════════════════════════════════════════
#  LEVEL 2 — CONFIDENCE ERROR
# ═══════════════════════════════════════════════════════════════════


class ConfidenceError(AxonRuntimeError):
    """Confidence score fell below the configured floor.

    Raised when a step or persona declares a ``confidence_floor``
    and the model's output does not meet it.

    Example:
        Persona requires ``confidence >= 0.85`` but the model
        self-reported confidence of 0.62.
    """

    level: int = 2


# ═══════════════════════════════════════════════════════════════════
#  LEVEL 3 — ANCHOR BREACH ERROR
# ═══════════════════════════════════════════════════════════════════


class AnchorBreachError(AxonRuntimeError):
    """A hard constraint (anchor) was violated.

    Anchors are inviolable rules. When the runtime detects
    a breach — whether through keyword rejection, factuality
    checks, or explicit violation patterns — this error fires.

    Example:
        Anchor ``NoHallucination`` requires ``factual_only``
        but the output contains speculative claims.
    """

    level: int = 3


# ═══════════════════════════════════════════════════════════════════
#  LEVEL 4 — REFINE EXHAUSTED ERROR
# ═══════════════════════════════════════════════════════════════════


class RefineExhaustedError(AxonRuntimeError):
    """All refine/retry attempts have been exhausted.

    Raised by the RetryEngine when a step fails validation
    repeatedly and the configured ``max_attempts`` ceiling
    has been reached without a successful result.

    Example:
        ``refine { max_attempts: 3 }`` — three attempts
        failed validation, no more retries available.
    """

    level: int = 4


# ═══════════════════════════════════════════════════════════════════
#  LEVEL 5 — MODEL CALL ERROR
# ═══════════════════════════════════════════════════════════════════


class ModelCallError(AxonRuntimeError):
    """The LLM API call itself failed.

    Covers network errors, rate limits, malformed responses,
    and any other failure at the model communication layer.

    Example:
        Anthropic API returned HTTP 429 (rate limited)
        during step ``analyze_contract``.
    """

    level: int = 5


# ═══════════════════════════════════════════════════════════════════
#  LEVEL 6 — EXECUTION TIMEOUT ERROR
# ═══════════════════════════════════════════════════════════════════


class ExecutionTimeoutError(AxonRuntimeError):
    """Execution exceeded the configured time limit.

    Raised when a step, flow, or entire program execution
    surpasses its ``max_time`` configuration.

    Example:
        Flow ``deep_analysis`` configured with 30s timeout
        but the model took 45s to respond.
    """

    level: int = 6


# ═══════════════════════════════════════════════════════════════════
#  LEVEL 7 — AGENT BUDGET EXHAUSTED ERROR
# ═══════════════════════════════════════════════════════════════════


class AgentBudgetExhaustedError(AxonRuntimeError):
    """Agent's BDI loop exhausted its resource budget.

    Raised when a running agent (IRAgent) exceeds one of its
    linear-logic resource constraints:
      - max_iterations reached without goal satisfaction
      - max_tokens consumed across all model calls
      - max_time wall-clock duration exceeded
      - max_cost accumulated API cost exceeded

    The agent returns a partial result when this fires,
    unless on_stuck='escalate' overrides to a hard error.

    Example:
        Agent ``Researcher`` configured with ``max_iterations: 10``
        completed 10 BDI cycles without reaching 'believe' state.
    """

    level: int = 7


# ═══════════════════════════════════════════════════════════════════
#  LEVEL 8 — AGENT STUCK ERROR
# ═══════════════════════════════════════════════════════════════════


class AgentStuckError(AxonRuntimeError):
    """Agent detected it is stuck and cannot make progress.

    Raised when an agent's deliberation cycle determines that
    no available action can advance toward the goal (¬◇φ in
    STIT logic). This triggers the on_stuck recovery policy:
      - forge     → creative synthesis to break the impasse
      - hibernate → suspend and return partial result
      - escalate  → raise this error to the caller
      - retry     → reset context and retry with modified params

    Example:
        Agent ``Analyzer`` returned the same epistemic state
        for 3 consecutive iterations, triggering 'escalate'.
    """

    level: int = 8

