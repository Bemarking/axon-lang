"""
AXON Backends — Ollama Backend (Stub)
=======================================
Placeholder for the Ollama local-model prompt compiler.

This backend will compile AXON IR into structures compatible with
the Ollama API for running local LLMs:
  - System/user message formatting for local models
  - Simplified tool calling (when model supports it)
  - Adaptation for smaller context windows
  - Quantization-aware prompt simplification

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


class OllamaBackend(BaseBackend):
    """
    Stub implementation for the Ollama backend.

    All methods raise NotImplementedError with guidance on
    what Phase 2 expansion should implement.
    """

    @property
    def name(self) -> str:
        return "ollama"

    def compile_step(
        self, step: IRNode, context: CompilationContext
    ) -> CompiledStep:
        raise NotImplementedError(
            "Ollama backend is not yet implemented. "
            "Scheduled for Phase 2 expansion. "
            "Should adapt prompts for local models with smaller "
            "context windows and optional tool support."
        )

    def compile_system_prompt(
        self,
        persona: IRPersona | None,
        context: IRContext | None,
        anchors: list[IRAnchor],
    ) -> str:
        raise NotImplementedError(
            "Ollama system prompt compilation is not yet implemented. "
            "Should produce simplified system prompts suitable for "
            "local models (Llama, Mistral, etc.)."
        )

    def compile_tool_spec(self, tool: IRToolSpec) -> dict[str, Any]:
        raise NotImplementedError(
            "Ollama tool spec compilation is not yet implemented. "
            "Should produce Ollama-compatible tool format or gracefully "
            "degrade for models without tool support."
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
            "Ollama agent system prompt is not yet implemented. "
            "Should produce simplified BDI-cycle instructions suitable "
            "for local models (Llama, Mistral, etc.) with smaller "
            "context windows."
        )
