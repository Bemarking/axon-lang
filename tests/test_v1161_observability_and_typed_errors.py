"""Tests for v1.16.1 (Fase 22.g) — observability + typed transport errors.

Three layers, mirroring the v1.15.1 pattern that proved its worth at
catching silent regressions:

1. **Construction smoke** for the five new typed-error subclasses
   (``RateLimitError``, ``AuthError``, ``ContextLengthError``,
   ``SafetyBreachError``, ``ModelNotFoundError``). Each must accept
   the ``(message, context)`` signature inherited from
   ``ModelCallError`` / ``AxonRuntimeError`` and serialise via
   ``to_dict()`` with the correct ``error_type`` name and severity
   level.

2. **HTTP error categorisation** — exercise
   ``HTTPProviderModelClient._categorise_http_error`` with synthetic
   ``httpx.HTTPStatusError`` instances covering every status code +
   body shape the v1.16.1 transport layer recognises. Each input
   maps to exactly one typed-error class; an unmapped status falls
   back to the generic ``ModelCallError``.

3. **Retry policy** — drive ``_call_with_retry`` against a stub
   transport that simulates 429 / 5xx / network-timeout sequences.
   Asserts:
     - 429 with ``Retry-After: 0`` triggers retry, eventual success
       returns ``retry_count > 0``.
     - Non-retryable 4xx (e.g., 401) raises immediately without
       retry attempts.
     - Retry budget exhaustion converts to the matching typed error.

4. **AST drift gate** — static check on
   ``axon/server/model_clients.py`` that the v1.16.1 retry path goes
   through ``_categorise_http_error`` (catches a future refactor that
   bypasses the typed-error mapping and resurrects the pre-v1.16.1
   "generic ``ModelCallError`` everywhere" failure mode).
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from axon.runtime.executor import ModelResponse
from axon.runtime.runtime_errors import (
    AuthError,
    AxonRuntimeError,
    ContextLengthError,
    ErrorContext,
    ModelCallError,
    ModelNotFoundError,
    RateLimitError,
    SafetyBreachError,
)
from axon.server.model_clients import (
    _MAX_RETRIES,
    HTTPProviderModelClient,
)


# ═══════════════════════════════════════════════════════════════════
#  Layer 1 — Construction smoke for the new typed errors
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "cls",
    [
        RateLimitError,
        AuthError,
        ContextLengthError,
        SafetyBreachError,
        ModelNotFoundError,
    ],
)
def test_v1161_typed_errors_construct_with_inherited_signature(cls) -> None:
    """The five v1.16.1 typed errors must accept the
    ``(message, context)`` signature inherited from ``ModelCallError``
    and report their class name via ``to_dict()['error_type']``."""
    err = cls(
        message=f"{cls.__name__} smoke",
        context=ErrorContext(step_name="probe", flow_name="smoke"),
    )
    assert isinstance(err, ModelCallError)
    assert isinstance(err, AxonRuntimeError)
    assert err.level == 5
    payload = err.to_dict()
    assert payload["error_type"] == cls.__name__
    assert payload["level"] == 5
    assert payload["message"] == f"{cls.__name__} smoke"
    assert payload["context"]["step_name"] == "probe"


def test_v1161_typed_errors_are_caught_by_modelcallerror_handler() -> None:
    """``except ModelCallError:`` must continue to catch the new
    subclasses — adopters who already handle ModelCallError stay
    correct without touching their except clauses."""
    for cls in (RateLimitError, AuthError, ContextLengthError, SafetyBreachError, ModelNotFoundError):
        try:
            raise cls(message="probe")
        except ModelCallError as exc:
            assert isinstance(exc, cls)


# ═══════════════════════════════════════════════════════════════════
#  Layer 2 — HTTP error categorisation
# ═══════════════════════════════════════════════════════════════════


def _make_client(provider: str = "openai") -> HTTPProviderModelClient:
    """Build an HTTPProviderModelClient suitable for unit tests.

    The transport is overridden in each retry test; for categorisation
    we only need an instance whose ``_categorise_http_error`` is
    callable, so the constructor args are minimal-valid.
    """
    return HTTPProviderModelClient(
        provider=provider,
        model_name="probe-model",
        api_key="test-key",
        base_url="https://example.test",
        timeout_seconds=1.0,
        max_prompt_chars=512,
        max_response_chars=512,
        latency_seconds=0.0,
    )


def _make_http_status_error(
    status: int,
    body: str = "",
    headers: dict[str, str] | None = None,
) -> Any:
    """Construct an ``httpx.HTTPStatusError`` with a synthetic response.

    We can't instantiate the response cleanly without an httpx
    ``Request``, so we use a lightweight mock that exposes only the
    attributes ``_categorise_http_error`` reads.
    """
    import httpx

    response = MagicMock(spec=httpx.Response)
    response.status_code = status
    response.text = body
    response.headers = headers or {}
    request = MagicMock(spec=httpx.Request)
    return httpx.HTTPStatusError(
        message=f"HTTP {status}",
        request=request,
        response=response,
    )


@pytest.mark.parametrize(
    "status,body,expected_cls",
    [
        (429, "rate limit", RateLimitError),
        (401, "Invalid API key", AuthError),
        (403, "Forbidden", AuthError),
        (404, "Not Found", ModelNotFoundError),
        (
            400,
            '{"error":{"code":"context_length_exceeded","message":"too long"}}',
            ContextLengthError,
        ),
        (
            400,
            '{"error":{"message":"Maximum context length reached"}}',
            ContextLengthError,
        ),
        (
            400,
            '{"error":{"code":"model_not_found"}}',
            ModelNotFoundError,
        ),
        (500, "Internal Server Error", ModelCallError),
        (502, "Bad Gateway", ModelCallError),
        (503, "Service Unavailable", ModelCallError),
    ],
)
def test_categorise_http_error_maps_status_to_typed_error(
    status, body, expected_cls
) -> None:
    """The exact mapping that v1.16.1 promises adopters: every status
    code + body shape combo lands in the right typed error class.
    Pre-v1.16.1 every error became a generic ``ModelCallError``,
    making ``except RateLimitError:`` impossible."""
    client = _make_client(provider="openai")
    exc = _make_http_status_error(status, body)
    err = client._categorise_http_error(exc)
    assert isinstance(err, expected_cls), (
        f"status={status} body={body!r} → expected {expected_cls.__name__} "
        f"got {type(err).__name__}"
    )


def test_categorise_http_error_includes_provider_and_model() -> None:
    """Diagnostic messages must surface the provider + model so the
    operator can correlate the failure to an env var / config block.
    """
    client = _make_client(provider="kimi")
    err = client._categorise_http_error(
        _make_http_status_error(401, "Invalid bearer token")
    )
    assert isinstance(err, AuthError)
    assert "kimi" in err.message
    # AuthError messages also surface the env var so the operator
    # knows what to rotate.
    assert "KIMI_API_KEY" in err.message


def test_categorise_unknown_status_falls_back_to_generic_modelcallerror() -> None:
    """An unmapped status (e.g., 418) must still produce a
    ``ModelCallError`` so the executor's existing handler works.
    Forward-compat: providers may add new status codes; we won't
    crash, we'll surface them generically."""
    client = _make_client(provider="anthropic")
    err = client._categorise_http_error(
        _make_http_status_error(418, "I'm a teapot")
    )
    assert isinstance(err, ModelCallError)
    assert not isinstance(err, (RateLimitError, AuthError, ContextLengthError, ModelNotFoundError))


# ═══════════════════════════════════════════════════════════════════
#  Layer 3 — Retry policy
# ═══════════════════════════════════════════════════════════════════


def _make_retryable_transport(
    *,
    fail_n_times_with_status: int = 0,
    status_code: int = 429,
    success_payload: dict[str, Any] | None = None,
    raise_timeout_first: int = 0,
):
    """Build a mock transport that fails N times with a given status
    code, then succeeds on attempt ``N+1``. Tracks the call count so
    tests can assert how many retries fired."""
    import httpx

    state = {
        "calls": 0,
        "raise_status": fail_n_times_with_status,
        "raise_timeout": raise_timeout_first,
    }

    async def transport(url, headers, body, timeout):
        state["calls"] += 1
        if state["raise_timeout"] > 0:
            state["raise_timeout"] -= 1
            raise httpx.TimeoutException("simulated timeout")
        if state["raise_status"] > 0:
            state["raise_status"] -= 1
            response = MagicMock(spec=httpx.Response)
            response.status_code = status_code
            response.text = f"simulated {status_code}"
            response.headers = {"retry-after": "0"} if status_code == 429 else {}
            request = MagicMock(spec=httpx.Request)
            raise httpx.HTTPStatusError(
                message=f"HTTP {status_code}",
                request=request,
                response=response,
            )
        return success_payload or {"choices": [{"message": {"content": "ok"}}]}

    return transport, state


@pytest.mark.asyncio
async def test_retry_recovers_from_two_429s_then_succeeds() -> None:
    """The pre-v1.16.1 transport gave up on the first 429. v1.16.1
    retries up to ``_MAX_RETRIES`` times honouring ``Retry-After``."""
    transport, state = _make_retryable_transport(
        fail_n_times_with_status=2, status_code=429
    )
    client = HTTPProviderModelClient(
        provider="openai",
        model_name="gpt-4o-mini",
        api_key="test",
        base_url="https://example.test",
        timeout_seconds=1.0,
        max_prompt_chars=128,
        max_response_chars=512,
        latency_seconds=0.0,
        transport=transport,
    )
    payload, retry_count = await client._call_with_retry(
        "https://example.test/v1/chat/completions",
        {"authorization": "Bearer test"},
        {"model": "gpt-4o-mini", "messages": []},
    )
    assert state["calls"] == 3  # 2 failures + 1 success
    assert retry_count == 2
    assert payload == {"choices": [{"message": {"content": "ok"}}]}


@pytest.mark.asyncio
async def test_retry_exhaustion_on_persistent_429_raises_ratelimiterror() -> None:
    """When 429 persists past the retry budget, the typed
    ``RateLimitError`` is raised — adopters can ``except`` it
    distinctly from generic transport failures."""
    transport, state = _make_retryable_transport(
        fail_n_times_with_status=10,  # exceeds budget
        status_code=429,
    )
    client = HTTPProviderModelClient(
        provider="openai",
        model_name="gpt-4o",
        api_key="test",
        base_url="https://example.test",
        timeout_seconds=1.0,
        max_prompt_chars=128,
        max_response_chars=512,
        latency_seconds=0.0,
        transport=transport,
    )
    with pytest.raises(RateLimitError) as exc_info:
        await client._call_with_retry(
            "https://example.test/v1/chat/completions",
            {},
            {},
        )
    assert state["calls"] == _MAX_RETRIES + 1
    assert "openai" in exc_info.value.message
    assert "gpt-4o" in exc_info.value.message


@pytest.mark.asyncio
async def test_401_fails_fast_without_retry() -> None:
    """Auth failures are not transient — retrying a 401 wastes time
    + tokens. v1.16.1 fails fast through ``_categorise_http_error``."""
    transport, state = _make_retryable_transport(
        fail_n_times_with_status=10,
        status_code=401,
    )
    client = HTTPProviderModelClient(
        provider="kimi",
        model_name="moonshot-v1-8k",
        api_key="bad-key",
        base_url="https://example.test",
        timeout_seconds=1.0,
        max_prompt_chars=128,
        max_response_chars=512,
        latency_seconds=0.0,
        transport=transport,
    )
    with pytest.raises(AuthError) as exc_info:
        await client._call_with_retry("https://example.test/v1/chat/completions", {}, {})
    # Critical: only ONE call attempt, not _MAX_RETRIES.
    assert state["calls"] == 1
    assert "kimi" in exc_info.value.message


@pytest.mark.asyncio
async def test_first_attempt_success_returns_retry_count_zero() -> None:
    """Happy path — no retries needed, ``retry_count == 0`` so
    downstream consumers can distinguish "succeeded clean" from
    "succeeded after backoff churn"."""
    transport, _ = _make_retryable_transport(fail_n_times_with_status=0)
    client = HTTPProviderModelClient(
        provider="openai",
        model_name="gpt-4o-mini",
        api_key="test",
        base_url="https://example.test",
        timeout_seconds=1.0,
        max_prompt_chars=128,
        max_response_chars=512,
        latency_seconds=0.0,
        transport=transport,
    )
    _, retry_count = await client._call_with_retry(
        "https://example.test/v1/chat/completions", {}, {}
    )
    assert retry_count == 0


# ═══════════════════════════════════════════════════════════════════
#  Layer 4 — Extraction helpers
# ═══════════════════════════════════════════════════════════════════


def test_extract_finish_reason_per_provider_shape() -> None:
    """Every provider names finish_reason differently. v1.16.1
    extracts the right field per provider so the trace event records
    the unified concept."""
    cases = [
        ("openai", {"choices": [{"finish_reason": "stop"}]}, "stop"),
        ("openai", {"choices": [{"finish_reason": "length"}]}, "length"),
        ("openai", {"choices": [{"finish_reason": "content_filter"}]}, "content_filter"),
        ("anthropic", {"stop_reason": "end_turn"}, "end_turn"),
        ("anthropic", {"stop_reason": "max_tokens"}, "max_tokens"),
        ("gemini", {"candidates": [{"finishReason": "STOP"}]}, "STOP"),
        ("gemini", {"candidates": [{"finishReason": "SAFETY"}]}, "SAFETY"),
        ("kimi", {"choices": [{"finish_reason": "stop"}]}, "stop"),
    ]
    for provider, payload, expected in cases:
        client = _make_client(provider=provider)
        assert client._extract_finish_reason(payload) == expected, (
            f"{provider}: got {client._extract_finish_reason(payload)!r} "
            f"want {expected!r}"
        )


def test_extract_finish_reason_returns_empty_on_missing() -> None:
    """Defensive default — when the provider response doesn't surface
    a finish reason, we return empty string, never crash."""
    client = _make_client(provider="openai")
    assert client._extract_finish_reason({}) == ""
    assert client._extract_finish_reason({"choices": []}) == ""
    assert client._extract_finish_reason({"choices": [{}]}) == ""


def test_extract_usage_preserves_provider_specific_keys() -> None:
    """Adopters analysing traces post-hoc need the verbatim provider
    keys (``input_tokens`` for Anthropic, ``prompt_tokens`` for OpenAI,
    ``promptTokenCount`` for Gemini) — not a normalised superset that
    loses info."""
    cases = [
        (
            "openai",
            {"usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}},
            {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        ),
        (
            "anthropic",
            {"usage": {"input_tokens": 200, "output_tokens": 80, "cache_read_input_tokens": 1000}},
            {"input_tokens": 200, "output_tokens": 80, "cache_read_input_tokens": 1000},
        ),
        (
            "gemini",
            {"usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 30, "totalTokenCount": 80}},
            {"promptTokenCount": 50, "candidatesTokenCount": 30, "totalTokenCount": 80},
        ),
    ]
    for provider, payload, expected in cases:
        client = _make_client(provider=provider)
        assert client._extract_usage(payload) == expected


def test_extract_usage_returns_empty_on_missing() -> None:
    client = _make_client(provider="openai")
    assert client._extract_usage({}) == {}


# ═══════════════════════════════════════════════════════════════════
#  Layer 5 — ModelResponse new fields
# ═══════════════════════════════════════════════════════════════════


def test_model_response_new_fields_default_empty() -> None:
    """Backward compat: ``ModelResponse()`` constructed without the
    v1.16.1 fields still works; defaults are empty/zero so existing
    call sites don't need to change."""
    r = ModelResponse(content="x")
    assert r.model_name == ""
    assert r.provider_name == ""
    assert r.finish_reason == ""
    assert r.retry_count == 0
    # to_dict() omits empty/zero fields so old consumers see the same
    # shape as before.
    d = r.to_dict()
    assert "model_name" not in d
    assert "provider_name" not in d
    assert "finish_reason" not in d
    assert "retry_count" not in d


def test_model_response_to_dict_emits_new_fields_when_populated() -> None:
    r = ModelResponse(
        content="x",
        model_name="gpt-4o-mini",
        provider_name="openai",
        finish_reason="stop",
        retry_count=2,
    )
    d = r.to_dict()
    assert d["model_name"] == "gpt-4o-mini"
    assert d["provider_name"] == "openai"
    assert d["finish_reason"] == "stop"
    assert d["retry_count"] == 2


# ═══════════════════════════════════════════════════════════════════
#  Layer 6 — AST drift gate
# ═══════════════════════════════════════════════════════════════════


_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_call_with_retry_routes_through_categorise_http_error() -> None:
    """Static guard against the v1.16.1 regression class. AST-walks
    ``HTTPProviderModelClient._call_with_retry`` and asserts that on
    ``HTTPStatusError`` the code path goes through
    ``self._categorise_http_error`` BEFORE raising. A future refactor
    that bypasses categorisation would re-create the pre-v1.16.1
    "every error is a generic ModelCallError" failure mode and
    silently lose the typed-error contract.
    """
    module = ast.parse(
        (_REPO_ROOT / "axon" / "server" / "model_clients.py").read_text(
            encoding="utf-8"
        )
    )
    target_func: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == "_call_with_retry"
        ):
            target_func = node
            break
    assert target_func is not None, (
        "_call_with_retry disappeared from HTTPProviderModelClient — "
        "drift gate needs an updated function name"
    )

    found_categorise = False
    for node in ast.walk(target_func):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if (
            isinstance(callee, ast.Attribute)
            and callee.attr == "_categorise_http_error"
            and isinstance(callee.value, ast.Name)
            and callee.value.id == "self"
        ):
            found_categorise = True
            break
    assert found_categorise, (
        "_call_with_retry no longer invokes self._categorise_http_error — "
        "the v1.16.1 typed-error mapping has been bypassed. Either "
        "restore the call or update the gate if the design changed "
        "intentionally."
    )


def test_emit_model_response_supports_v1161_observability_kwargs() -> None:
    """Soft drift gate: ``emit_model_response`` must accept the
    v1.16.1 kwargs (``model_name``, ``provider_name``, ``finish_reason``,
    ``retry_count``, ``usage``). If someone narrows the signature and
    drops these, the trace loses observability."""
    from axon.runtime.tracer import Tracer

    sig = inspect.signature(Tracer.emit_model_response)
    for required in ("model_name", "provider_name", "finish_reason", "retry_count", "usage"):
        assert required in sig.parameters, (
            f"Tracer.emit_model_response is missing v1.16.1 kwarg "
            f"{required!r} — observability regression"
        )
