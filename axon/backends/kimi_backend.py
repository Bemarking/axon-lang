"""AXON Backends — Kimi (Moonshot AI) Backend.

Compiles AXON IR into prompt structures for Moonshot's Kimi models
(``moonshot-v1-8k``, ``moonshot-v1-32k``, ``moonshot-v1-128k``,
``kimi-latest``). The Moonshot Open Platform exposes an OpenAI Chat
Completions-compatible endpoint at ``https://api.moonshot.cn/v1`` —
identical request/response shape to OpenAI itself, so the heavy
compilation work is shared with the other OpenAI-shape backends via
:class:`OpenAICompatibleBackend`.

Strengths:
  - Long context windows (up to 200k tokens on ``kimi-latest``)
  - Chinese language and bilingual zh/en reasoning
  - Function calling parity with OpenAI's tool spec
  - Native JSON mode for structured output

Auth: Bearer API key via ``AXON_KIMI_API_KEY`` environment variable.
Default base URL: ``https://api.moonshot.cn/v1``.
"""

from __future__ import annotations

from axon.backends._openai_compatible import OpenAICompatibleBackend


class KimiBackend(OpenAICompatibleBackend):
    """Kimi (Moonshot AI) backend.

    Inherits all compilation logic from :class:`OpenAICompatibleBackend`
    — Moonshot's API is byte-compatible with OpenAI Chat Completions on
    the request side, so the same compiled output flows through the
    transport layer pointed at the Moonshot base URL.
    """

    @property
    def name(self) -> str:
        return "kimi"
