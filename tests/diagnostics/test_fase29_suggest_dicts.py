"""§Fase 29.d — Tests for vertical-aware suggest dictionaries.

Covers:
  * D3 provenance discipline: every entry has a non-empty provenance.
  * D7 update process: schema invariants (term/provenance/category
    non-empty) enforced at load time.
  * D8 multi-vertical safety: HIPAA terms NEVER appear in legal /
    fintech dicts; cross-vertical contamination detector works.
  * D9 backwards-compat: GENERIC vertical loads to an empty dictionary.
  * Closed catalog: every TenantVertical has a load path (file or
    empty-dict fallback).
  * Loader cache: subsequent calls return the cached instance.
  * DiagnosticPolicy integration: extra_keywords plumbing matches.
  * Validation: malformed payloads raise loud ValueErrors.
  * First-cut size: each vertical with a dict ships ≥ 50 terms (per
    D3 resolution).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from importlib.resources import files

from axon_enterprise.diagnostics import (
    DictEntry,
    TenantVertical,
    VerticalDictionary,
    assert_no_cross_vertical_contamination,
    clear_dictionary_cache,
    load_vertical_dictionary,
    policy_with_suggest_dict,
    resolve_policy_for_vertical,
    resolve_policy_with_dict_for_vertical,
    terms_for_vertical,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    """Each test gets a fresh load cache so D8 invariants are checked
    against re-loaded JSON, not stale state."""
    clear_dictionary_cache()
    yield
    clear_dictionary_cache()


# ── §1 — Closed-catalog loadability ──────────────────────────────────


def test_every_tenant_vertical_loads_without_error() -> None:
    """Every variant of TenantVertical MUST produce a
    :class:`VerticalDictionary` — generic returns an empty one;
    HIPAA / legal / fintech load the per-vertical file.
    """
    for vertical in TenantVertical:
        loaded = load_vertical_dictionary(vertical)
        assert isinstance(loaded, VerticalDictionary)
        assert loaded.vertical == vertical


def test_generic_vertical_loads_to_empty_dict_d9() -> None:
    """D9 ratificada — generic tenants get the OSS Fase 28 suggest
    surface unchanged. No vertical-specific terms surface for them.
    """
    loaded = load_vertical_dictionary(TenantVertical.GENERIC)
    assert loaded.entries == ()
    assert loaded.terms == ()
    assert loaded.version == "0.0.0"


# ── §2 — D3 provenance discipline (every entry has provenance) ───────


def test_d3_every_loaded_entry_has_non_empty_provenance() -> None:
    """D3 ratificada — every entry across every vertical dict carries
    a non-empty provenance reference. The DictEntry.__post_init__
    enforces this at load time; this test pins it at the consumer
    layer too.
    """
    for vertical in (
        TenantVertical.HIPAA,
        TenantVertical.LEGAL,
        TenantVertical.FINTECH,
    ):
        loaded = load_vertical_dictionary(vertical)
        for entry in loaded.entries:
            assert entry.provenance, (
                f"{vertical.value}:{entry.term} violates D3: empty provenance"
            )
            assert entry.term, (
                f"{vertical.value}: entry with empty term + provenance="
                f"{entry.provenance!r}"
            )
            assert entry.category, (
                f"{vertical.value}:{entry.term} has empty category"
            )


def test_d3_empty_provenance_rejected_at_construction() -> None:
    """D3 ratificada — the type itself rejects empty provenance.
    Caught at DictEntry construction, not at integration time.
    """
    with pytest.raises(ValueError, match="D3.*provenance"):
        DictEntry(term="bogus", provenance="", category="x")
    with pytest.raises(ValueError, match="D3.*provenance"):
        DictEntry(term="bogus", provenance="   ", category="x")


def test_d3_empty_term_or_category_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="empty term"):
        DictEntry(term="", provenance="https://example.org", category="x")
    with pytest.raises(ValueError, match="empty category"):
        DictEntry(term="foo", provenance="https://example.org", category="")


# ── §3 — First-cut size invariant (~50 terms per vertical per D3 res) ─


def test_each_vertical_dict_ships_at_least_50_terms() -> None:
    """D3 resolution — ~50 terms per vertical first-cut. The PR-review
    process per D7 can grow this; the test pins the lower bound.
    """
    for vertical in (
        TenantVertical.HIPAA,
        TenantVertical.LEGAL,
        TenantVertical.FINTECH,
    ):
        terms = terms_for_vertical(vertical)
        assert len(terms) >= 50, (
            f"{vertical.value} dict has only {len(terms)} terms (need ≥ 50)"
        )


def test_each_vertical_dict_carries_semver_version() -> None:
    """Every dict file declares a version field, semver-shaped."""
    import re

    semver_re = re.compile(r"^\d+\.\d+\.\d+$")
    for vertical in (
        TenantVertical.HIPAA,
        TenantVertical.LEGAL,
        TenantVertical.FINTECH,
    ):
        loaded = load_vertical_dictionary(vertical)
        assert semver_re.match(loaded.version), (
            f"{vertical.value} version={loaded.version!r} is not semver-shaped"
        )


# ── §4 — D8 multi-vertical safety (no cross-vertical contamination) ──


def test_d8_hipaa_terms_disjoint_from_legal() -> None:
    """D8 ratificada — HIPAA terms NEVER appear in the legal dict.
    Adopter on a HIPAA tenant must not see `attorney_client_privilege`
    suggested for a typo'd healthcare keyword.
    """
    hipaa = set(terms_for_vertical(TenantVertical.HIPAA))
    legal = set(terms_for_vertical(TenantVertical.LEGAL))
    overlap = hipaa & legal
    assert overlap == set(), f"D8 violation: {sorted(overlap)} in both"


def test_d8_hipaa_terms_disjoint_from_fintech() -> None:
    hipaa = set(terms_for_vertical(TenantVertical.HIPAA))
    fintech = set(terms_for_vertical(TenantVertical.FINTECH))
    overlap = hipaa & fintech
    assert overlap == set(), f"D8 violation: {sorted(overlap)} in both"


def test_d8_legal_terms_disjoint_from_fintech() -> None:
    legal = set(terms_for_vertical(TenantVertical.LEGAL))
    fintech = set(terms_for_vertical(TenantVertical.FINTECH))
    overlap = legal & fintech
    assert overlap == set(), f"D8 violation: {sorted(overlap)} in both"


def test_d8_cross_vertical_assertion_passes_for_in_tree_dicts() -> None:
    """The :func:`assert_no_cross_vertical_contamination` helper is
    the canonical CI gate (29.g wires it). Must pass for the in-tree
    dictionaries.
    """
    snapshot = assert_no_cross_vertical_contamination()
    assert set(snapshot.keys()) == {
        TenantVertical.HIPAA,
        TenantVertical.LEGAL,
        TenantVertical.FINTECH,
    }
    for vertical, terms in snapshot.items():
        assert len(terms) >= 50


def test_d8_payload_vertical_mismatch_rejected(tmp_path: Path, monkeypatch) -> None:
    """If a JSON file's `vertical` field doesn't match the file name,
    the loader raises — prevents copy-paste accidents from leaking
    terms across verticals.
    """
    from axon_enterprise.diagnostics import suggest_dicts

    # Build a payload that claims to be HIPAA but is actually placed
    # via the legal load path. We exercise this by invoking the
    # internal validator directly (the loader's path indirection
    # makes monkeypatching the on-disk file fragile).
    payload = {
        "vertical": "legal",  # mismatched declaration
        "version": "1.0.0",
        "description": "test",
        "entries": [],
    }
    with pytest.raises(ValueError, match="D8 violation"):
        suggest_dicts._validate_payload(payload, TenantVertical.HIPAA)


# ── §5 — Duplicate term detection within a single dict ───────────────


def test_duplicate_term_within_dict_rejected() -> None:
    """Within a single vertical's dict, every term MUST be unique.
    Adopter Levenshtein hints depend on this — duplicate entries
    would surface inconsistent provenance / category metadata.
    """
    from axon_enterprise.diagnostics import suggest_dicts

    payload_entries = [
        {"term": "phi", "provenance": "https://x/1", "category": "compliance"},
        {"term": "phi", "provenance": "https://x/2", "category": "compliance"},
    ]
    with pytest.raises(ValueError, match="duplicate term"):
        suggest_dicts._parse_entries(payload_entries, TenantVertical.HIPAA)


# ── §6 — Loader cache (per-process, idempotent) ──────────────────────


def test_load_returns_same_instance_within_process() -> None:
    """Loader caches per-vertical. Two consecutive loads return the
    same object — important for the suggest-engine that hits this
    on every parser invocation.
    """
    first = load_vertical_dictionary(TenantVertical.HIPAA)
    second = load_vertical_dictionary(TenantVertical.HIPAA)
    assert first is second


def test_clear_cache_then_reload_returns_new_instance() -> None:
    first = load_vertical_dictionary(TenantVertical.HIPAA)
    clear_dictionary_cache()
    second = load_vertical_dictionary(TenantVertical.HIPAA)
    assert first is not second
    # But equal in content (loaded from same file).
    assert first.entries == second.entries


# ── §7 — Integration with DiagnosticPolicy (29.b hook) ───────────────


def test_policy_with_suggest_dict_populates_extra_keywords() -> None:
    """The 29.b hook `DiagnosticPolicy.extra_keywords` is now wired
    via :func:`policy_with_suggest_dict`."""
    base_policy = resolve_policy_for_vertical(TenantVertical.HIPAA)
    assert base_policy.extra_keywords == ()  # 29.b default empty
    enriched = policy_with_suggest_dict(base_policy)
    assert len(enriched.extra_keywords) >= 50
    assert "phi" in enriched.extra_keywords
    # Vertical is preserved.
    assert enriched.vertical == TenantVertical.HIPAA


def test_policy_with_suggest_dict_idempotent() -> None:
    """Calling the enricher twice keeps the same extra_keywords (the
    underlying dict is cached so the tuple is identical).
    """
    base_policy = resolve_policy_for_vertical(TenantVertical.LEGAL)
    once = policy_with_suggest_dict(base_policy)
    twice = policy_with_suggest_dict(once)
    assert once.extra_keywords == twice.extra_keywords


def test_policy_with_suggest_dict_generic_yields_empty() -> None:
    """D9 — generic policy enriched with the suggest dict has 0 extra
    keywords (because the generic dict is empty).
    """
    base_policy = resolve_policy_for_vertical(TenantVertical.GENERIC)
    enriched = policy_with_suggest_dict(base_policy)
    assert enriched.extra_keywords == ()
    assert enriched.matches_oss_default()


def test_resolve_policy_with_dict_one_shot_helper() -> None:
    """One-shot helper composes resolve + enrich."""
    policy = resolve_policy_with_dict_for_vertical(TenantVertical.FINTECH)
    assert policy.vertical == TenantVertical.FINTECH
    assert policy.telemetry_enabled is True  # fintech default
    assert "pci_req_10" in policy.extra_keywords


# ── §8 — VerticalDictionary accessor helpers ─────────────────────────


def test_category_for_lookup() -> None:
    hipaa = load_vertical_dictionary(TenantVertical.HIPAA)
    assert hipaa.category_for("phi") == "compliance"
    assert hipaa.category_for("never-existed") is None


def test_provenance_for_lookup() -> None:
    hipaa = load_vertical_dictionary(TenantVertical.HIPAA)
    prov = hipaa.provenance_for("phi")
    assert prov is not None
    assert "45 CFR" in prov
    assert hipaa.provenance_for("never-existed") is None


# ── §9 — Validation: malformed payloads ──────────────────────────────


def test_non_dict_payload_rejected() -> None:
    from axon_enterprise.diagnostics import suggest_dicts

    with pytest.raises(ValueError, match="must be a JSON object"):
        suggest_dicts._validate_payload(["not a dict"], TenantVertical.HIPAA)  # type: ignore[arg-type]


def test_payload_without_entries_rejected() -> None:
    from axon_enterprise.diagnostics import suggest_dicts

    with pytest.raises(ValueError, match="entries"):
        suggest_dicts._validate_payload(
            {"vertical": "hipaa", "version": "1.0.0"},
            TenantVertical.HIPAA,
        )


def test_non_object_entry_rejected() -> None:
    from axon_enterprise.diagnostics import suggest_dicts

    with pytest.raises(ValueError, match="must be a JSON object"):
        suggest_dicts._parse_entries(["not-a-dict"], TenantVertical.HIPAA)  # type: ignore[list-item]


# ── §10 — JSON files on-disk match the loaded shape ──────────────────


def _load_raw(vertical_slug: str) -> dict:
    """Read the raw JSON without going through the loader."""
    path = files("axon_enterprise.diagnostics.dicts").joinpath(f"{vertical_slug}.json")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def test_raw_files_carry_vertical_version_description() -> None:
    for slug in ("hipaa", "legal", "fintech"):
        payload = _load_raw(slug)
        assert payload["vertical"] == slug
        assert "version" in payload
        assert "description" in payload
        assert "entries" in payload
        assert isinstance(payload["entries"], list)


def test_raw_files_every_entry_has_term_provenance_category() -> None:
    """File-level shape pin: each entry MUST carry all three required
    keys. Catches PRs that ship malformed entries before any consumer
    code runs.
    """
    for slug in ("hipaa", "legal", "fintech"):
        payload = _load_raw(slug)
        for idx, entry in enumerate(payload["entries"]):
            assert "term" in entry, f"{slug}#{idx}: missing term"
            assert "provenance" in entry, f"{slug}#{idx}: missing provenance"
            assert "category" in entry, f"{slug}#{idx}: missing category"
            assert entry["term"].strip(), f"{slug}#{idx}: empty term"
            assert entry["provenance"].strip(), f"{slug}#{idx}: empty provenance"
            assert entry["category"].strip(), f"{slug}#{idx}: empty category"


# ── §11 — Immutability of loaded structures (frozen + slots) ─────────


def test_vertical_dictionary_is_frozen() -> None:
    loaded = load_vertical_dictionary(TenantVertical.HIPAA)
    with pytest.raises((AttributeError, TypeError)):
        loaded.entries = ()  # type: ignore[misc]


def test_dict_entry_is_frozen() -> None:
    entry = DictEntry(term="phi", provenance="45 CFR", category="compliance")
    with pytest.raises((AttributeError, TypeError)):
        entry.term = "ephi"  # type: ignore[misc]


# ── §12 — Terms are valid identifier-shaped (Levenshtein-suitable) ───


def test_all_terms_are_lowercase_snake_or_alphanumeric() -> None:
    """Suggest hints work on identifier-shaped tokens. Validate every
    term in every dict matches a permissive identifier shape (lower-
    case letters + digits + underscores).
    """
    import re

    identifier_re = re.compile(r"^[a-z][a-z0-9_]*$")
    for vertical in (
        TenantVertical.HIPAA,
        TenantVertical.LEGAL,
        TenantVertical.FINTECH,
    ):
        for term in terms_for_vertical(vertical):
            assert identifier_re.match(term), (
                f"{vertical.value}: term {term!r} is not a valid lowercase "
                "identifier; Levenshtein hints expect identifier-shaped tokens"
            )
