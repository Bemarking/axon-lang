"""§Fase 29.b — Tests for vertical-aware DiagnosticPolicy.

Covers:
  * Pure dispatch over the closed TenantVertical catalog (D1+D2).
  * Closed-catalog enforcement (every variant has a default).
  * Override semantics + immutability (frozen dataclass).
  * CLI argv projection (--strict only when policy says so).
  * Tenant→vertical registry isolation (D8 multi-vertical safety).
  * Current-tenant resolution + D9 backwards-compat fallback.
  * Thread safety of the registry under concurrent set/get.
  * OSS-default invariant (D9 — generic ≡ OSS Fase 28 surface).
"""

from __future__ import annotations

import threading

import pytest

from axon_enterprise.diagnostics import (
    DiagnosticPolicy,
    TenantVertical,
    clear_vertical_registry,
    get_tenant_vertical,
    resolve_policy_for_current_tenant,
    resolve_policy_for_vertical,
    set_tenant_vertical,
)
from axon_enterprise.diagnostics.policy import (
    all_registered_tenants,
    resolve_policy_for_tenant_context,
    unset_tenant_vertical,
)
from axon_enterprise.tenant.context import (
    CURRENT_TENANT,
    TenantContext,
    set_current_tenant,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """Every test runs against an empty registry to keep cases isolated.
    Mirrors the D8 multi-vertical-safety invariant: no cross-test
    bleed between tenants.
    """
    clear_vertical_registry()
    yield
    clear_vertical_registry()


@pytest.fixture
def reset_tenant_context() -> None:
    """Reset CURRENT_TENANT to None between tests that exercise it."""
    token = CURRENT_TENANT.set(None)
    yield
    CURRENT_TENANT.reset(token)


# ── §1 — Closed-catalog enforcement ──────────────────────────────────


def test_tenant_vertical_catalog_has_exactly_four_variants() -> None:
    """Closed-catalog pin: adding a 5th vertical must update this test
    AND every consumer's pattern matching. The pin caught at build
    time prevents drift.
    """
    assert set(TenantVertical) == {
        TenantVertical.GENERIC,
        TenantVertical.HIPAA,
        TenantVertical.LEGAL,
        TenantVertical.FINTECH,
    }
    assert len(TenantVertical) == 4


def test_every_vertical_has_a_default_policy() -> None:
    """The module-load assertion already enforces this; the test
    duplicates the contract at the consumer layer so a regression
    surfaces in the test report, not only at import time.
    """
    for vertical in TenantVertical:
        policy = resolve_policy_for_vertical(vertical)
        assert policy.vertical == vertical
        assert isinstance(policy.strict_mode, bool)
        assert isinstance(policy.telemetry_enabled, bool)
        assert isinstance(policy.recovery_mode, bool)


# ── §2 — Per-vertical default policies (D1 + D2 ratificadas) ─────────


def test_generic_vertical_defaults_match_oss_surface_d9() -> None:
    """D9 backwards-compat: generic tenants get the OSS Fase 28 surface
    verbatim. No strict, no telemetry, recovery on.
    """
    policy = resolve_policy_for_vertical(TenantVertical.GENERIC)
    assert policy.strict_mode is False
    assert policy.telemetry_enabled is False
    assert policy.recovery_mode is True
    assert policy.extra_keywords == ()
    assert policy.matches_oss_default()


def test_hipaa_vertical_defaults_strict_with_telemetry_d1_d2() -> None:
    """D1: HIPAA → strict mode. D2: telemetry-on for audit trail."""
    policy = resolve_policy_for_vertical(TenantVertical.HIPAA)
    assert policy.strict_mode is True
    assert policy.telemetry_enabled is True
    assert policy.recovery_mode is False
    assert not policy.matches_oss_default()


def test_legal_vertical_defaults_strict_with_telemetry_d1_d2() -> None:
    """D1: legal → strict mode. D2: telemetry-on for FRE 502 trail."""
    policy = resolve_policy_for_vertical(TenantVertical.LEGAL)
    assert policy.strict_mode is True
    assert policy.telemetry_enabled is True
    assert policy.recovery_mode is False


def test_fintech_vertical_defaults_recovery_with_telemetry_d1_d2() -> None:
    """D1: fintech → recovery + telemetry-on (full diagnostic surface
    for BSA/OFAC/MiFID II audit).
    """
    policy = resolve_policy_for_vertical(TenantVertical.FINTECH)
    assert policy.strict_mode is False
    assert policy.telemetry_enabled is True
    assert policy.recovery_mode is True


# ── §3 — TenantVertical.from_str fallback semantics ──────────────────


def test_from_str_known_slugs_round_trip() -> None:
    for v in TenantVertical:
        assert TenantVertical.from_str(v.value) == v


def test_from_str_case_insensitive() -> None:
    assert TenantVertical.from_str("HIPAA") == TenantVertical.HIPAA
    assert TenantVertical.from_str("Legal") == TenantVertical.LEGAL
    assert TenantVertical.from_str("FINTECH") == TenantVertical.FINTECH


def test_from_str_unknown_falls_back_to_generic() -> None:
    assert TenantVertical.from_str("crypto") == TenantVertical.GENERIC
    assert TenantVertical.from_str("aerospace") == TenantVertical.GENERIC
    assert TenantVertical.from_str("xyz_42") == TenantVertical.GENERIC


def test_from_str_empty_or_none_returns_generic_d9() -> None:
    assert TenantVertical.from_str("") == TenantVertical.GENERIC
    assert TenantVertical.from_str(None) == TenantVertical.GENERIC


# ── §4 — Override semantics (frozen + with_override) ─────────────────


def test_policy_is_frozen_immutable() -> None:
    policy = resolve_policy_for_vertical(TenantVertical.HIPAA)
    with pytest.raises((AttributeError, TypeError)):
        policy.strict_mode = False  # type: ignore[misc]


def test_with_override_returns_new_instance() -> None:
    """Frozen + with_override semantics: original unchanged, new
    instance has the override applied.
    """
    original = resolve_policy_for_vertical(TenantVertical.HIPAA)
    overridden = original.with_override(strict_mode=False)
    assert original.strict_mode is True
    assert overridden.strict_mode is False
    assert overridden is not original
    # Other fields preserved.
    assert overridden.vertical == original.vertical
    assert overridden.telemetry_enabled == original.telemetry_enabled
    assert overridden.recovery_mode == original.recovery_mode


def test_with_override_supports_all_dials_independently() -> None:
    policy = resolve_policy_for_vertical(TenantVertical.GENERIC)
    p2 = policy.with_override(strict_mode=True)
    p3 = policy.with_override(telemetry_enabled=True)
    p4 = policy.with_override(recovery_mode=False)
    p5 = policy.with_override(extra_keywords=("a", "b"))
    assert p2.strict_mode is True
    assert p3.telemetry_enabled is True
    assert p4.recovery_mode is False
    assert p5.extra_keywords == ("a", "b")


def test_with_override_none_preserves_existing_value() -> None:
    """Passing None for any field keeps that field's current value —
    the override only applies the named flips.
    """
    original = resolve_policy_for_vertical(TenantVertical.LEGAL)
    overridden = original.with_override()
    assert overridden == original


def test_with_override_does_not_change_vertical() -> None:
    """Vertical is intentionally not overridable through with_override
    — changing a tenant's vertical is a tenant-management operation.
    """
    policy = resolve_policy_for_vertical(TenantVertical.HIPAA)
    overridden = policy.with_override(strict_mode=False)
    assert overridden.vertical == TenantVertical.HIPAA


# ── §5 — CLI argv projection (D5 OSS contract preserved) ─────────────


def test_to_parse_args_generic_is_empty() -> None:
    """Generic policy projects to no extra CLI flags → OSS default."""
    policy = resolve_policy_for_vertical(TenantVertical.GENERIC)
    assert policy.to_parse_args() == []


def test_to_parse_args_strict_emits_strict_flag() -> None:
    for vertical in (TenantVertical.HIPAA, TenantVertical.LEGAL):
        policy = resolve_policy_for_vertical(vertical)
        assert "--strict" in policy.to_parse_args()


def test_to_parse_args_fintech_no_strict() -> None:
    """Fintech is recovery + telemetry-on, NOT strict (per D1)."""
    policy = resolve_policy_for_vertical(TenantVertical.FINTECH)
    assert policy.to_parse_args() == []


def test_to_parse_args_overrides_respected() -> None:
    """Overriding strict_mode flips the projected args."""
    policy = resolve_policy_for_vertical(TenantVertical.HIPAA).with_override(strict_mode=False)
    assert "--strict" not in policy.to_parse_args()


# ── §6 — Tenant → vertical registry ──────────────────────────────────


def test_unregistered_tenant_resolves_to_generic_d9() -> None:
    """D9: tenants without a registered vertical get OSS surface."""
    assert get_tenant_vertical("never-registered") == TenantVertical.GENERIC


def test_set_then_get_round_trips() -> None:
    set_tenant_vertical("tenant-a", TenantVertical.HIPAA)
    assert get_tenant_vertical("tenant-a") == TenantVertical.HIPAA


def test_set_is_idempotent_last_write_wins() -> None:
    set_tenant_vertical("tenant-a", TenantVertical.HIPAA)
    set_tenant_vertical("tenant-a", TenantVertical.LEGAL)
    assert get_tenant_vertical("tenant-a") == TenantVertical.LEGAL


def test_unset_tenant_vertical_idempotent() -> None:
    """Unsetting an unregistered tenant must not raise."""
    unset_tenant_vertical("never-registered")
    set_tenant_vertical("tenant-a", TenantVertical.HIPAA)
    unset_tenant_vertical("tenant-a")
    assert get_tenant_vertical("tenant-a") == TenantVertical.GENERIC


def test_clear_registry_resets_all() -> None:
    set_tenant_vertical("tenant-a", TenantVertical.HIPAA)
    set_tenant_vertical("tenant-b", TenantVertical.LEGAL)
    clear_vertical_registry()
    assert get_tenant_vertical("tenant-a") == TenantVertical.GENERIC
    assert get_tenant_vertical("tenant-b") == TenantVertical.GENERIC
    assert all_registered_tenants() == {}


def test_all_registered_tenants_is_defensive_copy() -> None:
    """Mutating the returned dict must not affect the registry."""
    set_tenant_vertical("tenant-a", TenantVertical.HIPAA)
    snapshot = all_registered_tenants()
    snapshot["tenant-a"] = TenantVertical.LEGAL
    snapshot["tenant-b"] = TenantVertical.FINTECH
    assert get_tenant_vertical("tenant-a") == TenantVertical.HIPAA
    assert get_tenant_vertical("tenant-b") == TenantVertical.GENERIC


# ── §7 — Multi-tenant isolation (D8 multi-vertical safety) ───────────


def test_d8_setting_vertical_for_tenant_a_does_not_affect_tenant_b() -> None:
    """D8 ratificada — vertical X policy MUST NEVER affect vertical Y
    tenants. Non-negotiable for multi-tenant SaaS.
    """
    set_tenant_vertical("tenant-a", TenantVertical.HIPAA)
    assert get_tenant_vertical("tenant-b") == TenantVertical.GENERIC
    set_tenant_vertical("tenant-b", TenantVertical.FINTECH)
    # Tenant A's vertical preserved.
    assert get_tenant_vertical("tenant-a") == TenantVertical.HIPAA
    assert get_tenant_vertical("tenant-b") == TenantVertical.FINTECH


def test_d8_policies_resolved_per_tenant_independently() -> None:
    set_tenant_vertical("hospital-x", TenantVertical.HIPAA)
    set_tenant_vertical("bank-y", TenantVertical.FINTECH)
    set_tenant_vertical("firm-z", TenantVertical.LEGAL)

    # Each tenant's policy is independent.
    ctx_hospital = TenantContext(tenant_id="hospital-x")
    ctx_bank = TenantContext(tenant_id="bank-y")
    ctx_firm = TenantContext(tenant_id="firm-z")

    p_hospital = resolve_policy_for_tenant_context(ctx_hospital)
    p_bank = resolve_policy_for_tenant_context(ctx_bank)
    p_firm = resolve_policy_for_tenant_context(ctx_firm)

    assert p_hospital.vertical == TenantVertical.HIPAA
    assert p_bank.vertical == TenantVertical.FINTECH
    assert p_firm.vertical == TenantVertical.LEGAL

    assert p_hospital.strict_mode is True
    assert p_bank.strict_mode is False  # fintech is recovery-mode
    assert p_firm.strict_mode is True


# ── §8 — Current-tenant resolution ───────────────────────────────────


def test_no_tenant_context_resolves_to_generic_d9(reset_tenant_context: None) -> None:
    """D9: no tenant context = OSS surface."""
    policy = resolve_policy_for_current_tenant()
    assert policy.vertical == TenantVertical.GENERIC
    assert policy.matches_oss_default()


def test_tenant_context_with_registered_vertical_resolves_policy() -> None:
    set_tenant_vertical("clinic-x", TenantVertical.HIPAA)
    token = set_current_tenant(TenantContext(tenant_id="clinic-x"))
    try:
        policy = resolve_policy_for_current_tenant()
        assert policy.vertical == TenantVertical.HIPAA
        assert policy.strict_mode is True
    finally:
        CURRENT_TENANT.reset(token)


def test_tenant_context_without_registered_vertical_falls_back_to_generic() -> None:
    """A tenant context exists but the tenant has never been
    registered with a vertical → OSS surface.
    """
    token = set_current_tenant(TenantContext(tenant_id="brand-new-tenant"))
    try:
        policy = resolve_policy_for_current_tenant()
        assert policy.vertical == TenantVertical.GENERIC
        assert policy.matches_oss_default()
    finally:
        CURRENT_TENANT.reset(token)


# ── §9 — Thread safety of the registry ───────────────────────────────


def test_concurrent_set_and_get_does_not_corrupt_registry() -> None:
    """Stress test: 50 threads each setting + reading their own
    tenant_id. Final registry must contain exactly the expected
    mapping.
    """
    tenant_ids = [f"tenant-{i}" for i in range(50)]
    verticals = [
        TenantVertical.HIPAA,
        TenantVertical.LEGAL,
        TenantVertical.FINTECH,
        TenantVertical.GENERIC,
    ]

    def worker(idx: int) -> None:
        tid = tenant_ids[idx]
        v = verticals[idx % len(verticals)]
        for _ in range(100):
            set_tenant_vertical(tid, v)
            recovered = get_tenant_vertical(tid)
            # The tenant might race other threads (different tenant
            # ids), but its OWN value must always read back as what
            # we just set since the registry lock serialises.
            assert recovered == v

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for idx, tid in enumerate(tenant_ids):
        expected = verticals[idx % len(verticals)]
        assert get_tenant_vertical(tid) == expected


# ── §10 — D9 OSS-default-invariant pin ───────────────────────────────


def test_d9_oss_default_invariant_pinned() -> None:
    """D9 ratificada — the GENERIC default policy MUST equal the OSS
    Fase 28 surface byte-for-byte. matches_oss_default() encodes the
    invariant; this test pins it at the test level too so an
    accidental shift surfaces here AND in the predicate.
    """
    generic = resolve_policy_for_vertical(TenantVertical.GENERIC)
    assert generic.matches_oss_default()

    # Any non-generic vertical CANNOT match OSS default.
    for vertical in (
        TenantVertical.HIPAA,
        TenantVertical.LEGAL,
        TenantVertical.FINTECH,
    ):
        non_generic = resolve_policy_for_vertical(vertical)
        assert not non_generic.matches_oss_default(), (
            f"{vertical} resolved to a policy that matches the OSS default "
            "— D9 violated; non-generic verticals must differ from generic."
        )


# ── §11 — Extra keywords plumbing (29.d hook contract) ───────────────


def test_extra_keywords_default_empty_tuple() -> None:
    """The 29.d hook contract: default policies start with no extra
    keywords; 29.d adds them via .with_override(extra_keywords=...).
    """
    for vertical in TenantVertical:
        policy = resolve_policy_for_vertical(vertical)
        assert policy.extra_keywords == ()


def test_with_override_extra_keywords_replaces_tuple() -> None:
    policy = resolve_policy_for_vertical(TenantVertical.HIPAA)
    p2 = policy.with_override(extra_keywords=("phi", "hipaa", "164"))
    assert p2.extra_keywords == ("phi", "hipaa", "164")
    # Original unchanged (frozen).
    assert policy.extra_keywords == ()


# ── §12 — Equality + hashability (frozen dataclass invariant) ────────


def test_two_policies_with_same_fields_are_equal() -> None:
    p1 = DiagnosticPolicy(
        vertical=TenantVertical.HIPAA,
        strict_mode=True,
        telemetry_enabled=True,
        recovery_mode=False,
    )
    p2 = DiagnosticPolicy(
        vertical=TenantVertical.HIPAA,
        strict_mode=True,
        telemetry_enabled=True,
        recovery_mode=False,
    )
    assert p1 == p2


def test_policies_with_different_verticals_unequal() -> None:
    p_hipaa = resolve_policy_for_vertical(TenantVertical.HIPAA)
    p_legal = resolve_policy_for_vertical(TenantVertical.LEGAL)
    # Both strict + telemetry-on + non-recovery, but different vertical.
    assert p_hipaa != p_legal
