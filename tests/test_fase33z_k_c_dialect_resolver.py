"""§Fase 33.z.k.c (v1.28.0) — Python tests for the effective-dialect
resolver. Mirrors `axon-frontend/tests/fase33z_k_c_dialect_resolver.rs`
byte-for-byte (D7 cross-stack contract)."""

from __future__ import annotations

import pytest

from axon.compiler.parser import _AXONENDPOINT_TRANSPORT_DIALECTS
from axon.compiler.type_checker import resolve_effective_dialect


# ─── §1 — Explicit dialect wins (Rule 1) ────────────────────────────


@pytest.mark.parametrize("dialect", ["axon", "openai", "anthropic"])
@pytest.mark.parametrize("algebraic", [False, True])
def test_s1_explicit_dialect_wins(dialect: str, algebraic: bool) -> None:
    assert resolve_effective_dialect(dialect, algebraic) == dialect


# ─── §2 — Q1 algebraic-effect default → openai (Rule 2) ─────────────


def test_s2_q1_algebraic_default_openai():
    assert resolve_effective_dialect("", True) == "openai", (
        "33.z.k.c Q1: tool with `effects: <stream:<policy>>` defaults "
        "to openai dialect — LLM-streaming ecosystem expectation"
    )


# ─── §3 — Q1 type-annotation default → axon (Rule 3) ────────────────


def test_s3_q1_type_annotation_default_axon():
    assert resolve_effective_dialect("", False) == "axon", (
        "33.z.k.c Q1: type-annotation-only stream flow (no tool effect) "
        "defaults to axon dialect — W3C named-events baseline"
    )


# ─── §4 — Total function: every output is in closed catalog ─────────


def test_s4_total_function_closed_catalog():
    catalog = _AXONENDPOINT_TRANSPORT_DIALECTS
    for explicit in ["", "axon", "openai", "anthropic"]:
        for algebraic in [False, True]:
            result = resolve_effective_dialect(explicit, algebraic)
            assert result in catalog, (
                f"resolve_effective_dialect({explicit!r}, {algebraic}) "
                f"= {result!r} — NOT in closed catalog {sorted(catalog)}"
            )


# ─── §5 — Cross-stack parity with Rust resolver ─────────────────────


def test_s5_cross_stack_parity_explicit_paths():
    # Same 6-cell truth table as the Rust resolver tests.
    # 33.z.k.i will eventually run this corpus through both stacks
    # under the dedicated drift gate; this test pins the Python
    # side ahead of that lane.
    cases = [
        ("axon", True, "axon"),
        ("axon", False, "axon"),
        ("openai", True, "openai"),
        ("openai", False, "openai"),
        ("anthropic", True, "anthropic"),
        ("anthropic", False, "anthropic"),
        ("", True, "openai"),
        ("", False, "axon"),
    ]
    for explicit, algebraic, expected in cases:
        assert resolve_effective_dialect(explicit, algebraic) == expected, (
            f"Cross-stack drift: resolve_effective_dialect({explicit!r}, "
            f"{algebraic}) = expected {expected!r}"
        )
