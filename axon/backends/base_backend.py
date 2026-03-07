"""
AXON Backends — Abstract Base Backend
=======================================
Defines the interface that every model-specific backend must implement.

A backend's job is to take model-agnostic AXON IR and produce
provider-specific prompt structures ready for execution.

The separation is intentional:
  - IR Generator produces WHAT to do (model-agnostic)
  - Backend produces HOW to say it (model-specific)
  - Runtime (Phase 3) will EXECUTE it

Design decisions:
  1. compile_program() produces the full compiled output.
  2. compile_step() handles individual step compilation with context.
  3. compile_system_prompt() builds the system prompt from persona + anchors.
  4. compile_tool_spec() produces provider-native tool declarations.
  5. CompilationContext carries state between step compilations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from axon.compiler.ir_nodes import (
    IRAnchor,
    IRAggregate,
    IRAssociate,
    IRContext,
    IRDataSpace,
    IRExplore,
    IRFlow,
    IRFocus,
    IRIngest,
    IRNode,
    IRPersona,
    IRProgram,
    IRRun,
    IRStep,
    IRToolSpec,
)

# IR types that represent Data Science operations
_DATA_SCIENCE_IR_TYPES = (IRDataSpace, IRIngest, IRFocus, IRAssociate, IRAggregate, IRExplore)


# ═══════════════════════════════════════════════════════════════════
#  COMPILATION OUTPUT CONTAINERS
# ═══════════════════════════════════════════════════════════════════

@dataclass
class CompiledStep:
    """
    The compilation result for a single cognitive step.

    Contains the prompt(s) to send to the model, any tool
    declarations needed, and output format expectations.
    """
    step_name: str = ""
    system_prompt: str = ""
    user_prompt: str = ""
    tool_declarations: list[dict[str, Any]] = field(default_factory=list)
    output_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        result: dict[str, Any] = {
            "step_name": self.step_name,
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
        }
        if self.tool_declarations:
            result["tool_declarations"] = self.tool_declarations
        if self.output_schema:
            result["output_schema"] = self.output_schema
        if self.metadata:
            result["metadata"] = self.metadata
        return result


@dataclass
class CompiledProgram:
    """
    The complete compilation output for an AXON program.

    Contains all compiled execution units (one per run statement),
    plus global metadata about the compilation.
    """
    backend_name: str = ""
    execution_units: list[CompiledExecutionUnit] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "backend_name": self.backend_name,
            "execution_units": [u.to_dict() for u in self.execution_units],
            "metadata": self.metadata,
        }


@dataclass
class CompiledExecutionUnit:
    """
    A single execution unit — one run statement fully compiled.

    Contains the system prompt (persona + anchors), the ordered
    step prompts, and all tool declarations needed.
    """
    flow_name: str = ""
    persona_name: str = ""
    context_name: str = ""
    system_prompt: str = ""
    steps: list[CompiledStep] = field(default_factory=list)
    tool_declarations: list[dict[str, Any]] = field(default_factory=list)
    anchor_instructions: list[str] = field(default_factory=list)
    active_anchors: list[dict[str, Any]] = field(default_factory=list)
    effort: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        result: dict[str, Any] = {
            "flow_name": self.flow_name,
            "system_prompt": self.system_prompt,
            "steps": [s.to_dict() for s in self.steps],
        }
        if self.persona_name:
            result["persona_name"] = self.persona_name
        if self.context_name:
            result["context_name"] = self.context_name
        if self.tool_declarations:
            result["tool_declarations"] = self.tool_declarations
        if self.anchor_instructions:
            result["anchor_instructions"] = self.anchor_instructions
        if self.active_anchors:
            result["active_anchors"] = self.active_anchors
        if self.effort:
            result["effort"] = self.effort
        if self.metadata:
            result["metadata"] = self.metadata
        return result


@dataclass
class CompilationContext:
    """
    Carries state through the step compilation process.

    Backends use this to track the current persona, active anchors,
    available tools, and any accumulated context from prior steps.
    """
    persona: IRPersona | None = None
    context: IRContext | None = None
    anchors: list[IRAnchor] = field(default_factory=list)
    tools: dict[str, IRToolSpec] = field(default_factory=dict)
    flow: IRFlow | None = None
    prior_step_names: list[str] = field(default_factory=list)
    effort: str = ""


# ═══════════════════════════════════════════════════════════════════
#  ABSTRACT BASE BACKEND
# ═══════════════════════════════════════════════════════════════════

class BaseBackend(ABC):
    """
    Abstract base class for all AXON model backends.

    Every backend must implement these four methods to compile
    AXON IR into provider-specific prompt structures.

    The default compile_program() implementation handles the
    orchestration logic (iterating runs, building context),
    delegating model-specific work to the abstract methods.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The canonical name of this backend (e.g., 'anthropic')."""
        ...

    def compile_program(self, ir: IRProgram) -> CompiledProgram:
        """
        Compile a complete IR program into backend-specific output.

        The default implementation iterates over all run statements,
        resolves their dependencies, and delegates step compilation
        to the abstract methods. Subclasses may override for custom
        orchestration.
        """
        # Build tool lookup from program-level declarations
        tools = {tool.name: tool for tool in ir.tools}

        execution_units: list[CompiledExecutionUnit] = []

        for run in ir.runs:
            if run.resolved_flow is None:
                continue  # unresolved run — skip (should not happen post-IR gen)

            # Build compilation context for this run
            ctx = CompilationContext(
                persona=run.resolved_persona,
                context=run.resolved_context,
                anchors=list(run.resolved_anchors),
                tools=tools,
                flow=run.resolved_flow,
                effort=run.effort,
            )

            # Phase 1: Compile system prompt (persona + anchors)
            system_prompt = self.compile_system_prompt(
                persona=run.resolved_persona,
                context=run.resolved_context,
                anchors=list(run.resolved_anchors),
            )

            # Phase 2: Compile anchor enforcement instructions
            anchor_instructions = [
                self.compile_anchor_instruction(anchor)
                for anchor in run.resolved_anchors
            ]

            # Phase 3: Compile tool declarations
            tool_declarations = [
                self.compile_tool_spec(tools[name])
                for name in tools
                if name in tools
            ]

            # Phase 4: Compile each step in the flow
            compiled_steps: list[CompiledStep] = []
            for step in run.resolved_flow.steps:
                # Data Science IR nodes bypass the model — compile as
                # metadata-only steps that the executor routes to the
                # DataScienceDispatcher.
                if isinstance(step, _DATA_SCIENCE_IR_TYPES):
                    ds_step = self._compile_data_science_step(step)
                    compiled_steps.append(ds_step)
                else:
                    compiled = self.compile_step(step, ctx)
                    compiled_steps.append(compiled)
                ctx.prior_step_names.append(
                    step.name if isinstance(step, IRStep) else ""
                )

            active_anchors = [
                {"name": anchor.name, "require": anchor.require, "reject": anchor.reject}
                for anchor in run.resolved_anchors
            ]

            unit = CompiledExecutionUnit(
                flow_name=run.flow_name,
                persona_name=run.persona_name,
                context_name=run.context_name,
                system_prompt=system_prompt,
                steps=compiled_steps,
                tool_declarations=tool_declarations,
                anchor_instructions=anchor_instructions,
                active_anchors=active_anchors,
                effort=run.effort,
            )
            execution_units.append(unit)

        return CompiledProgram(
            backend_name=self.name,
            execution_units=execution_units,
        )

    @staticmethod
    def _compile_data_science_step(step: IRNode) -> CompiledStep:
        """Compile a Data Science IR node into a metadata-only step.

        These steps bypass the model — the executor routes them
        directly to the ``DataScienceDispatcher``.
        """
        from axon.compiler.ir_nodes import (
            IRAggregate,
            IRAssociate,
            IRDataSpace,
            IRExplore,
            IRFocus,
            IRIngest,
        )

        op: str = "unknown"
        args: dict[str, Any] = {}

        match step:
            case IRDataSpace(name=name):
                op = "dataspace"
                args = {"name": name}
            case IRIngest(source=src, target=tgt):
                op = "ingest"
                args = {"source": src, "target": tgt}
            case IRFocus(expression=expr):
                op = "focus"
                args = {"expression": expr}
            case IRAssociate(left=l, right=r, using_field=f):
                op = "associate"
                args = {"left": l, "right": r, "using_field": f}
            case IRAggregate(target=tgt, group_by=gb, alias=alias):
                op = "aggregate"
                args = {"target": tgt, "group_by": list(gb), "alias": alias}
            case IRExplore(target=tgt, limit=lim):
                op = "explore"
                args = {"target": tgt, "limit": lim}

        return CompiledStep(
            step_name=f"ds:{op}",
            user_prompt="",
            metadata={
                "data_science": {
                    "operation": op,
                    "args": args,
                },
            },
        )

    @abstractmethod
    def compile_step(
        self, step: IRNode, context: CompilationContext
    ) -> CompiledStep:
        """
        Compile a single IR step into a backend-specific prompt.

        Args:
            step: The IR node to compile (IRStep, IRProbe, etc.)
            context: The current compilation context.

        Returns:
            A CompiledStep with model-specific prompts.
        """
        ...

    @abstractmethod
    def compile_system_prompt(
        self,
        persona: IRPersona | None,
        context: IRContext | None,
        anchors: list[IRAnchor],
    ) -> str:
        """
        Build the system prompt from persona, context, and anchors.

        This is the Anchor Enforcer's injection point: all hard
        constraints are woven into the system-level instructions
        that the model receives before any user messages.
        """
        ...

    @abstractmethod
    def compile_tool_spec(self, tool: IRToolSpec) -> dict[str, Any]:
        """
        Compile a tool specification into the backend's native format.

        E.g., for Anthropic: {"name": ..., "description": ..., "input_schema": ...}
        E.g., for Gemini: {"function_declarations": [...]}
        """
        ...

    def compile_anchor_instruction(self, anchor: IRAnchor) -> str:
        """
        Compile a single anchor into a natural-language enforcement
        instruction for inclusion in the system prompt.

        The default implementation produces a structured constraint
        block. Backends may override for provider-specific formatting.
        """
        parts: list[str] = [f"[CONSTRAINT: {anchor.name}]"]

        if anchor.require:
            parts.append(f"  REQUIRE: {anchor.require}")
        if anchor.reject:
            parts.append(f"  REJECT: {', '.join(anchor.reject)}")
        if anchor.enforce:
            parts.append(f"  ENFORCE: {anchor.enforce}")
        if anchor.confidence_floor is not None:
            parts.append(
                f"  CONFIDENCE FLOOR: {anchor.confidence_floor}"
            )
        if anchor.unknown_response:
            parts.append(
                f"  WHEN UNCERTAIN: \"{anchor.unknown_response}\""
            )
        if anchor.on_violation:
            violation = anchor.on_violation
            if anchor.on_violation_target:
                violation += f" {anchor.on_violation_target}"
            parts.append(f"  ON VIOLATION: {violation}")

        return "\n".join(parts)
