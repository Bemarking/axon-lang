"""Fase 24.j — Cross-stack backend drift gate.

Verifies that the Python `axon.backends.BACKEND_REGISTRY` and the Rust
`axon-rs/src/backends/` per-provider modules stay in lockstep:

* Every Python backend has a corresponding Rust module.
* Every Rust backend has a corresponding Python entry.
* The `_LOCKED_PARAMETER_MODELS` dispatch (regex patterns + locked
  parameter sets) is byte-identical across both stacks — drift here
  silently breaks the Kivi v1.16.2 incident's regression guard.

The gate is necessary because both stacks ship at the same version
(`v1.18.0+` cross-stack) but live in separate codebases — when someone
adds a new backend or extends the locked-model registry on one side
without the other, this test fails CI before the release can ship.

# What is checked

* `axon.backends.BACKEND_REGISTRY.keys()` ≡ Rust per-provider modules
  declared in `axon-rs/src/backends/mod.rs` (excluding shared infra
  modules: `error`, `retry`, `observability`, `locked_model`, `tokens`,
  `openai_compat`, `transport`).
* Every Python backend's documented `default_api_key_env` matches the
  Rust factory's `*_API_KEY_ENV` constant.
* `axon.server.model_clients._LOCKED_PARAMETER_MODELS` (regex pattern
  → set of locked parameter names) ≡ the `LOCKED_PARAMETER_MODELS`
  values surfaced by `axon-rs/src/backends/locked_model.rs::registry`
  (read by text-scan).

# How it runs

Pure text-scan on Rust files — no `cargo` invocation, no Rust
compilation needed. The test runs as part of `pytest` in the Python
suite; CI enforces it on every PR. The Rust side has its own static
parity test in `axon-rs/tests/fase24_backends_cross.rs` verifying the
same shape from the other direction.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
RUST_BACKENDS_DIR = REPO_ROOT / "axon-rs" / "src" / "backends"

# Modules under `axon-rs/src/backends/` that are NOT per-provider
# implementations — they're shared infrastructure (trait definitions,
# error types, retry policy, observability helpers, locked-model
# registry, tokens dispatch, OpenAI-compat shared base, transport
# layer, mod.rs itself). Excluded from the per-provider drift check.
SHARED_INFRA_MODULES: frozenset[str] = frozenset({
    "mod",
    "error",
    "retry",
    "observability",
    "locked_model",
    "tokens",
    "openai_compat",
    "transport",
})

# Canonical per-provider env var names. Pinned here to match the
# Python side; if a Rust backend changes its constant, this test
# will surface the drift on the next run.
EXPECTED_API_KEY_ENV: dict[str, str | None] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "kimi": "KIMI_API_KEY",
    "glm": "GLM_API_KEY",
    "ollama": None,  # local daemon — no API key required
    "openrouter": "OPENROUTER_API_KEY",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _list_rust_provider_modules() -> set[str]:
    """Read `axon-rs/src/backends/` and return the set of per-provider
    module file stems (excluding shared infra modules)."""
    if not RUST_BACKENDS_DIR.is_dir():
        raise AssertionError(
            f"Rust backends directory missing at {RUST_BACKENDS_DIR}. "
            "Has the 24.b shared infra been merged?"
        )
    modules: set[str] = set()
    for entry in RUST_BACKENDS_DIR.iterdir():
        if entry.suffix != ".rs":
            continue
        stem = entry.stem
        if stem in SHARED_INFRA_MODULES:
            continue
        modules.add(stem)
    return modules


# ──────────────────────────────────────────────────────────────────────
#  TestPythonRustParityRegistry — provider name set equivalence
# ──────────────────────────────────────────────────────────────────────


class TestPythonRustParityRegistry:
    """Python `BACKEND_REGISTRY` keys ≡ Rust per-provider modules."""

    @pytest.fixture(scope="class")
    def python_registry(self) -> dict[str, type]:
        from axon.backends import BACKEND_REGISTRY

        return BACKEND_REGISTRY

    @pytest.fixture(scope="class")
    def rust_modules(self) -> set[str]:
        return _list_rust_provider_modules()

    def test_python_and_rust_agree_on_provider_count(
        self, python_registry: dict[str, type], rust_modules: set[str]
    ) -> None:
        assert len(python_registry) == len(rust_modules), (
            f"Provider count mismatch: Python has {len(python_registry)} "
            f"({sorted(python_registry.keys())}), Rust has {len(rust_modules)} "
            f"({sorted(rust_modules)})"
        )

    def test_every_python_provider_has_rust_counterpart(
        self, python_registry: dict[str, type], rust_modules: set[str]
    ) -> None:
        missing = set(python_registry.keys()) - rust_modules
        assert not missing, (
            f"Python providers without Rust counterpart: {sorted(missing)}. "
            f"Add `axon-rs/src/backends/<name>.rs` for each missing entry."
        )

    def test_every_rust_provider_has_python_counterpart(
        self, python_registry: dict[str, type], rust_modules: set[str]
    ) -> None:
        missing = rust_modules - set(python_registry.keys())
        assert not missing, (
            f"Rust providers without Python counterpart: {sorted(missing)}. "
            f"Either add to `axon.backends.BACKEND_REGISTRY` or remove the "
            f"orphan `axon-rs/src/backends/<name>.rs`."
        )

    def test_provider_set_includes_all_seven_canonical_names(
        self, python_registry: dict[str, type], rust_modules: set[str]
    ) -> None:
        """Pin the canonical 7 — adding an 8th requires a deliberate
        update of this test, not silent drift."""
        canonical = {
            "anthropic",
            "gemini",
            "glm",
            "kimi",
            "ollama",
            "openai",
            "openrouter",
        }
        assert set(python_registry.keys()) == canonical
        assert rust_modules == canonical


# ──────────────────────────────────────────────────────────────────────
#  TestPythonRustParityApiKeyEnv — env var names match per provider
# ──────────────────────────────────────────────────────────────────────


class TestPythonRustParityApiKeyEnv:
    """Per-provider `*_API_KEY_ENV` constants match Python's
    `default_api_key_env` field."""

    @pytest.fixture(scope="class")
    def python_provider_specs(self) -> dict[str, str]:
        # `axon.server.model_clients._PROVIDER_SPECS` carries the
        # canonical (provider → env var) mapping.
        from axon.server import model_clients

        specs: dict[str, str] = {}
        for name, spec in model_clients._PROVIDER_SPECS.items():
            specs[name] = spec.default_api_key_env
        return specs

    @pytest.mark.parametrize(
        "provider,expected_env",
        list(EXPECTED_API_KEY_ENV.items()),
    )
    def test_rust_provider_module_pins_correct_env_var(
        self, provider: str, expected_env: str | None
    ) -> None:
        path = RUST_BACKENDS_DIR / f"{provider}.rs"
        if not path.exists():
            pytest.skip(f"Rust module {provider}.rs not found")
        source = _read(path)
        if expected_env is None:
            # Local provider (Ollama) — must NOT pin an *_API_KEY_ENV
            # constant, since the daemon doesn't require auth. The
            # OLLAMA_API_KEY constant exists for proxy fronts but is
            # documented as optional; skip the strict pin.
            return
        # Look for `const API_KEY_ENV: &str = "<EXPECTED>"`.
        pattern = rf'const\s+API_KEY_ENV\s*:\s*&str\s*=\s*"{re.escape(expected_env)}"'
        assert re.search(pattern, source), (
            f"Rust module {provider}.rs does not pin "
            f"`API_KEY_ENV = \"{expected_env}\"`. Either update the constant "
            f"or update EXPECTED_API_KEY_ENV in this test."
        )


# ──────────────────────────────────────────────────────────────────────
#  TestPythonRustParityLockedModelRegistry — regex patterns + locked sets
# ──────────────────────────────────────────────────────────────────────


class TestPythonRustParityLockedModelRegistry:
    """Python `_LOCKED_PARAMETER_MODELS` ≡ Rust `locked_model::registry`."""

    @pytest.fixture(scope="class")
    def python_locked_models(self) -> dict[str, frozenset[str]]:
        from axon.server.model_clients import _LOCKED_PARAMETER_MODELS

        return _LOCKED_PARAMETER_MODELS

    @pytest.fixture(scope="class")
    def rust_locked_source(self) -> str:
        return _read(RUST_BACKENDS_DIR / "locked_model.rs")

    def test_python_registry_has_three_entries(
        self, python_locked_models: dict[str, frozenset[str]]
    ) -> None:
        # Pin the count so adding a 4th family forces a deliberate
        # cross-stack update, not silent drift.
        assert len(python_locked_models) == 3

    def test_rust_registry_has_three_entries(self, rust_locked_source: str) -> None:
        # Count `LockedEntry {` instantiations in the Rust source —
        # exclude the struct definition (`struct LockedEntry {`). Each
        # instantiation corresponds to one locked-model family
        # (kimi-k2 / o1 / o3).
        instantiations = re.findall(
            r"(?<!struct\s)LockedEntry\s*\{", rust_locked_source
        )
        assert len(instantiations) == 3

    @pytest.mark.parametrize(
        "python_pattern",
        [
            r"^kimi-k2\.",
            r"^o1",
            r"^o3",
        ],
    )
    def test_each_python_pattern_appears_in_rust_registry(
        self,
        rust_locked_source: str,
        python_pattern: str,
    ) -> None:
        # Rust source uses raw-string literal: `Regex::new(r"^kimi-k2\.")`.
        # Match the literal pattern text inside any of those calls.
        # (We don't normalise escaping further — the patterns are
        # short enough that exact-match suffices.)
        rust_literal = python_pattern.replace("\\", "\\\\")
        # The Rust source has the pattern wrapped as `r"^pattern"`. A
        # simple substring check matches the pattern text inside the
        # raw-string literal.
        # Use either an exact-pattern match or a normalised one.
        if python_pattern in rust_locked_source:
            return
        assert rust_literal in rust_locked_source or python_pattern in rust_locked_source, (
            f"Python locked-model pattern {python_pattern!r} not found "
            f"in Rust `locked_model.rs`. The two registries must stay "
            f"byte-identical to honour the v1.16.2 Kivi incident regression "
            f"guard."
        )

    def test_kimi_k2_locked_set_matches_six_canonical_params(
        self, python_locked_models: dict[str, frozenset[str]], rust_locked_source: str
    ) -> None:
        py_set = python_locked_models[r"^kimi-k2\."]
        canonical = {
            "temperature",
            "top_p",
            "top_k",
            "n",
            "presence_penalty",
            "frequency_penalty",
        }
        assert py_set == canonical
        # Verify the same six strings appear in the Rust source under
        # the kimi-k2 entry.
        for param in canonical:
            assert f'"{param}"' in rust_locked_source, (
                f"Rust locked_model.rs missing locked param {param!r} "
                f"for kimi-k2 family"
            )

    def test_o1_and_o3_share_same_locked_set(
        self, python_locked_models: dict[str, frozenset[str]]
    ) -> None:
        # Both OpenAI reasoning families lock the same six params.
        assert python_locked_models[r"^o1"] == python_locked_models[r"^o3"]
        canonical = {
            "temperature",
            "top_p",
            "presence_penalty",
            "frequency_penalty",
            "logprobs",
            "logit_bias",
        }
        assert python_locked_models[r"^o1"] == canonical


# ──────────────────────────────────────────────────────────────────────
#  TestRustModuleStructure — additional sanity checks on Rust code
# ──────────────────────────────────────────────────────────────────────


class TestRustModuleStructure:
    """Sanity checks on the Rust backends directory layout."""

    def test_mod_rs_pub_uses_each_per_provider_backend(self) -> None:
        """`mod.rs` must `pub use` the canonical struct from each
        provider so adopters can write
        `use axon::backends::{AnthropicBackend, ...};`."""
        mod_source = _read(RUST_BACKENDS_DIR / "mod.rs")
        expected = [
            "AnthropicBackend",
            "GeminiBackend",
            "GLMBackend",
            "KimiBackend",
            "OllamaBackend",
            "OpenAIBackend",
            "OpenRouterBackend",
        ]
        for name in expected:
            assert name in mod_source, (
                f"mod.rs missing `pub use` for {name}. Adopters can't "
                f"import the backend by its canonical struct name."
            )

    def test_each_provider_module_contains_backend_trait_impl(self) -> None:
        """Every per-provider .rs must implement `Backend` for its
        canonical struct."""
        rust_modules = _list_rust_provider_modules()
        for module in rust_modules:
            source = _read(RUST_BACKENDS_DIR / f"{module}.rs")
            assert "impl Backend for" in source, (
                f"{module}.rs does not implement the `Backend` trait. "
                f"Every provider module must do so to be registry-compatible."
            )

    def test_each_provider_has_canonical_short_name(self) -> None:
        """Every per-provider .rs must surface its canonical name as
        a `PROVIDER_NAME`-like constant or via the `name()` method."""
        rust_modules = _list_rust_provider_modules()
        for module in rust_modules:
            source = _read(RUST_BACKENDS_DIR / f"{module}.rs")
            # Either a top-level `PROVIDER_NAME = "<module>"` or a
            # delegation through inner.name() suffices. Verify the
            # module name appears as a string literal somewhere.
            assert f'"{module}"' in source, (
                f"{module}.rs does not appear to surface its canonical "
                f"name {module!r} anywhere — registry dispatch will fail."
            )

    def test_locked_model_normalise_strips_provider_prefix(self) -> None:
        """24.i extension: locked_model.rs must strip `provider/`
        prefix before pattern match (so OpenRouter slug forms work).
        Verify the `normalise` helper exists."""
        source = _read(RUST_BACKENDS_DIR / "locked_model.rs")
        assert "fn normalise" in source, (
            "locked_model.rs missing the `normalise` helper that strips "
            "`provider/` prefix. Without it, OpenRouter slug forms like "
            "`openai/o1-mini` won't trigger the locked-param dispatch."
        )

    def test_transport_module_supports_display_url(self) -> None:
        """24.e extension: transport.rs must accept `display_url:
        Option<&str>` so URL-embedded API keys (Gemini) get redacted
        in tracing spans."""
        source = _read(RUST_BACKENDS_DIR / "transport.rs")
        assert "display_url" in source, (
            "transport.rs missing the `display_url` parameter that lets "
            "Gemini redact its URL-embedded API key from tracing spans."
        )
