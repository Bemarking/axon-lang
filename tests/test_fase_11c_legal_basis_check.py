"""
Unit tests — §λ-L-E Fase 11.c Python legal-basis checker (tool-level).

Mirrors the Rust pass in ``axon-rs::type_checker``. The parity
harness (see ``tests/parity/``) asserts both sides emit identical
diagnostics for the same effect list.
"""

from __future__ import annotations

from axon.compiler.legal_basis import (
    LEGAL_BASIS_CATALOG,
    Regulation,
    is_legal_basis,
    regulation_for,
)
from axon.compiler.legal_basis_check import (
    check_tool_sensitive_coherence,
    classify_effect,
    effect_declares_legal_basis,
    effect_declares_sensitive,
)


# ── Catalogue invariants ──────────────────────────────────────────────


def test_catalog_contains_all_regulations() -> None:
    assert "GDPR.Art6.Consent" in LEGAL_BASIS_CATALOG
    assert "CCPA.1798_100" in LEGAL_BASIS_CATALOG
    assert "SOX.404" in LEGAL_BASIS_CATALOG
    assert "HIPAA.164_502" in LEGAL_BASIS_CATALOG
    assert "GLBA.501b" in LEGAL_BASIS_CATALOG
    assert "PCI_DSS.v4_Req3" in LEGAL_BASIS_CATALOG


def test_is_legal_basis_case_sensitive() -> None:
    assert is_legal_basis("HIPAA.164_502")
    assert not is_legal_basis("hipaa.164_502")
    assert not is_legal_basis("")


def test_regulation_for_maps_every_slug() -> None:
    mapping = {
        "GDPR.Art6.Consent": Regulation.GDPR,
        "CCPA.1798_100": Regulation.CCPA,
        "SOX.404": Regulation.SOX,
        "HIPAA.164_502": Regulation.HIPAA,
        "GLBA.501b": Regulation.GLBA,
        "PCI_DSS.v4_Req3": Regulation.PCI_DSS,
    }
    for slug, reg in mapping.items():
        assert regulation_for(slug) is reg
    assert regulation_for("UNKNOWN.x") is None


# ── Classifier helpers ────────────────────────────────────────────────


def test_classify_effect_plain() -> None:
    assert classify_effect("io") == ("io", None)


def test_classify_effect_composite() -> None:
    assert classify_effect("sensitive:health_data") == (
        "sensitive",
        "health_data",
    )
    assert classify_effect("legal:HIPAA.164_502") == (
        "legal",
        "HIPAA.164_502",
    )


def test_effect_declares_sensitive() -> None:
    assert effect_declares_sensitive("sensitive:phi")
    assert not effect_declares_sensitive("sensitive")
    assert not effect_declares_sensitive("io")


def test_effect_declares_legal_basis() -> None:
    assert effect_declares_legal_basis("legal:HIPAA.164_502")
    assert not effect_declares_legal_basis("legal")
    assert not effect_declares_legal_basis("legal:MADE_UP")
    assert not effect_declares_legal_basis("legal:hipaa.164_502")  # case-sensitive


# ── check_tool_sensitive_coherence ───────────────────────────────────


def _check(effects: list[str]) -> list[str]:
    diags = check_tool_sensitive_coherence(
        tool_name="t",
        tool_line=1,
        tool_column=0,
        effects=effects,
    )
    return [d.message for d in diags]


def test_clean_tool_with_no_sensitive_or_legal_passes() -> None:
    assert _check(["io", "network"]) == []


def test_sensitive_without_legal_errors() -> None:
    msgs = _check(["sensitive:health_data"])
    assert len(msgs) == 1
    assert "no 'legal:<basis>' effect" in msgs[0]


def test_sensitive_with_matching_legal_passes() -> None:
    msgs = _check(["sensitive:health_data", "legal:HIPAA.164_502"])
    assert msgs == []


def test_sensitive_without_category_errors() -> None:
    msgs = _check(["sensitive", "legal:HIPAA.164_502"])
    assert any("jurisdiction qualifier" in m for m in msgs)


def test_legal_without_qualifier_errors() -> None:
    msgs = _check(["sensitive:health_data", "legal"])
    assert any("basis qualifier" in m for m in msgs)


def test_legal_with_unknown_basis_errors() -> None:
    msgs = _check(["sensitive:health_data", "legal:MADE_UP.Act42"])
    assert any("Unknown legal basis" in m for m in msgs)


def test_multiple_sensitive_categories_bundled_in_one_error() -> None:
    msgs = _check(["sensitive:health_data", "sensitive:financial_txn"])
    # Single diagnostic that lists both categories.
    err_msgs = [m for m in msgs if "no 'legal:<basis>' effect" in m]
    assert len(err_msgs) == 1
    assert "health_data" in err_msgs[0]
    assert "financial_txn" in err_msgs[0]


def test_legal_alone_without_sensitive_is_tolerated() -> None:
    # A tool that carries a broad legal authorization without
    # processing regulated data is allowed — not every legal declaration
    # pairs with a sensitive effect.
    msgs = _check(["io", "legal:SOX.404"])
    assert msgs == []


def test_every_catalog_slug_passes_legal_with_sensitive() -> None:
    for slug in LEGAL_BASIS_CATALOG:
        msgs = _check(["sensitive:category_a", f"legal:{slug}"])
        assert msgs == [], f"expected {slug} to pass, got {msgs}"
