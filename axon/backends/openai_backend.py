"""AXON Backends — OpenAI (ChatGPT / GPT-4 / o1) Backend.

Compiles AXON IR into prompt structures for OpenAI's Chat Completions
API (``https://api.openai.com/v1``). Supports the full GPT-4o / GPT-4.1
/ o1 / o3-mini family.

Pre-v1.16.0 this module was an 85-LOC stub raising ``NotImplementedError``
on every call — it advertised support in ``BACKEND_REGISTRY`` but
crashed at runtime. v1.16.0 promotes it to a real implementation
inheriting :class:`OpenAICompatibleBackend` (which is itself modeled on
this exact API shape — OpenAI is the canonical reference).

Strengths:
  - Mature function calling + parallel tool use
  - Native JSON mode + structured outputs (schema-validated)
  - Reasoning models (o1, o3-mini) for chain-of-thought workloads
  - Largest ecosystem of compatible tooling

Auth: Bearer API key via ``AXON_OPENAI_API_KEY`` environment variable.
Default base URL: ``https://api.openai.com/v1``.
"""

from __future__ import annotations

from axon.backends._openai_compatible import OpenAICompatibleBackend


class OpenAIBackend(OpenAICompatibleBackend):
    """OpenAI Chat Completions backend.

    Inherits all compilation logic from :class:`OpenAICompatibleBackend`
    — that base class IS the OpenAI Chat Completions reference shape;
    every other ``*-compatible`` provider differs only in transport
    (URL + auth), not in compiled output.
    """

    @property
    def name(self) -> str:
        return "openai"
