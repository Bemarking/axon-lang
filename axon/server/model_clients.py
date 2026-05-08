"""Endpoint model client adapters for AxonServer.

This module keeps provider-specific API wiring at the server edge while
preserving an LLM-agnostic core runtime.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from axon.runtime.executor import ModelResponse


TransportFn = Callable[[str, dict[str, str], dict[str, Any], float], Awaitable[dict[str, Any]]]
_JSON_CONTENT_TYPE = "application/json"

# v1.16.1 — retry policy constants. Conservative defaults; transport
# layer wrap-up at most ``_MAX_RETRIES`` times on retryable status
# codes (429, 5xx) before raising a typed error. ``Retry-After`` from
# the provider takes precedence over computed exponential backoff
# when present and within ``_MAX_BACKOFF_SECONDS``.
_MAX_RETRIES = 3
_MAX_BACKOFF_SECONDS = 30.0
_BASE_BACKOFF_SECONDS = 0.5
_BACKOFF_JITTER_SECONDS = 0.5

# Provider response keywords that flag a content-filter / safety
# block on a 200 OK response (OpenAI, Gemini, Anthropic all surface
# this as a non-error finish reason). Detected in ``_extract_finish_reason``.
_SAFETY_FINISH_REASONS: frozenset[str] = frozenset(
    {"content_filter", "safety", "blocked", "recitation"}
)


@dataclass(frozen=True)
class _ProviderSpec:
    name: str
    default_model: str
    default_api_key_env: str
    default_base_url: str


_PROVIDER_SPECS: dict[str, _ProviderSpec] = {
    "openai": _ProviderSpec(
        name="openai",
        default_model="gpt-4o-mini",
        default_api_key_env="OPENAI_API_KEY",
        default_base_url="https://api.openai.com",
    ),
    "kimi": _ProviderSpec(
        name="kimi",
        default_model="moonshot-v1-8k",
        default_api_key_env="KIMI_API_KEY",
        default_base_url="https://api.moonshot.ai",
    ),
    "anthropic": _ProviderSpec(
        name="anthropic",
        default_model="claude-3-5-haiku-latest",
        default_api_key_env="ANTHROPIC_API_KEY",
        default_base_url="https://api.anthropic.com",
    ),
    "gemini": _ProviderSpec(
        name="gemini",
        default_model="gemini-1.5-flash",
        default_api_key_env="GEMINI_API_KEY",
        default_base_url="https://generativelanguage.googleapis.com",
    ),
}


class DeterministicEndpointModelClient:
    """Deterministic model client with bounded I/O for endpoint runtime."""

    def __init__(
        self,
        *,
        max_prompt_chars: int,
        max_response_chars: int,
        latency_seconds: float,
    ) -> None:
        self._max_prompt_chars = max(256, int(max_prompt_chars))
        self._max_response_chars = max(256, int(max_response_chars))
        self._latency_seconds = max(0.0, float(latency_seconds))

    @property
    def provider_name(self) -> str:
        return "deterministic"

    @property
    def model_name(self) -> str:
        return "deterministic"

    @property
    def transport_kind(self) -> str:
        return "local"

    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        output_schema: dict[str, Any] | None = None,
        effort: str = "",
        failure_context: str = "",
    ) -> ModelResponse:
        del system_prompt, tools, effort, failure_context

        if self._latency_seconds > 0:
            await asyncio.sleep(self._latency_seconds)

        safe_prompt = self._clip_text(str(user_prompt), self._max_prompt_chars)
        payload, trace_id = self._extract_payload_context(safe_prompt)
        projected = self._project_payload(output_schema, payload)

        structured = {
            "output": projected,
            "trace_id": trace_id,
            "payload": payload,
        }
        content = json.dumps({"output": projected}, ensure_ascii=True, sort_keys=True)
        if len(content) > self._max_response_chars:
            content = self._clip_text(content, self._max_response_chars)
            structured["truncated"] = True

        return ModelResponse(content=content, structured=structured)

    @staticmethod
    def _clip_text(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 14] + " ...[truncated]"

    @staticmethod
    def _extract_payload_context(prompt: str) -> tuple[dict[str, Any], str]:
        header = "Endpoint request payload (JSON):\n"
        if header not in prompt:
            return {}, ""

        body = prompt.split(header, 1)[1]
        payload_raw, sep, rest = body.partition("\n\nTrace ID: ")
        if not sep:
            return {}, ""

        trace_id, _, _ = rest.partition("\n\n")
        try:
            parsed = json.loads(payload_raw)
        except json.JSONDecodeError:
            return {}, trace_id.strip()
        if isinstance(parsed, dict):
            return parsed, trace_id.strip()
        return {}, trace_id.strip()

    def _project_payload(
        self,
        output_schema: dict[str, Any] | None,
        payload: dict[str, Any],
    ) -> Any:
        if not output_schema or not isinstance(output_schema, dict):
            return payload

        props = output_schema.get("properties")
        if not isinstance(props, dict):
            return payload

        projected: dict[str, Any] = {}
        for key, field_schema in props.items():
            if key in payload:
                projected[key] = payload[key]
                continue
            projected[key] = self._default_value(field_schema)
        return projected

    @staticmethod
    def _default_value(field_schema: Any) -> Any:
        if not isinstance(field_schema, dict):
            return None

        t = field_schema.get("type")
        if t == "string":
            return ""
        if t in {"number", "integer"}:
            return 0
        if t == "boolean":
            return False
        if t == "array":
            return []
        if t == "object":
            return {}
        return None


class HTTPProviderModelClient:
    """Provider adapter for commercial APIs behind a common model client contract."""

    def __init__(
        self,
        *,
        provider: str,
        model_name: str,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        max_prompt_chars: int,
        max_response_chars: int,
        latency_seconds: float,
        transport: TransportFn | None = None,
    ) -> None:
        self._provider = provider
        self._model_name = model_name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = max(1.0, float(timeout_seconds))
        self._max_prompt_chars = max(256, int(max_prompt_chars))
        self._max_response_chars = max(256, int(max_response_chars))
        self._latency_seconds = max(0.0, float(latency_seconds))
        self._transport = transport or _httpx_transport

    @property
    def provider_name(self) -> str:
        return self._provider

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def transport_kind(self) -> str:
        return "http"

    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        output_schema: dict[str, Any] | None = None,
        effort: str = "",
        failure_context: str = "",
    ) -> ModelResponse:
        del tools, output_schema, effort, failure_context

        if self._latency_seconds > 0:
            await asyncio.sleep(self._latency_seconds)

        safe_prompt = DeterministicEndpointModelClient._clip_text(
            str(user_prompt),
            self._max_prompt_chars,
        )
        url, headers, body = self._build_request(system_prompt, safe_prompt)

        # v1.16.1 — retry-aware transport invocation. Returns the
        # provider payload + how many retries fired before success.
        raw, retry_count = await self._call_with_retry(url, headers, body)

        # v1.16.1 — extract observability fields from the raw provider
        # response BEFORE detecting safety blocks; safety detection
        # uses ``finish_reason`` so it must come first.
        finish_reason = self._extract_finish_reason(raw)
        usage = self._extract_usage(raw)

        # v1.16.1 — content-filter / safety blocks land as 200 OK with
        # a sentinel finish_reason; surface them as a typed error so
        # adopters in regulated domains audit them distinctly from
        # transport failures.
        if finish_reason and finish_reason.lower() in _SAFETY_FINISH_REASONS:
            from axon.runtime.runtime_errors import SafetyBreachError

            raise SafetyBreachError(
                message=(
                    f"Provider {self._provider!r} returned a safety-block "
                    f"finish_reason {finish_reason!r} for model "
                    f"{self._model_name!r}. The model produced no content "
                    "because its content filter intercepted either the "
                    "prompt or the in-progress response."
                ),
            )

        text = self._extract_text(raw)
        structured = self._normalize_structured(text)

        payload, trace_id = DeterministicEndpointModelClient._extract_payload_context(safe_prompt)
        if isinstance(structured, dict):
            structured.setdefault("trace_id", trace_id)
            structured.setdefault("payload", payload)
            structured.setdefault("provider", self._provider)
            structured.setdefault("model", self._model_name)

        content = json.dumps(structured, ensure_ascii=True, sort_keys=True)
        if len(content) > self._max_response_chars:
            content = DeterministicEndpointModelClient._clip_text(
                content,
                self._max_response_chars,
            )
            if isinstance(structured, dict):
                structured["truncated"] = True

        return ModelResponse(
            content=content,
            structured=structured,
            raw=raw,
            usage=usage,
            model_name=self._model_name,
            provider_name=self._provider,
            finish_reason=finish_reason,
            retry_count=retry_count,
        )

    # ── v1.16.1 — retry policy + error categorisation ──────────────

    async def _call_with_retry(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
    ) -> tuple[dict[str, Any], int]:
        """Invoke the transport with exponential-backoff retry.

        Returns ``(payload, retry_count)`` on success — ``retry_count``
        is 0 when the first attempt succeeds. On unrecoverable
        failure, raises one of the v1.16.1 typed errors
        (``RateLimitError``, ``AuthError``, ``ContextLengthError``,
        ``ModelNotFoundError``) or the generic ``ModelCallError`` for
        unmapped 4xx / 5xx categories.

        Retry policy:
          - HTTP 429 → retry, honour ``Retry-After`` header up to
            ``_MAX_BACKOFF_SECONDS``; fall back to exponential backoff
            with jitter when header absent.
          - HTTP 5xx → retry with exponential backoff + jitter.
          - HTTP 4xx (other) → fail-fast through ``_categorise_http_error``.
          - Network timeout / request error → retry.
          - All retry budgets capped by ``_MAX_RETRIES`` (default 3).
        """
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover — same dep as transport
            raise RuntimeError(
                "httpx is required for HTTP provider model calls."
            ) from exc

        last_exception: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                payload = await self._transport(
                    url, headers, body, self._timeout_seconds
                )
                return payload, attempt
            except httpx.HTTPStatusError as exc:
                last_exception = exc
                status = exc.response.status_code
                if attempt < _MAX_RETRIES and self._is_retryable_status(status):
                    delay = self._compute_backoff(exc.response, attempt)
                    await asyncio.sleep(delay)
                    continue
                raise self._categorise_http_error(exc) from exc
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                last_exception = exc
                if attempt < _MAX_RETRIES:
                    delay = self._compute_backoff(None, attempt)
                    await asyncio.sleep(delay)
                    continue
                from axon.runtime.runtime_errors import ModelCallError

                raise ModelCallError(
                    message=(
                        f"Transport failure after {attempt + 1} attempts "
                        f"to provider {self._provider!r}: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                ) from exc

        # Defensive — loop above always returns or raises.
        from axon.runtime.runtime_errors import ModelCallError

        raise ModelCallError(
            message=(
                f"Retry budget exhausted ({_MAX_RETRIES} retries) for "
                f"provider {self._provider!r}. Last error: {last_exception}"
            ),
        )

    @staticmethod
    def _is_retryable_status(status: int) -> bool:
        """429 + 5xx are transient; 4xx (other) is fail-fast.

        408 (request timeout) is also retryable but rare from these
        providers; included for completeness.
        """
        if status == 429:
            return True
        if status == 408:
            return True
        return 500 <= status < 600

    @staticmethod
    def _compute_backoff(response: Any, attempt: int) -> float:
        """Exponential backoff with jitter, honouring ``Retry-After``.

        ``Retry-After`` may be an integer (seconds) or HTTP-date.
        v1.16.1 only handles the integer-seconds form — HTTP-date is
        rare from these providers and complicates the parser. When
        the header is missing or unparseable, falls back to
        ``base * 2^attempt + jitter`` capped at ``_MAX_BACKOFF_SECONDS``.
        """
        if response is not None:
            header = response.headers.get("retry-after", "")
            if header.isdigit():
                return min(float(header), _MAX_BACKOFF_SECONDS)
        base = min(
            _BASE_BACKOFF_SECONDS * (2 ** attempt),
            _MAX_BACKOFF_SECONDS,
        )
        return base + (random.random() * _BACKOFF_JITTER_SECONDS)

    def _categorise_http_error(self, exc: Any) -> Exception:
        """Map an ``httpx.HTTPStatusError`` to a v1.16.1 typed error.

        Inspects status code first, then response body for
        provider-specific shape disambiguation (OpenAI's
        ``error.code`` field, Anthropic's ``error.type`` field).
        Returns a constructed exception ready to be raised by the
        caller; never raises itself.
        """
        from axon.runtime.runtime_errors import (
            AuthError,
            ContextLengthError,
            ModelCallError,
            ModelNotFoundError,
            RateLimitError,
        )

        status = exc.response.status_code
        body_text = exc.response.text or ""
        body_preview = body_text[:200]
        body_lower = body_text.lower()

        if status == 429:
            retry_after = exc.response.headers.get("retry-after", "")
            return RateLimitError(
                message=(
                    f"Rate limit on provider {self._provider!r} "
                    f"(model={self._model_name!r}, status=429"
                    + (f", retry_after={retry_after!r}" if retry_after else "")
                    + f"). Retries exhausted. Body: {body_preview}"
                ),
            )

        if status in (401, 403):
            spec = _PROVIDER_SPECS.get(self._provider)
            env_var_hint = (
                f" (env var: {spec.default_api_key_env})" if spec else ""
            )
            return AuthError(
                message=(
                    f"Authentication failed on provider {self._provider!r}"
                    f"{env_var_hint}, status={status}. Verify the API "
                    f"key is set, valid, and has access to model "
                    f"{self._model_name!r}. Body: {body_preview}"
                ),
            )

        if status == 404:
            return ModelNotFoundError(
                message=(
                    f"Model {self._model_name!r} not found at provider "
                    f"{self._provider!r} (status=404). Either the slug "
                    f"is mistyped or the model was deprecated. "
                    f"Body: {body_preview}"
                ),
            )

        if status == 400:
            if (
                "context_length" in body_lower
                or "context length" in body_lower
                or "maximum context" in body_lower
                or "too long" in body_lower
            ):
                return ContextLengthError(
                    message=(
                        f"Prompt exceeds context window of model "
                        f"{self._model_name!r} on provider "
                        f"{self._provider!r} (status=400). "
                        f"Body: {body_preview}"
                    ),
                )
            if (
                "model_not_found" in body_lower
                or "model not found" in body_lower
                or "no such model" in body_lower
            ):
                return ModelNotFoundError(
                    message=(
                        f"Model {self._model_name!r} not recognised by "
                        f"provider {self._provider!r} (status=400). "
                        f"Body: {body_preview}"
                    ),
                )

        return ModelCallError(
            message=(
                f"Provider {self._provider!r} returned HTTP {status} "
                f"for model {self._model_name!r}. Body: {body_preview}"
            ),
        )

    # ── v1.16.1 — observability extraction ─────────────────────────

    def _extract_finish_reason(self, payload: dict[str, Any]) -> str:
        """Read the provider-specific finish/stop reason from a 200 OK
        response. Empty string when not surfaced (defensive default).

        Mapping:
          - OpenAI Chat Completions: ``choices[0].finish_reason``
          - Anthropic Messages: ``stop_reason``
          - Gemini: ``candidates[0].finishReason``
          - Other OpenAI-compatible: same as OpenAI
        """
        try:
            if self._provider == "anthropic":
                return str(payload.get("stop_reason", ""))
            if self._provider == "gemini":
                cands = payload.get("candidates", [])
                if cands and isinstance(cands[0], dict):
                    return str(cands[0].get("finishReason", ""))
            choices = payload.get("choices", [])
            if choices and isinstance(choices[0], dict):
                return str(choices[0].get("finish_reason", ""))
        except Exception:  # noqa: BLE001 — never let extraction error fail the call
            pass
        return ""

    def _extract_usage(self, payload: dict[str, Any]) -> dict[str, int]:
        """Read the provider-specific usage breakdown verbatim.

        Each provider names tokens differently:
          - OpenAI: ``usage.prompt_tokens``, ``usage.completion_tokens``,
            ``usage.total_tokens`` (+ ``reasoning_tokens`` on o1/o3)
          - Anthropic: ``usage.input_tokens``, ``usage.output_tokens``
            (+ ``cache_read_input_tokens``, ``cache_creation_input_tokens``)
          - Gemini: ``usageMetadata.promptTokenCount``,
            ``candidatesTokenCount``, ``totalTokenCount``

        Returns a normalised dict with the provider's keys preserved
        (e.g., callers can do ``usage.get("input_tokens", usage.get("prompt_tokens", 0))``
        without losing detail). When usage is absent in the response,
        returns an empty dict.
        """
        try:
            if self._provider == "gemini":
                meta = payload.get("usageMetadata", {})
                if isinstance(meta, dict):
                    return {
                        k: int(v)
                        for k, v in meta.items()
                        if isinstance(v, (int, float))
                    }
            usage = payload.get("usage", {})
            if isinstance(usage, dict):
                return {
                    k: int(v)
                    for k, v in usage.items()
                    if isinstance(v, (int, float))
                }
        except Exception:  # noqa: BLE001
            pass
        return {}

    def _build_request(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        if self._provider == "anthropic":
            return (
                f"{self._base_url}/v1/messages",
                {
                    "content-type": _JSON_CONTENT_TYPE,
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                },
                {
                    "model": self._model_name,
                    "max_tokens": 1024,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            )

        if self._provider == "gemini":
            return (
                f"{self._base_url}/v1beta/models/{self._model_name}:generateContent?key={self._api_key}",
                {"content-type": _JSON_CONTENT_TYPE},
                {
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"parts": [{"text": user_prompt}]}],
                },
            )

        return (
            f"{self._base_url}/v1/chat/completions",
            {
                "content-type": _JSON_CONTENT_TYPE,
                "authorization": f"Bearer {self._api_key}",
            },
            {
                "model": self._model_name,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )

    def _extract_text(self, payload: dict[str, Any]) -> str:
        try:
            if self._provider == "anthropic":
                content_items = payload.get("content", [])
                if content_items and isinstance(content_items[0], dict):
                    return str(content_items[0].get("text", ""))

            if self._provider == "gemini":
                cands = payload.get("candidates", [])
                if cands:
                    parts = cands[0].get("content", {}).get("parts", [])
                    if parts and isinstance(parts[0], dict):
                        return str(parts[0].get("text", ""))

            choices = payload.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                return str(msg.get("content", ""))
        except Exception:
            pass

        return json.dumps(payload, ensure_ascii=True, sort_keys=True)

    @staticmethod
    def _normalize_structured(text: str) -> dict[str, Any]:
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
            return {"output": data}
        except json.JSONDecodeError:
            return {"output": text}


def create_endpoint_model_client(
    config: Any,
    *,
    logger: logging.Logger | None = None,
    transport: TransportFn | None = None,
) -> Any:
    """Build endpoint model client from AxonServerConfig-compatible object."""
    log = logger or logging.getLogger(__name__)

    provider = (
        getattr(config, "endpoint_model_provider", "")
        or getattr(config, "endpoint_model", "deterministic")
    ).strip().lower()

    max_prompt = int(getattr(config, "endpoint_model_max_prompt_chars", 16000))
    max_response = int(getattr(config, "endpoint_model_max_response_chars", 32000))
    latency = float(getattr(config, "endpoint_model_latency_seconds", 0.0))

    if provider in {"", "deterministic", "mock", "local"}:
        return DeterministicEndpointModelClient(
            max_prompt_chars=max_prompt,
            max_response_chars=max_response,
            latency_seconds=latency,
        )

    spec = _PROVIDER_SPECS.get(provider)
    if spec is None:
        log.warning(
            "Unknown endpoint model provider '%s'; falling back to deterministic",
            provider,
        )
        return DeterministicEndpointModelClient(
            max_prompt_chars=max_prompt,
            max_response_chars=max_response,
            latency_seconds=latency,
        )

    strict = bool(getattr(config, "endpoint_model_strict", False))
    api_key_env = (getattr(config, "endpoint_model_api_key_env", "") or spec.default_api_key_env).strip()
    api_key = os.getenv(api_key_env)
    if not api_key:
        msg = (
            f"Missing API key for provider '{provider}'. "
            f"Set env var '{api_key_env}' or switch endpoint model provider."
        )
        if strict:
            raise ValueError(msg)
        log.warning("%s Falling back to deterministic.", msg)
        return DeterministicEndpointModelClient(
            max_prompt_chars=max_prompt,
            max_response_chars=max_response,
            latency_seconds=latency,
        )

    model_name = (getattr(config, "endpoint_model_name", "") or spec.default_model).strip()
    base_url = (getattr(config, "endpoint_model_base_url", "") or spec.default_base_url).strip()
    timeout_seconds = float(getattr(config, "endpoint_model_timeout_seconds", 30.0))

    return HTTPProviderModelClient(
        provider=provider,
        model_name=model_name,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        max_prompt_chars=max_prompt,
        max_response_chars=max_response,
        latency_seconds=latency,
        transport=transport,
    )


async def _httpx_transport(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError(
            "httpx is required for commercial endpoint model providers. "
            "Install with: pip install axon-lang[server]"
        ) from exc

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        return {"output": payload}
