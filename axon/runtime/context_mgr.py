"""
AXON Runtime — Context Manager
================================
Maintains mutable execution state that flows between steps
within a single execution unit.

The ContextManager is the working memory of a running AXON program.
It tracks:
    - Step results: named outputs from completed steps
    - Message history: the multi-turn conversation with the model
    - Flow parameters: input arguments passed to the flow
    - System prompt: the compiled persona + anchor instructions

Every mutation is traced through the Tracer for full observability.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from axon.runtime.tracer import Tracer


# ═══════════════════════════════════════════════════════════════════
#  MESSAGE ROLE — typed conversation roles
# ═══════════════════════════════════════════════════════════════════

ROLE_SYSTEM = "system"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
VALID_ROLES = frozenset({ROLE_SYSTEM, ROLE_USER, ROLE_ASSISTANT})


# ═══════════════════════════════════════════════════════════════════
#  CONTEXT SNAPSHOT — immutable state capture
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ContextSnapshot:
    """An immutable point-in-time capture of execution state.

    Used by the Tracer and debugging tools to record the exact
    state of the context at any moment during execution.

    Attributes:
        step_results:     Copy of all step name → result mappings.
        message_count:    Number of messages in the conversation.
        variables:        Copy of all flow parameter bindings.
        current_step:     Name of the step being executed (if any).
    """

    step_results: dict[str, Any] = field(default_factory=dict)
    message_count: int = 0
    variables: dict[str, Any] = field(default_factory=dict)
    current_step: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        result: dict[str, Any] = {
            "step_results": {
                k: repr(v) for k, v in self.step_results.items()
            },
            "message_count": self.message_count,
        }
        if self.variables:
            result["variables"] = {
                k: repr(v) for k, v in self.variables.items()
            }
        if self.current_step:
            result["current_step"] = self.current_step
        return result


# ═══════════════════════════════════════════════════════════════════
#  CONTEXT MANAGER — mutable execution state
# ═══════════════════════════════════════════════════════════════════


class ContextManager:
    """Maintains execution state between steps in a flow.

    The ContextManager is scoped to a single ``CompiledExecutionUnit``
    (one ``run`` statement). Each run gets its own context.

    Usage::

        ctx = ContextManager(system_prompt="You are LegalExpert.", tracer=tracer)
        ctx.set_variable("document", contract_text)
        ctx.append_message("user", "Analyze this contract.")
        ctx.append_message("assistant", "The contract contains...")
        ctx.set_step_result("analyze", {"clauses": [...]})
        result = ctx.get_step_result("analyze")
        snapshot = ctx.snapshot()
    """

    def __init__(
        self,
        system_prompt: str = "",
        tracer: Tracer | None = None,
    ) -> None:
        self._system_prompt = system_prompt
        self._tracer = tracer
        self._step_results: dict[str, Any] = {}
        self._variables: dict[str, Any] = {}
        self._messages: list[dict[str, str]] = []
        self._current_step: str = ""
        # ── Fase 13.i — typed-channel runtime integration ──
        # The Executor injects a TypedEventBus per-unit so emit/publish/
        # discover steps can dispatch through it. `_capabilities` indexes
        # the capability tokens published during this unit, keyed by the
        # channel name they expose so a downstream `discover ChannelName
        # as alias` can find them. `_discovered_handles` records the
        # alias bindings that resulted from `discover` so subsequent
        # references to the alias resolve to the live handle.
        self._typed_bus: Any = None  # TypedEventBus | None — Any to avoid import cycle
        self._capabilities: dict[str, Any] = {}      # channel_name → Capability
        self._discovered_handles: dict[str, Any] = {}  # alias → TypedChannelHandle

    # — System prompt —

    @property
    def system_prompt(self) -> str:
        """The compiled system prompt for this execution unit."""
        return self._system_prompt

    # — Step state tracking —

    @property
    def current_step(self) -> str:
        """The name of the step currently being executed."""
        return self._current_step

    @current_step.setter
    def current_step(self, name: str) -> None:
        """Set the current step being executed."""
        self._current_step = name

    def set_step_result(self, step_name: str, result: Any) -> None:
        """Record the output of a completed step.

        Args:
            step_name:  The name of the step that produced the result.
            result:     The step's output value.

        Raises:
            ValueError: If ``step_name`` is empty.
        """
        if not step_name:
            raise ValueError("step_name must not be empty")

        self._step_results[step_name] = result

    def get_step_result(self, step_name: str) -> Any:
        """Retrieve the output of a previously completed step.

        Args:
            step_name:  The name of the step whose result is needed.

        Returns:
            The step's output value.

        Raises:
            KeyError: If the step has not completed yet.
        """
        if step_name not in self._step_results:
            raise KeyError(
                f"Step '{step_name}' has no result. "
                f"Available: {list(self._step_results.keys())}"
            )
        return self._step_results[step_name]

    def has_step_result(self, step_name: str) -> bool:
        """Check whether a step has a recorded result."""
        return step_name in self._step_results

    @property
    def completed_steps(self) -> list[str]:
        """Names of all steps that have recorded results, in insertion order."""
        return list(self._step_results.keys())

    def resolve_value_ref(self, value_ref: str) -> Any:
        """Resolve an `emit` value_ref against the live execution state
        (Fase 13.i).

        The parser's `_parse_emit_value_ref` accepts two shapes:
          - bare identifier (e.g. ``payload``)            → variable / step / discovered handle
          - dotted access  (e.g. ``Build.output.score``)  → step result + nested attribute walk

        Resolution order for the head segment:
          1. discovered channel handle (alias bound by ``discover X as alias``)
          2. flow variable (``ctx.set_variable``)
          3. step result (``ctx.set_step_result``)

        For dotted paths, the head is resolved by the same lookup; subsequent
        segments walk attribute / mapping access on the result. ``KeyError``
        is raised on miss with a deterministic message that lists the
        candidates the executor saw, so failures are debuggable from the
        trace alone.
        """
        if not value_ref:
            raise KeyError("resolve_value_ref called with empty value_ref")

        parts = value_ref.split(".")
        head = parts[0]

        # 1) discovered handle wins — the binding `discover C as alias` is
        # the only mechanism that introduces a TypedChannelHandle into the
        # local scope, and shadowing a variable with a discovered handle is
        # legal per paper §3.4.
        if head in self._discovered_handles:
            current: Any = self._discovered_handles[head]
        elif head in self._variables:
            current = self._variables[head]
        elif head in self._step_results:
            current = self._step_results[head]
        else:
            raise KeyError(
                f"value_ref '{value_ref}' — head segment '{head}' is not a "
                f"variable, step result, or discovered handle. "
                f"Variables: {list(self._variables.keys())}; "
                f"Step results: {list(self._step_results.keys())}; "
                f"Discovered handles: {list(self._discovered_handles.keys())}"
            )

        # Walk the remaining segments. Each segment is tried first as a
        # mapping key (most step results are dicts) then as an attribute
        # (dataclass / object instances). This matches the dual nature of
        # AXON step outputs: model responses are dicts, while computed /
        # tool steps may return typed objects.
        for segment in parts[1:]:
            if isinstance(current, dict) and segment in current:
                current = current[segment]
            elif hasattr(current, segment):
                current = getattr(current, segment)
            else:
                raise KeyError(
                    f"value_ref '{value_ref}' — cannot resolve '{segment}' on "
                    f"intermediate value of type {type(current).__name__}"
                )
        return current

    # — Typed-channel runtime integration (Fase 13.i) —

    @property
    def typed_bus(self) -> Any:
        """The TypedEventBus injected by the Executor for this unit.

        ``None`` until the Executor calls :meth:`set_typed_bus`. Returning
        ``Any`` keeps the import graph acyclic — ContextManager has no
        runtime dependency on ``axon.runtime.channels.typed``.
        """
        return self._typed_bus

    def set_typed_bus(self, bus: Any) -> None:
        """Bind the per-unit TypedEventBus. Called once by ``Executor._execute_unit``."""
        self._typed_bus = bus

    def record_capability(self, channel_name: str, capability: Any) -> None:
        """Stash a capability token returned by ``publish`` so a downstream
        ``discover`` step in the same unit can consume it."""
        self._capabilities[channel_name] = capability

    def take_capability(self, channel_name: str) -> Any:
        """Pop a previously-recorded capability for the given channel.

        One-shot semantics — capabilities are consumed by the first
        ``discover`` that asks for them, mirroring the bus-level
        ``Capability`` lifecycle (issued once → discovered once).

        Raises ``KeyError`` if no capability has been published for that
        channel in the current unit.
        """
        if channel_name not in self._capabilities:
            raise KeyError(
                f"No capability recorded for channel '{channel_name}'. "
                f"Did a `publish {channel_name} within Shield` step run "
                f"earlier in this unit? Recorded: "
                f"{list(self._capabilities.keys())}"
            )
        return self._capabilities.pop(channel_name)

    def bind_discovered_handle(self, alias: str, handle: Any) -> None:
        """Register a TypedChannelHandle under the alias produced by
        ``discover ChannelName as alias`` so subsequent ``emit alias(...)``
        or value_ref lookups resolve to the live handle."""
        if not alias:
            raise ValueError("alias must not be empty")
        self._discovered_handles[alias] = handle

    @property
    def discovered_handles(self) -> dict[str, Any]:
        """Snapshot of the alias → handle bindings (read-only view)."""
        return dict(self._discovered_handles)

    # — Variable bindings (flow parameters & intermediate values) —

    def set_variable(self, name: str, value: Any) -> None:
        """Bind a named variable in the execution context.

        Args:
            name:   The variable name.
            value:  The variable's value.

        Raises:
            ValueError: If ``name`` is empty.
        """
        if not name:
            raise ValueError("Variable name must not be empty")

        self._variables[name] = value

    def get_variable(self, name: str) -> Any:
        """Retrieve a named variable from the execution context.

        Args:
            name:  The variable name.

        Returns:
            The variable's value.

        Raises:
            KeyError: If the variable has not been set.
        """
        if name not in self._variables:
            raise KeyError(
                f"Variable '{name}' is not defined. "
                f"Available: {list(self._variables.keys())}"
            )
        return self._variables[name]

    def has_variable(self, name: str) -> bool:
        """Check whether a named variable exists."""
        return name in self._variables

    def get_variables(self) -> dict[str, Any]:
        """Return a shallow copy of all variable bindings."""
        return dict(self._variables)

    # — Message history (multi-turn conversation) —

    def append_message(self, role: str, content: str) -> None:
        """Add a message to the conversation history.

        Args:
            role:     One of ``"system"``, ``"user"``, ``"assistant"``.
            content:  The message content.

        Raises:
            ValueError: If ``role`` is not a valid conversation role.
            ValueError: If ``content`` is empty.
        """
        if role not in VALID_ROLES:
            raise ValueError(
                f"Invalid role '{role}'. Must be one of: {sorted(VALID_ROLES)}"
            )
        if not content:
            raise ValueError("Message content must not be empty")

        self._messages.append({"role": role, "content": content})

    def get_message_history(self) -> list[dict[str, str]]:
        """Return a copy of the full message history."""
        return list(self._messages)

    @property
    def message_count(self) -> int:
        """The number of messages in the conversation history."""
        return len(self._messages)

    def clear_messages(self) -> None:
        """Clear the entire message history."""
        self._messages.clear()

    # — Snapshot (immutable state capture) —

    def snapshot(self) -> ContextSnapshot:
        """Capture an immutable snapshot of the current execution state.

        The snapshot deep-copies step results and variables to prevent
        mutations from affecting the captured state.

        Returns:
            An immutable ``ContextSnapshot`` representing the current state.
        """
        return ContextSnapshot(
            step_results=copy.deepcopy(self._step_results),
            message_count=self.message_count,
            variables=copy.deepcopy(self._variables),
            current_step=self._current_step,
        )

    # — Reset —

    def reset(self) -> None:
        """Clear all state, returning the context to its initial condition.

        The system prompt is preserved; everything else is cleared.
        """
        self._step_results.clear()
        self._variables.clear()
        self._messages.clear()
        self._current_step = ""
