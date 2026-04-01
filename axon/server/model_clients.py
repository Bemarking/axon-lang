"""Endpoint model client adapters for AxonServer.

This module keeps provider-specific API wiring at the server edge while
preserving an LLM-agnostic core runtime.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from axon.runtime.executor import ModelResponse


TransportFn = Callable[[str, dict[str, str], dict[str, Any], float], Awaitable[dict[str, Any]]]
_JSON_CONTENT_TYPE = "application/json"


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
        raw = await self._transport(url, headers, body, self._timeout_seconds)
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

        return ModelResponse(content=content, structured=structured, raw=raw)

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
