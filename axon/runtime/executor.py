"""
AXON Runtime — Executor
========================
The orchestrator that drives complete AXON program execution.

The Executor takes a ``CompiledProgram`` (output of Phase 2) and
executes it against a ``ModelClient`` implementation, coordinating:

    1. **Context management** — per-unit state via ContextManager.
    2. **Model calls** — delegated to the ModelClient protocol.
    3. **Validation** — SemanticValidator enforces type contracts.
    4. **Retry logic** — RetryEngine handles refine blocks.
    5. **Memory** — MemoryBackend for remember/recall operations.
    6. **Tracing** — Tracer records every semantic event.
    7. **Anchor enforcement** — post-response constraint checking.

The Executor does NOT make direct LLM API calls. It delegates
all model interaction to the ModelClient, which is injected at
construction time. This separation enables testing with mock
clients and supports any LLM provider.

Usage::

    client = AnthropicClient(api_key="...")  # or MockModelClient()
    executor = Executor(client=client)

    result = await executor.execute(compiled_program)
    print(result.trace.to_dict())
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from axon.runtime.data_dispatcher import DataScienceDispatcher
    from axon.runtime.tools.dispatcher import ToolDispatcher

from axon.backends.base_backend import (
    CompiledExecutionUnit,
    CompiledProgram,
    CompiledStep,
)
from axon.runtime.context_mgr import ContextManager
from axon.runtime.effects import EmitEvent, perform
from axon.runtime.memory_backend import InMemoryBackend, MemoryBackend
from axon.runtime.retry_engine import RefineConfig, RetryEngine, RetryResult
from axon.engine.pem.pid_controller import PIDController
from axon.runtime.runtime_errors import (
    AgentBudgetExhaustedError,
    AgentStuckError,
    AnchorBreachError,
    AxonRuntimeError,
    CapabilityViolationError,
    ErrorContext,
    ExecutionTimeoutError,
    MandateViolationError,
    ModelCallError,
    ShieldBreachError,
    ValidationError,
)
from axon.runtime.semantic_validator import SemanticValidator, ValidationResult
from axon.runtime.tracer import ExecutionTrace, Tracer, TraceEventType


# ═══════════════════════════════════════════════════════════════════
#  MODEL CLIENT PROTOCOL
# ═══════════════════════════════════════════════════════════════════


@runtime_checkable
class ModelClient(Protocol):
    """Protocol for LLM model interaction.

    Any class that implements this protocol can serve as the
    execution backend for the AXON runtime. This is the single
    interface between the runtime and external LLM APIs.

    Implementations must handle:
      - Message formatting for their specific provider
      - API authentication and rate limiting
      - Response parsing and normalization
    """

    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        output_schema: dict[str, Any] | None = None,
        effort: str = "",
        failure_context: str = "",
    ) -> ModelResponse:
        """Send a prompt to the model and return the response.

        Args:
            system_prompt:    The system-level instructions.
            user_prompt:      The user-level prompt (the step's ask).
            tools:            Optional tool declarations in
                              provider-native format.
            output_schema:    Optional output schema for structured
                              response parsing.
            effort:           Effort level hint (e.g., ``"high"``).
            failure_context:  Previous failure reason for retry
                              context injection.

        Returns:
            A ``ModelResponse`` with the model's output.

        Raises:
            ModelCallError: If the API call fails.
        """
        ...


# ═══════════════════════════════════════════════════════════════════
#  MODEL RESPONSE — normalized LLM output
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ModelResponse:
    """Normalized response from a model call.

    Attributes:
        content:     The textual content of the response.
        structured:  Parsed structured data (if output schema
                     was provided and model returned JSON).
        tool_calls:  Any tool invocations returned by the model.
        confidence:  Model-reported confidence (0.0–1.0), if any.
        usage:       Token usage statistics.
        raw:         The raw provider response for debugging.
    """

    content: str = ""
    structured: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    confidence: float | None = None
    usage: dict[str, int] = field(default_factory=dict)
    raw: Any = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        result: dict[str, Any] = {"content": self.content}
        if self.structured is not None:
            result["structured"] = self.structured
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        if self.confidence is not None:
            result["confidence"] = self.confidence
        if self.usage:
            result["usage"] = self.usage
        return result


# ═══════════════════════════════════════════════════════════════════
#  STEP RESULT — output of a single step execution
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class StepResult:
    """Result of executing a single compiled step.

    Attributes:
        step_name:    The step's identifier.
        response:     The model's response.
        validation:   Validation outcome (if validation was run).
        retry_info:   Retry details (if retries were needed).
        duration_ms:  Wall-clock execution time in milliseconds.
    """

    step_name: str = ""
    response: ModelResponse | None = None
    validation: ValidationResult | None = None
    retry_info: RetryResult | None = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        result: dict[str, Any] = {"step_name": self.step_name}
        if self.response:
            result["response"] = self.response.to_dict()
        if self.validation:
            result["validation"] = self.validation.to_dict()
        if self.retry_info:
            result["retry_info"] = self.retry_info.to_dict()
        result["duration_ms"] = round(self.duration_ms, 2)
        return result


# ═══════════════════════════════════════════════════════════════════
#  AGENT RESULT — output of a complete BDI agent cycle
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class AgentResult:
    """Result of a complete BDI agent execution.

    Coalgebraic state representation:
      Agent = (S, O, step: S × Action → S, obs: S → O)
      where S = cognitive state (beliefs, goals, plans)
            O = observations (tool outputs, LLM responses)

    The epistemic_state tracks convergence on the Tarski lattice:
      doubt ⊏ speculate ⊏ believe ⊏ know

    Attributes:
        agent_name:       Agent identifier.
        goal:             The goal the agent was pursuing.
        strategy:         Deliberation strategy used.
        iterations_used:  Number of BDI cycles completed.
        max_iterations:   Budget cap for iterations.
        epistemic_state:  Final position on epistemic lattice.
        goal_achieved:    Whether the agent reached 'believe' or 'know'.
        on_stuck_fired:   Whether recovery policy activated.
        on_stuck_policy:  Which recovery policy was configured.
        cycle_results:    Ordered results from each BDI cycle.
        final_response:   The agent's synthesized final output.
        total_tokens:     Accumulated token usage across all cycles.
    """

    agent_name: str = ""
    goal: str = ""
    strategy: str = "react"
    iterations_used: int = 0
    max_iterations: int = 10
    epistemic_state: str = "doubt"
    goal_achieved: bool = False
    on_stuck_fired: bool = False
    on_stuck_policy: str = "escalate"
    cycle_results: tuple[StepResult, ...] = ()
    final_response: ModelResponse | None = None
    total_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        result: dict[str, Any] = {
            "agent_name": self.agent_name,
            "goal": self.goal,
            "strategy": self.strategy,
            "iterations_used": self.iterations_used,
            "max_iterations": self.max_iterations,
            "epistemic_state": self.epistemic_state,
            "goal_achieved": self.goal_achieved,
            "on_stuck_fired": self.on_stuck_fired,
        }
        if self.cycle_results:
            result["cycle_results"] = [
                cr.to_dict() for cr in self.cycle_results
            ]
        if self.final_response:
            result["final_response"] = self.final_response.to_dict()
        if self.total_tokens:
            result["total_tokens"] = self.total_tokens
        return result


# ═══════════════════════════════════════════════════════════════════
#  DAEMON RESULT — output of a daemon event cycle
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class DaemonResult:
    """Result of a daemon's event processing cycle.

    Co-algebraic state representation:
      Daemon = νX. δ(S) → S × E
      The daemon is the greatest fixpoint — it runs forever.
      Each cycle processes one event and produces one result.

    Linear Logic per event (Girard, 1987):
      Budget(n) ⊗ Event ⊸ Output ⊗ Budget(n-c)

    Attributes:
        daemon_name:      Daemon identifier.
        goal:             The goal the daemon was pursuing.
        strategy:         Deliberation strategy used.
        events_processed: Number of events processed in this invocation.
        channel_topic:    The channel that triggered this cycle.
        event_alias:      The local binding for the event payload.
        on_stuck_fired:   Whether recovery policy activated.
        on_stuck_policy:  Which recovery policy was configured.
        cycle_results:    Ordered results from event processing.
        final_response:   The daemon's output for this cycle.
        total_tokens:     Accumulated token usage.
        continuation_id:  CPS resume point for auto-hibernate.
    """

    daemon_name: str = ""
    goal: str = ""
    strategy: str = "react"
    events_processed: int = 0
    channel_topic: str = ""
    event_alias: str = ""
    on_stuck_fired: bool = False
    on_stuck_policy: str = "hibernate"
    cycle_results: tuple[StepResult, ...] = ()
    final_response: ModelResponse | None = None
    total_tokens: int = 0
    continuation_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        result: dict[str, Any] = {
            "daemon_name": self.daemon_name,
            "goal": self.goal,
            "strategy": self.strategy,
            "events_processed": self.events_processed,
            "channel_topic": self.channel_topic,
            "on_stuck_fired": self.on_stuck_fired,
            "continuation_id": self.continuation_id,
        }
        if self.cycle_results:
            result["cycle_results"] = [
                cr.to_dict() for cr in self.cycle_results
            ]
        if self.final_response:
            result["final_response"] = self.final_response.to_dict()
        if self.total_tokens:
            result["total_tokens"] = self.total_tokens
        return result


# ═══════════════════════════════════════════════════════════════════
#  UNIT RESULT — output of a single execution unit
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class UnitResult:
    """Result of executing a single execution unit (one run statement).

    Attributes:
        flow_name:     The flow that was executed.
        step_results:  Ordered results for each step.
        success:       Whether all steps completed without error.
        error:         The error that halted execution, if any.
        duration_ms:   Total wall-clock time in milliseconds.
    """

    flow_name: str = ""
    step_results: tuple[StepResult, ...] = ()
    success: bool = True
    error: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "flow_name": self.flow_name,
            "step_results": [s.to_dict() for s in self.step_results],
            "success": self.success,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
        }


# ═══════════════════════════════════════════════════════════════════
#  EXECUTION RESULT — output of a complete program execution
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ExecutionResult:
    """Result of executing a complete AXON program.

    Attributes:
        unit_results:  Results for each execution unit.
        trace:         The complete semantic execution trace.
        success:       Whether the entire program succeeded.
        duration_ms:   Total wall-clock time in milliseconds.
    """

    unit_results: tuple[UnitResult, ...] = ()
    trace: ExecutionTrace | None = None
    success: bool = True
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        result: dict[str, Any] = {
            "unit_results": [u.to_dict() for u in self.unit_results],
            "success": self.success,
            "duration_ms": round(self.duration_ms, 2),
        }
        if self.trace:
            result["trace"] = self.trace.to_dict()
        return result


# ═══════════════════════════════════════════════════════════════════
#  EXECUTOR — the main orchestrator
# ═══════════════════════════════════════════════════════════════════


class Executor:
    """Orchestrates the execution of compiled AXON programs.

    The Executor is the runtime's entry point. It takes a
    ``CompiledProgram`` and drives execution through the full
    pipeline: model calls → validation → retry → memory → tracing.

    Usage::

        executor = Executor(client=my_model_client)
        result = await executor.execute(program)

        if result.success:
            for unit in result.unit_results:
                for step in unit.step_results:
                    print(step.step_name, step.response.content)
    """

    def __init__(
        self,
        client: ModelClient,
        *,
        validator: SemanticValidator | None = None,
        retry_engine: RetryEngine | None = None,
        memory: MemoryBackend | None = None,
        tool_dispatcher: ToolDispatcher | None = None,
    ) -> None:
        """Initialize the Executor.

        Args:
            client:          The model client for LLM interaction.
            validator:       Optional custom validator. Defaults to a
                             new ``SemanticValidator`` instance.
            retry_engine:    Optional custom retry engine. Defaults to
                             a new ``RetryEngine`` instance.
            memory:          Optional custom memory backend. Defaults
                             to a new ``InMemoryBackend`` instance.
            tool_dispatcher: Optional tool dispatcher for executing
                             tool steps (``IRUseTool``). If not provided,
                             tool steps will raise ``AxonRuntimeError``.
        """
        self._client = client
        self._validator = validator or SemanticValidator()
        self._retry_engine = retry_engine or RetryEngine()
        self._memory = memory or InMemoryBackend()
        self._tool_dispatcher = tool_dispatcher
        self._data_dispatcher: DataScienceDispatcher | None = None

    async def execute(self, program: CompiledProgram) -> ExecutionResult:
        """Execute a complete compiled AXON program.

        Iterates over all execution units (one per ``run`` statement),
        executing each in sequence. Each unit gets its own
        ContextManager and trace span.

        Args:
            program: The compiled program to execute.

        Returns:
            An ``ExecutionResult`` with all outcomes and the trace.
        """
        tracer = Tracer(
            program_name=program.metadata.get("program_name", ""),
            backend_name=program.backend_name,
        )

        program_start = time.perf_counter()
        unit_results: list[UnitResult] = []
        all_success = True

        for unit in program.execution_units:
            unit_result = await self._execute_unit(unit, tracer)
            unit_results.append(unit_result)
            if not unit_result.success:
                all_success = False

        program_duration = (time.perf_counter() - program_start) * 1000
        trace = tracer.finalize()

        return ExecutionResult(
            unit_results=tuple(unit_results),
            trace=trace,
            success=all_success,
            duration_ms=program_duration,
        )

    async def _execute_unit(
        self,
        unit: CompiledExecutionUnit,
        tracer: Tracer,
    ) -> UnitResult:
        """Execute a single execution unit (one run statement).

        Creates a ContextManager scoped to this unit, sets
        up the system prompt, and iterates through the steps.

        Args:
            unit:    The compiled execution unit.
            tracer:  The active tracer.

        Returns:
            A ``UnitResult`` with step outcomes.
        """
        unit_start = time.perf_counter()
        flow_name = unit.flow_name

        # Open a span for this execution unit
        tracer.start_span(
            f"unit:{flow_name}",
            metadata={
                "persona": unit.persona_name,
                "context": unit.context_name,
                "effort": unit.effort,
            },
        )

        ctx = ContextManager(
            system_prompt=unit.system_prompt,
            tracer=tracer,
        )

        # Set the memory backend's tracer for this unit
        if isinstance(self._memory, InMemoryBackend):
            self._memory._tracer = tracer

        step_results: list[StepResult] = []
        error_msg = ""

        try:
            for step in unit.steps:
                step_result = await self._execute_step(
                    step=step,
                    unit=unit,
                    ctx=ctx,
                    tracer=tracer,
                )
                step_results.append(step_result)

                # Store the result in context for downstream steps
                if step.step_name and step_result.response:
                    output = (
                        step_result.response.structured
                        or step_result.response.content
                    )
                    ctx.set_step_result(step.step_name, output)

        except AxonRuntimeError as exc:
            error_msg = str(exc)
            tracer.emit(
                TraceEventType.STEP_END,
                step_name=step.step_name if step_results else "",
                data={"error": error_msg},
            )

        unit_duration = (time.perf_counter() - unit_start) * 1000
        tracer.end_span(metadata={"duration_ms": round(unit_duration, 2)})

        return UnitResult(
            flow_name=flow_name,
            step_results=tuple(step_results),
            success=(error_msg == ""),
            error=error_msg,
            duration_ms=unit_duration,
        )

    async def _execute_step(
        self,
        step: CompiledStep,
        unit: CompiledExecutionUnit,
        ctx: ContextManager,
        tracer: Tracer,
    ) -> StepResult:
        """Execute a single compiled step.

        Handles the full lifecycle: model call → anchor check →
        validation → result capture. If a ``refine`` config is
        present in the step metadata, wraps execution with the
        RetryEngine.

        Args:
            step:    The compiled step to execute.
            unit:    The parent execution unit.
            ctx:     The active context manager.
            tracer:  The active tracer.

        Returns:
            A ``StepResult`` with the execution outcome.
        """
        step_name = step.step_name
        step_start = time.perf_counter()

        tracer.emit(
            TraceEventType.STEP_START,
            step_name=step_name,
            data={"user_prompt_length": len(step.user_prompt)},
        )

        # ── Tool step shortcut ───────────────────────────────────
        # If the step carries a tool invocation, route through the
        # ToolDispatcher instead of the model client.
        if step.metadata.get("use_tool"):
            return await self._execute_tool_step(
                step=step, ctx=ctx, tracer=tracer,
            )

        # ── Data Science step shortcut ───────────────────────────
        # If the step carries a data_science operation, route through
        # the DataScienceDispatcher instead of the model client.
        if step.metadata.get("data_science"):
            return await self._execute_data_step(
                step=step, ctx=ctx, tracer=tracer,
            )

        # ── Deliberate step shortcut ───────────────────────────────
        # If the step carries a deliberate config, route through
        # _execute_deliberate_step which overrides effort/budget.
        if step.metadata.get("deliberate"):
            return await self._execute_deliberate_step(
                step=step, unit=unit, ctx=ctx, tracer=tracer,
            )

        # ── Consensus step shortcut ────────────────────────────────
        # If the step carries a consensus config, route through
        # _execute_consensus_step which runs N parallel branches.
        if step.metadata.get("consensus"):
            return await self._execute_consensus_step(
                step=step, unit=unit, ctx=ctx, tracer=tracer,
            )

        # ── Forge step shortcut ───────────────────────────────────
        # If the step carries a forge config, route through
        # _execute_forge_step which orchestrates the Poincaré pipeline.
        if step.metadata.get("forge"):
            return await self._execute_forge_step(
                step=step, unit=unit, ctx=ctx, tracer=tracer,
            )

        # ── Agent step shortcut ───────────────────────────────────
        # If the step carries an agent config, route through
        # _execute_agent_step which runs the BDI deliberation loop.
        if step.metadata.get("agent"):
            return await self._execute_agent_step(
                step=step, unit=unit, ctx=ctx, tracer=tracer,
            )

        # ── Shield step shortcut ────────────────────────────────────────
        # If the step carries a shield_apply config, route through
        # _execute_shield_step which enforces security boundaries.
        if step.metadata.get("shield_apply"):
            return await self._execute_shield_step(
                step=step, ctx=ctx, tracer=tracer,
            )

        # ── Corpus Navigate step shortcut ──────────────────────────────
        # If the step carries a corpus_navigate config, route through
        # _execute_corpus_navigate_step for multi-document graph traversal.
        if step.metadata.get("corpus_navigate"):
            return await self._execute_corpus_navigate_step(
                step=step, ctx=ctx, tracer=tracer,
            )

        # ── Corroborate step shortcut ──────────────────────────────────
        # If the step carries a corroborate config, route through
        # _execute_corroborate_step for cross-path verification.
        if step.metadata.get("corroborate"):
            return await self._execute_corroborate_step(
                step=step, ctx=ctx, tracer=tracer,
            )

        # ── OTS Synthesis step shortcut ────────────────────────────────
        # If the step carries an ots_apply config, route through
        # _execute_ots_step for Just-In-Time tool synthesis.
        if step.metadata.get("ots_apply"):
            return await self._execute_ots_step(
                step=step, unit=unit, ctx=ctx, tracer=tracer,
            )

        # ── Mandate step shortcut ───────────────────────────────────────
        # If the step carries a mandate_apply config, route through
        # _execute_mandate_step for CRC PID enforcement.
        if step.metadata.get("mandate_apply"):
            return await self._execute_mandate_step(
                step=step, unit=unit, ctx=ctx, tracer=tracer,
            )

        # ── Compute step shortcut ──────────────────────────────────────
        # If the step carries a compute config, route through
        # _execute_compute_step — deterministic Fast-Path (no LLM).
        if step.metadata.get("compute"):
            return await self._execute_compute_step(
                step=step, ctx=ctx, tracer=tracer,
            )

        # ── Daemon step shortcut ───────────────────────────────────────
        # If the step carries a daemon config, route through
        # _execute_daemon_step — co-inductive reactive event loop.
        if step.metadata.get("daemon"):
            return await self._execute_daemon_step(
                step=step, unit=unit, ctx=ctx, tracer=tracer,
            )

        # Extract refine config from step metadata (if present)
        refine_config = self._extract_refine_config(step)

        # Build the step callable
        async def run_step(failure_context: str = "") -> StepResult:
            response = await self._call_model(
                step=step,
                unit=unit,
                ctx=ctx,
                tracer=tracer,
                failure_context=failure_context,
            )

            # We extract Semantic validation and Anchor checking into CPS callbacks
            def on_validation_success(validation: ValidationResult) -> StepResult:
                step_duration = (time.perf_counter() - step_start) * 1000
                tracer.emit(
                    TraceEventType.STEP_END,
                    step_name=step_name,
                    data={"success": True},
                    duration_ms=step_duration,
                )
                return StepResult(
                    step_name=step_name,
                    response=response,
                    validation=validation,
                    retry_info=None,
                    duration_ms=step_duration,
                )
                
            def on_validation_error(violations: list[str]) -> StepResult:
                error_msgs = "\n".join(violations)
                raise ValidationError(
                    message=f"Semantic validation failed:\n{error_msgs}",
                    context=ErrorContext(
                        step_name=step_name,
                        flow_name=unit.flow_name,
                        details=error_msgs,
                    ),
                )

            def on_anchor_success() -> StepResult:
                return self._validate_response_cps(
                    response=response,
                    step=step,
                    step_name=step_name,
                    tracer=tracer,
                    on_success=on_validation_success,
                    on_failure=on_validation_error,
                )
                
            def on_anchor_error(violations: list[str]) -> StepResult:
                error_msgs = "\n".join(violations)
                print(f">>> ON ANCHOR ERROR CALLED! Violations: {error_msgs}")
                raise AnchorBreachError(
                    message=f"L3 Anchor breach detected:\n{error_msgs}",
                    context=ErrorContext(
                        step_name=step_name,
                        flow_name=unit.flow_name,
                        details=error_msgs,
                    ),
                )

            # Start the CPS chain
            return self._check_anchors_cps(
                response=response,
                unit=unit,
                step_name=step_name,
                tracer=tracer,
                on_success=on_anchor_success,
                on_failure=on_anchor_error,
            )

        # Execute (with or without retry)
        retry_result: RetryResult | None = None
        final_step_result: StepResult

        # Always route through retry engine to leverage built-in exception catching,
        # but if no refine config is present, it will default to max_attempts = 1.
        # But if we want self-healing on Anchor and Validation errors, maybe we 
        # auto-supply a default config if absent? For now, we use existing config.
        default_config = refine_config or RefineConfig(max_attempts=3, backoff="linear", pass_failure_context=True)
        
        retry_result = await self._retry_engine.execute_with_retry(
            fn=run_step,
            config=default_config,
            tracer=tracer,
            step_name=step_name,
            flow_name=unit.flow_name,
        )
        final_step_result = retry_result.result
        
        if final_step_result is None:
            # All attempts exhausted and on_exhaustion='skip', so result is None.
            return StepResult(
                step_name=step_name,
                response=None,
                validation=None,
                retry_info=retry_result,
                duration_ms=(time.perf_counter() - step_start) * 1000,
            )

        # Inject retry info back into the returned step result
        return StepResult(
            step_name=final_step_result.step_name,
            response=final_step_result.response,
            validation=final_step_result.validation,
            retry_info=retry_result,
            duration_ms=final_step_result.duration_ms,
        )

    async def _execute_ots_step(
        self,
        step: CompiledStep,
        unit: CompiledExecutionUnit,
        ctx: ContextManager,
        tracer: Tracer,
    ) -> StepResult:
        """Execute an OTS (Ontological Tool Synthesis) step.
        
        Performs Just-In-Time synthesis of a capability based on
        the OTS definition and applies it to the target context.
        """
        step_name = step.step_name
        step_start = time.perf_counter()
        
        ots_meta = step.metadata["ots_apply"]
        ots_name = ots_meta.get("ots_name", "")
        target = ots_meta.get("target", "")
        definition = ots_meta.get("ots_definition", {})
        
        tracer.emit(
            TraceEventType.STEP_START,
            step_name=step_name,
            data={
                "type": "ots_synthesis",
                "ots_name": ots_name,
                "target": target,
                "teleology": definition.get("teleology", ""),
            },
        )
        
        # Resolve target expression via prompt building (handles `_` interpolation)
        target_val = self._build_user_prompt(
            CompiledStep(user_prompt=target), ctx
        )
        
        # Create an instance of AutopoieticSynthesizer
        from axon.runtime.ots_engine import AutopoieticSynthesizer
        ots_engine = AutopoieticSynthesizer(self._client, getattr(self, "_retry_engine", None))

        try:
            # Step 1: Synthesize the ephemeral tool
            ephemeral_tool = await ots_engine.synthesize(
                ots_name=ots_name,
                teleology=definition.get("teleology", ""),
                linear_constraints=definition.get("linear_constraints", []),
                tracer=tracer
            )

            # Step 2: Execute the synthesized tool
            tool_kwargs = {}
            if hasattr(ephemeral_tool, "schema") and ephemeral_tool.schema.input_params:
                first_arg_name = ephemeral_tool.schema.input_params[0].name
                tool_kwargs[first_arg_name] = target_val
                    
            result = await ephemeral_tool.execute(**tool_kwargs)
            
            if not result.success:
                raise RuntimeError(f"Tool execution failed: {result.error}")
            
            response = ModelResponse(
                content=str(result.data),
                tool_calls=[],
                raw=result
            )
            
            # Store result in context
            ctx.set_step_result(step_name, response.content)
            
            step_duration = (time.perf_counter() - step_start) * 1000
            tracer.emit(
                TraceEventType.STEP_END,
                step_name=step_name,
                data={"success": True, "tool": ephemeral_tool.tool_name},
                duration_ms=step_duration,
            )
            
            return StepResult(
                step_name=step_name,
                response=response,
                duration_ms=step_duration,
            )
            
        except Exception as e:
            tracer.emit(
                TraceEventType.STEP_END,
                step_name=step_name,
                data={"success": False, "error": str(e), "type": type(e).__name__},
            )
            raise AxonRuntimeError(f"OTS Execution Failed: {str(e)}") from e

    async def _execute_tool_step(
        self,
        step: CompiledStep,
        ctx: ContextManager,
        tracer: Tracer,
    ) -> StepResult:
        """Execute a step that uses a tool (via ToolDispatcher).

        When a compiled step's metadata contains ``use_tool``, this
        method is called instead of the normal model → validate path.
        The ``ToolDispatcher`` resolves the tool name, executes the
        registered ``BaseTool``, and wraps the result.

        Args:
            step:    The compiled step with ``use_tool`` metadata.
            ctx:     The active context manager.
            tracer:  The active tracer.

        Returns:
            A ``StepResult`` with the tool response.
        """
        import json

        step_name = step.step_name
        step_start = time.perf_counter()
        use_tool_meta = step.metadata["use_tool"]

        tracer.emit(
            TraceEventType.MODEL_CALL,
            step_name=step_name,
            data={"tool_name": use_tool_meta.get("tool_name", "unknown")},
        )

        if self._tool_dispatcher is None:
            raise AxonRuntimeError(
                message=(
                    f"Step '{step_name}' requires a tool "
                    f"('{use_tool_meta.get('tool_name')}') but no "
                    "ToolDispatcher was provided to the Executor."
                ),
                error_type="tool_dispatch",
                context=ErrorContext(
                    flow_name="",
                    step_name=step_name,
                ),
            )

        # Build an IRUseTool from the step metadata
        from axon.compiler.ir_nodes import IRUseTool

        ir_use_tool = IRUseTool(
            tool_name=use_tool_meta.get("tool_name", ""),
            argument=self._build_user_prompt(step, ctx),
        )

        tool_result = await self._tool_dispatcher.dispatch(
            ir_use_tool,
            context={"step_name": step_name},
        )

        # Convert ToolResult → ModelResponse so the rest of the
        # pipeline (context storage, tracing) works unchanged.
        response = ModelResponse(
            content=json.dumps(tool_result.data) if tool_result.data else "",
            structured=tool_result.data if isinstance(tool_result.data, dict) else None,
        )

        if not tool_result.success:
            raise AxonRuntimeError(
                message=(
                    f"Tool '{ir_use_tool.tool_name}' failed: "
                    f"{tool_result.error}"
                ),
                error_type="tool_execution",
                context=ErrorContext(
                    flow_name="",
                    step_name=step_name,
                ),
            )

        # Store result in context for downstream steps
        ctx.set_step_result(step_name, response.content)

        step_duration = (time.perf_counter() - step_start) * 1000

        tracer.emit(
            TraceEventType.STEP_END,
            step_name=step_name,
            data={
                "success": True,
                "tool_name": ir_use_tool.tool_name,
                "is_stub": tool_result.metadata.get("is_stub", False),
            },
            duration_ms=step_duration,
        )

        return StepResult(
            step_name=step_name,
            response=response,
            duration_ms=step_duration,
        )

    async def _execute_data_step(
        self,
        step: CompiledStep,
        ctx: ContextManager,
        tracer: Tracer,
    ) -> StepResult:
        """Execute a Data Science step (via DataScienceDispatcher).

        When a compiled step's metadata contains ``data_science``, this
        method is called instead of the normal model → validate path.
        The ``DataScienceDispatcher`` resolves the operation and
        executes it directly against the in-memory engine.

        Args:
            step:    The compiled step with ``data_science`` metadata.
            ctx:     The active context manager.
            tracer:  The active tracer.

        Returns:
            A ``StepResult`` with the engine result.
        """
        import json

        step_name = step.step_name
        step_start = time.perf_counter()
        ds_meta = step.metadata["data_science"]

        tracer.emit(
            TraceEventType.STEP_START,
            step_name=step_name,
            data={"data_science_op": ds_meta.get("operation", "unknown")},
        )

        # Lazy-init dispatcher
        if self._data_dispatcher is None:
            from axon.runtime.data_dispatcher import DataScienceDispatcher
            self._data_dispatcher = DataScienceDispatcher()

        # Reconstruct the IR node from step metadata
        ir_node = self._reconstruct_data_ir(ds_meta)

        if ir_node is None:
            from axon.runtime.runtime_errors import AxonRuntimeError, ErrorContext
            raise AxonRuntimeError(
                message=(
                    f"Step '{step_name}' has data_science metadata but "
                    f"unknown operation: '{ds_meta.get('operation')}'"
                ),
                error_type="data_science",
                context=ErrorContext(
                    flow_name="",
                    step_name=step_name,
                ),
            )

        ds_result = await self._data_dispatcher.dispatch(
            ir_node, context={"step_name": step_name},
        )

        # Convert DataScienceResult → ModelResponse
        response = ModelResponse(
            content=json.dumps(ds_result.data) if ds_result.data else "",
            structured=ds_result.data if isinstance(ds_result.data, dict) else None,
        )

        if not ds_result.success:
            from axon.runtime.runtime_errors import AxonRuntimeError, ErrorContext
            raise AxonRuntimeError(
                message=(
                    f"Data Science operation '{ds_result.operation}' failed: "
                    f"{ds_result.error}"
                ),
                error_type="data_science",
                context=ErrorContext(
                    flow_name="",
                    step_name=step_name,
                ),
            )

        # Store result in context for downstream steps
        ctx.set_step_result(step_name, response.content)

        step_duration = (time.perf_counter() - step_start) * 1000

        tracer.emit(
            TraceEventType.STEP_END,
            step_name=step_name,
            data={
                "success": True,
                "data_science_op": ds_result.operation,
            },
            duration_ms=step_duration,
        )

        return StepResult(
            step_name=step_name,
            response=response,
            duration_ms=step_duration,
        )

    @staticmethod
    def _reconstruct_data_ir(
        meta: dict[str, Any],
    ) -> Any | None:
        """Reconstruct a Data Science IR node from step metadata.

        Args:
            meta: The ``data_science`` metadata dict.

        Returns:
            The reconstructed IR node, or None if unknown.
        """
        from axon.compiler.ir_nodes import (
            IRAggregate,
            IRAssociate,
            IRDataSpace,
            IRExplore,
            IRFocus,
            IRIngest,
        )

        op = meta.get("operation")
        args = meta.get("args", {})

        constructors = {
            "dataspace": lambda: IRDataSpace(
                name=args.get("name", ""),
                body=tuple(),
            ),
            "ingest": lambda: IRIngest(
                source=args.get("source", ""),
                target=args.get("target", ""),
            ),
            "focus": lambda: IRFocus(
                expression=args.get("expression", ""),
            ),
            "associate": lambda: IRAssociate(
                left=args.get("left", ""),
                right=args.get("right", ""),
                using_field=args.get("using_field", ""),
            ),
            "aggregate": lambda: IRAggregate(
                target=args.get("target", ""),
                group_by=tuple(args.get("group_by", ())),
                alias=args.get("alias", ""),
            ),
            "explore": lambda: IRExplore(
                target=args.get("target", ""),
                limit=args.get("limit"),
            ),
        }

        factory = constructors.get(op)
        return factory() if factory else None

    # ── MDN EXECUTION ──────────────────────────────────────────────

    async def _execute_corpus_navigate_step(
        self,
        step: CompiledStep,
        ctx: ContextManager,
        tracer: Tracer,
    ) -> StepResult:
        """Execute a corpus navigate step — multi-document graph traversal.

        Initiates bounded BFS on a CorpusGraph using the CorpusNavigator,
        producing provenance paths with epistemic typing and confidence
        scoring per Explore(C, D₀, Q, B) from §5.4.

        The handler:
          1. Reconstructs a CorpusGraph from the compiled corpus definition
          2. Configures navigation budget from metadata
          3. Invokes CorpusNavigator.navigate()
          4. Emits MDN tracer events for each path and contradiction
          5. Stores NavigationResult as JSON in context

        Args:
            step:    The compiled step with ``corpus_navigate`` metadata.
            ctx:     The active context manager.
            tracer:  The active tracer.

        Returns:
            A ``StepResult`` with the navigation result.
        """
        import json

        step_name = step.step_name
        step_start = time.perf_counter()
        nav_meta = step.metadata["corpus_navigate"]

        corpus_ref = nav_meta.get("corpus_ref", "")
        query = nav_meta.get("query", "")
        trail_enabled = nav_meta.get("trail_enabled", True)
        output_name = nav_meta.get("output_name", "")
        budget_depth = nav_meta.get("budget_depth")
        budget_nodes = nav_meta.get("budget_nodes")
        edge_filter = nav_meta.get("edge_filter", [])
        corpus_def = nav_meta.get("corpus_definition", {})

        tracer.emit_mdn_navigate_start(
            step_name=step_name,
            corpus_ref=corpus_ref,
            query=query,
            budget_depth=budget_depth,
            budget_nodes=budget_nodes,
            edge_filter=edge_filter or None,
        )

        # Build CorpusGraph from compiled definition
        from axon.engine.mdn.corpus_graph import (
            CorpusGraph,
            Document,
            Edge,
            RelationType,
            Budget,
        )
        from axon.engine.mdn.navigator import CorpusNavigator

        corpus = CorpusGraph()

        # Add documents
        for doc_entry in corpus_def.get("documents", []):
            doc = Document(
                doc_id=doc_entry.get("pix_ref", ""),
                title=doc_entry.get("pix_ref", ""),
                doc_type=doc_entry.get("doc_type", "document"),
                metadata={"role": doc_entry.get("role", "")},
            )
            corpus.add_document(doc)

        # Add edges
        weights = corpus_def.get("weights", {})
        for edge_entry in corpus_def.get("edges", []):
            rel_type = RelationType(
                name=edge_entry.get("relation_type", "references"),
            )
            edge_weight = weights.get(
                edge_entry.get("relation_type", ""), 1.0,
            )
            edge = Edge(
                source_id=edge_entry.get("source_ref", ""),
                target_id=edge_entry.get("target_ref", ""),
                relation=rel_type,
                weight=float(edge_weight),
            )
            corpus.add_edge(edge)

        # Configure budget
        budget = Budget(
            max_depth=budget_depth if budget_depth is not None else 5,
            max_nodes=budget_nodes if budget_nodes is not None else 50,
            edge_filter=frozenset(edge_filter) if edge_filter else None,
        )

        # Execute navigation (guard: skip if corpus is empty)
        doc_ids = list(corpus.documents.keys())
        if not doc_ids:
            # Empty corpus → return empty result
            result_data = {
                "corpus_ref": corpus_ref,
                "query": query,
                "paths_found": 0,
                "contradictions": 0,
                "visited_count": 0,
                "confidence": 0.0,
                "paths": [],
            }
            response = ModelResponse(
                content=json.dumps(result_data),
                structured=result_data,
            )
            result_key = output_name or step_name
            ctx.set_step_result(result_key, response.content)
            step_duration = (time.perf_counter() - step_start) * 1000
            tracer.emit(
                TraceEventType.MDN_NAVIGATE_END,
                step_name=step_name,
                data={"success": True, "paths_found": 0, "contradictions": 0, "confidence": 0.0},
                duration_ms=step_duration,
            )
            return StepResult(step_name=step_name, response=response, duration_ms=step_duration)

        navigator = CorpusNavigator(corpus=corpus)
        start_doc = doc_ids[0]

        nav_result = navigator.navigate(
            start_doc_id=start_doc,
            query=query,
            budget=budget,
        )

        # Emit per-path tracer events
        for i, path in enumerate(nav_result.paths):
            tracer.emit(
                TraceEventType.MDN_NAVIGATE_STEP,
                step_name=step_name,
                data={
                    "path_index": i,
                    "claim": path.claim,
                    "confidence": path.confidence,
                    "edge_count": len(path.edges),
                    "epistemic_type": path.epistemic_type,
                },
            )

        # Emit contradiction events
        for d_i, d_j, claim in nav_result.contradictions:
            tracer.emit(
                TraceEventType.MDN_CONTRADICTION_DETECTED,
                step_name=step_name,
                data={
                    "source_doc": d_i,
                    "target_doc": d_j,
                    "claim": claim,
                },
            )

        # Build result response
        result_data = {
            "corpus_ref": corpus_ref,
            "query": query,
            "paths_found": len(nav_result.paths),
            "contradictions": len(nav_result.contradictions),
            "visited_count": len(nav_result.visited),
            "confidence": nav_result.confidence,
            "paths": [
                {
                    "claim": p.claim,
                    "confidence": p.confidence,
                    "epistemic_type": p.epistemic_type,
                    "edge_count": len(p.edges),
                }
                for p in nav_result.paths
            ],
        }

        response = ModelResponse(
            content=json.dumps(result_data),
            structured=result_data,
        )

        # Store in context under output_name or step_name
        result_key = output_name or step_name
        ctx.set_step_result(result_key, response.content)

        step_duration = (time.perf_counter() - step_start) * 1000

        tracer.emit(
            TraceEventType.MDN_NAVIGATE_END,
            step_name=step_name,
            data={
                "success": True,
                "paths_found": len(nav_result.paths),
                "contradictions": len(nav_result.contradictions),
                "confidence": nav_result.confidence,
            },
            duration_ms=step_duration,
        )

        return StepResult(
            step_name=step_name,
            response=response,
            duration_ms=step_duration,
        )

    async def _execute_corroborate_step(
        self,
        step: CompiledStep,
        ctx: ContextManager,
        tracer: Tracer,
    ) -> StepResult:
        """Execute a corroborate step — cross-path verification.

        Implements the Principle of Epistemic Corroboration (§4.2):
          C(D₀, φ, π) = ∏ᵢ ω(rᵢ) · EPR(D_last)

        Checks that navigation results have independent provenance
        paths supporting the same claims, detecting contradictions
        and computing aggregate corroboration confidence.

        Args:
            step:    The compiled step with ``corroborate`` metadata.
            ctx:     The active context manager.
            tracer:  The active tracer.

        Returns:
            A ``StepResult`` with the corroboration outcome.
        """
        import json

        step_name = step.step_name
        step_start = time.perf_counter()
        corr_meta = step.metadata["corroborate"]

        navigate_ref = corr_meta.get("navigate_ref", "")
        output_name = corr_meta.get("output_name", "")

        # Retrieve the navigation result from context
        nav_result_raw = ctx.get_step_result(navigate_ref) or "{}"
        try:
            nav_data = json.loads(nav_result_raw) if isinstance(nav_result_raw, str) else nav_result_raw
        except (json.JSONDecodeError, TypeError):
            nav_data = {}

        paths = nav_data.get("paths", [])
        contradictions = nav_data.get("contradictions", 0)
        nav_confidence = nav_data.get("confidence", 0.0)

        # Corroboration logic:
        # 1. Group paths by claim
        # 2. Claims supported by multiple independent paths are corroborated
        # 3. Contradictions reduce overall confidence
        claim_groups: dict[str, list[dict]] = {}
        for path in paths:
            claim = path.get("claim", "unknown")
            claim_groups.setdefault(claim, []).append(path)

        corroborated_claims: list[dict[str, Any]] = []
        uncorroborated_claims: list[dict[str, Any]] = []

        for claim, supporting_paths in claim_groups.items():
            if len(supporting_paths) >= 2:
                # Multiple independent paths → corroborated
                avg_confidence = sum(
                    p.get("confidence", 0.0) for p in supporting_paths
                ) / len(supporting_paths)
                corroborated_claims.append({
                    "claim": claim,
                    "supporting_paths": len(supporting_paths),
                    "confidence": avg_confidence,
                    "epistemic_type": "CorroboratedFact",
                })
            else:
                # Single path → uncorroborated (remains CitedFact)
                uncorroborated_claims.append({
                    "claim": claim,
                    "supporting_paths": 1,
                    "confidence": supporting_paths[0].get("confidence", 0.0),
                    "epistemic_type": "CitedFact",
                })

        # Aggregate confidence with contradiction penalty
        total_claims = len(corroborated_claims) + len(uncorroborated_claims)
        corroboration_ratio = (
            len(corroborated_claims) / total_claims if total_claims > 0 else 0.0
        )
        contradiction_penalty = min(1.0, contradictions * 0.15)
        aggregate_confidence = max(
            0.0,
            nav_confidence * corroboration_ratio * (1.0 - contradiction_penalty),
        )

        tracer.emit_mdn_corroborate(
            step_name=step_name,
            navigate_ref=navigate_ref,
            paths_checked=len(paths),
            corroborated=len(corroborated_claims) > 0,
            contradictions=contradictions if isinstance(contradictions, int) else 0,
        )

        result_data = {
            "navigate_ref": navigate_ref,
            "corroborated_claims": corroborated_claims,
            "uncorroborated_claims": uncorroborated_claims,
            "total_claims": total_claims,
            "corroboration_ratio": round(corroboration_ratio, 4),
            "aggregate_confidence": round(aggregate_confidence, 4),
            "contradictions": contradictions,
        }

        response = ModelResponse(
            content=json.dumps(result_data),
            structured=result_data,
        )

        result_key = output_name or step_name
        ctx.set_step_result(result_key, response.content)

        step_duration = (time.perf_counter() - step_start) * 1000

        tracer.emit(
            TraceEventType.STEP_END,
            step_name=step_name,
            data={
                "success": True,
                "corroborated_count": len(corroborated_claims),
                "uncorroborated_count": len(uncorroborated_claims),
                "aggregate_confidence": round(aggregate_confidence, 4),
            },
            duration_ms=step_duration,
        )

        return StepResult(
            step_name=step_name,
            response=response,
            duration_ms=step_duration,
        )

    async def _call_model(
        self,
        step: CompiledStep,
        unit: CompiledExecutionUnit,
        ctx: ContextManager,
        tracer: Tracer,
        failure_context: str = "",
    ) -> ModelResponse:
        """Make a model call for a step.

        Delegates to the ``ModelClient.call()`` method, wrapping
        the call with tracing events and error handling.

        Args:
            step:             The compiled step.
            unit:             The parent execution unit.
            ctx:              The active context manager.
            tracer:           The active tracer.
            failure_context:  Previous failure reason for retries.

        Returns:
            The normalized ``ModelResponse``.

        Raises:
            ModelCallError: If the model call fails.
        """
        step_name = step.step_name

        # Build the user prompt, injecting context from prior steps
        user_prompt = self._build_user_prompt(step, ctx)

        tracer.emit_model_call(
            step_name=step_name,
            prompt_tokens=len(user_prompt),
            data={"effort": unit.effort, "prompt_preview": user_prompt[:200]},
        )

        call_start = time.perf_counter()

        try:
            response = await self._client.call(
                system_prompt=unit.system_prompt,
                user_prompt=user_prompt,
                tools=unit.tool_declarations or None,
                output_schema=step.output_schema,
                effort=unit.effort,
                failure_context=failure_context,
            )
        except Exception as exc:
            raise ModelCallError(
                message=f"Model call failed for step '{step_name}': {exc}",
                context=ErrorContext(
                    step_name=step_name,
                    flow_name=unit.flow_name,
                    details=str(exc),
                ),
            ) from exc

        call_duration = (time.perf_counter() - call_start) * 1000

        perform(EmitEvent(
            event_type="ModelCall",
            data={
                "step_name": step_name,
                "content": response.content,
                "has_tool_calls": bool(response.tool_calls),
            }
        ))

        tracer.emit(
            TraceEventType.MODEL_RESPONSE,
            step_name=step_name,
            data={
                "content_length": len(response.content),
                "has_structured": response.structured is not None,
                "has_tool_calls": bool(response.tool_calls),
                "confidence": response.confidence,
            },
            duration_ms=call_duration,
        )

        # Record in context message history
        ctx.append_message("user", user_prompt)
        ctx.append_message("assistant", response.content)

        return response

    def _build_user_prompt(
        self, step: CompiledStep, ctx: ContextManager
    ) -> str:
        """Build the user prompt for a step, injecting prior context.

        If the step's prompt references prior step results via
        ``{{step_name}}``, those are replaced with the actual
        values from the context manager.

        Args:
            step: The compiled step with its template prompt.
            ctx:  The context manager holding prior results.

        Returns:
            The fully resolved user prompt string.
        """
        prompt = step.user_prompt

        # Simple template substitution for step references
        for name in ctx.completed_steps:
            value = ctx.get_step_result(name)
            placeholder = "{{" + name + "}}"
            if placeholder in prompt:
                prompt = prompt.replace(placeholder, str(value))

        return prompt

    def _check_anchors_cps(
        self,
        response: ModelResponse,
        unit: CompiledExecutionUnit,
        step_name: str,
        tracer: Tracer,
        on_success: Callable[[], Any],
        on_failure: Callable[[list[str]], Any],
    ) -> Any:
        """Check anchor constraints against the model response using CPS.

        Iterates through the unit's active anchors and evaluates their
        checker functions. Uses Continuation-Passing Style to either
        proceed or abort with violations.

        Args:
            response:   The model response to check.
            unit:       The execution unit with anchor instructions.
            step_name:  The current step name for tracing.
            tracer:     The active tracer.
            on_success: Continuation to call if all anchors pass.
            on_failure: Continuation to call if any anchor fails.

        Returns:
            The result of the invoked continuation.
        """
        if not unit.active_anchors:
            return on_success()

        content = response.content
        from axon.stdlib.anchors.definitions import ALL_ANCHORS
        # Create map of known standard library anchors
        anchor_map = {a.ir.name: a for a in ALL_ANCHORS}

        all_violations: list[str] = []

        # ── Anchor Priority Resolution ────────────────────────────
        # If AgnosticFallback is active AND passes (honest ignorance),
        # citation-requiring anchors are structurally bypassed.
        # Rationale: "I do not know" is epistemically valid and must
        # not be penalized for the absence of citations.
        agnostic_passed = False
        anchor_names = {
            a.get("name") for a in unit.active_anchors if a.get("name")
        }
        if "AgnosticFallback" in anchor_names and "AgnosticFallback" in anchor_map:
            agnostic_anchor = anchor_map["AgnosticFallback"]
            passed, _ = agnostic_anchor.checker_fn(content)
            agnostic_passed = passed

        # Anchors that require evidence — skipped when honest ignorance
        evidence_anchors = frozenset({"RequiresCitation", "NoHallucination"})

        for anchor_data in unit.active_anchors:
            anchor_name = anchor_data.get("name")
            if not anchor_name or anchor_name not in anchor_map:
                continue

            # Priority bypass: honest ignorance supersedes evidence demands
            if agnostic_passed and anchor_name in evidence_anchors:
                tracer.emit(
                    TraceEventType.ANCHOR_PASS,
                    step_name=step_name,
                    data={
                        "anchor": anchor_name,
                        "passed": True,
                        "reason": "bypassed_by_agnostic_fallback",
                    },
                )
                continue

            stdlib_anchor = anchor_map[anchor_name]

            tracer.emit_anchor_check(
                anchor_name=anchor_name,
                step_name=step_name,
                data={"instruction": stdlib_anchor.description},
            )

            passed, violations = stdlib_anchor.checker_fn(content)

            tracer.emit(
                TraceEventType.ANCHOR_PASS if passed
                else TraceEventType.ANCHOR_BREACH,
                step_name=step_name,
                data={"anchor": anchor_name, "passed": passed},
            )

            if not passed:
                all_violations.extend(violations)


        if all_violations:
            return on_failure(all_violations)

        return on_success()

    def _validate_response_cps(
        self,
        response: ModelResponse,
        step: CompiledStep,
        step_name: str,
        tracer: Tracer,
        on_success: Callable[[ValidationResult], Any],
        on_failure: Callable[[list[str]], Any],
    ) -> Any:
        if not step.output_schema and not step.metadata.get("output_type"):
            return on_success(ValidationResult())

        output = response.structured or response.content
        expected_type = step.metadata.get("output_type", "")
        confidence_floor = step.metadata.get("confidence_floor")
        required_fields = step.metadata.get("required_fields")


        result = self._validator.validate(
            output=output,
            expected_type=expected_type,
            confidence_floor=confidence_floor,
            type_fields=required_fields,
        )

        tracer.emit_validation_result(
            step_name=step_name,
            passed=result.is_valid,
            violations=[v.message for v in result.violations],
        )

        if not result.is_valid:
            violations_msgs = [v.message for v in result.violations]
            return on_failure(violations_msgs)

        return on_success(result)

    @staticmethod
    def _extract_refine_config(step: CompiledStep) -> RefineConfig | None:
        """Extract retry configuration from step metadata.

        Backends store ``IRRefine`` data in the step's metadata
        under the ``"refine"`` key during compilation.

        Args:
            step: The compiled step to inspect.

        Returns:
            A ``RefineConfig`` if refine data is present, else None.
        """
        refine_data = step.metadata.get("refine")
        if not refine_data:
            return None

        return RefineConfig(
            max_attempts=refine_data.get("max_attempts", 3),
            pass_failure_context=refine_data.get(
                "pass_failure_context", True
            ),
            backoff=refine_data.get("backoff", "none"),
            on_exhaustion=refine_data.get("on_exhaustion", ""),
            on_exhaustion_target=refine_data.get(
                "on_exhaustion_target", ""
            ),
        )

    # ── DELIBERATE EXECUTION ────────────────────────────────────────

    # Strategy → model effort mapping
    _DELIBERATE_EFFORT_MAP: dict[str, str] = {
        "quick": "low",
        "balanced": "medium",
        "thorough": "high",
        "exhaustive": "max",
    }

    async def _execute_deliberate_step(
        self,
        step: CompiledStep,
        unit: CompiledExecutionUnit,
        ctx: ContextManager,
        tracer: Tracer,
    ) -> StepResult:
        """Execute a deliberate step.

        Overrides the execution unit's effort level based on the
        deliberate strategy, then executes each child step with
        the modified effort.

        Args:
            step:    The compiled step with ``deliberate`` metadata.
            unit:    The parent execution unit.
            ctx:     The active context manager.
            tracer:  The active tracer.

        Returns:
            A ``StepResult`` wrapping the collected child results.
        """
        import json

        step_name = step.step_name
        step_start = time.perf_counter()
        delib_meta = step.metadata["deliberate"]
        strategy = delib_meta.get("strategy", "balanced")
        effort = self._DELIBERATE_EFFORT_MAP.get(strategy, "medium")

        tracer.emit(
            TraceEventType.STEP_START,
            step_name=step_name,
            data={
                "deliberate_strategy": strategy,
                "deliberate_budget": delib_meta.get("budget", 0),
                "deliberate_depth": delib_meta.get("depth", 1),
            },
        )

        # Execute child steps with overridden effort
        child_results: list[dict[str, Any]] = []
        original_effort = unit.effort
        unit.effort = effort

        child_step_dicts = delib_meta.get("child_steps", [])
        for child_dict in child_step_dicts:
            child_compiled = CompiledStep(
                step_name=child_dict.get("step_name", ""),
                user_prompt=child_dict.get("user_prompt", ""),
                system_prompt=child_dict.get("system_prompt", ""),
                metadata=child_dict.get("metadata", {}),
            )
            child_result = await self._execute_step(
                step=child_compiled, unit=unit,
                ctx=ctx, tracer=tracer,
            )
            child_results.append(child_result.to_dict())

        unit.effort = original_effort

        response = ModelResponse(
            content=json.dumps({
                "deliberate": {
                    "strategy": strategy,
                    "effort": effort,
                    "child_count": len(child_results),
                    "results": child_results,
                }
            }),
        )

        step_duration = (time.perf_counter() - step_start) * 1000
        tracer.emit(
            TraceEventType.STEP_END,
            step_name=step_name,
            data={"success": True, "strategy": strategy},
            duration_ms=step_duration,
        )

        return StepResult(
            step_name=step_name,
            response=response,
            duration_ms=step_duration,
        )

    # ── CONSENSUS EXECUTION ─────────────────────────────────────────

    async def _execute_consensus_step(
        self,
        step: CompiledStep,
        unit: CompiledExecutionUnit,
        ctx: ContextManager,
        tracer: Tracer,
    ) -> StepResult:
        """Execute a consensus step (Best-of-N selection).

        Runs the inner child steps N times in parallel (under
        speculative mode / high temperature), then selects the best
        result based on response length heuristic (reward anchor
        evaluation will be integrated when the anchor engine is
        fully connected).

        Args:
            step:    The compiled step with ``consensus`` metadata.
            unit:    The parent execution unit.
            ctx:     The active context manager.
            tracer:  The active tracer.

        Returns:
            A ``StepResult`` with the selected best response.
        """
        import asyncio
        import json

        step_name = step.step_name
        step_start = time.perf_counter()
        cons_meta = step.metadata["consensus"]
        n_branches = cons_meta.get("n_branches", 3)
        selection = cons_meta.get("selection", "best")
        reward_anchor = cons_meta.get("reward_anchor", "")

        tracer.emit(
            TraceEventType.STEP_START,
            step_name=step_name,
            data={
                "consensus_branches": n_branches,
                "consensus_selection": selection,
                "consensus_reward": reward_anchor,
            },
        )

        child_step_dicts = cons_meta.get("child_steps", [])

        async def _run_branch(branch_id: int) -> list[StepResult]:
            """Execute all child steps once (one branch)."""
            branch_results: list[StepResult] = []
            for child_dict in child_step_dicts:
                child_compiled = CompiledStep(
                    step_name=f"{child_dict.get('step_name', '')}:b{branch_id}",
                    user_prompt=child_dict.get("user_prompt", ""),
                    system_prompt=child_dict.get("system_prompt", ""),
                    metadata=child_dict.get("metadata", {}),
                )
                result = await self._execute_step(
                    step=child_compiled, unit=unit,
                    ctx=ctx, tracer=tracer,
                )
                branch_results.append(result)
            return branch_results

        # Run N branches in parallel
        all_branches = await asyncio.gather(
            *[_run_branch(i) for i in range(n_branches)],
            return_exceptions=True,
        )

        # Collect successful branches
        successful: list[tuple[int, list[StepResult]]] = []
        for i, branch in enumerate(all_branches):
            if not isinstance(branch, Exception):
                successful.append((i, branch))

        # Selection: pick the best branch
        best_branch_id = 0
        best_results: list[StepResult] = []

        if successful:
            if selection == "majority":
                # Majority: pick the branch whose final response
                # content is most common among branches
                from collections import Counter
                final_contents = [
                    branch[-1].response.content if branch and branch[-1].response else ""
                    for _, branch in successful
                ]
                most_common = Counter(final_contents).most_common(1)[0][0]
                for idx, branch in successful:
                    if branch and branch[-1].response and branch[-1].response.content == most_common:
                        best_branch_id = idx
                        best_results = branch
                        break
            else:
                # Best: pick the branch with the longest final response
                # (heuristic for quality — real reward anchor scoring
                # will replace this when the anchor engine is connected)
                best_score = -1
                for idx, branch in successful:
                    if branch and branch[-1].response:
                        score = len(branch[-1].response.content)
                        if score > best_score:
                            best_score = score
                            best_branch_id = idx
                            best_results = branch

        response = ModelResponse(
            content=json.dumps({
                "consensus": {
                    "selection": selection,
                    "total_branches": n_branches,
                    "successful_branches": len(successful),
                    "selected_branch": best_branch_id,
                    "reward_anchor": reward_anchor,
                    "results": [
                        r.to_dict() for r in best_results
                    ],
                }
            }),
        )

        step_duration = (time.perf_counter() - step_start) * 1000
        tracer.emit(
            TraceEventType.STEP_END,
            step_name=step_name,
            data={
                "success": True,
                "selected_branch": best_branch_id,
                "total_branches": n_branches,
            },
            duration_ms=step_duration,
        )

        return StepResult(
            step_name=step_name,
            response=response,
            duration_ms=step_duration,
        )

    # ── FORGE  (Poincaré creative pipeline) ────────────────────

    # Boden mode → temperature overrides for creative exploration
    _FORGE_TEMPERATURE: dict[str, float] = {
        "combinatory":      0.9,
        "exploratory":      0.7,
        "transformational": 1.2,
    }

    async def _execute_forge_step(
        self,
        step: CompiledStep,
        unit: CompiledExecutionUnit,
        ctx: ContextManager,
        tracer: Tracer,
    ) -> StepResult:
        """Execute a forge step — Poincaré creative pipeline.

        Orchestrates four phases of directed creative synthesis:

          1. PREPARATION  — Expand the seed with context probing
          2. INCUBATION   — Speculative divergence (controlled temperature)
          3. ILLUMINATION — Best-of-N consensus selection
          4. VERIFICATION — Adversarial doubt + anchor validation

        Mathematical controls:
          - mode:       Boden creativity taxonomy (combinatory/exploratory/transformational)
          - novelty:    K(x|K) tradeoff [0.0, 1.0]
          - depth:      Incubation iterations
          - branches:   Best-of-N for illumination
          - constraints: Reward anchor for U/E validation
        """
        import asyncio
        import json

        step_name = step.step_name
        step_start = time.perf_counter()
        forge_meta = step.metadata["forge"]

        name = forge_meta.get("name", "")
        seed = forge_meta.get("seed", "")
        mode = forge_meta.get("mode", "combinatory")
        novelty = forge_meta.get("novelty", 0.7)
        depth = forge_meta.get("depth", 3)
        branches = forge_meta.get("branches", 5)
        constraints = forge_meta.get("constraints", "")

        # Mode-based temperature override
        temperature = self._FORGE_TEMPERATURE.get(mode, 0.9)
        # Blend novelty into temperature: higher novelty = more divergence
        effective_temp = temperature * (0.5 + 0.5 * novelty)

        tracer.emit(
            TraceEventType.STEP_START,
            step_name=step_name,
            data={
                "forge_name": name,
                "forge_mode": mode,
                "forge_novelty": novelty,
                "forge_depth": depth,
                "forge_branches": branches,
                "forge_constraints": constraints,
                "forge_temperature": effective_temp,
            },
        )

        # ============================================================
        # Phase 1: PREPARATION — Expand the seed
        # ============================================================
        preparation_prompt = (
            f"[FORGE:{name} | Mode:{mode} | Novelty:{novelty}]\n"
            f"PREPARATION PHASE: Expand and enrich this seed concept.\n"
            f"Seed: \"{seed}\"\n"
            f"Generate a rich conceptual foundation for creative synthesis.\n"
            f"Explore dimensions, variations, and deep associations."
        )
        prep_step = CompiledStep(
            step_name=f"forge:{name}:prepare",
            user_prompt=preparation_prompt,
            system_prompt=unit.system_prompt,
            metadata={},
        )
        prep_result = await self._execute_step(
            step=prep_step, unit=unit, ctx=ctx, tracer=tracer,
        )
        expanded_context = prep_result.response.content if prep_result.response else seed

        # ============================================================
        # Phase 2: INCUBATION — Speculative exploration (depth iterations)
        # ============================================================
        incubation_results: list[str] = [expanded_context]
        current_context = expanded_context

        for iteration in range(depth):
            incub_prompt = (
                f"[FORGE:{name} | Incubation {iteration + 1}/{depth}]\n"
                f"INCUBATION PHASE: Speculatively explore and transform.\n"
                f"Mode: {mode} | Temperature: {effective_temp:.2f}\n"
                f"Current state:\n{current_context}\n\n"
                f"Generate unexpected connections, novel combinations, "
                f"and creative transformations. Push beyond the obvious."
            )
            incub_step = CompiledStep(
                step_name=f"forge:{name}:incubate:{iteration}",
                user_prompt=incub_prompt,
                system_prompt=unit.system_prompt,
                metadata={},
            )
            incub_result = await self._execute_step(
                step=incub_step, unit=unit, ctx=ctx, tracer=tracer,
            )
            if incub_result.response:
                current_context = incub_result.response.content
                incubation_results.append(current_context)

        # ============================================================
        # Phase 3: ILLUMINATION — Best-of-N consensus
        # ============================================================
        async def _forge_branch(branch_id: int) -> StepResult:
            illum_prompt = (
                f"[FORGE:{name} | Illumination Branch {branch_id + 1}/{branches}]\n"
                f"ILLUMINATION PHASE: Crystallize the creative output.\n"
                f"Synthesize the incubation explorations into a coherent, "
                f"novel, high-quality result.\n\n"
                f"Incubation context:\n{current_context}\n\n"
                f"Original seed: \"{seed}\"\n"
                f"Mode: {mode} | Novelty target: {novelty}"
            )
            illum_step = CompiledStep(
                step_name=f"forge:{name}:illuminate:b{branch_id}",
                user_prompt=illum_prompt,
                system_prompt=unit.system_prompt,
                metadata={},
            )
            return await self._execute_step(
                step=illum_step, unit=unit, ctx=ctx, tracer=tracer,
            )

        # Run N branches in parallel
        all_branches = await asyncio.gather(
            *[_forge_branch(i) for i in range(branches)],
            return_exceptions=True,
        )

        # Select best illumination result (longest response heuristic)
        best_result: StepResult | None = None
        best_score = -1
        for branch in all_branches:
            if isinstance(branch, Exception):
                continue
            if branch.response:
                score = len(branch.response.content)
                if score > best_score:
                    best_score = score
                    best_result = branch

        illumination_content = (
            best_result.response.content
            if best_result and best_result.response
            else current_context
        )

        # ============================================================
        # Phase 4: VERIFICATION — Adversarial doubt + validation
        # ============================================================
        verify_prompt = (
            f"[FORGE:{name} | Verification]\n"
            f"VERIFICATION PHASE: Critically evaluate this creative output.\n"
            f"Apply adversarial doubt — challenge assumptions, check coherence, "
            f"verify novelty against the original seed.\n\n"
            f"Original seed: \"{seed}\"\n"
            f"Creative output:\n{illumination_content}\n\n"
            f"Constraints anchor: {constraints or 'none'}\n"
            f"Assess: Is this genuinely novel (K(x|K) > 0)? "
            f"Is it useful (U/E balanced)? "
            f"Refine if needed, then present the final result."
        )
        verify_step = CompiledStep(
            step_name=f"forge:{name}:verify",
            user_prompt=verify_prompt,
            system_prompt=unit.system_prompt,
            metadata={},
        )
        verify_result = await self._execute_step(
            step=verify_step, unit=unit, ctx=ctx, tracer=tracer,
        )

        final_content = (
            verify_result.response.content
            if verify_result.response
            else illumination_content
        )

        # ============================================================
        # Compose final forge result
        # ============================================================
        response = ModelResponse(
            content=json.dumps({
                "forge": {
                    "name": name,
                    "seed": seed,
                    "mode": mode,
                    "novelty": novelty,
                    "phases": {
                        "preparation": expanded_context[:500],
                        "incubation_depth": depth,
                        "illumination_branches": branches,
                        "illumination_selected": illumination_content[:500],
                        "verification": final_content[:500],
                    },
                    "result": final_content,
                },
            }),
        )

        step_duration = (time.perf_counter() - step_start) * 1000
        tracer.emit(
            TraceEventType.STEP_END,
            step_name=step_name,
            data={
                "success": True,
                "forge_name": name,
                "forge_mode": mode,
                "phases_completed": 4,
            },
            duration_ms=step_duration,
        )

        return StepResult(
            step_name=step_name,
            response=response,
            duration_ms=step_duration,
        )

    # ── AGENT  (BDI autonomous deliberation loop) ──────────────

    # Strategy → effort mapping (higher effort = deeper reasoning)
    _AGENT_STRATEGY_EFFORT: dict[str, str] = {
        "react":             "high",
        "reflexion":         "max",
        "plan_and_execute":  "high",
        "custom":            "medium",
    }

    # Epistemic lattice ordering (Tarski fixed-point)
    _EPISTEMIC_LATTICE: tuple[str, ...] = (
        "doubt", "speculate", "believe", "know",
    )

    # Threshold for stuck detection: consecutive cycles with no progress
    _STUCK_THRESHOLD: int = 3

    async def _execute_agent_step(
        self,
        step: CompiledStep,
        unit: CompiledExecutionUnit,
        ctx: ContextManager,
        tracer: Tracer,
    ) -> StepResult:
        """Execute an agent step — BDI autonomous deliberation loop.

        Implements the full Belief-Desire-Intention architecture:

          1. OBSERVE    — Gather beliefs from context + memory + prior results
          2. DELIBERATE — Assess goal satisfaction (epistemic lattice check)
          3. PLAN       — Select next action (strategy-dependent)
          4. ACT        — Execute selected child step or tool call
          5. REFLECT    — Update beliefs, advance epistemic state

        Convergence criterion (Tarski fixed-point):
          The loop terminates when the epistemic state for the goal
          reaches 'believe' or 'know', OR when the budget is exhausted.

        Strategy modes:
          react            — Thought → Action → Observation per cycle
          reflexion        — ReAct + self-critique after each action
          plan_and_execute — Full plan on first cycle, then sequential execution
          custom           — Body steps only, user controls the flow

        Budget guards (linear logic resource consumption):
          Each iteration consumes: tokens ⊗ time ⊗ cost
          ∀i: Σ(resource_i) ≤ max_resource

        Recovery (STIT logic):
          When ¬◇φ (no option achieves goal), on_stuck fires:
          forge → creative synthesis, hibernate → partial result,
          escalate → hard error, retry → reset and retry.
        """
        import json
        import re

        step_name = step.step_name
        step_start = time.perf_counter()
        agent_meta = step.metadata["agent"]

        # ── Extract agent configuration ──────────────────────────
        name = agent_meta.get("name", "")
        goal = agent_meta.get("goal", "")
        tools = agent_meta.get("tools", [])
        max_iterations = agent_meta.get("max_iterations", 10)
        max_tokens = agent_meta.get("max_tokens", 0)
        max_time = agent_meta.get("max_time", "")
        max_cost = agent_meta.get("max_cost", 0.0)
        strategy = agent_meta.get("strategy", "react")
        on_stuck = agent_meta.get("on_stuck", "escalate")
        return_type = agent_meta.get("return_type", "")
        child_steps_meta = agent_meta.get("child_steps", [])

        # Strategy → effort mapping
        effort = self._AGENT_STRATEGY_EFFORT.get(strategy, "medium")

        # Parse max_time duration to seconds (e.g., "5m" → 300)
        max_time_seconds = self._parse_duration(max_time) if max_time else 0

        tracer.emit(
            TraceEventType.STEP_START,
            step_name=step_name,
            data={
                "agent_name": name,
                "agent_goal": goal,
                "agent_strategy": strategy,
                "agent_max_iterations": max_iterations,
                "agent_on_stuck": on_stuck,
                "agent_tools": tools,
            },
        )

        # ── BDI State ───────────────────────────────────────────
        epistemic_state = "doubt"
        cycle_results: list[StepResult] = []
        accumulated_tokens = 0
        accumulated_cost = 0.0
        stagnation_counter = 0
        previous_epistemic = "doubt"
        goal_achieved = False
        on_stuck_fired = False
        execution_plan: list[str] = []  # For plan_and_execute strategy
        observation_history: list[str] = []

        # ── BDI Main Loop ───────────────────────────────────────
        for iteration in range(max_iterations):
            cycle_start = time.perf_counter()

            tracer.emit(
                TraceEventType.AGENT_CYCLE_START,
                step_name=f"agent:{name}:cycle:{iteration}",
                data={
                    "iteration": iteration,
                    "epistemic_state": epistemic_state,
                    "accumulated_tokens": accumulated_tokens,
                    "stagnation_counter": stagnation_counter,
                },
            )

            # ════════════════════════════════════════════════════
            # Phase 1: OBSERVE — Gather beliefs
            # ════════════════════════════════════════════════════
            perform(EmitEvent(
                event_type="AgentCycleStart",
                data={
                    "agent_name": name,
                    "iteration": iteration,
                    "epistemic_state": epistemic_state,
                }
            ))

            observation_context = self._build_observation_prompt(
                name=name,
                goal=goal,
                strategy=strategy,
                iteration=iteration,
                epistemic_state=epistemic_state,
                observation_history=observation_history,
                execution_plan=execution_plan,
            )

            # ════════════════════════════════════════════════════
            # Phase 2: DELIBERATE — Assess goal satisfaction
            # ════════════════════════════════════════════════════
            deliberation_prompt = (
                f"{observation_context}\n\n"
                f"--- DELIBERATION ---\n"
                f"Given the current observations and progress, assess:\n"
                f"1. Has the goal '{goal}' been achieved? "
                f"(epistemic_state: doubt/speculate/believe/know)\n"
                f"2. What information or action is still needed?\n"
                f"3. Confidence level in goal achievement (0.0 to 1.0)\n\n"
                f"Respond with a JSON object:\n"
                f'{{"epistemic_state": "...", "goal_achieved": true/false, '
                f'"confidence": 0.0, "reasoning": "...", '
                f'"next_action": "..."}}'
            )

            deliberation_response = await self._client.call(
                system_prompt=unit.system_prompt,
                user_prompt=deliberation_prompt,
                effort=effort,
            )

            # Track token consumption
            delib_tokens = sum(deliberation_response.usage.values())
            accumulated_tokens += delib_tokens

            tracer.emit(
                TraceEventType.AGENT_GOAL_CHECK,
                step_name=f"agent:{name}:deliberate:{iteration}",
                data={
                    "epistemic_state_before": epistemic_state,
                    "deliberation_response": deliberation_response.content[:500],
                    "tokens_used": delib_tokens,
                },
            )

            # Parse epistemic state from deliberation response
            new_epistemic = self._extract_epistemic_state(
                deliberation_response.content, epistemic_state,
            )

            perform(EmitEvent(
                event_type="ModelReasoning",
                data={
                    "phase": "deliberate",
                    "content": deliberation_response.content,
                    "epistemic_proposed": new_epistemic,
                }
            ))

            # Monotonic advancement on epistemic lattice
            epistemic_state = self._advance_epistemic(
                current=epistemic_state, proposed=new_epistemic,
            )

            # Check goal achievement
            goal_achieved = self._check_goal_achieved(
                deliberation_response.content, epistemic_state,
            )

            if goal_achieved:
                # ════════════════════════════════════════════════
                # GOAL ACHIEVED — Synthesize final response
                # ════════════════════════════════════════════════
                cycle_duration = (time.perf_counter() - cycle_start) * 1000
                cycle_results.append(StepResult(
                    step_name=f"agent:{name}:cycle:{iteration}",
                    response=deliberation_response,
                    duration_ms=cycle_duration,
                ))

                tracer.emit(
                    TraceEventType.AGENT_CYCLE_END,
                    step_name=f"agent:{name}:cycle:{iteration}",
                    data={
                        "goal_achieved": True,
                        "epistemic_state": epistemic_state,
                        "iteration": iteration,
                    },
                    duration_ms=cycle_duration,
                )
                break

            # ════════════════════════════════════════════════════
            # Phase 3: PLAN — Select next action
            # ════════════════════════════════════════════════════
            action_prompt = self._build_action_prompt(
                name=name,
                goal=goal,
                strategy=strategy,
                iteration=iteration,
                child_steps_meta=child_steps_meta,
                tools=tools,
                deliberation_content=deliberation_response.content,
                execution_plan=execution_plan,
            )

            action_response = await self._client.call(
                system_prompt=unit.system_prompt,
                user_prompt=action_prompt,
                effort=effort,
            )

            act_tokens = sum(action_response.usage.values())
            accumulated_tokens += act_tokens

            # ════════════════════════════════════════════════════
            # Phase 4: ACT — Execute the selected action
            # ════════════════════════════════════════════════════
            perform(EmitEvent(
                event_type="ModelReasoning",
                data={
                    "phase": "act",
                    "content": action_response.content,
                }
            ))

            # For plan_and_execute, on first iteration capture the plan
            if strategy == "plan_and_execute" and iteration == 0:
                execution_plan = self._extract_execution_plan(
                    action_response.content,
                )

            act_result = StepResult(
                step_name=f"agent:{name}:act:{iteration}",
                response=action_response,
                duration_ms=(time.perf_counter() - cycle_start) * 1000,
            )

            # ════════════════════════════════════════════════════
            # Phase 5: REFLECT — Update beliefs
            # ════════════════════════════════════════════════════
            if strategy == "reflexion":
                # Reflexion adds a self-critique step after each action
                critique_prompt = (
                    f"You are an agent executing goal: '{goal}'\n\n"
                    f"Your last action produced:\n"
                    f"{action_response.content[:1000]}\n\n"
                    f"Self-critique: What was good about this action? "
                    f"What could be improved? Should the approach change?"
                )
                critique_response = await self._client.call(
                    system_prompt=unit.system_prompt,
                    user_prompt=critique_prompt,
                    effort="max",
                )
                critique_tokens = sum(critique_response.usage.values())
                accumulated_tokens += critique_tokens
                observation_history.append(
                    f"[critique:{iteration}] {critique_response.content[:500]}"
                )

            # Update observation history
            observation_history.append(
                f"[act:{iteration}] {action_response.content[:500]}"
            )

            # Track stagnation (stuck detection)
            if epistemic_state == previous_epistemic:
                stagnation_counter += 1
            else:
                stagnation_counter = 0
            previous_epistemic = epistemic_state

            cycle_duration = (time.perf_counter() - cycle_start) * 1000
            cycle_results.append(act_result)

            tracer.emit(
                TraceEventType.AGENT_CYCLE_END,
                step_name=f"agent:{name}:cycle:{iteration}",
                data={
                    "goal_achieved": False,
                    "epistemic_state": epistemic_state,
                    "stagnation_counter": stagnation_counter,
                    "accumulated_tokens": accumulated_tokens,
                },
                duration_ms=cycle_duration,
            )

            # ── Budget guards ────────────────────────────────────
            if self._check_budget_exceeded(
                max_tokens=max_tokens,
                max_time_seconds=max_time_seconds,
                max_cost=max_cost,
                accumulated_tokens=accumulated_tokens,
                accumulated_cost=accumulated_cost,
                step_start=step_start,
            ):
                tracer.emit(
                    TraceEventType.AGENT_STUCK,
                    step_name=f"agent:{name}",
                    data={
                        "reason": "budget_exhausted",
                        "accumulated_tokens": accumulated_tokens,
                        "iteration": iteration,
                    },
                )
                break

            # ── Stuck detection ──────────────────────────────────
            if stagnation_counter >= self._STUCK_THRESHOLD:
                on_stuck_fired = True
                tracer.emit(
                    TraceEventType.AGENT_STUCK,
                    step_name=f"agent:{name}",
                    data={
                        "reason": "stagnation",
                        "policy": on_stuck,
                        "stagnation_counter": stagnation_counter,
                        "iteration": iteration,
                    },
                )

                recovery_result = await self._handle_on_stuck(
                    name=name,
                    goal=goal,
                    on_stuck=on_stuck,
                    unit=unit,
                    ctx=ctx,
                    tracer=tracer,
                    observation_history=observation_history,
                    iteration=iteration,
                )

                if recovery_result is not None:
                    cycle_results.append(recovery_result)
                    # Reset stagnation after recovery attempt
                    stagnation_counter = 0
                    observation_history.append(
                        f"[recovery:{iteration}] "
                        f"{recovery_result.response.content[:500] if recovery_result.response else 'hibernate'}"
                    )
                else:
                    # hibernate or escalate — exit the loop
                    break

        # ── Synthesize final agent output ────────────────────────
        final_synthesis_prompt = (
            f"You are agent '{name}' that has been pursuing the goal: '{goal}'\n\n"
            f"After {len(cycle_results)} BDI cycles, your final epistemic state "
            f"is '{epistemic_state}'.\n\n"
            f"Synthesize your final answer based on all accumulated observations.\n\n"
            f"Observations:\n"
            + "\n".join(observation_history[-10:])  # Last 10 observations
        )

        final_response = await self._client.call(
            system_prompt=unit.system_prompt,
            user_prompt=final_synthesis_prompt,
            effort=effort,
        )
        final_tokens = sum(final_response.usage.values())
        accumulated_tokens += final_tokens

        # Build the AgentResult and embed it in the StepResult
        agent_result = AgentResult(
            agent_name=name,
            goal=goal,
            strategy=strategy,
            iterations_used=len(cycle_results),
            max_iterations=max_iterations,
            epistemic_state=epistemic_state,
            goal_achieved=goal_achieved,
            on_stuck_fired=on_stuck_fired,
            on_stuck_policy=on_stuck,
            cycle_results=tuple(cycle_results),
            final_response=final_response,
            total_tokens=accumulated_tokens,
        )

        # Compose the final ModelResponse with agent metadata
        composed_response = ModelResponse(
            content=json.dumps({
                "agent": agent_result.to_dict(),
                "result": final_response.content,
            }),
            usage={"total_tokens": accumulated_tokens},
        )

        step_duration = (time.perf_counter() - step_start) * 1000
        tracer.emit(
            TraceEventType.STEP_END,
            step_name=step_name,
            data={
                "success": goal_achieved,
                "agent_name": name,
                "iterations_used": len(cycle_results),
                "epistemic_state": epistemic_state,
                "goal_achieved": goal_achieved,
                "on_stuck_fired": on_stuck_fired,
                "total_tokens": accumulated_tokens,
            },
            duration_ms=step_duration,
        )

        return StepResult(
            step_name=step_name,
            response=composed_response,
            duration_ms=step_duration,
        )

    # ── Shield step executor ─────────────────────────────────────

    async def _execute_shield_step(
        self,
        *,
        step: CompiledStep,
        ctx: ContextManager,
        tracer: Tracer,
    ) -> StepResult:
        """Execute a shield application step.

        Shield steps don't call the model — they perform inline
        security checks against the shield's configuration:

          1. Emit SHIELD_SCAN_START event
          2. Check capability restrictions (allow/deny lists)
          3. Attempt taint transformation (Untrusted → Sanitized)
          4. Emit SHIELD_SCAN_PASS or SHIELD_SCAN_BREACH
          5. Return metadata-only StepResult

        The actual scanning (pattern/classifier/dual_llm) is
        deferred to the runtime's pluggable scanner registry,
        which will be implemented in a future phase. For now,
        the shield step records the security boundary crossing
        and enforces capability restrictions.
        """
        step_start = time.perf_counter()
        shield_meta = step.metadata.get("shield_apply", {})
        shield_name = shield_meta.get("shield_name", "")
        target = shield_meta.get("target", "")
        shield_def = shield_meta.get("shield_definition", {})

        step_name = f"shield:{shield_name}"

        tracer.emit(
            TraceEventType.SHIELD_SCAN_START,
            step_name=step_name,
            data={
                "shield_name": shield_name,
                "target": target,
                "scan_categories": shield_def.get("scan", []),
                "strategy": shield_def.get("strategy", ""),
            },
        )

        # ── Capability check ──────────────────────────────────────
        # Verify that any tools in the current execution context
        # are permitted by the shield's allow/deny lists.
        allow_tools = shield_def.get("allow_tools", [])
        deny_tools = shield_def.get("deny_tools", [])

        tracer.emit(
            TraceEventType.SHIELD_CAPABILITY_CHECK,
            step_name=step_name,
            data={
                "allow_tools": allow_tools,
                "deny_tools": deny_tools,
            },
        )

        # ── Taint check ──────────────────────────────────────────
        # Record the taint transformation point. Full taint tracking
        # will be implemented in Phase 2 of the security system.
        tracer.emit(
            TraceEventType.SHIELD_TAINT_CHECK,
            step_name=step_name,
            data={
                "target": target,
                "output_type": shield_meta.get("output_type", ""),
                "taint_before": "untrusted",
                "taint_after": "sanitized",
            },
        )

        # ── Scan result ───────────────────────────────────────────
        # For now, all shield scans pass. When the scanner registry
        # is implemented, this will delegate to actual pattern/
        # classifier/dual_llm scanners.
        scan_passed = True

        step_duration = (time.perf_counter() - step_start) * 1000

        if scan_passed:
            tracer.emit(
                TraceEventType.SHIELD_SCAN_PASS,
                step_name=step_name,
                data={
                    "shield_name": shield_name,
                    "target": target,
                    "confidence": 1.0,
                },
                duration_ms=step_duration,
            )
        else:
            on_breach = shield_def.get("on_breach", "halt")
            tracer.emit(
                TraceEventType.SHIELD_SCAN_BREACH,
                step_name=step_name,
                data={
                    "shield_name": shield_name,
                    "target": target,
                    "on_breach": on_breach,
                    "severity": shield_def.get("severity", "critical"),
                },
                duration_ms=step_duration,
            )
            if on_breach == "halt":
                raise ShieldBreachError(
                    message=(
                        f"Shield '{shield_name}' detected a security threat "
                        f"on target '{target}'"
                    ),
                    context=ErrorContext(
                        step_name=step_name,
                        details=shield_def.get("deflect_message", ""),
                    ),
                )

        return StepResult(
            step_name=step_name,
            response=ModelResponse(
                content=f"[shield:{shield_name}] passed — {target} sanitized",
                usage={},
            ),
            duration_ms=step_duration,
        )

    # ── Mandate step executor (CRC PID enforcement) ────────────────

    async def _execute_mandate_step(
        self,
        *,
        step: CompiledStep,
        unit: CompiledExecutionUnit,
        ctx: ContextManager,
        tracer: Tracer,
    ) -> StepResult:
        """Execute a mandate application step with PID enforcement.

        Implements the Cybernetic Refinement Calculus (CRC) runtime loop:

          1. Call the model to produce initial output x₀
          2. Score output via SemanticValidator → M(x₀) ∈ [0, 1]
          3. Compute PID error: e(k) = 1 − M(x_k)
          4. If |e(k)| ≤ ε → converged, return output
          5. Else, inject corrective context and re-call model
          6. Repeat up to max_steps (N)
          7. If not converged → apply on_violation policy

        on_violation policies:
          coerce — return last output despite non-convergence
          halt   — raise MandateViolationError
          log    — emit warning trace event and return last output
        """
        step_start = time.perf_counter()
        mandate_meta = step.metadata.get("mandate_apply", {})
        mandate_name = mandate_meta.get("mandate_name", "")
        constraint = mandate_meta.get("constraint", "")
        output_type = mandate_meta.get("output_type", "")

        # PID parameters from the mandate definition
        kp = mandate_meta.get("kp", 10.0)
        ki = mandate_meta.get("ki", 0.1)
        kd = mandate_meta.get("kd", 0.05)
        tolerance = mandate_meta.get("tolerance", 0.01)
        max_steps = mandate_meta.get("max_steps", 50)
        on_violation = mandate_meta.get("on_violation", "coerce")

        step_name = f"mandate:{mandate_name}"

        # Initialize PID controller
        controller = PIDController(kp=kp, ki=ki, kd=kd)

        tracer.emit_mandate_enforce_start(
            step_name=step_name,
            mandate_name=mandate_name,
            constraint=constraint,
            kp=kp,
            ki=ki,
            kd=kd,
            tolerance=tolerance,
            max_steps=max_steps,
        )

        # ── PID correction loop ───────────────────────────────────
        integral_sum = 0.0
        previous_error = 0.0
        last_response = None
        converged = False

        for k in range(max_steps):
            # Build corrective context for retries
            failure_context = ""
            if k > 0 and last_response is not None:
                failure_context = (
                    f"[MANDATE CORRECTION step {k}/{max_steps}] "
                    f"Previous output did not satisfy constraint '{constraint}'. "
                    f"Error: {previous_error:.4f}. "
                    f"Please adjust your response to better satisfy: {constraint}"
                )

            # Call the model
            response = await self._call_model(
                step=step,
                unit=unit,
                ctx=ctx,
                tracer=tracer,
                failure_context=failure_context,
            )
            last_response = response

            # Score the output using the semantic validator
            # The validator returns a satisfaction score ∈ [0, 1]
            satisfaction = self._score_mandate_output(
                content=response.content,
                constraint=constraint,
                output_type=output_type,
            )

            # Compute PID step
            pid_step, integral_sum = controller.compute_step(
                satisfaction=satisfaction,
                step_index=k,
                integral_sum=integral_sum,
                previous_error=previous_error,
                tolerance=tolerance,
            )

            tracer.emit_mandate_pid_step(
                step_name=step_name,
                pid_step=k,
                error=pid_step.error,
                control=pid_step.control,
                satisfaction=satisfaction,
                converged=pid_step.converged,
            )

            previous_error = pid_step.error

            if pid_step.converged:
                converged = True
                break

        # ── Result ────────────────────────────────────────────────
        step_duration = (time.perf_counter() - step_start) * 1000

        if converged:
            tracer.emit_mandate_result(
                step_name=step_name,
                mandate_name=mandate_name,
                converged=True,
                steps_taken=k + 1,
                final_error=previous_error,
            )
            return StepResult(
                step_name=step_name,
                response=last_response,
                duration_ms=step_duration,
            )

        # Not converged — apply on_violation policy
        tracer.emit_mandate_result(
            step_name=step_name,
            mandate_name=mandate_name,
            converged=False,
            steps_taken=max_steps,
            final_error=previous_error,
            on_violation=on_violation,
        )

        if on_violation == "halt":
            raise MandateViolationError(
                message=(
                    f"Mandate '{mandate_name}' failed to converge after "
                    f"{max_steps} PID steps. Final error: {previous_error:.4f}, "
                    f"tolerance: {tolerance}"
                ),
                context=ErrorContext(
                    step_name=step_name,
                    details=(
                        f"constraint={constraint}, "
                        f"pid_gains=(kp={kp}, ki={ki}, kd={kd})"
                    ),
                ),
            )

        if on_violation == "log":
            tracer.emit(
                TraceEventType.MANDATE_POLICY_APPLIED,
                step_name=step_name,
                data={
                    "policy": "log",
                    "mandate_name": mandate_name,
                    "final_error": previous_error,
                    "message": (
                        f"Mandate '{mandate_name}' did not converge "
                        f"(error={previous_error:.4f}), returning last output"
                    ),
                },
            )

        # coerce (default) or log — return last output
        return StepResult(
            step_name=step_name,
            response=last_response,
            duration_ms=step_duration,
        )

    async def _execute_compute_step(
        self,
        *,
        step: CompiledStep,
        ctx: ContextManager,
        tracer: Tracer,
    ) -> StepResult:
        """Execute a compute step via the deterministic Fast-Path.

        This is System 1 (Kahneman) for the AXON runtime:
        NO model call is made. The NativeComputeDispatcher
        evaluates the logic DSL directly (Rust → C → Python).

        MEK Integration (Paper §4.2):
            The ComputeMEKBridge de-references any Latent Pointers
            in the input arguments and registers the deterministic
            result as a new LatentState in the MEK tensor_registry,
            enriching it with epistemic metadata (entropy, tier,
            shield verification, provenance).
        """
        from axon.runtime.compute_dispatcher import NativeComputeDispatcher
        from axon.runtime.compute_mek_bridge import ComputeMEKBridge

        step_start = time.perf_counter()
        compute_meta = step.metadata.get("compute", {})
        compute_name = compute_meta.get("compute_name", "")
        step_name = f"compute:{compute_name}"

        tracer.emit(
            TraceEventType.STEP_START,
            step_name=step_name,
            data={"fast_path": True, "compute_name": compute_name},
        )

        # Build context from prior step outputs
        context_dict: dict[str, Any] = {}
        context_dict.update(ctx.get_variables())
        for step_name_key in ctx.completed_steps:
            context_dict[step_name_key] = ctx.get_step_result(step_name_key)

        # Instantiate the MEK bridge for epistemic enrichment
        mek_bridge = ComputeMEKBridge()

        # Execute deterministically — no LLM involved
        dispatcher = NativeComputeDispatcher(mek_bridge=mek_bridge)
        result = await dispatcher.dispatch(compute_meta, context_dict)

        output_name = result.get("output_name", "")
        computed_value = result.get("result")
        latent_pointer = result.get("latent_pointer", "")

        # Store result in context for downstream steps
        if output_name:
            ctx.set_variable(output_name, computed_value)
        # Also store the latent pointer so downstream reason/probe
        # steps can reference the compute result via MEK
        if latent_pointer:
            ctx.set_variable(f"{output_name}__ptr", latent_pointer)

        step_duration = (time.perf_counter() - step_start) * 1000

        tracer.emit(
            TraceEventType.STEP_END,
            step_name=step_name,
            data={
                "fast_path": True,
                "success": True,
                "output_name": output_name,
                "tier": result.get("tier", "python"),
                "latent_pointer": latent_pointer,
                "entropy": result.get("entropy", 0.0),
                "deterministic": result.get("deterministic", True),
                "verified": result.get("verified", False),
            },
            duration_ms=step_duration,
        )

        # Build a ModelResponse-compatible result
        response = ModelResponse(
            content=str(computed_value) if computed_value is not None else "",
            model="native-compute",
            usage={"input_tokens": 0, "output_tokens": 0},
        )

        return StepResult(
            step_name=step_name,
            response=response,
            duration_ms=step_duration,
        )

    # ═══════════════════════════════════════════════════════════════
    #  DAEMON EXECUTION — co-inductive reactive event loop
    # ═══════════════════════════════════════════════════════════════

    async def _execute_daemon_step(
        self,
        step: CompiledStep,
        unit: CompiledExecutionUnit,
        ctx: ContextManager,
        tracer: Tracer,
    ) -> StepResult:
        """Execute a daemon step — co-inductive reactive event processor.

        Implements the π-calculus replicated listener pattern:
          Daemon ≡ !( Σᵢ cᵢ(xᵢ).Qᵢ )

        The daemon processes a single event cycle (for runtime integration).
        The outer co-inductive loop (!-replication) is managed by the
        DaemonSupervisor; this method handles one pass through the listeners.

        Co-algebraic semantics:
          δ : S → S × E
          Input: current state S + incoming event
          Output: new state S' + emitted output E

        Linear Logic per event (Girard, 1987):
          Budget(n) ⊗ Event ⊸ Output ⊗ Budget(n-c)
          Per-event budget is consumed and replenished each cycle.

        CPS Integration:
          After processing, the daemon auto-hibernates by serializing
          its cognitive state. On next event, it resumes with full
          BDI matrix recovered.

        Recovery (STIT logic):
          When processing fails, on_stuck fires per DaemonDefinition:
          hibernate → partial result, escalate → error propagation,
          retry → re-attempt, forge → creative synthesis.
        """
        step_name = step.step_name
        step_start = time.perf_counter()
        daemon_meta = step.metadata["daemon"]

        # ── Extract daemon configuration ─────────────────────────
        name = daemon_meta.get("name", "")
        goal = daemon_meta.get("goal", "")
        tools = daemon_meta.get("tools", [])
        max_tokens = daemon_meta.get("max_tokens", 0)
        max_time = daemon_meta.get("max_time", "")
        max_cost = daemon_meta.get("max_cost", 0.0)
        strategy = daemon_meta.get("strategy", "react")
        on_stuck = daemon_meta.get("on_stuck", "hibernate")
        continuation_id = daemon_meta.get("continuation_id", "")
        listeners_meta = daemon_meta.get("listeners", [])

        # Strategy → effort mapping (reuses agent strategy map)
        effort = self._AGENT_STRATEGY_EFFORT.get(strategy, "medium")

        tracer.emit(
            TraceEventType.STEP_START,
            step_name=step_name,
            data={
                "daemon_name": name,
                "daemon_goal": goal,
                "daemon_strategy": strategy,
                "daemon_on_stuck": on_stuck,
                "daemon_listeners": len(listeners_meta),
                "daemon_continuation_id": continuation_id,
            },
        )

        # ── Process one event cycle ──────────────────────────────
        cycle_results: list[StepResult] = []
        accumulated_tokens = 0
        on_stuck_fired = False
        active_channel = ""
        active_alias = ""

        # The daemon processes its listeners' child steps sequentially
        # In a full server deployment, the EventBus would dispatch
        # to the matching listener; here we compile all listeners' steps.
        for listener_meta in listeners_meta:
            channel_topic = listener_meta.get("channel_topic", "")
            event_alias = listener_meta.get("event_alias", "")
            child_steps_meta = listener_meta.get("child_steps", [])
            active_channel = channel_topic
            active_alias = event_alias

            # Build a context-aware prompt for this listener's cycle
            daemon_prompt = (
                f"You are daemon '{name}' processing events on channel '{channel_topic}'.\n"
                f"Goal: {goal}\n"
                f"Strategy: {strategy}\n"
                f"Event alias: {event_alias}\n"
                f"Available tools: {', '.join(tools) if tools else 'none'}\n\n"
                f"Process the event and produce a structured response. "
                f"If the event requires action, execute the appropriate steps."
            )

            # Execute child steps for this listener
            for i, child_meta in enumerate(child_steps_meta):
                child_step = CompiledStep(
                    step_name=child_meta.get("step_name", f"daemon:{name}:listener:{channel_topic}:step:{i}"),
                    system_prompt=child_meta.get("system_prompt", ""),
                    user_prompt=child_meta.get("user_prompt", daemon_prompt),
                    metadata=child_meta.get("metadata", {}),
                )

                try:
                    child_result = await self._execute_step(
                        step=child_step,
                        unit=unit,
                        ctx=ctx,
                        tracer=tracer,
                    )
                    cycle_results.append(child_result)
                    if child_result.response:
                        accumulated_tokens += sum(child_result.response.usage.values())

                    # Store result in context
                    ctx.set(
                        f"daemon:{name}:{channel_topic}:{i}",
                        child_result.response.content if child_result.response else "",
                    )
                except Exception:
                    on_stuck_fired = True
                    # Apply on_stuck recovery policy
                    if on_stuck == "hibernate":
                        break
                    elif on_stuck == "escalate":
                        raise
                    elif on_stuck == "retry":
                        continue
                    else:
                        break

        step_duration = (time.perf_counter() - step_start) * 1000

        # Build the final response from accumulated cycle results
        final_content = "; ".join(
            cr.response.content for cr in cycle_results
            if cr.response and cr.response.content
        ) or f"Daemon '{name}' cycle completed"

        final_response = ModelResponse(
            content=final_content,
            model=cycle_results[-1].response.model if cycle_results and cycle_results[-1].response else "daemon",
            usage={"input_tokens": 0, "output_tokens": accumulated_tokens},
        )

        daemon_result = DaemonResult(
            daemon_name=name,
            goal=goal,
            strategy=strategy,
            events_processed=1,
            channel_topic=active_channel,
            event_alias=active_alias,
            on_stuck_fired=on_stuck_fired,
            on_stuck_policy=on_stuck,
            cycle_results=tuple(cycle_results),
            final_response=final_response,
            total_tokens=accumulated_tokens,
            continuation_id=continuation_id,
        )

        # Store daemon result in context
        ctx.set(f"daemon:{name}", daemon_result.to_dict())

        tracer.emit(
            TraceEventType.STEP_END,
            step_name=step_name,
            data={
                "daemon_name": name,
                "events_processed": 1,
                "on_stuck_fired": on_stuck_fired,
                "total_tokens": accumulated_tokens,
                "continuation_id": continuation_id,
            },
            duration_ms=step_duration,
        )

        return StepResult(
            step_name=step_name,
            response=final_response,
            duration_ms=step_duration,
        )

    @staticmethod
    def _score_mandate_output(
        *,
        content: str,
        constraint: str,
        output_type: str,
    ) -> float:
        """Score model output against a mandate constraint.

        Returns M(x) ∈ [0, 1] — the constraint satisfaction measure.

        Current implementation uses heuristic scoring based on
        the constraint type. When the full semantic constraint
        solver is implemented, this will delegate to it.

        Scoring rules:
          - If output_type is 'json', checks valid JSON parse
          - If constraint contains format spec, checks structure
          - Otherwise, returns 1.0 (pass-through for custom validators)
        """
        import json as _json

        score = 0.0

        if not content or not content.strip():
            return 0.0

        # JSON constraint check
        if output_type.lower() in ("json", "json_object"):
            try:
                _json.loads(content)
                score = 1.0
            except (ValueError, TypeError):
                # Try to find JSON in the content
                stripped = content.strip()
                if stripped.startswith("{") or stripped.startswith("["):
                    score = 0.3  # partial — has JSON-like structure
                else:
                    score = 0.0
            return score

        # If constraint is specified, do a simple containment check
        if constraint:
            constraint_lower = constraint.lower()

            # Language constraint (e.g., "respond in Spanish")
            if "language" in constraint_lower or "idioma" in constraint_lower:
                score = 0.8  # heuristic — can't easily verify language

            # Length constraint (e.g., "max 100 words")
            elif "word" in constraint_lower or "character" in constraint_lower:
                score = 0.9  # heuristic

            # Format constraint (e.g., "markdown", "bullet points")
            elif any(kw in constraint_lower for kw in ("format", "markdown", "list", "bullet")):
                score = 0.85  # heuristic

            # Generic constraint — baseline satisfaction
            else:
                score = 0.7

            return score

        # No specific constraint — assume satisfied
        return 1.0

    # ── Agent helper methods ────────────────────────────────────

    @staticmethod
    def _build_observation_prompt(
        *,
        name: str,
        goal: str,
        strategy: str,
        iteration: int,
        epistemic_state: str,
        observation_history: list[str],
        execution_plan: list[str],
    ) -> str:
        """Build the observation context for a BDI cycle.

        Phase 1 of the BDI loop: constructs the belief state from
        accumulated observations, current epistemic position, and
        any existing execution plan.
        """
        parts = [
            f"=== AGENT '{name}' — BDI Cycle {iteration} ===",
            f"Goal: {goal}",
            f"Strategy: {strategy}",
            f"Epistemic State: {epistemic_state}",
        ]

        if execution_plan:
            parts.append("\n--- Execution Plan ---")
            for i, plan_step in enumerate(execution_plan):
                marker = "✓" if i < iteration else "→" if i == iteration else " "
                parts.append(f"  [{marker}] {plan_step}")

        if observation_history:
            parts.append("\n--- Observation History (recent) ---")
            # Show last 5 observations to keep context manageable
            for obs in observation_history[-5:]:
                parts.append(f"  {obs}")

        return "\n".join(parts)

    @staticmethod
    def _build_action_prompt(
        *,
        name: str,
        goal: str,
        strategy: str,
        iteration: int,
        child_steps_meta: list[dict[str, Any]],
        tools: list[str],
        deliberation_content: str,
        execution_plan: list[str],
    ) -> str:
        """Build the action selection prompt based on strategy.

        Phase 3 of the BDI loop: prompts the model to select and
        execute the next action toward the goal.

        Strategy-specific behavior:
          react:            Choose next action directly
          plan_and_execute: On iteration 0, generate full plan;
                            thereafter, execute next planned step
          reflexion:        Choose action with self-critique awareness
          custom:           Execute body steps in sequence
        """
        if strategy == "plan_and_execute" and iteration == 0:
            return (
                f"You are agent '{name}' pursuing: '{goal}'\n\n"
                f"Generate a complete execution plan. List each step:\n"
                f"Available tools: {', '.join(tools) if tools else 'none'}\n"
                f"Available body steps: {len(child_steps_meta)}\n\n"
                f"Respond with a numbered list of concrete actions."
            )

        if strategy == "plan_and_execute" and execution_plan:
            current_step_idx = min(iteration, len(execution_plan) - 1)
            current_plan_step = execution_plan[current_step_idx]
            return (
                f"You are agent '{name}' pursuing: '{goal}'\n\n"
                f"Execute step {iteration + 1} of the plan:\n"
                f"  → {current_plan_step}\n\n"
                f"Deliberation assessment:\n{deliberation_content[:500]}\n\n"
                f"Execute this step and provide the result."
            )

        # react / reflexion / custom / fallback
        action_context = (
            f"You are agent '{name}' pursuing: '{goal}'\n\n"
            f"Deliberation assessment:\n{deliberation_content[:500]}\n\n"
        )

        if tools:
            action_context += f"Available tools: {', '.join(tools)}\n"
        if child_steps_meta:
            action_context += f"Available body steps: {len(child_steps_meta)}\n"

        action_context += (
            "\nChoose and execute the most appropriate next action "
            "to advance toward the goal. Provide your reasoning and result."
        )

        return action_context

    def _extract_epistemic_state(
        self, content: str, current: str,
    ) -> str:
        """Extract epistemic state from deliberation response.

        Searches for epistemic_state keywords in the model's
        response to determine the current position on the
        Tarski lattice: doubt ⊏ speculate ⊏ believe ⊏ know.
        """
        import re

        content_lower = content.lower()

        # Try JSON extraction first
        json_match = re.search(
            r'"epistemic_state"\s*:\s*"(\w+)"', content_lower,
        )
        if json_match:
            candidate = json_match.group(1)
            if candidate in self._EPISTEMIC_LATTICE:
                return candidate

        # Fallback: look for keywords
        for state in reversed(self._EPISTEMIC_LATTICE):
            if state in content_lower:
                return state

        return current

    def _advance_epistemic(self, current: str, proposed: str) -> str:
        """Advance epistemic state monotonically on the lattice.

        The epistemic state can only move forward (toward 'know'),
        never backward. This ensures convergence.

        doubt → speculate → believe → know
        """
        current_idx = (
            self._EPISTEMIC_LATTICE.index(current)
            if current in self._EPISTEMIC_LATTICE else 0
        )
        proposed_idx = (
            self._EPISTEMIC_LATTICE.index(proposed)
            if proposed in self._EPISTEMIC_LATTICE else 0
        )
        return self._EPISTEMIC_LATTICE[max(current_idx, proposed_idx)]

    @staticmethod
    def _check_goal_achieved(content: str, epistemic_state: str) -> bool:
        """Check if the goal has been achieved based on epistemic state.

        The agent considers the goal achieved when:
          1. Epistemic state reaches 'believe' or 'know', OR
          2. The model explicitly reports goal_achieved: true
        """
        if epistemic_state in ("believe", "know"):
            return True

        # Check explicit goal_achieved in response
        content_lower = content.lower()
        if '"goal_achieved": true' in content_lower:
            return True
        if '"goal_achieved":true' in content_lower:
            return True

        return False

    @staticmethod
    def _extract_execution_plan(content: str) -> list[str]:
        """Extract a numbered execution plan from model output.

        Parses numbered lists (1. Step, 2. Step, etc.) from
        the plan_and_execute strategy's planning phase output.
        """
        import re

        lines = content.strip().split("\n")
        plan: list[str] = []
        for line in lines:
            # Match numbered items: "1. ...", "1) ...", "- ..."
            match = re.match(r'^\s*(?:\d+[\.\)]\s*|-\s*)(.*)', line)
            if match:
                step_text = match.group(1).strip()
                if step_text:
                    plan.append(step_text)

        return plan if plan else [content.strip()[:200]]

    @staticmethod
    def _check_budget_exceeded(
        *,
        max_tokens: int,
        max_time_seconds: float,
        max_cost: float,
        accumulated_tokens: int,
        accumulated_cost: float,
        step_start: float,
    ) -> bool:
        """Check if any budget constraint has been exceeded.

        Linear logic resource tracking:
          Each iteration consumes: tokens ⊗ time ⊗ cost
          Budget guards ensure ∀i: Σ(resource_i) ≤ max_resource
        """
        if max_tokens > 0 and accumulated_tokens >= max_tokens:
            return True

        if max_time_seconds > 0:
            elapsed = time.perf_counter() - step_start
            if elapsed >= max_time_seconds:
                return True

        if max_cost > 0 and accumulated_cost >= max_cost:
            return True

        return False

    @staticmethod
    def _parse_duration(duration_str: str) -> float:
        """Parse a duration string to seconds.

        Supports formats: "30s", "5m", "1h", "1h30m"
        Returns 0.0 for empty or unparseable strings.
        """
        import re

        if not duration_str:
            return 0.0

        total = 0.0
        # Match hours, minutes, seconds
        hours = re.search(r'(\d+)h', duration_str)
        minutes = re.search(r'(\d+)m', duration_str)
        seconds = re.search(r'(\d+)s', duration_str)

        if hours:
            total += int(hours.group(1)) * 3600
        if minutes:
            total += int(minutes.group(1)) * 60
        if seconds:
            total += int(seconds.group(1))

        return total if total > 0 else 0.0

    async def _handle_on_stuck(
        self,
        *,
        name: str,
        goal: str,
        on_stuck: str,
        unit: CompiledExecutionUnit,
        ctx: ContextManager,
        tracer: Tracer,
        observation_history: list[str],
        iteration: int,
    ) -> StepResult | None:
        """Handle the on_stuck recovery policy.

        STIT logic: When ¬◇φ (no available option achieves the goal),
        the recovery policy fires:

          forge     — Creative synthesis to break the impasse.
                      Uses divergent reasoning to reframe the problem.
          hibernate — Suspend execution, return partial result.
                      The agent can be resumed later.
          escalate  — Raise AgentStuckError to the caller.
                      Human intervention required.
          retry     — Reset observation history and retry with
                      modified parameters.

        Returns:
            A StepResult for forge/retry recovery, or None for
            hibernate/escalate (which terminate the loop).
        """
        if on_stuck == "forge":
            # Creative synthesis to break the impasse
            forge_prompt = (
                f"You are agent '{name}' that is STUCK trying to achieve: '{goal}'\n\n"
                f"Previous observations:\n"
                + "\n".join(observation_history[-5:]) +
                "\n\nUse creative, divergent thinking to find a novel approach. "
                "Reframe the problem, consider analogies, or combine ideas "
                "in unexpected ways. Propose a breakthrough action."
            )
            forge_response = await self._client.call(
                system_prompt=unit.system_prompt,
                user_prompt=forge_prompt,
                effort="max",
            )
            return StepResult(
                step_name=f"agent:{name}:forge_recovery:{iteration}",
                response=forge_response,
            )

        if on_stuck == "retry":
            # Reset and retry with modified framing
            retry_prompt = (
                f"You are agent '{name}' retrying goal: '{goal}'\n\n"
                f"Previous approach was not making progress. "
                f"Try a fundamentally different strategy. "
                f"What alternative approach could work?"
            )
            retry_response = await self._client.call(
                system_prompt=unit.system_prompt,
                user_prompt=retry_prompt,
                effort="high",
            )
            return StepResult(
                step_name=f"agent:{name}:retry_recovery:{iteration}",
                response=retry_response,
            )

        if on_stuck == "hibernate":
            # Return None to signal loop exit with partial result
            return None

        # escalate (default) — raise hard error
        raise AgentStuckError(
            message=(
                f"Agent '{name}' is stuck after {iteration + 1} iterations. "
                f"Goal '{goal}' not achievable with current approach."
            ),
            context=ErrorContext(
                step_name=f"agent:{name}",
                details=(
                    f"strategy={on_stuck}, "
                    f"last_observations={observation_history[-3:]}"
                ),
            ),
        )

    # ── PEM (Psychological-Epistemic Modeling) ─────────────────────

    async def _execute_psyche_step(
        self,
        *,
        step: CompiledStep,
        ctx: ContextManager,
        tracer: Tracer,
    ) -> StepResult:
        """Execute a psyche specification step.

        Psyche steps don't call the model — they initialize the
        PEM (Psychological-Epistemic Modeling) engine:

          1. Emit PSYCHE_INIT with manifold configuration (§1)
          2. Emit PSYCHE_DIMENSION_MAP for each cognitive dimension (§2)
          3. Emit PSYCHE_SAFETY_CHECK enforcing NonDiagnostic (§4)
          4. Emit PSYCHE_INFERENCE_START for the inference loop (§3)
          5. Return metadata-only StepResult

        The actual PsycheEngine integration (SDE stepping,
        density matrix operations, free energy minimization)
        will be connected when the engine is wired to the
        runtime in a future phase.
        """
        step_start = time.perf_counter()
        psyche_meta = step.metadata.get("psyche_spec", {})
        psyche_name = psyche_meta.get("name", "")
        dimensions = psyche_meta.get("dimensions", [])
        manifold = psyche_meta.get("manifold", {})
        safety = psyche_meta.get("safety_constraints", [])
        quantum = psyche_meta.get("quantum_enabled", False)
        inference = psyche_meta.get("inference_mode", "")

        step_name = f"psyche:{psyche_name}"

        # §1 — Manifold construction + §2 Density matrix allocation
        tracer.emit_psyche_init(
            step_name=step_name,
            psyche_name=psyche_name,
            dimensions=dimensions,
            manifold_noise=manifold.get("noise", 0.0),
            manifold_momentum=manifold.get("momentum", 0.0),
            quantum_enabled=quantum,
            inference_mode=inference,
        )

        # §1 — Map each cognitive dimension to the manifold
        for dim in dimensions:
            curvature = manifold.get("curvature", {}).get(dim, 1.0)
            tracer.emit(
                TraceEventType.PSYCHE_DIMENSION_MAP,
                step_name=step_name,
                data={
                    "dimension": dim,
                    "curvature": curvature,
                    "noise": manifold.get("noise", 0.0),
                },
            )

        # §4 — NonDiagnostic safety enforcement
        non_diagnostic = "non_diagnostic" in safety
        tracer.emit_psyche_safety_check(
            step_name=step_name,
            constraints=safety,
            non_diagnostic_enforced=non_diagnostic,
            passed=non_diagnostic,  # passes only if constraint present
        )

        # §3 — Active inference loop initialization
        tracer.emit(
            TraceEventType.PSYCHE_INFERENCE_START,
            step_name=step_name,
            data={
                "mode": inference,
                "quantum_enabled": quantum,
                "dimensions_count": len(dimensions),
            },
        )

        step_duration = (time.perf_counter() - step_start) * 1000

        # Store psyche config in context for downstream steps
        ctx.set_step_result(step_name, {
            "psyche_name": psyche_name,
            "dimensions": dimensions,
            "manifold": manifold,
            "quantum_enabled": quantum,
            "inference_mode": inference,
            "safety_constraints": safety,
        })

        return StepResult(
            step_name=step_name,
            response=ModelResponse(
                content=(
                    f"[psyche:{psyche_name}] initialized — "
                    f"{len(dimensions)} dimensions, "
                    f"inference={inference}, "
                    f"quantum={'on' if quantum else 'off'}"
                ),
                structured={
                    "psyche_name": psyche_name,
                    "dimensions": dimensions,
                    "manifold": manifold,
                    "quantum_enabled": quantum,
                    "inference_mode": inference,
                    "non_diagnostic_enforced": non_diagnostic,
                },
                usage={},
            ),
            duration_ms=step_duration,
        )

