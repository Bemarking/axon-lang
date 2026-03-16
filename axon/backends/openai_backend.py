"""
AXON Backends — OpenAI Backend (Stub)
=======================================
Placeholder for the OpenAI/ChatGPT prompt compiler.

This backend will compile AXON IR into structures compatible with
the OpenAI Chat Completions API:
  - system/user/assistant message roles
  - function_call / tool_call declarations
  - JSON mode for structured output

Status: NOT YET IMPLEMENTED — scheduled for Phase 2 expansion.
"""

from __future__ import annotations

from typing import Any

from axon.compiler.ir_nodes import (
    IRAnchor,
    IRContext,
    IRNode,
    IRPersona,
    IRToolSpec,
)
from axon.backends.base_backend import (
    BaseBackend,
    CompiledStep,
    CompilationContext,
)


class OpenAIBackend(BaseBackend):
    """
    Stub implementation for the OpenAI backend.

    All methods raise NotImplementedError with guidance on
    what Phase 2 expansion should implement.
    """

    @property
    def name(self) -> str:
        return "openai"

    def compile_step(
        self, step: IRNode, context: CompilationContext
    ) -> CompiledStep:
        raise NotImplementedError(
            "OpenAI backend is not yet implemented. "
            "Scheduled for Phase 2 expansion. "
            "See: anthropic_backend.py for reference implementation."
        )

    def compile_system_prompt(
        self,
        persona: IRPersona | None,
        context: IRContext | None,
        anchors: list[IRAnchor],
    ) -> str:
        raise NotImplementedError(
            "OpenAI system prompt compilation is not yet implemented. "
            "Should produce OpenAI Chat Completions 'system' role content."
        )

    def compile_tool_spec(self, tool: IRToolSpec) -> dict[str, Any]:
        raise NotImplementedError(
            "OpenAI tool spec compilation is not yet implemented. "
            "Should produce OpenAI function_call / tool_call format."
        )

    def compile_agent_system_prompt(
        self,
        agent_name: str,
        goal: str,
        strategy: str,
        tools: list[str],
        epistemic_state: str,
        iteration: int,
        max_iterations: int,
    ) -> str:
        raise NotImplementedError(
            "OpenAI agent system prompt is not yet implemented. "
            "Should produce BDI-cycle system instructions for GPT. "
            "See: anthropic_backend.py for reference implementation."
        )
