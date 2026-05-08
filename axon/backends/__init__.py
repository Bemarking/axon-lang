# AXON Backends — Model-specific prompt compilers
# IR → Backend-specific prompt structures
#
# Each backend implements BaseBackend to compile AXON IR into
# provider-native formats (Anthropic, Gemini, OpenAI Chat
# Completions-compatible providers, etc.).
#
# Two compilation lineages:
#
#   - Anthropic Messages API  → AnthropicBackend (system field outside
#     messages array, input_schema for tool definitions, native
#     thinking blocks).
#   - Gemini generateContent  → GeminiBackend (systemInstruction +
#     contents array, function_declarations for tools).
#   - OpenAI Chat Completions → OpenAIBackend, KimiBackend,
#     OllamaBackend, GlmBackend, OpenRouterBackend (all share the
#     ``_openai_compatible.OpenAICompatibleBackend`` base — same
#     request/response shape, only base URL + auth differ).

from .base_backend import (
    BaseBackend,
    CompiledProgram,
    CompiledExecutionUnit,
    CompiledStep,
    CompilationContext,
)
from .anthropic_backend import AnthropicBackend
from .gemini_backend import GeminiBackend
from .openai_backend import OpenAIBackend
from .ollama_backend import OllamaBackend
from .kimi_backend import KimiBackend
from .glm_backend import GlmBackend
from .openrouter_backend import OpenRouterBackend

# Backend registry — maps canonical names to backend classes.
# Every entry MUST be a fully-implemented backend (no NotImplementedError
# stubs). The drift gate in tests/test_backend_registry_drift_gate.py
# enforces this; pre-Fase-22 the registry advertised openai + ollama as
# stubs that crashed at runtime — never again.
BACKEND_REGISTRY: dict[str, type[BaseBackend]] = {
    "anthropic": AnthropicBackend,
    "gemini": GeminiBackend,
    "openai": OpenAIBackend,
    "ollama": OllamaBackend,
    "kimi": KimiBackend,
    "glm": GlmBackend,
    "openrouter": OpenRouterBackend,
}


def get_backend(name: str) -> BaseBackend:
    """
    Get a backend instance by canonical name.

    Raises:
        ValueError: If the backend name is not recognized.
    """
    if name not in BACKEND_REGISTRY:
        available = ", ".join(sorted(BACKEND_REGISTRY.keys()))
        raise ValueError(
            f"Unknown backend '{name}'. Available: {available}"
        )
    return BACKEND_REGISTRY[name]()
