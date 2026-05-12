"""§Fase 29.e — Tests for ``/api/v1/tenant/diagnostics/recent``.

Covers:
  * Store layer — D4 privacy boundary (no source field), D8
    multi-tenant isolation, pagination via `since`, aggregation
    grouping, capacity-bounded ring buffer.
  * StoreBackedAuditSink — round-trip from emit_parser_error
    through the sink into the store.
  * HTTP route — auth via require_principal (Q4 resolution), D4
    JSON shape pin (no source text), D8 tenant isolation,
    pagination cursors, filter params, limit clamping.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from axon_enterprise.diagnostics import (
    DiagnosticRecord,
    DiagnosticSeverity,
    ParserDiagnostic,
    RecentDiagnosticsStore,
    StoreBackedAuditSink,
    TenantVertical,
    clear_vertical_registry,
    emit_parser_error,
    get_default_store,
    resolve_policy_for_vertical,
    set_audit_sink,
    set_default_store,
    set_tenant_vertical,
)
from axon_enterprise.http.api import diagnostics as diag_routes
from axon_enterprise.identity.principal import (
    CURRENT_PRINCIPAL,
    PrincipalContext,
    set_current_principal,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_state() -> Generator[None, None, None]:
    """Reset registry + audit sink + diagnostics store between tests."""
    clear_vertical_registry()
    set_audit_sink(None)
    get_default_store().clear()
    token = CURRENT_PRINCIPAL.set(None)
    yield
    clear_vertical_registry()
    set_audit_sink(None)
    get_default_store().clear()
    CURRENT_PRINCIPAL.reset(token)


@pytest.fixture
def store() -> Generator[RecentDiagnosticsStore, None, None]:
    s = RecentDiagnosticsStore(capacity_per_tenant=100)
    set_default_store(s)
    yield s
    set_default_store(RecentDiagnosticsStore())


@pytest.fixture
def hipaa_principal() -> PrincipalContext:
    set_tenant_vertical("clinic-x", TenantVertical.HIPAA)
    principal = PrincipalContext(
        user_id=uuid.UUID(int=42),
        email="admin@clinic-x.example",
        tenant_id="clinic-x",
        role_names=frozenset(),
    )
    return principal


def _record(
    *,
    tenant_id: str = "clinic-x",
    vertical: str = "hipaa",
    code: str = "AX-0042",
    file_path: str = "src/flow.axon",
    line: int = 7,
    column: int = 3,
    severity: str = "error",
    timestamp: datetime | None = None,
) -> DiagnosticRecord:
    return DiagnosticRecord(
        tenant_id=tenant_id,
        vertical=vertical,
        code=code,
        file_path=file_path,
        line=line,
        column=column,
        severity=severity,
        timestamp=timestamp or datetime.now(timezone.utc),
    )


# ── §1 — DiagnosticRecord D4 privacy boundary ─────────────────────────


def test_diagnostic_record_has_no_source_text_field() -> None:
    """D4 baked into the type — no `source` / `snippet` / `content`
    / `text` / `body` field exists on the record.
    """
    forbidden = {"source", "snippet", "content", "text", "body", "excerpt"}
    field_names = set(DiagnosticRecord.__dataclass_fields__)
    assert field_names.isdisjoint(forbidden), (
        f"DiagnosticRecord carries forbidden source-text field(s): "
        f"{field_names & forbidden}"
    )


def test_diagnostic_record_is_frozen() -> None:
    rec = _record()
    with pytest.raises((AttributeError, TypeError)):
        rec.code = "AX-9999"  # type: ignore[misc]


# ── §2 — RecentDiagnosticsStore basic operations ─────────────────────


def test_empty_store_returns_empty_list() -> None:
    s = RecentDiagnosticsStore()
    assert s.recent_for_tenant("any") == []
    assert s.aggregated_for_tenant("any") == []
    assert s.tenant_count() == 0


def test_record_then_recent_round_trips() -> None:
    s = RecentDiagnosticsStore()
    rec = _record()
    s.record(rec)
    recent = s.recent_for_tenant("clinic-x")
    assert recent == [rec]


def test_recent_returns_newest_first() -> None:
    s = RecentDiagnosticsStore()
    t0 = datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)
    s.record(_record(code="AX-0001", timestamp=t0))
    s.record(_record(code="AX-0002", timestamp=t0 + timedelta(seconds=1)))
    s.record(_record(code="AX-0003", timestamp=t0 + timedelta(seconds=2)))
    recent = s.recent_for_tenant("clinic-x")
    assert [r.code for r in recent] == ["AX-0003", "AX-0002", "AX-0001"]


def test_recent_respects_limit() -> None:
    s = RecentDiagnosticsStore()
    for i in range(20):
        s.record(_record(code=f"AX-{i:04d}"))
    recent = s.recent_for_tenant("clinic-x", limit=5)
    assert len(recent) == 5


def test_recent_clamps_limit_to_capacity() -> None:
    s = RecentDiagnosticsStore(capacity_per_tenant=10)
    for i in range(10):
        s.record(_record(code=f"AX-{i:04d}"))
    # Request limit > capacity → clamped.
    recent = s.recent_for_tenant("clinic-x", limit=10_000)
    assert len(recent) == 10


def test_recent_clamps_limit_to_min_one() -> None:
    s = RecentDiagnosticsStore()
    s.record(_record())
    assert len(s.recent_for_tenant("clinic-x", limit=0)) == 1
    assert len(s.recent_for_tenant("clinic-x", limit=-5)) == 1


def test_since_cursor_returns_strictly_newer() -> None:
    s = RecentDiagnosticsStore()
    t0 = datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)
    s.record(_record(code="OLD", timestamp=t0))
    s.record(_record(code="NEW", timestamp=t0 + timedelta(seconds=10)))
    # Strict > semantics — record at t0 NOT returned when since=t0.
    recent = s.recent_for_tenant("clinic-x", since=t0)
    assert [r.code for r in recent] == ["NEW"]


def test_filter_by_file_path() -> None:
    s = RecentDiagnosticsStore()
    s.record(_record(file_path="a.axon"))
    s.record(_record(file_path="b.axon"))
    s.record(_record(file_path="a.axon"))
    recent = s.recent_for_tenant("clinic-x", file_path="a.axon")
    assert len(recent) == 2
    assert all(r.file_path == "a.axon" for r in recent)


def test_filter_by_code() -> None:
    s = RecentDiagnosticsStore()
    s.record(_record(code="AX-0001"))
    s.record(_record(code="AX-0002"))
    s.record(_record(code="AX-0001"))
    recent = s.recent_for_tenant("clinic-x", code="AX-0001")
    assert len(recent) == 2


# ── §3 — Ring buffer capacity ────────────────────────────────────────


def test_capacity_bounded_per_tenant() -> None:
    s = RecentDiagnosticsStore(capacity_per_tenant=3)
    t0 = datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)
    for i in range(10):
        s.record(_record(code=f"AX-{i:04d}", timestamp=t0 + timedelta(seconds=i)))
    recent = s.recent_for_tenant("clinic-x", limit=10)
    # Only the 3 newest survive.
    assert [r.code for r in recent] == ["AX-0009", "AX-0008", "AX-0007"]


# ── §4 — Aggregation grouping ────────────────────────────────────────


def test_aggregate_groups_by_file_code_line_bucket() -> None:
    s = RecentDiagnosticsStore()
    t0 = datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)
    # Three records same file + code + line-bucket → 1 group, count=3.
    s.record(_record(line=7, timestamp=t0))
    s.record(_record(line=8, timestamp=t0 + timedelta(seconds=1)))
    s.record(_record(line=2, timestamp=t0 + timedelta(seconds=2)))
    # Different code → separate group.
    s.record(_record(code="AX-0099", line=5, timestamp=t0 + timedelta(seconds=3)))
    # Different bucket → separate group.
    s.record(_record(line=15, timestamp=t0 + timedelta(seconds=4)))

    agg = s.aggregated_for_tenant("clinic-x")
    groups_by_key = {(g.file_path, g.code, g.line_bucket): g for g in agg}
    # 3 distinct groups: AX-0042/bucket-0, AX-0099/bucket-0,
    # AX-0042/bucket-10.
    assert len(groups_by_key) == 3
    assert groups_by_key[("src/flow.axon", "AX-0042", 0)].count == 3
    assert groups_by_key[("src/flow.axon", "AX-0099", 0)].count == 1
    assert groups_by_key[("src/flow.axon", "AX-0042", 10)].count == 1


def test_aggregate_sorted_by_count_desc() -> None:
    s = RecentDiagnosticsStore()
    # AX-0001 appears 5 times in same bucket; AX-0002 only 2.
    t0 = datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        s.record(_record(code="AX-0001", timestamp=t0 + timedelta(seconds=i)))
    for i in range(2):
        s.record(_record(code="AX-0002", timestamp=t0 + timedelta(seconds=10 + i)))
    agg = s.aggregated_for_tenant("clinic-x")
    assert agg[0].code == "AX-0001"
    assert agg[0].count == 5
    assert agg[1].code == "AX-0002"
    assert agg[1].count == 2


def test_aggregate_first_seen_and_last_seen_are_extremes() -> None:
    s = RecentDiagnosticsStore()
    t0 = datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)
    s.record(_record(line=1, timestamp=t0))
    s.record(_record(line=2, timestamp=t0 + timedelta(seconds=60)))
    s.record(_record(line=3, timestamp=t0 + timedelta(seconds=30)))
    agg = s.aggregated_for_tenant("clinic-x")
    assert len(agg) == 1
    assert agg[0].first_seen == t0
    assert agg[0].last_seen == t0 + timedelta(seconds=60)
    assert agg[0].count == 3


def test_aggregate_bucket_size_param() -> None:
    s = RecentDiagnosticsStore()
    # Bucket size 100 collapses lines 1..99 into bucket 0.
    s.record(_record(line=5))
    s.record(_record(line=50))
    s.record(_record(line=99))
    agg = s.aggregated_for_tenant("clinic-x", bucket_size=100)
    assert len(agg) == 1
    assert agg[0].line_bucket == 0
    assert agg[0].count == 3


# ── §5 — D8 multi-tenant isolation (store level) ─────────────────────


def test_d8_record_for_tenant_a_does_not_surface_to_tenant_b() -> None:
    s = RecentDiagnosticsStore()
    s.record(_record(tenant_id="hospital-x", code="AX-A"))
    s.record(_record(tenant_id="hospital-y", code="AX-B"))
    x_only = s.recent_for_tenant("hospital-x")
    y_only = s.recent_for_tenant("hospital-y")
    assert len(x_only) == 1
    assert x_only[0].code == "AX-A"
    assert len(y_only) == 1
    assert y_only[0].code == "AX-B"


def test_d8_clear_tenant_does_not_affect_other_tenants() -> None:
    s = RecentDiagnosticsStore()
    s.record(_record(tenant_id="hospital-x"))
    s.record(_record(tenant_id="hospital-y"))
    s.clear_tenant("hospital-x")
    assert s.recent_for_tenant("hospital-x") == []
    assert len(s.recent_for_tenant("hospital-y")) == 1


# ── §6 — StoreBackedAuditSink round-trip from emit_parser_error ──────


def test_store_backed_sink_captures_emitted_diagnostics(
    hipaa_principal: PrincipalContext,
) -> None:
    store = get_default_store()
    set_audit_sink(StoreBackedAuditSink(store))
    policy = resolve_policy_for_vertical(TenantVertical.HIPAA)

    emit_parser_error(
        ParserDiagnostic(
            code="AX-0042",
            file_path="src/x.axon",
            line=7,
            column=4,
            severity=DiagnosticSeverity.ERROR,
        ),
        policy=policy,
        tenant_id=hipaa_principal.tenant_id,
    )

    recent = store.recent_for_tenant(hipaa_principal.tenant_id)
    assert len(recent) == 1
    assert recent[0].code == "AX-0042"
    assert recent[0].vertical == "hipaa"
    assert recent[0].severity == "error"


def test_store_backed_sink_silent_when_telemetry_disabled(
    hipaa_principal: PrincipalContext,
) -> None:
    """D9: a policy with telemetry_enabled=False must NOT feed the store."""
    store = get_default_store()
    set_audit_sink(StoreBackedAuditSink(store))
    policy = resolve_policy_for_vertical(
        TenantVertical.HIPAA
    ).with_override(telemetry_enabled=False)
    emit_parser_error(
        ParserDiagnostic(
            code="AX-0001",
            file_path="x.axon",
            line=1,
            column=1,
        ),
        policy=policy,
        tenant_id=hipaa_principal.tenant_id,
    )
    assert store.recent_for_tenant(hipaa_principal.tenant_id) == []


# ── §7 — HTTP route — auth gate (Q4 resolution) ──────────────────────


def _build_app() -> Starlette:
    """Minimal Starlette app mounting the diagnostics routes for
    isolated testing. Production mounts via `build_api_router()`."""
    return Starlette(
        routes=[
            Mount("/api/v1/tenant/diagnostics", routes=diag_routes.routes()),
        ]
    )


def test_endpoint_returns_500_when_no_principal_set() -> None:
    """`require_principal` raises RuntimeError when CURRENT_PRINCIPAL
    is None. The default Starlette error handler maps that to 500 —
    in production the AuthMiddleware would 401 first; this test
    exercises the inner guard.
    """
    app = _build_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/v1/tenant/diagnostics/recent")
        assert resp.status_code == 500


def _with_principal(
    principal: PrincipalContext, app: Starlette
) -> TestClient:
    """Return a TestClient that installs the principal before each
    request. Mirrors the production AuthMiddleware behavior in tests.
    """
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware

    class _InstallPrincipal(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            token = set_current_principal(principal)
            try:
                return await call_next(request)
            finally:
                CURRENT_PRINCIPAL.reset(token)

    # Re-build with middleware (starlette doesn't allow mounting
    # middleware after construction).
    new_app = Starlette(
        routes=app.routes,
        middleware=[Middleware(_InstallPrincipal)],
    )
    return TestClient(new_app)


# ── §8 — HTTP route — response shape + D4 + D8 ───────────────────────


def test_endpoint_returns_empty_entries_when_no_records(
    hipaa_principal: PrincipalContext,
) -> None:
    app = _build_app()
    with _with_principal(hipaa_principal, app) as client:
        resp = client.get("/api/v1/tenant/diagnostics/recent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == hipaa_principal.tenant_id
        assert data["vertical"] == "hipaa"
        assert data["mode"] == "aggregated"
        assert data["entries"] == []


def test_endpoint_returns_aggregated_entries_for_authenticated_tenant(
    hipaa_principal: PrincipalContext,
    store: RecentDiagnosticsStore,
) -> None:
    t0 = datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)
    for i in range(3):
        store.record(
            _record(
                tenant_id=hipaa_principal.tenant_id,
                code="AX-0042",
                line=7,
                timestamp=t0 + timedelta(seconds=i),
            )
        )
    app = _build_app()
    with _with_principal(hipaa_principal, app) as client:
        resp = client.get("/api/v1/tenant/diagnostics/recent")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entries"]) == 1
        entry = data["entries"][0]
        assert entry["code"] == "AX-0042"
        assert entry["file_path"] == "src/flow.axon"
        assert entry["line_bucket"] == 0
        assert entry["count"] == 3
        assert entry["vertical"] == "hipaa"


def test_endpoint_d4_response_carries_no_source_text(
    hipaa_principal: PrincipalContext,
    store: RecentDiagnosticsStore,
) -> None:
    """D4 ratificada — the JSON response must NEVER carry source text.
    Inspect every field of every entry; forbidden keys NEVER appear.
    """
    store.record(_record(tenant_id=hipaa_principal.tenant_id))
    app = _build_app()
    with _with_principal(hipaa_principal, app) as client:
        # Test both raw + aggregated modes.
        for mode in ("true", "false"):
            resp = client.get(
                f"/api/v1/tenant/diagnostics/recent?aggregated={mode}"
            )
            assert resp.status_code == 200
            data = resp.json()
            forbidden = {"source", "snippet", "content", "text", "body", "excerpt"}
            for entry in data["entries"]:
                assert forbidden.isdisjoint(entry.keys()), (
                    f"D4 violation in mode={mode}: forbidden field "
                    f"{forbidden & set(entry.keys())} in entry"
                )


def test_endpoint_d8_tenant_a_cannot_see_tenant_b_records(
    hipaa_principal: PrincipalContext,
    store: RecentDiagnosticsStore,
) -> None:
    """D8 — tenant A authenticated; tenant B records in the store
    NEVER surface to A even via crafted query params.
    """
    # Tenant B is HIPAA too; A authenticates but B has records.
    set_tenant_vertical("hospital-b", TenantVertical.HIPAA)
    store.record(_record(tenant_id="hospital-b", code="LEAK-IF-VISIBLE"))
    app = _build_app()
    with _with_principal(hipaa_principal, app) as client:
        # Try every plausible param to coerce cross-tenant retrieval.
        for params in (
            {},
            {"limit": "500"},
            {"aggregated": "false"},
            {"aggregated": "false", "code": "LEAK-IF-VISIBLE"},
        ):
            resp = client.get(
                "/api/v1/tenant/diagnostics/recent", params=params
            )
            assert resp.status_code == 200
            data = resp.json()
            for entry in data["entries"]:
                # Aggregated entries have no tenant_id (the envelope
                # carries it); raw entries don't either by design.
                # The data MUST come from clinic-x's store partition;
                # since hospital-b's record was the only one in B's
                # partition AND clinic-x's partition is empty, the
                # entries array MUST be empty.
                pytest.fail(
                    f"D8 violation: entry leaked from another tenant: {entry}"
                )


def test_endpoint_raw_mode_returns_individual_records(
    hipaa_principal: PrincipalContext,
    store: RecentDiagnosticsStore,
) -> None:
    store.record(
        _record(
            tenant_id=hipaa_principal.tenant_id,
            code="AX-0001",
        )
    )
    store.record(
        _record(
            tenant_id=hipaa_principal.tenant_id,
            code="AX-0002",
        )
    )
    app = _build_app()
    with _with_principal(hipaa_principal, app) as client:
        resp = client.get(
            "/api/v1/tenant/diagnostics/recent?aggregated=false"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "raw"
        codes = {e["code"] for e in data["entries"]}
        assert codes == {"AX-0001", "AX-0002"}
        # Per-record shape is structural-only.
        for entry in data["entries"]:
            assert set(entry.keys()) == {
                "code",
                "file_path",
                "line",
                "column",
                "vertical",
                "severity",
                "timestamp",
            }


def test_endpoint_limit_clamped(
    hipaa_principal: PrincipalContext,
    store: RecentDiagnosticsStore,
) -> None:
    """Limit > 500 clamps to 500 (the max defined in the route)."""
    app = _build_app()
    with _with_principal(hipaa_principal, app) as client:
        resp = client.get(
            "/api/v1/tenant/diagnostics/recent?limit=99999"
        )
        assert resp.status_code == 200
        assert resp.json()["limit"] == 500


def test_endpoint_pagination_via_since(
    hipaa_principal: PrincipalContext,
    store: RecentDiagnosticsStore,
) -> None:
    """`since` cursor returns strictly-newer records (paginate
    forward by passing the previous page's `last_seen` as `since`)."""
    t0 = datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)
    store.record(
        _record(
            tenant_id=hipaa_principal.tenant_id,
            code="OLD",
            timestamp=t0,
        )
    )
    store.record(
        _record(
            tenant_id=hipaa_principal.tenant_id,
            code="NEW",
            timestamp=t0 + timedelta(seconds=60),
        )
    )
    app = _build_app()
    with _with_principal(hipaa_principal, app) as client:
        # Use params dict so the `+` in `+00:00` is properly URL-encoded
        # as `%2B` (TestClient escapes via httpx).
        resp = client.get(
            "/api/v1/tenant/diagnostics/recent",
            params={"aggregated": "false", "since": t0.isoformat()},
        )
        assert resp.status_code == 200
        codes = [e["code"] for e in resp.json()["entries"]]
        # Strict > semantics — OLD (at exactly t0) NOT included.
        assert codes == ["NEW"]


def test_endpoint_malformed_since_treated_as_first_page(
    hipaa_principal: PrincipalContext,
    store: RecentDiagnosticsStore,
) -> None:
    """A garbage `since` value should yield the first page rather than
    a 500."""
    store.record(_record(tenant_id=hipaa_principal.tenant_id))
    app = _build_app()
    with _with_principal(hipaa_principal, app) as client:
        resp = client.get(
            "/api/v1/tenant/diagnostics/recent?since=not-a-date"
        )
        assert resp.status_code == 200
        assert len(resp.json()["entries"]) == 1


def test_endpoint_raw_mode_filter_by_file_path(
    hipaa_principal: PrincipalContext,
    store: RecentDiagnosticsStore,
) -> None:
    store.record(
        _record(tenant_id=hipaa_principal.tenant_id, file_path="a.axon")
    )
    store.record(
        _record(tenant_id=hipaa_principal.tenant_id, file_path="b.axon")
    )
    app = _build_app()
    with _with_principal(hipaa_principal, app) as client:
        resp = client.get(
            "/api/v1/tenant/diagnostics/recent?aggregated=false&file_path=a.axon"
        )
        data = resp.json()
        assert len(data["entries"]) == 1
        assert data["entries"][0]["file_path"] == "a.axon"


def test_endpoint_envelope_carries_vertical_for_authenticated_tenant(
    hipaa_principal: PrincipalContext,
) -> None:
    app = _build_app()
    with _with_principal(hipaa_principal, app) as client:
        data = client.get("/api/v1/tenant/diagnostics/recent").json()
        assert data["vertical"] == "hipaa"


def test_endpoint_envelope_vertical_for_unregistered_tenant_is_generic() -> None:
    """D9: tenants without a registered vertical surface as 'generic'."""
    principal = PrincipalContext(
        user_id=uuid.UUID(int=99),
        email="x@example",
        tenant_id="brand-new-tenant",
    )
    app = _build_app()
    with _with_principal(principal, app) as client:
        data = client.get("/api/v1/tenant/diagnostics/recent").json()
        assert data["vertical"] == "generic"


# ── §9 — get_default_store / set_default_store hooks ─────────────────


def test_set_then_get_default_store_round_trips() -> None:
    new_store = RecentDiagnosticsStore(capacity_per_tenant=5)
    set_default_store(new_store)
    assert get_default_store() is new_store
