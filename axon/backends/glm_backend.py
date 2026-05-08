"""AXON Backends — GLM (Zhipu AI / 智谱AI) Backend.

Compiles AXON IR into prompt structures for Zhipu's GLM models
(``glm-4-plus``, ``glm-4-air``, ``glm-4-airx``, ``glm-4-flash``,
``glm-4v``). Zhipu's v4 API at ``https://open.bigmodel.cn/api/paas/v4``
exposes an OpenAI Chat Completions-compatible surface — same request
shape, same tool format, same response shape — so the heavy
compilation work is shared with the other OpenAI-shape backends via
:class:`OpenAICompatibleBackend`.

Strengths:
  - Strong Chinese-language reasoning + bilingual zh/en
  - RAG-tuned variants (``glm-4-airx`` for retrieval-heavy flows)
  - Vision-capable variants (``glm-4v``) for multi-modal tasks
  - Free tier on ``glm-4-flash`` for prototyping

Auth: API key via ``AXON_GLM_API_KEY`` (Zhipu's signed-JWT auth is
handled at the transport layer; the compilation backend only emits the
Chat Completions request body shape).
Default base URL: ``https://open.bigmodel.cn/api/paas/v4``.
"""

from __future__ import annotations

from axon.backends._openai_compatible import OpenAICompatibleBackend


class GlmBackend(OpenAICompatibleBackend):
    """GLM (Zhipu AI) backend.

    Inherits all compilation logic from :class:`OpenAICompatibleBackend`.
    Zhipu's v4 endpoint accepts the OpenAI request shape verbatim; the
    transport layer constructs the auth JWT from the API key (Zhipu
    splits the API key into ``id.secret`` form and signs an
    expiry-bounded HS256 token, but that's a transport concern, not a
    compilation concern).
    """

    @property
    def name(self) -> str:
        return "glm"
