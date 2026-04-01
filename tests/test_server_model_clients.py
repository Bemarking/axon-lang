from __future__ import annotations

import os
from typing import Any

import pytest

from axon.server.config import AxonServerConfig
from axon.server.model_clients import (
    DeterministicEndpointModelClient,
    HTTPProviderModelClient,
    create_endpoint_model_client,
)


def _request_prompt(payload: dict[str, Any], trace_id: str = "trace-1") -> str:
    import json

    return (
        "Endpoint request payload (JSON):\n"
        f"{json.dumps(payload, ensure_ascii=True, sort_keys=True)}\n\n"
        f"Trace ID: {trace_id}\n\n"
        "analyze"
    )


async def test_deterministic_client_projects_schema() -> None:
    client = DeterministicEndpointModelClient(
        max_prompt_chars=4000,
        max_response_chars=4000,
        latency_seconds=0,
    )

    response = await client.call(
        system_prompt="",
        user_prompt=_request_prompt({"text": "hola"}, trace_id="abc"),
        output_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "score": {"type": "number"},
            },
        },
    )

    assert response.structured is not None
    assert response.structured["trace_id"] == "abc"
    assert response.structured["output"]["text"] == "hola"
    assert response.structured["output"]["score"] == 0


async def test_registry_openai_uses_http_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k-openai")
    seen: dict[str, Any] = {}

    async def fake_transport(
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        seen["url"] = url
        seen["headers"] = headers
        seen["body"] = body
        seen["timeout"] = timeout
        return {"choices": [{"message": {"content": '{"answer":"ok"}'}}]}

    cfg = AxonServerConfig(
        endpoint_model="openai",
        endpoint_model_name="gpt-4o-mini",
        endpoint_model_timeout_seconds=12.0,
    )
    client = create_endpoint_model_client(cfg, transport=fake_transport)
    assert isinstance(client, HTTPProviderModelClient)

    response = await client.call("sys", _request_prompt({"x": 1}, "tr-openai"))

    assert seen["url"].endswith("/v1/chat/completions")
    assert seen["headers"]["authorization"] == "Bearer k-openai"
    assert seen["body"]["model"] == "gpt-4o-mini"
    assert response.structured is not None
    assert response.structured["answer"] == "ok"
    assert response.structured["provider"] == "openai"


async def test_registry_kimi_uses_openai_compatible_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIMI_API_KEY", "k-kimi")

    async def fake_transport(
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        assert url.startswith("https://api.moonshot.ai")
        assert headers["authorization"] == "Bearer k-kimi"
        assert body["messages"][1]["role"] == "user"
        return {"choices": [{"message": {"content": "plain result"}}]}

    cfg = AxonServerConfig(endpoint_model="kimi")
    client = create_endpoint_model_client(cfg, transport=fake_transport)
    response = await client.call("sys", _request_prompt({"x": 2}, "tr-kimi"))

    assert response.structured is not None
    assert response.structured["output"] == "plain result"
    assert response.structured["provider"] == "kimi"


async def test_registry_anthropic_uses_messages_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k-anth")

    async def fake_transport(
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        assert url.endswith("/v1/messages")
        assert headers["x-api-key"] == "k-anth"
        assert body["messages"][0]["role"] == "user"
        return {"content": [{"text": '{"answer":"anth"}'}]}

    cfg = AxonServerConfig(endpoint_model="anthropic")
    client = create_endpoint_model_client(cfg, transport=fake_transport)
    response = await client.call("sys", _request_prompt({"x": 3}, "tr-anth"))

    assert response.structured is not None
    assert response.structured["answer"] == "anth"
    assert response.structured["provider"] == "anthropic"


async def test_registry_gemini_uses_generate_content_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k-gem")

    async def fake_transport(
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        assert ":generateContent" in url
        assert "?key=k-gem" in url
        assert headers["content-type"] == "application/json"
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": '{"answer":"gem"}'},
                        ]
                    }
                }
            ]
        }

    cfg = AxonServerConfig(endpoint_model="gemini")
    client = create_endpoint_model_client(cfg, transport=fake_transport)
    response = await client.call("sys", _request_prompt({"x": 4}, "tr-gem"))

    assert response.structured is not None
    assert response.structured["answer"] == "gem"
    assert response.structured["provider"] == "gemini"


def test_missing_key_falls_back_to_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = AxonServerConfig(endpoint_model="openai", endpoint_model_strict=False)
    client = create_endpoint_model_client(cfg)
    assert isinstance(client, DeterministicEndpointModelClient)


def test_missing_key_strict_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = AxonServerConfig(endpoint_model="openai", endpoint_model_strict=True)
    with pytest.raises(ValueError, match="Missing API key"):
        create_endpoint_model_client(cfg)


def test_explicit_provider_field_overrides_endpoint_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "k-openai")

    async def fake_transport(
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        return {"choices": [{"message": {"content": "{}"}}]}

    cfg = AxonServerConfig(
        endpoint_model="deterministic",
        endpoint_model_provider="openai",
    )
    client = create_endpoint_model_client(cfg, transport=fake_transport)
    assert isinstance(client, HTTPProviderModelClient)
