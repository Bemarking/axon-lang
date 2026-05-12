"""§Fase 29 — Enterprise diagnostic enhancements.

Public surface for the vertical-aware diagnostic stack:

- :class:`TenantVertical` — closed catalog {generic, hipaa, legal, fintech}.
- :class:`DiagnosticPolicy` — resolved per-tenant policy bundling
  strict-mode + telemetry-enabled + recovery-mode + extra-keywords.
- :func:`resolve_policy_for_vertical` — pure dispatch vertical → default policy.
- :func:`resolve_policy_for_current_tenant` — wraps the active
  :class:`TenantContext` and returns the resolved policy.
- :func:`set_tenant_vertical` / :func:`get_tenant_vertical` — in-memory
  registry; production deployments back this with the tenant settings DB.

D1 + D2 + D8 + D9 ratificadas 2026-05-12 (plan vivo
``docs/fase_29_enterprise_diagnostic_enhancements.md`` in axon-lang).
"""

from __future__ import annotations

from .policy import (
    DiagnosticPolicy,
    TenantVertical,
    clear_vertical_registry,
    get_tenant_vertical,
    resolve_policy_for_current_tenant,
    resolve_policy_for_vertical,
    set_tenant_vertical,
)
from .suggest_dicts import (
    DictEntry,
    VerticalDictionary,
    assert_no_cross_vertical_contamination,
    clear_dictionary_cache,
    load_vertical_dictionary,
    policy_with_suggest_dict,
    resolve_policy_with_dict_for_vertical,
    terms_for_vertical,
)
from .telemetry import (
    AuditSink,
    DiagnosticSeverity,
    InMemoryAuditSink,
    ParserDiagnostic,
    emit_parser_error,
    get_audit_sink,
    set_audit_sink,
)

__all__ = [
    "AuditSink",
    "DiagnosticPolicy",
    "DiagnosticSeverity",
    "DictEntry",
    "InMemoryAuditSink",
    "ParserDiagnostic",
    "TenantVertical",
    "VerticalDictionary",
    "assert_no_cross_vertical_contamination",
    "clear_dictionary_cache",
    "clear_vertical_registry",
    "emit_parser_error",
    "get_audit_sink",
    "get_tenant_vertical",
    "load_vertical_dictionary",
    "policy_with_suggest_dict",
    "resolve_policy_for_current_tenant",
    "resolve_policy_for_vertical",
    "resolve_policy_with_dict_for_vertical",
    "set_audit_sink",
    "set_tenant_vertical",
    "terms_for_vertical",
]
