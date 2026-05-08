"""AXON Backends — OpenRouter (multi-provider gateway) Backend.

Compiles AXON IR into prompt structures for OpenRouter's unified
gateway at ``https://openrouter.ai/api/v1``. OpenRouter is an
OpenAI Chat Completions-compatible aggregator that routes a single
API key to 200+ models across every major provider (Anthropic,
OpenAI, Mistral, Cohere, Meta, Google, etc.) using the slug format
``provider/model-name`` (e.g., ``anthropic/claude-3.5-sonnet``,
``mistralai/mistral-large``, ``meta-llama/llama-3.1-405b-instruct``).

Strengths:
  - One API key + one billing surface across N providers
  - Built-in fallback chains (declare a list of model preferences;
    OpenRouter retries down the list on rate limits / errors)
  - Cost / latency routing — pick model by ``:floor`` price tier
  - Useful for evaluation flows that compare multiple models

Auth: Bearer API key via ``AXON_OPENROUTER_API_KEY`` environment
variable. OpenRouter additionally recommends ``HTTP-Referer`` +
``X-Title`` headers for analytics; the transport layer adds those
automatically when the relevant config fields are set.
Default base URL: ``https://openrouter.ai/api/v1``.

Model identifiers: use the OpenRouter slug as the ``model_name``
(e.g., ``"anthropic/claude-3.5-sonnet"``, NOT just
``"claude-3.5-sonnet"``). The transport layer passes it verbatim.
"""

from __future__ import annotations

from axon.backends._openai_compatible import OpenAICompatibleBackend


class OpenRouterBackend(OpenAICompatibleBackend):
    """OpenRouter multi-provider gateway backend.

    Inherits all compilation logic from :class:`OpenAICompatibleBackend`
    — OpenRouter's API is OpenAI-shape on both request and response.
    The slug-based model routing is a transport-layer + adopter-config
    concern, not a compilation concern; the compiled output flows
    through verbatim and OpenRouter dispatches based on the
    ``model`` field of the request body.
    """

    @property
    def name(self) -> str:
        return "openrouter"
