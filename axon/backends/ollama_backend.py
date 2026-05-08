"""AXON Backends — Ollama (Local) Backend.

Compiles AXON IR into prompt structures for a local Ollama server
(default ``http://localhost:11434``). Ollama exposes an OpenAI-compatible
Chat Completions endpoint at ``/v1/chat/completions`` (in addition to
its legacy native ``/api/chat``), so the heavy compilation work is
shared with the other OpenAI-shape backends via
:class:`OpenAICompatibleBackend`.

Strengths:
  - Fully on-prem / offline (no network egress, no API costs)
  - Any Ollama-pulled model: ``llama3``, ``mistral``, ``qwen``, ``phi3``,
    ``gemma``, custom Modelfiles, etc.
  - Privacy-sensitive workloads where data cannot leave the host
  - Development without API budget concerns

Auth: none (local). The transport layer must point at the Ollama
endpoint; the typical environment variable is ``AXON_OLLAMA_BASE_URL``
(default ``http://localhost:11434/v1``).

Tool-call caveat: not every Ollama model supports function calling.
Modern ``llama3.1+``, ``mistral-large``, and ``qwen2.5`` do; older
``llama3.0`` does not. Adopters running tool-using flows against
non-tool-capable models will see the model ignore tool declarations.
This is a model-capability concern, not a compilation concern — the
compiled output is identical; the runtime behaviour varies. Document
explicitly so adopters pin tool-capable models.
"""

from __future__ import annotations

from axon.backends._openai_compatible import OpenAICompatibleBackend


class OllamaBackend(OpenAICompatibleBackend):
    """Ollama local backend.

    Inherits all compilation logic from :class:`OpenAICompatibleBackend`
    — Ollama's ``/v1/chat/completions`` endpoint is byte-compatible with
    OpenAI's. The transport layer dispatches the same compiled output
    to the local Ollama base URL instead of a cloud endpoint.
    """

    @property
    def name(self) -> str:
        return "ollama"
