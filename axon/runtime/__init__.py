"""
AXON Runtime Package
=====================
The execution engine for compiled AXON programs.

This package provides all components needed to execute AXON
programs against LLM model clients:

    Executor          — Program execution orchestrator
    ModelClient        — Protocol for LLM interaction
    ModelResponse      — Normalized model output
    ExecutionResult    — Complete program execution result
    ContextManager     — Mutable execution state
    SemanticValidator  — Type contract enforcement
    RetryEngine        — Adaptive retry with backoff
    MemoryBackend      — Abstract semantic memory storage
    InMemoryBackend    — Dict-based memory implementation
    Tracer             — Semantic execution trace recorder

Usage::

    from axon.runtime import Executor, ModelResponse

    class MyClient:
        async def call(self, system_prompt, user_prompt, **kw):
            ...  # call your LLM
            return ModelResponse(content="...")

    executor = Executor(client=MyClient())
    result = await executor.execute(compiled_program)
"""

from axon.runtime.context_mgr import ContextManager, ContextSnapshot
from axon.runtime.executor import (
    DaemonResult,
    ExecutionResult,
    Executor,
    ModelClient,
    ModelResponse,
    StepResult,
    UnitResult,
)
from axon.runtime.memory_backend import (
    InMemoryBackend,
    MemoryBackend,
    MemoryEntry,
)
from axon.runtime.retry_engine import (
    AttemptRecord,
    RefineConfig,
    RetryEngine,
    RetryResult,
)
from axon.runtime.runtime_errors import (
    AnchorBreachError,
    AxonRuntimeError,
    ConfidenceError,
    ErrorContext,
    ExecutionTimeoutError,
    MandateViolationError,
    ModelCallError,
    RefineExhaustedError,
    ValidationError,
)
from axon.runtime.semantic_validator import (
    SemanticValidator,
    ValidationResult,
    Violation,
)
from axon.runtime.tools import (
    BaseTool,
    RuntimeToolRegistry,
    ToolDispatcher,
    ToolResult,
    create_default_registry,
)
from axon.runtime.tracer import (
    ExecutionTrace,
    TraceEvent,
    TraceEventType,
    TraceSpan,
    Tracer,
)

__all__ = [
    # Executor & Protocol
    "Executor",
    "ModelClient",
    "ModelResponse",
    "ExecutionResult",
    "StepResult",
    "UnitResult",
    "DaemonResult",
    # Context
    "ContextManager",
    "ContextSnapshot",
    # Validation
    "SemanticValidator",
    "ValidationResult",
    "Violation",
    # Retry
    "RetryEngine",
    "RefineConfig",
    "RetryResult",
    "AttemptRecord",
    # Memory
    "MemoryBackend",
    "InMemoryBackend",
    "MemoryEntry",
    # Tools
    "BaseTool",
    "ToolResult",
    "RuntimeToolRegistry",
    "ToolDispatcher",
    "create_default_registry",
    # Tracing
    "Tracer",
    "TraceEvent",
    "TraceEventType",
    "TraceSpan",
    "ExecutionTrace",
    # Errors
    "AxonRuntimeError",
    "ValidationError",
    "ConfidenceError",
    "AnchorBreachError",
    "RefineExhaustedError",
    "MandateViolationError",
    "ModelCallError",
    "ExecutionTimeoutError",
    "ErrorContext",
]
