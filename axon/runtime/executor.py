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
from axon.runtime.memory_backend import InMemoryBackend, MemoryBackend
from axon.runtime.retry_engine import RefineConfig, RetryEngine, RetryResult
from axon.runtime.runtime_errors import (
    AnchorBreachError,
    AxonRuntimeError,
    ErrorContext,
    ExecutionTimeoutError,
    ModelCallError,
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
