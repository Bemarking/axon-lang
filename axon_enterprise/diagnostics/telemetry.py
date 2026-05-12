"""§Fase 29.c — Diagnostics-to-telemetry sink.

D2 + D4 + D6 + D8 + D9 ratificadas 2026-05-12.

## What this module ships

A canonical emitter for parser-error events that fans out to three
parallel sinks per :class:`DiagnosticPolicy`:

1. **OpenTelemetry span** under the ``axon.diagnostics`` instrumentation
   namespace, with attributes ``axon.tenant_id``, ``axon.vertical``,
   ``axon.severity``, ``axon.error.code``, ``axon.file``, ``axon.line``,
   ``axon.column``.
2. **Prometheus counter** ``axon_parser_errors_total{tenant_id,
   vertical, code}`` (registered in
   :mod:`axon_enterprise.observability.metrics`).
3. **Audit-log entry** of type ``AuditEventType.COMPLIANCE_PARSE_ERROR``
   (HMAC-chained per existing :class:`AuditService` path), with the
   payload containing ONLY file path + line + col + error code + severity.

## D4 privacy boundary (RATIFICADA bloque)

**NEVER emit source text content to any sink.** The emitter accepts
file-path + line + col + error-code only; even if a caller mistakenly
passes a source-text excerpt, the projection functions strip it before
emission. Adopter clients fetch source separately via existing repo
access controls if they need the full block.

The audit log includes file-path + line + col + error code only —
identical privacy posture to the existing audit-log discipline
(no source content in long-retention storage).

## D8 multi-tenant isolation

Every emission carries the tenant_id label/attribute. A counter
increment for tenant A does NOT increment tenant B's series; an OTel
span for tenant A's vertical does NOT inherit tenant B's baggage.

## D9 backwards-compat

When :attr:`DiagnosticPolicy.telemetry_enabled` is False (generic
tenants by default), :func:`emit_parser_error` is a no-op. OSS adopters
who never opt in to enterprise see no telemetry plumbing fire.

## Pillar trace

- **MATHEMATICS** — :class:`ParserDiagnostic` is a frozen + slots
  dataclass with a closed set of fields. No source text field exists,
  so the privacy boundary is enforced by the type system.
- **LOGIC** — the emit() function's policy gate is precise:
  emit ⟺ policy.telemetry_enabled. Off-by-default for generic tenants.
- **PHILOSOPHY** — declared `telemetry_enabled` IS the runtime
  behavior. An adopter who flips the dial on a HIPAA tenant gets
  every parser error in OTel + Prom + audit log; flipping it off
  silences all three sinks.
- **COMPUTING** — Counter.labels(...).inc() is atomic; OTel span
  creation is non-blocking via the no-op fallback when SDK absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from axon_enterprise.diagnostics.policy import (
    DiagnosticPolicy,
    TenantVertical,
    resolve_policy_for_current_tenant,
)
from axon_enterprise.observability.metrics import PARSER_ERRORS_TOTAL
from axon_enterprise.observability.tracing import get_tracer
from axon_enterprise.tenant.context import current_tenant_or_none

# ──────────────────────────────────────────────────────────────────
#  Diagnostic shape (D4 privacy boundary baked into the type)
# ──────────────────────────────────────────────────────────────────


class DiagnosticSeverity(StrEnum):
    """Closed catalog of severity levels emitted to telemetry.

    Mirrors the OSS axon-lang AxonParseError severity discipline:
    ``error`` is the canonical parser-failure level. ``warning`` is
    reserved for the Fase 31 ``axon-W001`` warning channel; future
    closer-to-the-source surfaces (type-checker, IR generator) may
    add ``hint`` or ``info``.
    """

    ERROR = "error"
    WARNING = "warning"
    HINT = "hint"


@dataclass(frozen=True, slots=True)
class ParserDiagnostic:
    """One parser-error event ready for telemetry emission.

    **D4 privacy boundary baked into the type**: there is no ``source``
    or ``snippet`` field. Callers passing source text must strip it
    before constructing the diagnostic; the emitter functions enforce
    the boundary by never reading from any field other than the ones
    declared here.

    The fields are deliberately minimal:

    - ``code`` — the parser error code (e.g. ``AX-0042``); appears in
      OTel span attributes, the Prometheus counter label, and the
      audit-log payload.
    - ``file_path`` — relative to the tenant's repo root; informational
      for audit/dashboard surfaces, never leaked into Prom labels
      (cardinality risk).
    - ``line``/``column`` — 1-indexed source positions; audit-log
      payload only.
    - ``severity`` — :class:`DiagnosticSeverity` slug.
    """

    code: str
    file_path: str
    line: int
    column: int
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR


# ──────────────────────────────────────────────────────────────────
#  Audit-sink protocol (test-injectable)
# ──────────────────────────────────────────────────────────────────


class AuditSink(Protocol):
    """Minimal protocol for the audit-log sink the emitter calls.

    Production wires this to the real :class:`AuditService` (HMAC-
    chained, DB-backed); tests inject a fake that captures the
    payloads in-memory for assertion.

    The protocol is intentionally narrower than the full
    AuditWriteRequest contract so the emitter never reaches for
    fields it doesn't need (no IP, no user-agent, no actor) — the
    privacy boundary is enforced by what the emitter CAN pass.
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
        """Persist a parser-error audit entry. Implementations MUST
        be idempotent under retry — the emitter calls this exactly
        once per parser error but a future retry layer may re-call.
        """


# Module-level default sink; tests/production swap it.
_AUDIT_SINK: AuditSink | None = None


def set_audit_sink(sink: AuditSink | None) -> None:
    """Install the audit sink. Pass None to disable audit-log emission
    (tracing + Prom still fire).
    """
    global _AUDIT_SINK
    _AUDIT_SINK = sink


def get_audit_sink() -> AuditSink | None:
    """Return the currently-installed audit sink, or None."""
    return _AUDIT_SINK


# ──────────────────────────────────────────────────────────────────
#  Canonical emit function
# ──────────────────────────────────────────────────────────────────


def emit_parser_error(
    diagnostic: ParserDiagnostic,
    *,
    policy: DiagnosticPolicy | None = None,
    tenant_id: str | None = None,
) -> None:
    """Fan out a single parser-error event to OTel + Prom + audit-log.

    Resolution order for the policy + tenant:

    1. Explicit ``policy`` + ``tenant_id`` arguments (test paths +
       batch workers iterating across tenants).
    2. Otherwise resolved from the active
       :class:`TenantContext` via
       :func:`resolve_policy_for_current_tenant`.

    When the resolved policy's :attr:`DiagnosticPolicy.telemetry_enabled`
    is False (D9 default for generic tenants), this function is a
    no-op — every sink is bypassed.

    All three sinks fire on a best-effort basis: a failure in one
    sink does NOT prevent the others from emitting. A failure in
    the OTel exporter is silently swallowed (telemetry must NEVER
    block business logic per existing D-letter discipline).
    """
    # 1. Resolve policy + tenant.
    if policy is None:
        policy = resolve_policy_for_current_tenant()
    if tenant_id is None:
        ctx = current_tenant_or_none()
        tenant_id = ctx.tenant_id if ctx is not None else "default"

    # 2. D9 gate — generic tenants with telemetry off → no-op.
    if not policy.telemetry_enabled:
        return

    # 3. Fan out to the three sinks. Each wrapped in best-effort
    #    exception handling so one sink failure doesn't drop the others.
    _emit_otel(diagnostic, policy, tenant_id)
    _emit_prometheus(diagnostic, policy, tenant_id)
    _emit_audit(diagnostic, policy, tenant_id)


# ──────────────────────────────────────────────────────────────────
#  Sink-specific emit helpers
# ──────────────────────────────────────────────────────────────────


def _emit_otel(
    diagnostic: ParserDiagnostic,
    policy: DiagnosticPolicy,
    tenant_id: str,
) -> None:
    """Emit an OTel span under the ``axon.diagnostics`` namespace.

    Falls back to a no-op span when the OTel SDK isn't installed (the
    :func:`get_tracer` helper already handles this). The span is
    started + ended within this function — no caller-side context
    management. Span name is ``axon.diagnostics.parse_error`` so
    OTel-side dashboards can group cleanly.

    D4 privacy: only the structural attributes (code, file, line, col,
    severity, tenant_id, vertical) are set. No source text reaches
    the span.
    """
    try:
        tracer = get_tracer("axon_enterprise.diagnostics")
        with tracer.start_as_current_span("axon.diagnostics.parse_error") as span:
            span.set_attribute("axon.tenant_id", tenant_id)
            span.set_attribute("axon.vertical", policy.vertical.value)
            span.set_attribute("axon.severity", diagnostic.severity.value)
            span.set_attribute("axon.error.code", diagnostic.code)
            span.set_attribute("axon.file", diagnostic.file_path)
            span.set_attribute("axon.line", diagnostic.line)
            span.set_attribute("axon.column", diagnostic.column)
    except Exception:  # pragma: no cover  (defense-in-depth)
        # Telemetry MUST NOT block. If OTel raises (export failure,
        # SDK misconfiguration, ...), swallow — the other sinks
        # continue to fire.
        pass


def _emit_prometheus(
    diagnostic: ParserDiagnostic,
    policy: DiagnosticPolicy,
    tenant_id: str,
) -> None:
    """Increment the ``axon_parser_errors_total`` counter.

    Labels are bounded-cardinality per the metrics-module contract:
    tenant_id × vertical × code. No file path, no line/col — those
    explode the label set.
    """
    try:
        PARSER_ERRORS_TOTAL.labels(
            tenant_id=tenant_id,
            vertical=policy.vertical.value,
            code=diagnostic.code,
        ).inc()
    except Exception:  # pragma: no cover
        pass


def _emit_audit(
    diagnostic: ParserDiagnostic,
    policy: DiagnosticPolicy,
    tenant_id: str,
) -> None:
    """Write an audit-log entry via the installed :class:`AuditSink`.

    Skips silently when no audit sink is installed (OSS dev / tests
    without the audit service).
    """
    sink = _AUDIT_SINK
    if sink is None:
        return
    try:
        sink.write_parser_error(
            tenant_id=tenant_id,
            vertical=policy.vertical.value,
            code=diagnostic.code,
            file_path=diagnostic.file_path,
            line=diagnostic.line,
            column=diagnostic.column,
            severity=diagnostic.severity.value,
        )
    except Exception:  # pragma: no cover
        pass


# ──────────────────────────────────────────────────────────────────
#  In-memory audit sink (testing + bootstrap)
# ──────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _CapturedAuditEntry:
    """One audit-log payload captured by the :class:`InMemoryAuditSink`."""

    tenant_id: str
    vertical: str
    code: str
    file_path: str
    line: int
    column: int
    severity: str


class InMemoryAuditSink:
    """Test-only audit sink that captures payloads in a list.

    Used by the 29.c test pack + by 29.e (dashboard endpoint) to
    serve the recent-error feed without a DB round-trip during
    bootstrap. Production deployments swap with the real
    :class:`AuditService` adapter (lands in 29.e wiring).
    """

    def __init__(self, capacity: int = 1024) -> None:
        self._entries: list[_CapturedAuditEntry] = []
        self._capacity = capacity

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
        entry = _CapturedAuditEntry(
            tenant_id=tenant_id,
            vertical=vertical,
            code=code,
            file_path=file_path,
            line=line,
            column=column,
            severity=severity,
        )
        self._entries.append(entry)
        # Cap retention to bounded memory in long-running tests.
        if len(self._entries) > self._capacity:
            self._entries = self._entries[-self._capacity :]

    def entries(self) -> list[_CapturedAuditEntry]:
        """Defensive copy of captured entries."""
        return list(self._entries)

    def entries_for_tenant(self, tenant_id: str) -> list[_CapturedAuditEntry]:
        """Filter captured entries by tenant. D8 multi-tenant isolation
        helper for tests + dashboard.
        """
        return [e for e in self._entries if e.tenant_id == tenant_id]

    def clear(self) -> None:
        self._entries.clear()


__all__ = [
    "AuditSink",
    "DiagnosticSeverity",
    "InMemoryAuditSink",
    "ParserDiagnostic",
    "emit_parser_error",
    "get_audit_sink",
    "set_audit_sink",
]
