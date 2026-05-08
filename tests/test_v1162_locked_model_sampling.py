"""Tests for v1.16.2 (Fase 22.g.2) — locked-model sampling-parameter omission.

Pre-v1.16.2 the OpenAI Chat Completions default branch in
``HTTPProviderModelClient._build_request`` hardcoded
``"temperature": 0`` into every request body. Reasoning models that
lock that parameter to a fixed provider-side default (Kimi K2.6
requires 1.0/0.6, OpenAI o1/o3 family requires 1.0) rejected the
request with HTTP 400 — a model that the registry advertised as
working actually crashed every call.

v1.16.2 introduces a registry of locked-parameter models keyed by
regex pattern over ``model_name`` and routes the request body through
``_apply_sampling_params``, which omits any parameter the resolved
model rejects. Adopters keep full control on flexible models;
locked-model deployments stop crashing without code changes.

Three layers:

1. **Locked-model regex resolution** — ``_locked_params_for_model``
   identifies the right set of locked parameters for a given model
   name. Parametrized over the documented constraints from
   Moonshot's Kimi K2.x and OpenAI's o1/o3 reasoning docs.

2. **Body construction integration** — ``_build_request`` produces a
   body whose ``temperature`` field is present iff (adopter set it)
   AND (model does NOT lock it). Parametrized over every relevant
   combination so a future regression that adds a hardcoded literal
   back to the body fails immediately.

3. **AST drift gate** — static scan of ``_build_request`` asserts
   that no key from ``_SAMPLING_PARAMETER_NAMES`` appears as a
   hardcoded literal in any body dict. Catches future code that
   adds ``"top_p": 0.95`` (etc.) without routing through
   ``_apply_sampling_params``, which would re-create the v1.16.2
   bug class for whichever new reasoning model surfaces next.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from axon.server.model_clients import (
    _LOCKED_PARAMETER_MODELS,
    _LOCKED_PARAMETER_PATTERNS,
    _SAMPLING_PARAMETER_NAMES,
    _WARNED_LOCKED_OVERRIDES,
    HTTPProviderModelClient,
    _locked_params_for_model,
)


@pytest.fixture(autouse=True)
def _reset_warning_dedup_set() -> None:
    """Each test starts with a clean warning-dedup set so the
    ``_warn_locked_override_once`` behaviour is deterministic.
    Pre-v1.16.2 there was no warning dedup; v1.16.2 dedupes per
    ``(model, parameter)`` tuple, so tests that exercise the same
    pair twice would silently miss the second log line. The
    autouse fixture resets between tests."""
    _WARNED_LOCKED_OVERRIDES.clear()


def _make_client(
    model_name: str,
    *,
    provider: str = "openai",
    temperature: float | None = 0.0,
) -> HTTPProviderModelClient:
    return HTTPProviderModelClient(
        provider=provider,
        model_name=model_name,
        api_key="test-key",
        base_url="https://example.test",
        timeout_seconds=1.0,
        max_prompt_chars=128,
        max_response_chars=128,
        latency_seconds=0.0,
        temperature=temperature,
    )


# ═══════════════════════════════════════════════════════════════════
#  Layer 1 — Locked-model regex resolution
# ═══════════════════════════════════════════════════════════════════


class TestLockedParamsForModel:
    """``_locked_params_for_model`` resolves a model name against
    ``_LOCKED_PARAMETER_MODELS`` regex patterns and returns the set
    of body parameters the model rejects with HTTP 400."""

    @pytest.mark.parametrize(
        "model_name",
        [
            # Kimi K2.x reasoning family — Moonshot docs §quickstart.
            "kimi-k2.6",
            "kimi-k2.5",
            "kimi-k2.6-thinking",
            "kimi-k2.6-vision",
            "kimi-k2.99",  # forward-compat: any future k2.x variant
        ],
    )
    def test_kimi_k2_locks_temperature_top_p_n_penalties(self, model_name) -> None:
        locked = _locked_params_for_model(model_name)
        for required in (
            "temperature",
            "top_p",
            "top_k",
            "n",
            "presence_penalty",
            "frequency_penalty",
        ):
            assert required in locked, (
                f"{model_name!r} should lock {required!r}; "
                f"_LOCKED_PARAMETER_MODELS may have drifted"
            )

    @pytest.mark.parametrize(
        "model_name",
        ["o1", "o1-mini", "o1-preview", "o3", "o3-mini", "o3-pro"],
    )
    def test_openai_reasoning_family_locks_sampling_params(self, model_name) -> None:
        locked = _locked_params_for_model(model_name)
        for required in (
            "temperature",
            "top_p",
            "presence_penalty",
            "frequency_penalty",
            "logprobs",
            "logit_bias",
        ):
            assert required in locked, (
                f"{model_name!r} should lock {required!r}"
            )

    @pytest.mark.parametrize(
        "model_name",
        [
            # Older Kimi without locks.
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k",
            # OpenAI flexible models.
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-3.5-turbo",
            # Anthropic.
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-latest",
            # Other providers.
            "gemini-1.5-flash",
            "llama3.1",
            "glm-4-air",
        ],
    )
    def test_flexible_models_have_no_locks(self, model_name) -> None:
        """Models not matching any regex in ``_LOCKED_PARAMETER_MODELS``
        return an empty frozenset — the request body can carry any
        sampling parameter freely. Catches an over-broad regex that
        would accidentally lock a flexible model."""
        assert _locked_params_for_model(model_name) == frozenset()

    def test_empty_model_name_returns_empty_set(self) -> None:
        """Defensive: empty input must not match any regex."""
        assert _locked_params_for_model("") == frozenset()


# ═══════════════════════════════════════════════════════════════════
#  Layer 2 — Body construction integration
# ═══════════════════════════════════════════════════════════════════


class TestBodyConstructionWithSamplingParams:
    """End-to-end: ``_build_request`` produces the right body for
    each (model_name, adopter_temperature) combination."""

    def test_kimi_k2_6_omits_temperature_even_when_adopter_set(self) -> None:
        """The exact bug Kivi reported: ``temperature: 0`` in the body
        triggers HTTP 400 on Kimi K2.6 because the model requires
        ``1.0`` (thinking) or ``0.6`` (non-thinking). v1.16.2 omits
        the field so the provider applies its own default."""
        client = _make_client("kimi-k2.6", provider="kimi", temperature=0.0)
        _, _, body = client._build_request("system", "user")
        assert "temperature" not in body, (
            f"kimi-k2.6 must omit temperature field; got body={body!r}. "
            "This regression breaks production for any adopter using "
            "the K2.x reasoning family."
        )

    def test_kimi_k2_6_with_explicit_one_still_omits(self) -> None:
        """Even when the adopter sets the 'correct' value (1.0 for
        thinking mode), v1.16.2 still omits to be safe — the provider
        accepts only the *exact* fixed default for the active mode,
        and we don't know which mode the request will run in (Moonshot
        decides server-side). Omission lets the provider pick its
        own default per-mode without us guessing."""
        client = _make_client("kimi-k2.6", provider="kimi", temperature=1.0)
        _, _, body = client._build_request("system", "user")
        assert "temperature" not in body

    def test_moonshot_v1_legacy_includes_temperature(self) -> None:
        """Backward compat: older Kimi models accept temperature=0 and
        every existing deployment depended on it. v1.16.2 must
        preserve that for any adopter not on the K2.x reasoning
        family."""
        client = _make_client(
            "moonshot-v1-32k", provider="kimi", temperature=0.0
        )
        _, _, body = client._build_request("system", "user")
        assert body.get("temperature") == 0.0

    def test_openai_o1_omits_temperature(self) -> None:
        """OpenAI o1 family rejects temperature override the same way
        Kimi K2.x does. Same fix applies."""
        client = _make_client("o1-mini", provider="openai", temperature=0.0)
        _, _, body = client._build_request("system", "user")
        assert "temperature" not in body

    def test_openai_o3_omits_temperature(self) -> None:
        client = _make_client("o3", provider="openai", temperature=0.5)
        _, _, body = client._build_request("system", "user")
        assert "temperature" not in body

    def test_openai_gpt4o_includes_explicit_temperature(self) -> None:
        """Flexible model + adopter-set value → the value flows
        through unchanged. v1.16.2 doesn't regress adopter control
        on any model that doesn't lock the parameter."""
        client = _make_client("gpt-4o", provider="openai", temperature=0.7)
        _, _, body = client._build_request("system", "user")
        assert body.get("temperature") == 0.7

    def test_temperature_none_omits_field_globally(self) -> None:
        """Adopter explicit opt-out: ``temperature=None`` omits the
        field on every model, locked or flexible. Useful for
        deployments that want to delegate to provider defaults
        uniformly without per-model awareness."""
        for model in ("gpt-4o", "moonshot-v1-32k", "kimi-k2.6", "o1-mini"):
            client = _make_client(model, temperature=None)
            _, _, body = client._build_request("system", "user")
            assert "temperature" not in body, (
                f"{model}: temperature=None should always omit; got body={body!r}"
            )

    def test_default_temperature_preserves_pre_v1162_behaviour(self) -> None:
        """Backward compat: a client constructed without explicit
        ``temperature`` argument behaves identically to pre-v1.16.2
        for every model that didn't already lock the parameter
        (i.e., the historical happy path)."""
        client = HTTPProviderModelClient(
            provider="openai",
            model_name="gpt-4o-mini",
            api_key="test",
            base_url="https://example.test",
            timeout_seconds=1.0,
            max_prompt_chars=128,
            max_response_chars=128,
            latency_seconds=0.0,
            # No temperature kwarg — uses default 0.0.
        )
        _, _, body = client._build_request("system", "user")
        assert body.get("temperature") == 0.0


# ═══════════════════════════════════════════════════════════════════
#  Layer 3 — Warning emission on locked override
# ═══════════════════════════════════════════════════════════════════


class TestLockedOverrideWarning:
    """When an adopter sets a parameter on a model that locks it,
    v1.16.2 logs a single WARNING per (model, parameter) pair
    explaining the override was ignored."""

    def test_warning_emitted_for_kimi_k2_6_temperature_override(
        self, caplog
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="axon.server.model_clients"):
            client = _make_client("kimi-k2.6", provider="kimi", temperature=0.0)
            client._build_request("system", "user")
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1
        msg = warnings[0].message
        assert "kimi-k2.6" in msg
        assert "temperature" in msg
        assert "override" in msg.lower()

    def test_warning_deduplicated_per_model_param_pair(self, caplog) -> None:
        """A flow firing the same call 1000× must not emit 1000
        warnings — that floods the logger and obscures real signal.
        v1.16.2 dedupes per ``(model, parameter)`` pair within a
        process lifetime."""
        with caplog.at_level(logging.WARNING, logger="axon.server.model_clients"):
            client = _make_client("kimi-k2.6", provider="kimi", temperature=0.0)
            for _ in range(50):
                client._build_request("system", "user")
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1, (
            f"Expected exactly 1 deduped warning, got {len(warnings)}"
        )

    def test_no_warning_when_adopter_passes_none(self, caplog) -> None:
        """When the adopter explicitly opts out (temperature=None),
        we omit silently — they made the choice deliberately, no
        need to warn."""
        with caplog.at_level(logging.WARNING, logger="axon.server.model_clients"):
            client = _make_client("kimi-k2.6", provider="kimi", temperature=None)
            client._build_request("system", "user")
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 0

    def test_no_warning_for_flexible_models(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="axon.server.model_clients"):
            client = _make_client("gpt-4o", provider="openai", temperature=0.0)
            client._build_request("system", "user")
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


# ═══════════════════════════════════════════════════════════════════
#  Layer 4 — AST drift gate
# ═══════════════════════════════════════════════════════════════════


_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_no_sampling_param_hardcoded_in_build_request() -> None:
    """Static guard against the v1.16.2 regression class.

    Walks the AST of ``HTTPProviderModelClient._build_request`` and
    asserts that no dict literal inside that function contains a key
    matching ``_SAMPLING_PARAMETER_NAMES`` paired with a value that
    is a Python literal (Constant or Name → not a method call /
    attribute lookup that would route through the locked-model
    machinery).

    Pre-v1.16.2 the body had ``"temperature": 0`` literal. The fix
    routes sampling parameters through ``_apply_sampling_params`` so
    locked-model omission applies uniformly. A future refactor that
    adds ``"top_p": 0.95`` literal (etc.) would re-create the bug
    for the next reasoning-model release. This gate fails CI loud
    in that case.
    """
    source = (_REPO_ROOT / "axon" / "server" / "model_clients.py").read_text(
        encoding="utf-8"
    )
    module = ast.parse(source)

    target_func: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(module):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_build_request"
        ):
            target_func = node
            break
    assert target_func is not None, (
        "_build_request disappeared from model_clients.py — "
        "drift gate needs an updated function name"
    )

    violations: list[str] = []
    for node in ast.walk(target_func):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            if key.value not in _SAMPLING_PARAMETER_NAMES:
                continue
            # If the value is a literal (Constant), it's hardcoded.
            # If it's an attribute access (self._xxx) or call expr,
            # it routes through dynamic logic — that's fine.
            if isinstance(value, ast.Constant):
                violations.append(
                    f"line {key.lineno}: dict literal sets sampling "
                    f"param {key.value!r} to constant {value.value!r} — "
                    "must route through _apply_sampling_params instead"
                )
    assert not violations, (
        "v1.16.2 regression detected — sampling parameter hardcoded "
        "in _build_request body literal:\n  "
        + "\n  ".join(violations)
    )


def test_locked_parameter_models_pattern_compiles() -> None:
    """Sanity: every regex in ``_LOCKED_PARAMETER_MODELS`` compiles.
    Catches a typo in the pattern literal at module-load time
    instead of at first request."""
    for pattern, _ in _LOCKED_PARAMETER_PATTERNS:
        assert pattern is not None
        # Round-trip — match against a benign string just to confirm
        # the pattern is callable.
        pattern.search("smoke")


def test_locked_parameter_models_documents_all_known_reasoning_families() -> None:
    """Pin the documented constraints. If the registry ever drops
    Kimi K2.x or OpenAI o1/o3 entries, this test fails — surfacing
    a regression to the maintainer before adopters discover it via
    400s in production."""
    assert any(
        "kimi-k2" in pattern.lower() for pattern in _LOCKED_PARAMETER_MODELS
    ), "Kimi K2.x family missing from _LOCKED_PARAMETER_MODELS"
    assert any(
        "o1" in pattern for pattern in _LOCKED_PARAMETER_MODELS
    ), "OpenAI o1 family missing from _LOCKED_PARAMETER_MODELS"
    assert any(
        "o3" in pattern for pattern in _LOCKED_PARAMETER_MODELS
    ), "OpenAI o3 family missing from _LOCKED_PARAMETER_MODELS"
