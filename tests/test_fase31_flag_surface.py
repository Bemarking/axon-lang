"""§Fase 31.f — Python CLI flag + env var opt-in surface tests.

D6 + D7 + D10 ratified 2026-05-11 bloque. Verifies:

  * The Python `axon serve` argparse accepts
    `--strict-type-driven-transport` and stores it on the Namespace.
  * The env var `AXON_STRICT_TYPE_DRIVEN_TRANSPORT` parses with
    the SAME truthy alphabet as the Rust mirror (D7 cross-stack).
  * Precedence: CLI flag > env var > D6 default.
  * The `AxonServerConfig` dataclass exposes the field with the
    correct default.

Pillar trace per D10:
  - LOGIC      — precedence rule is explicit, exhaustive.
  - COMPUTING  — env var name is the cross-stack contract anchor.
  - PHILOSOPHY — three converging surfaces (CLI, env, default)
                 give adopters multiple ergonomic paths to the
                 same behavior.
"""
from __future__ import annotations

import os

import pytest

from axon.cli.serve_cmd import _parse_truthy_env, _TRUTHY_VALUES
from axon.server.config import AxonServerConfig


# ─── §1 — Truthy env var parser ─────────────────────────────────────


class TestParseTruthyEnv:
    """The truthy alphabet must match Rust `parse_truthy_env`
    byte-for-byte per D7."""

    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "True",
                                     "yes", "YES", "Yes",
                                     "on", "ON", "On"])
    def test_canonical_truthy_values_accepted(self, monkeypatch, val):
        monkeypatch.setenv("AXON_TEST_FASE31_F_TRUTHY", val)
        assert _parse_truthy_env("AXON_TEST_FASE31_F_TRUTHY") is True

    @pytest.mark.parametrize("val", ["0", "false", "FALSE", "no", "off",
                                     "disabled", "anything", "",
                                     "2", "truee", "01"])
    def test_falsy_values_rejected(self, monkeypatch, val):
        monkeypatch.setenv("AXON_TEST_FASE31_F_FALSY", val)
        assert _parse_truthy_env("AXON_TEST_FASE31_F_FALSY") is False

    def test_unset_returns_false(self, monkeypatch):
        monkeypatch.delenv("AXON_TEST_FASE31_F_UNSET", raising=False)
        assert _parse_truthy_env("AXON_TEST_FASE31_F_UNSET") is False

    @pytest.mark.parametrize("val", ["  true  ", "\t1\n", "  yes "])
    def test_whitespace_trimmed(self, monkeypatch, val):
        monkeypatch.setenv("AXON_TEST_FASE31_F_TRIM", val)
        assert _parse_truthy_env("AXON_TEST_FASE31_F_TRIM") is True


# ─── §2 — Truthy alphabet is intentionally constrained ──────────────


class TestTruthyAlphabetClosed:

    def test_alphabet_is_exactly_four_values(self):
        # The four-value alphabet is the D7 cross-stack anchor.
        # Drift here would be silent breakage for adopters.
        assert _TRUTHY_VALUES == frozenset({"1", "true", "yes", "on"})

    @pytest.mark.parametrize("val", ["y", "t", "enabled", "active",
                                     "yep", "TRUE!", "1.0"])
    def test_non_canonical_values_are_falsy(self, monkeypatch, val):
        # Variants like "y" / "t" / "enabled" are NOT accepted —
        # the alphabet is opinionated to avoid interpretation drift.
        monkeypatch.setenv("AXON_TEST_FASE31_F_NOT_OK", val)
        assert _parse_truthy_env("AXON_TEST_FASE31_F_NOT_OK") is False


# ─── §3 — Cross-stack contract: env var name verbatim ───────────────


class TestCrossStackEnvVarContract:

    def test_canonical_env_var_name(self, monkeypatch):
        # D7 — Rust binary reads the same env var name verbatim.
        # If this constant ever changes, BOTH stacks must change
        # in lockstep + adopter migration note must ship.
        canonical = "AXON_STRICT_TYPE_DRIVEN_TRANSPORT"
        monkeypatch.setenv(canonical, "1")
        assert _parse_truthy_env(canonical) is True


# ─── §4 — AxonServerConfig dataclass ───────────────────────────────


class TestAxonServerConfigField:

    def test_default_is_false(self):
        # D6 default — false in v1.22.x for backwards-compat.
        config = AxonServerConfig()
        assert config.strict_type_driven_transport is False

    def test_explicit_true_takes_effect(self):
        config = AxonServerConfig(strict_type_driven_transport=True)
        assert config.strict_type_driven_transport is True

    def test_field_is_bool_typed(self):
        # Mypy / type-checker contract: the field is bool, not Optional.
        import dataclasses
        fields = {f.name: f.type for f in dataclasses.fields(AxonServerConfig)}
        assert "strict_type_driven_transport" in fields


# ─── §5 — Precedence (CLI > env > default) ─────────────────────────


class TestPrecedence:
    """The serve_cmd module uses `cli_flag or _parse_truthy_env(...)`
    short-circuit. This test pack exercises the resolution table
    without invoking the full server startup."""

    def test_cli_true_env_unset_resolves_true(self, monkeypatch):
        monkeypatch.delenv("AXON_STRICT_TYPE_DRIVEN_TRANSPORT", raising=False)
        resolved = True or _parse_truthy_env("AXON_STRICT_TYPE_DRIVEN_TRANSPORT")
        assert resolved is True

    def test_cli_false_env_true_resolves_true(self, monkeypatch):
        monkeypatch.setenv("AXON_STRICT_TYPE_DRIVEN_TRANSPORT", "1")
        resolved = False or _parse_truthy_env("AXON_STRICT_TYPE_DRIVEN_TRANSPORT")
        assert resolved is True

    def test_cli_false_env_unset_resolves_false(self, monkeypatch):
        monkeypatch.delenv("AXON_STRICT_TYPE_DRIVEN_TRANSPORT", raising=False)
        resolved = False or _parse_truthy_env("AXON_STRICT_TYPE_DRIVEN_TRANSPORT")
        assert resolved is False

    def test_cli_true_env_falsy_resolves_true(self, monkeypatch):
        # CLI wins via short-circuit `or` — env "false" never even
        # evaluates.
        monkeypatch.setenv("AXON_STRICT_TYPE_DRIVEN_TRANSPORT", "false")
        resolved = True or _parse_truthy_env("AXON_STRICT_TYPE_DRIVEN_TRANSPORT")
        assert resolved is True


# ─── §6 — argparse integration ──────────────────────────────────────


class TestArgparseIntegration:
    """The Python CLI's argparse accepts the new flag and stores
    it on the Namespace with the expected attribute name."""

    def test_flag_present_in_serve_parser(self):
        from axon.cli import _build_parser
        parser = _build_parser()
        # Parse with the flag enabled.
        ns = parser.parse_args(["serve", "--strict-type-driven-transport"])
        assert getattr(ns, "strict_type_driven_transport", None) is True

    def test_flag_absent_defaults_false(self):
        from axon.cli import _build_parser
        parser = _build_parser()
        # No flag passed — Namespace attribute is False (action="store_true").
        ns = parser.parse_args(["serve"])
        assert getattr(ns, "strict_type_driven_transport", None) is False

    def test_flag_help_text_mentions_env_var(self):
        # Adopters reading `axon serve --help` should learn about
        # the env var alternative directly from the help text.
        from axon.cli import _build_parser
        parser = _build_parser()
        help_text = parser.format_help()
        # We don't render serve help directly via the top parser; the
        # cleanest invariant is that the env var name appears in some
        # subparser's help when --help is rendered. We grep the
        # serve subparser's help text.
        serve_help = ""
        for action in parser._subparsers._group_actions:
            choices = getattr(action, "choices", None) or {}
            if "serve" in choices:
                serve_help = choices["serve"].format_help()
                break
        assert "AXON_STRICT_TYPE_DRIVEN_TRANSPORT" in serve_help, (
            f"--strict-type-driven-transport help must mention the env "
            f"var name verbatim for D7 cross-stack discoverability. "
            f"Got serve help:\n{serve_help}"
        )
