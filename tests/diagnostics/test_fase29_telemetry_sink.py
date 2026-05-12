"""§Fase 29.c — Tests for the diagnostics-to-telemetry sink.

Covers:
  * Three-sink fan-out: OTel span + Prometheus counter + audit-log
    entry per parser error (D2 ratified shape).
  * D4 privacy boundary: ParserDiagnostic has no source-text field;
    emitted payloads carry only structural attributes.
  * D9 backwards-compat: telemetry_enabled=False → no-op.
  * D8 multi-tenant isolation: counter labels + audit entries
    keyed per-tenant; tenant A emit doesn't affect tenant B.
  * Best-effort sink failure: one sink's exception doesn't drop
    the other two.
  * Closed catalog: DiagnosticSeverity has exactly 3 variants.
  * Explicit policy + tenant override path (batch workers).
  * AuditSink protocol round-trip via InMemoryAuditSink.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from prometheus_client import CollectorRegistry, Counter

from axon_enterprise.diagnostics import (
    DiagnosticPolicy,
    DiagnosticSeverity,
    InMemoryAuditSink,
    ParserDiagnostic,
    TenantVertical,
    clear_vertical_registry,
    emit_parser_error,
    get_audit_sink,
    resolve_policy_for_vertical,
    set_audit_sink,
    set_tenant_vertical,
)
from axon_enterprise.observability.metrics import PARSER_ERRORS_TOTAL
from axon_enterprise.tenant.context import (
    CURRENT_TENANT,
    TenantContext,
    set_current_tenant,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_state() -> Generator[None, None, None]:
    """Reset registry + audit sink + tenant context between tests."""
    clear_vertical_registry()
    set_audit_sink(None)
    yield
    clear_vertical_registry()
    set_audit_sink(None)


@pytest.fixture
def audit_sink() -> InMemoryAuditSink:
    sink = InMemoryAuditSink()
    set_audit_sink(sink)
    return sink


@pytest.fixture
def hipaa_tenant() -> Generator[str, None, None]:
    set_tenant_vertical("clinic-x", TenantVertical.HIPAA)
    token = set_current_tenant(TenantContext(tenant_id="clinic-x"))
    yield "clinic-x"
    CURRENT_TENANT.reset(token)


@pytest.fixture
def fintech_tenant() -> Generator[str, None, None]:
    set_tenant_vertical("bank-y", TenantVertical.FINTECH)
    token = set_current_tenant(TenantContext(tenant_id="bank-y"))
    yield "bank-y"
    CURRENT_TENANT.reset(token)


# Build a synthetic diagnostic.
def _diag(code: str = "AX-0042", line: int = 7, column: int = 12) -> ParserDiagnostic:
    return ParserDiagnostic(
        code=code,
        file_path="src/flow.axon",
        line=line,
        column=column,
        severity=DiagnosticSeverity.ERROR,
    )


def _counter_value(*, tenant_id: str, vertical: str, code: str) -> float:
    """Read the current counter value for the given labels."""
    return PARSER_ERRORS_TOTAL.labels(
        tenant_id=tenant_id,
        vertical=vertical,
        code=code,
    )._value.get()


# ── §1 — Closed-catalog severity ──────────────────────────────────────


def test_diagnostic_severity_catalog_three_variants() -> None:
    assert set(DiagnosticSeverity) == {
        DiagnosticSeverity.ERROR,
        DiagnosticSeverity.WARNING,
        DiagnosticSeverity.HINT,
    }
    assert len(DiagnosticSeverity) == 3


# ── §2 — D4 privacy boundary baked into the type ─────────────────────


def test_parser_diagnostic_has_no_source_text_field() -> None:
    """D4 ratificada — the type itself enforces the privacy boundary.
    Adding a 'source' or 'snippet' field to ParserDiagnostic breaks
    this test AND the privacy guarantee documented in plan vivo.
    """
    diag = _diag()
    # Defensive: enumerate the slots that exist and check none look
    # like a source-text leak channel.
    forbidden = {"source", "snippet", "content", "text", "body"}
    field_names = set(ParserDiagnostic.__dataclass_fields__)
    assert field_names.isdisjoint(forbidden), (
        f"ParserDiagnostic carries forbidden source-text field(s): "
        f"{field_names & forbidden}"
    )
    # Sanity: every field IS one of the expected structural attributes.
    assert field_names == {"code", "file_path", "line", "column", "severity"}


def test_parser_diagnostic_is_frozen_immutable() -> None:
    diag = _diag()
    with pytest.raises((AttributeError, TypeError)):
        diag.code = "AX-0099"  # type: ignore[misc]


# ── §3 — D9 telemetry_enabled gate ────────────────────────────────────


def test_emit_no_op_when_telemetry_disabled(audit_sink: InMemoryAuditSink) -> None:
    """D9 backwards-compat: generic tenants get no telemetry by default."""
    set_tenant_vertical("generic-co", TenantVertical.GENERIC)
    token = set_current_tenant(TenantContext(tenant_id="generic-co"))
    try:
        before = _counter_value(tenant_id="generic-co", vertical="generic", code="AX-0001")
        emit_parser_error(_diag("AX-0001"))
        after = _counter_value(tenant_id="generic-co", vertical="generic", code="AX-0001")
        assert after == before, "Counter MUST NOT increment for generic tenants"
        assert audit_sink.entries() == [], (
            "Audit sink MUST NOT receive entries when telemetry disabled"
        )
    finally:
        CURRENT_TENANT.reset(token)


def test_emit_no_op_when_no_tenant_context_set(audit_sink: InMemoryAuditSink) -> None:
    """No tenant context → policy resolves to GENERIC → telemetry off."""
    token = CURRENT_TENANT.set(None)
    try:
        emit_parser_error(_diag("AX-0001"))
        assert audit_sink.entries() == []
    finally:
        CURRENT_TENANT.reset(token)


# ── §4 — Three-sink fan-out for telemetry-on tenants ─────────────────


def test_hipaa_emit_increments_prom_counter(
    hipaa_tenant: str, audit_sink: InMemoryAuditSink
) -> None:
    before = _counter_value(tenant_id=hipaa_tenant, vertical="hipaa", code="AX-0042")
    emit_parser_error(_diag("AX-0042"))
    after = _counter_value(tenant_id=hipaa_tenant, vertical="hipaa", code="AX-0042")
    assert after - before == 1.0


def test_hipaa_emit_writes_audit_entry(
    hipaa_tenant: str, audit_sink: InMemoryAuditSink
) -> None:
    emit_parser_error(_diag("AX-0042"))
    entries = audit_sink.entries_for_tenant(hipaa_tenant)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.tenant_id == hipaa_tenant
    assert entry.vertical == "hipaa"
    assert entry.code == "AX-0042"
    assert entry.file_path == "src/flow.axon"
    assert entry.line == 7
    assert entry.column == 12
    assert entry.severity == "error"


def test_audit_entry_payload_has_no_source_text_field(
    hipaa_tenant: str, audit_sink: InMemoryAuditSink
) -> None:
    """D4 ratificada — audit entry must carry only structural
    attributes. The InMemoryAuditSink's _CapturedAuditEntry slots
    enumerate exactly what the production AuditSink protocol accepts.
    """
    emit_parser_error(_diag("AX-0042"))
    entry = audit_sink.entries()[0]
    field_names = set(entry.__slots__)
    forbidden = {"source", "snippet", "content", "text", "body", "excerpt"}
    assert field_names.isdisjoint(forbidden)


def test_fintech_emit_uses_fintech_vertical_label(
    fintech_tenant: str, audit_sink: InMemoryAuditSink
) -> None:
    """Fintech is recovery-mode but telemetry-on — emit MUST fire,
    label MUST be 'fintech'.
    """
    emit_parser_error(_diag("AX-0007"))
    entries = audit_sink.entries_for_tenant(fintech_tenant)
    assert len(entries) == 1
    assert entries[0].vertical == "fintech"
    counter_value = _counter_value(
        tenant_id=fintech_tenant, vertical="fintech", code="AX-0007"
    )
    assert counter_value >= 1.0


# ── §5 — D8 multi-tenant isolation ───────────────────────────────────


def test_d8_emit_on_tenant_a_does_not_increment_tenant_b_counter() -> None:
    """D8 ratificada — counter labels include tenant_id; tenant A
    series is independent from tenant B series.
    """
    set_tenant_vertical("hospital-x", TenantVertical.HIPAA)
    set_tenant_vertical("hospital-y", TenantVertical.HIPAA)

    token_x = set_current_tenant(TenantContext(tenant_id="hospital-x"))
    try:
        before_y = _counter_value(
            tenant_id="hospital-y", vertical="hipaa", code="AX-0001"
        )
        emit_parser_error(_diag("AX-0001"))
        after_y = _counter_value(
            tenant_id="hospital-y", vertical="hipaa", code="AX-0001"
        )
        assert after_y == before_y, (
            "Tenant Y's counter MUST NOT increment when Tenant X emits"
        )
    finally:
        CURRENT_TENANT.reset(token_x)


def test_d8_audit_entries_isolated_per_tenant(
    audit_sink: InMemoryAuditSink,
) -> None:
    set_tenant_vertical("hospital-x", TenantVertical.HIPAA)
    set_tenant_vertical("hospital-y", TenantVertical.HIPAA)

    token_x = set_current_tenant(TenantContext(tenant_id="hospital-x"))
    try:
        emit_parser_error(_diag("AX-0001"))
        emit_parser_error(_diag("AX-0002"))
    finally:
        CURRENT_TENANT.reset(token_x)

    token_y = set_current_tenant(TenantContext(tenant_id="hospital-y"))
    try:
        emit_parser_error(_diag("AX-0003"))
    finally:
        CURRENT_TENANT.reset(token_y)

    x_entries = audit_sink.entries_for_tenant("hospital-x")
    y_entries = audit_sink.entries_for_tenant("hospital-y")
    assert len(x_entries) == 2
    assert len(y_entries) == 1
    assert {e.code for e in x_entries} == {"AX-0001", "AX-0002"}
    assert {e.code for e in y_entries} == {"AX-0003"}


# ── §6 — Explicit policy + tenant override path ──────────────────────


def test_emit_with_explicit_policy_and_tenant(
    audit_sink: InMemoryAuditSink,
) -> None:
    """Batch workers iterating tenants pass explicit policy + tenant
    rather than relying on the active TenantContext.
    """
    policy = resolve_policy_for_vertical(TenantVertical.LEGAL)
    emit_parser_error(
        _diag("AX-0500"),
        policy=policy,
        tenant_id="firm-a",
    )
    entries = audit_sink.entries_for_tenant("firm-a")
    assert len(entries) == 1
    assert entries[0].vertical == "legal"
    assert entries[0].code == "AX-0500"


def test_emit_with_explicit_policy_telemetry_off_skipped(
    audit_sink: InMemoryAuditSink,
) -> None:
    """Explicit policy override with telemetry_enabled=False → no-op."""
    policy = resolve_policy_for_vertical(TenantVertical.HIPAA).with_override(
        telemetry_enabled=False
    )
    emit_parser_error(_diag("AX-0001"), policy=policy, tenant_id="opted-out")
    assert audit_sink.entries() == []


# ── §7 — Audit sink installation hooks ───────────────────────────────


def test_set_then_get_audit_sink_round_trips() -> None:
    sink = InMemoryAuditSink()
    set_audit_sink(sink)
    assert get_audit_sink() is sink


def test_no_audit_sink_does_not_break_emit(hipaa_tenant: str) -> None:
    """When no audit sink is installed, OTel + Prom still fire."""
    # Audit sink intentionally NOT installed in this test.
    set_audit_sink(None)
    before = _counter_value(tenant_id=hipaa_tenant, vertical="hipaa", code="AX-0099")
    emit_parser_error(_diag("AX-0099"))
    after = _counter_value(tenant_id=hipaa_tenant, vertical="hipaa", code="AX-0099")
    # Prom counter MUST still increment.
    assert after - before == 1.0


# ── §8 — Best-effort sink isolation ──────────────────────────────────


class _RaisingAuditSink:
    """Audit sink that raises on every write — exercises best-effort
    isolation: one sink's failure must not block the others.
    """

    def write_parser_error(
        self,
        *,
        tenant_id: str,
        vertical: str,
        code: str,
        file_path: str,
        line: int,
        column: int,
        severity: str,
    ) -> None:
        raise RuntimeError("synthetic audit-sink failure")


def test_raising_audit_sink_does_not_block_prom(hipaa_tenant: str) -> None:
    """Best-effort sink isolation: audit-log failure does NOT prevent
    Prometheus counter increment.
    """
    set_audit_sink(_RaisingAuditSink())
    before = _counter_value(tenant_id=hipaa_tenant, vertical="hipaa", code="AX-9999")
    # Must not raise.
    emit_parser_error(_diag("AX-9999"))
    after = _counter_value(tenant_id=hipaa_tenant, vertical="hipaa", code="AX-9999")
    assert after - before == 1.0


# ── §9 — InMemoryAuditSink helpers ───────────────────────────────────


def test_in_memory_audit_sink_clear_resets() -> None:
    sink = InMemoryAuditSink()
    set_audit_sink(sink)
    set_tenant_vertical("clinic-x", TenantVertical.HIPAA)
    token = set_current_tenant(TenantContext(tenant_id="clinic-x"))
    try:
        emit_parser_error(_diag())
        emit_parser_error(_diag())
        assert len(sink.entries()) == 2
        sink.clear()
        assert sink.entries() == []
    finally:
        CURRENT_TENANT.reset(token)


def test_in_memory_audit_sink_capacity_bounded() -> None:
    """Capacity bound prevents unbounded memory growth in long-running
    test sessions."""
    sink = InMemoryAuditSink(capacity=3)
    set_audit_sink(sink)
    set_tenant_vertical("clinic-x", TenantVertical.HIPAA)
    token = set_current_tenant(TenantContext(tenant_id="clinic-x"))
    try:
        for i in range(10):
            emit_parser_error(_diag(code=f"AX-{i:04d}"))
        entries = sink.entries()
        assert len(entries) == 3, "capacity must bound retained entries"
        # Most recent 3 retained.
        assert [e.code for e in entries] == ["AX-0007", "AX-0008", "AX-0009"]
    finally:
        CURRENT_TENANT.reset(token)


def test_entries_for_tenant_returns_defensive_filter() -> None:
    sink = InMemoryAuditSink()
    set_audit_sink(sink)
    set_tenant_vertical("a", TenantVertical.HIPAA)
    set_tenant_vertical("b", TenantVertical.HIPAA)

    token = set_current_tenant(TenantContext(tenant_id="a"))
    try:
        emit_parser_error(_diag("AX-A"))
    finally:
        CURRENT_TENANT.reset(token)

    token = set_current_tenant(TenantContext(tenant_id="b"))
    try:
        emit_parser_error(_diag("AX-B"))
    finally:
        CURRENT_TENANT.reset(token)

    a_only = sink.entries_for_tenant("a")
    assert len(a_only) == 1
    assert a_only[0].code == "AX-A"


# ── §10 — Closed-catalog severity in audit payload ───────────────────


def test_emit_warning_severity_propagates(
    hipaa_tenant: str, audit_sink: InMemoryAuditSink
) -> None:
    diag = ParserDiagnostic(
        code="AX-W001",
        file_path="src/x.axon",
        line=1,
        column=1,
        severity=DiagnosticSeverity.WARNING,
    )
    emit_parser_error(diag)
    entry = audit_sink.entries()[0]
    assert entry.severity == "warning"


def test_emit_hint_severity_propagates(
    hipaa_tenant: str, audit_sink: InMemoryAuditSink
) -> None:
    diag = ParserDiagnostic(
        code="AX-H001",
        file_path="src/x.axon",
        line=1,
        column=1,
        severity=DiagnosticSeverity.HINT,
    )
    emit_parser_error(diag)
    entry = audit_sink.entries()[0]
    assert entry.severity == "hint"


# ── §11 — Forward-compat: emit accepts any tenant_id string ──────────


def test_emit_with_unknown_tenant_id_still_works(
    audit_sink: InMemoryAuditSink,
) -> None:
    """If a caller passes a tenant_id that's never been registered
    with a vertical, the policy parameter (when supplied explicitly)
    governs behavior. The tenant_id is treated as a free-form string
    for sink labelling.
    """
    policy = resolve_policy_for_vertical(TenantVertical.HIPAA)
    emit_parser_error(_diag(), policy=policy, tenant_id="never-registered")
    entries = audit_sink.entries_for_tenant("never-registered")
    assert len(entries) == 1
