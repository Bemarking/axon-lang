"""§Fase 29.g — Corpus-driven drift gate.

Single source of truth for the cross-lane CI: every case in
``tests/fixtures/fase29_vertical_corpus.json`` is exercised by the
3+1 parallel lanes (vertical-policy + telemetry-sink + suggest-dict
+ compliance-gate). If any one lane's implementation drifts from
the corpus, exactly one lane fails — drift caught at PR time.

The corpus is hand-curated; entries reference the D-letter that
locked the invariant. Updates ship via PRs labeled
`vertical-dict:<vertical>` per D7 (same CODEOWNERS gate as 29.d
dictionary updates).
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from axon_enterprise.diagnostics import (
    DiagnosticPolicy,
    DiagnosticSeverity,
    InMemoryAuditSink,
    ParserDiagnostic,
    TenantVertical,
    assert_no_cross_vertical_contamination,
    clear_dictionary_cache,
    clear_vertical_registry,
    emit_parser_error,
    load_vertical_dictionary,
    resolve_policy_for_vertical,
    set_audit_sink,
    set_tenant_vertical,
)
from axon_enterprise.diagnostics.gate import GateConfig, GateVerdict, evaluate
from axon_enterprise.observability.metrics import PARSER_ERRORS_TOTAL


# ── Corpus loading ────────────────────────────────────────────────────


_CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "fase29_vertical_corpus.json"
)


def _load_corpus() -> dict[str, Any]:
    with _CORPUS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


# ── Module-load corpus sanity ────────────────────────────────────────


def test_corpus_file_exists_at_canonical_path() -> None:
    assert _CORPUS_PATH.exists(), f"corpus missing at {_CORPUS_PATH}"


def test_corpus_loads_with_required_shape() -> None:
    corpus = _load_corpus()
    assert "description" in corpus
    assert "d_letter_anchors" in corpus
    assert isinstance(corpus["d_letter_anchors"], list)
    # Each lane MUST have at least one case so the CI lane never runs empty.
    assert len(corpus["policy_resolution_cases"]) >= 4
    assert len(corpus["telemetry_emission_cases"]) >= 3
    assert len(corpus["suggest_dict_cases"]) >= 4
    assert len(corpus["compliance_gate_cases"]) >= 3


def test_corpus_d_letter_anchors_cover_d1_through_d9() -> None:
    """Every D-letter the spec ratified must appear in the corpus
    anchors (catches drift between plan vivo + corpus)."""
    corpus = _load_corpus()
    anchors_text = " ".join(corpus["d_letter_anchors"])
    for letter in ("D1", "D2", "D3", "D4", "D8", "D9"):
        assert letter in anchors_text, f"corpus missing {letter} anchor"


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_state() -> Generator[None, None, None]:
    """Every corpus entry runs against fresh state — D8 isolation
    by construction.
    """
    clear_vertical_registry()
    clear_dictionary_cache()
    set_audit_sink(None)
    yield
    clear_vertical_registry()
    clear_dictionary_cache()
    set_audit_sink(None)


# ── Lane 1 — Vertical policy resolution ──────────────────────────────


@pytest.mark.parametrize(
    "case",
    _load_corpus()["policy_resolution_cases"],
    ids=lambda c: c["name"],
)
def test_corpus_policy_resolution(case: dict[str, Any]) -> None:
    """Drift gate — every policy-resolution case in the corpus must
    match the live module behavior. D1 + D2 + D9 invariants."""
    vertical = TenantVertical(case["vertical"])
    policy = resolve_policy_for_vertical(vertical)

    assert policy.strict_mode == case["expected_strict_mode"], (
        f"{case['name']}: strict_mode drift "
        f"(corpus says {case['expected_strict_mode']}, module says {policy.strict_mode})"
    )
    assert policy.telemetry_enabled == case["expected_telemetry_enabled"], (
        f"{case['name']}: telemetry_enabled drift"
    )
    assert policy.recovery_mode == case["expected_recovery_mode"], (
        f"{case['name']}: recovery_mode drift"
    )
    assert policy.matches_oss_default() == case["matches_oss_default"], (
        f"{case['name']}: matches_oss_default drift — D9 invariant pin"
    )
    assert policy.to_parse_args() == case["expected_parse_args"], (
        f"{case['name']}: to_parse_args drift"
    )


# ── Lane 2 — Telemetry emission ──────────────────────────────────────


def _counter_value(*, tenant_id: str, vertical: str, code: str) -> float:
    return PARSER_ERRORS_TOTAL.labels(
        tenant_id=tenant_id, vertical=vertical, code=code
    )._value.get()


@pytest.mark.parametrize(
    "case",
    _load_corpus()["telemetry_emission_cases"],
    ids=lambda c: c["name"],
)
def test_corpus_telemetry_emission(case: dict[str, Any]) -> None:
    """Drift gate — every telemetry case in the corpus is replayed
    through `emit_parser_error` + sink assertions validated."""
    vertical = TenantVertical(case["vertical"])
    set_tenant_vertical(case["tenant_id"], vertical)

    sink = InMemoryAuditSink()
    set_audit_sink(sink)

    diag = case["diagnostic"]
    severity_map = {
        "error": DiagnosticSeverity.ERROR,
        "warning": DiagnosticSeverity.WARNING,
        "hint": DiagnosticSeverity.HINT,
    }
    diagnostic = ParserDiagnostic(
        code=diag["code"],
        file_path=diag["file_path"],
        line=diag["line"],
        column=diag["column"],
        severity=severity_map[diag["severity"]],
    )

    counter_before = _counter_value(
        tenant_id=case["tenant_id"],
        vertical=case["vertical"],
        code=diag["code"],
    )

    policy = resolve_policy_for_vertical(vertical)
    emit_parser_error(diagnostic, policy=policy, tenant_id=case["tenant_id"])

    # ── Audit-sink assertions ──────────────────────────────────
    expected_audit = case["expected_audit_entry"]
    entries = sink.entries_for_tenant(case["tenant_id"])
    if expected_audit is None:
        # D9 — generic tenants don't emit; sink remains empty.
        assert entries == [], (
            f"{case['name']}: D9 violation — telemetry-off vertical emitted"
        )
    else:
        assert len(entries) == 1, (
            f"{case['name']}: expected exactly 1 audit entry, got {len(entries)}"
        )
        entry = entries[0]
        assert entry.tenant_id == expected_audit["tenant_id"]
        assert entry.vertical == expected_audit["vertical"]
        assert entry.code == expected_audit["code"]
        assert entry.file_path == expected_audit["file_path"]
        assert entry.line == expected_audit["line"]
        assert entry.column == expected_audit["column"]
        assert entry.severity == expected_audit["severity"]

        # D4 boundary: forbidden fields NEVER present on the captured
        # entry. Uses entry.__slots__ to enumerate the type's exact
        # field set.
        forbidden = set(case["forbidden_fields_on_audit"])
        entry_fields = set(entry.__slots__)
        assert entry_fields.isdisjoint(forbidden), (
            f"{case['name']}: D4 violation — audit entry has forbidden "
            f"fields {entry_fields & forbidden}"
        )

    # ── Counter assertion ──────────────────────────────────────
    counter_after = _counter_value(
        tenant_id=case["tenant_id"],
        vertical=case["vertical"],
        code=diag["code"],
    )
    delta = counter_after - counter_before
    assert delta == case["expected_counter_increment"], (
        f"{case['name']}: counter increment drift "
        f"(corpus says {case['expected_counter_increment']}, observed {delta})"
    )


# ── Lane 3 — Suggest dictionaries ────────────────────────────────────


@pytest.mark.parametrize(
    "case",
    _load_corpus()["suggest_dict_cases"],
    ids=lambda c: c["name"],
)
def test_corpus_suggest_dict(case: dict[str, Any]) -> None:
    """Drift gate — every suggest-dict case validates against the
    in-tree JSON files. D3 provenance + D8 multi-vertical safety + D9
    generic-empty invariants pinned per-case."""

    # Cross-vertical contamination check has a different shape than
    # per-vertical cases.
    if "verticals_compared" in case:
        snapshots = assert_no_cross_vertical_contamination()
        # Verify each compared vertical loaded successfully.
        for slug in case["verticals_compared"]:
            v = TenantVertical(slug)
            assert v in snapshots, f"{case['name']}: vertical {slug} not loaded"
        # The assertion itself raises if contamination is found; if
        # we reach here, pairwise-disjoint holds.
        assert case["expected_pairwise_disjoint"] is True
        return

    vertical = TenantVertical(case["vertical"])
    loaded = load_vertical_dictionary(vertical)
    terms = list(loaded.terms)

    # Size invariants.
    min_terms = case["expected_min_terms"]
    max_terms = case.get("expected_max_terms")
    assert len(terms) >= min_terms, (
        f"{case['name']}: {len(terms)} terms < expected_min_terms={min_terms}"
    )
    if max_terms is not None:
        assert len(terms) <= max_terms, (
            f"{case['name']}: {len(terms)} terms > expected_max_terms={max_terms}"
        )

    # Sample-term presence.
    for sample in case["sample_terms"]:
        assert sample in terms, (
            f"{case['name']}: sample term {sample!r} missing from {vertical.value} dict"
        )

    # Provenance pin — the FIRST sample term's provenance must contain
    # the substring (loose check — exact references can evolve;
    # substring catches structural drift like "switched to a different
    # CFR title" or removed regulatory anchor).
    if case["sample_terms"] and "sample_term_provenance_must_contain" in case:
        first_sample = case["sample_terms"][0]
        provenance = loaded.provenance_for(first_sample)
        assert provenance is not None, (
            f"{case['name']}: {first_sample!r} missing provenance"
        )
        substring = case["sample_term_provenance_must_contain"]
        assert substring in provenance, (
            f"{case['name']}: provenance {provenance!r} missing substring {substring!r}"
        )

    # Category coverage — every advertised category appears in at
    # least one entry.
    if case.get("categories_present"):
        observed_categories = {entry.category for entry in loaded.entries}
        for cat in case["categories_present"]:
            assert cat in observed_categories, (
                f"{case['name']}: category {cat!r} absent from {vertical.value} dict"
            )


# ── Lane 4 — Compliance gate verdict ─────────────────────────────────


@pytest.mark.parametrize(
    "case",
    _load_corpus()["compliance_gate_cases"],
    ids=lambda c: c["name"],
)
def test_corpus_compliance_gate(case: dict[str, Any]) -> None:
    """Drift gate — every compliance-gate case in the corpus runs
    through `evaluate(payload, config)` + the verdict/exit-code
    projection is validated."""

    config_dict = case["config"]
    config = GateConfig(
        max_errors=config_dict["max_errors"],
        max_warnings=config_dict["max_warnings"],
        fail_on_hint=config_dict["fail_on_hint"],
    )

    if "raw_payload" in case:
        payload: Any = case["raw_payload"]
    else:
        payload = {
            "tenant_id": "test-tenant",
            "vertical": "hipaa",
            "mode": case["payload_mode"],
            "entries": case["payload_entries"],
        }

    result = evaluate(payload, config)

    expected_verdict = GateVerdict(case["expected_verdict"])
    assert result.verdict == expected_verdict, (
        f"{case['name']}: verdict drift "
        f"(corpus says {expected_verdict}, module says {result.verdict})"
    )
    assert result.exit_code == case["expected_exit_code"], (
        f"{case['name']}: exit-code drift"
    )
    if "expected_threshold_breached" in case:
        assert result.threshold_breached == case["expected_threshold_breached"], (
            f"{case['name']}: threshold_breached drift"
        )


# ── Cross-lane closure pin ────────────────────────────────────────────


def test_corpus_covers_every_tenant_vertical() -> None:
    """Closed-catalog pin: every variant of :class:`TenantVertical`
    has at least one case in the policy_resolution lane. Adding a 5th
    vertical without updating the corpus surfaces here."""
    corpus = _load_corpus()
    cases = corpus["policy_resolution_cases"]
    verticals_in_corpus = {case["vertical"] for case in cases}
    expected_verticals = {v.value for v in TenantVertical}
    assert verticals_in_corpus == expected_verticals, (
        f"corpus policy lane covers {verticals_in_corpus}; "
        f"expected {expected_verticals}"
    )
