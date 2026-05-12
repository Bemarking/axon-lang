---
title: "Plan vivo: Fase 29 — Enterprise Diagnostic Enhancements"
status: IN PROGRESS 2026-05-12 — D1–D10 RATIFICADAS bloque (founder verbatim "Te ratifico todos los D-Letters"); 29.a + 29.b + 29.c + 29.d + 29.e + 29.f SHIPPED on `feature/29b-vertical-diagnostic-policy` branch (axon-enterprise commits `645324b` + `32e53a8` + `f58c1f7` + `6bc0fd4` + `c99c9e5`); 172 diagnostics tests green; 29.g–29.i pending; target axon-enterprise v1.15.0 (next minor after the Fase 33 catch-up at v1.14.0)
owner: AXON Enterprise Team
created: 2026-05-10
ratified: 2026-05-12
target: axon-enterprise v1.15.0 — ENTERPRISE-only release layered on the existing OSS Fase 28 surface; axon-lang permanece en v1.24.0+ (no upstream change required for this fase); axon-frontend permanece en 0.11.1
depends_on: (a) Fase 28 SHIPPED — axon-lang v1.20.0 closed the OSS adopter diagnostic surface (recovery + source-context + smart-suggest + multi-file + JSON + strict + cross-stack drift gate); the diagnostic baseline this fase extends is now 4 OSS versions deep (axon-lang 1.20→1.21→1.22→1.23→1.23.1→1.24.0, all transitively inherited by enterprise via v1.11.0 / v1.12.0 / v1.13.0 / v1.13.1 / v1.14.0 catch-up releases). (b) axon-enterprise v1.14.0 SHIPPED 2026-05-12 — Fase 33 SSE-as-Cognitive-Primitive cascade transitively live (PR #16 merged, tag v1.14.0). (c) Fase 27.k.1 Python ctypes integration permanece on `feature/27k1-ctypes-foundation` branch — independent track, does NOT block Fase 29.
charter_class: ENTERPRISE — privileged R&D layered on top of the OSS Fase 28 baseline; OSS adopters keep getting the OSS surface unchanged; this fase is the canonical materialisation of "axon-enterprise NO es solo wrapper multitenant; es capa privilegiada con R&D vertical (Salud/HealthTech/Legal/Fintech) + behaviors enterprise-only"
---

## ⓘ Versioning convention

This plan vivo describes a **Fase** (a unit of planning work). The
specific axon-enterprise release version that ships this Fase
depends on the cadence of preceding releases — Fases can move
between versions, versions are immutable once published. As of
2026-05-12 the enterprise cadence is:

| Version | Status | Content (what it includes) |
|---|---|---|
| v1.10.0 | ✅ SHIPPED 2026-05-09 | axon-csys-enterprise crate + 5 C23 kernels (Fase 27 sesión 1 Rust foundation) |
| v1.11.0 | ✅ SHIPPED 2026-05-10 | Catch-up: dep pin `axon-lang>=1.20.0` (Fase 28 cascade adoption) |
| v1.12.0 | ✅ SHIPPED 2026-05-11 | Catch-up: dep pin `axon-lang>=1.22.0` (Fase 30 + 31 cascade — HTTP transport for Stream effects + type-driven wire inference) |
| v1.13.0 | ✅ SHIPPED 2026-05-11 | Catch-up: dep pin `axon-lang>=1.23.0` (Fase 32 cascade — axonendpoint as first-class HTTP REST primitive) |
| v1.13.1 | ✅ SHIPPED 2026-05-12 | Catch-up: dep pin `axon-lang>=1.23.1` (Fase 32.l Rust parser disjunct (a) for `output: Stream<T>` step-body — Kivi adopter trail) |
| v1.14.0 | ✅ SHIPPED 2026-05-12 | Catch-up: dep pin `axon-lang>=1.24.0` (Fase 33 SSE-as-Cognitive-Primitive architectural cycle — 4 layers + D6 cancel-safety + D12 fuzz + adopter docs) |
| **v1.15.0** | **🎯 target for this Fase 29** | First **substantive** ENTERPRISE-only release since v1.10.0; ships the vertical-aware diagnostic policy + telemetry sink + suggest dicts + dashboard + CI gate stack |
| v1.16.0+ | future | Reserved for Fase 27.k.1 Python ctypes integration (independent track, currently on `feature/27k1-ctypes-foundation` branch with FFI foundation shipped at commit `c24cc3b`) |

**Note on cadence shape**: v1.11.0 through v1.14.0 were all **lean
catch-up releases** (2-file bump: pyproject.toml + `__version__`)
consuming upstream axon-lang work. v1.15.0 is the first
**substantive enterprise-only** release in this cadence — it carries
the ~2 100 LOC + ~80 tests of Fase 29 R&D layered on top of the
fully-shipped OSS Fase 28+30+31+32+33 baseline.

> **Companion documents:**
> - OSS baseline: [`fase_28_adopter_diagnostic_robustness.md`](fase_28_adopter_diagnostic_robustness.md) — every Fase 29 surface is layered on top of this.
> - Public adopter guide: [`ADOPTER_DIAGNOSTICS.md`](ADOPTER_DIAGNOSTICS.md) — adopter-facing prose for the OSS surface; Fase 29 will extend the enterprise-specific section in `axon-enterprise/docs/INTEGRATION_GUIDE.md`.

## ▶ Status snapshot (2026-05-10 — DRAFTED)

Fase 28 closed the OSS adopter diagnostic surface (recovery + source-
context + smart-suggest + multi-file + JSON + strict + cross-stack
drift gate). Every adopter, including enterprise tenants, now sees
the full diagnostic landscape in one pass.

Fase 29 layers the **enterprise-only privileged R&D** on top:
vertical-aware policy (HIPAA / legal / fintech tenants get
default-strict diagnostics + per-vertical suggest dictionaries),
telemetry sink integration (OTel spans + Prometheus counters +
audit log entries for every parser error), and adopter diagnostic
dashboard surface (privacy-preserving aggregate view per tenant).

The OSS axon-lang baseline stays unchanged — Fase 28 already shipped
every observable surface adopters depend on. Fase 29 is a pure
**axon-enterprise** release; OSS tenants keep their existing surface
verbatim, enterprise tenants gain the regulated-vertical extensions.

**Charter discipline (rep from prior fases):**
> *axon-enterprise NO es solo wrapper multitenant; es capa privilegiada
> con R&D vertical (Salud/HealthTech/Legal/Fintech) + behaviors
> enterprise-only.*

Fase 29 is the canonical example: every sub-fase below is **ENTERPRISE-only**.

| Sub-phase | Status | LOC target | Stack | Module(s) / Notes |
|---|---|---|---|---|
| 29.a Engineering spec + D-letter ratification | ✅ SHIPPED 2026-05-12 (axon-lang commit `7ceb9ec`) | doc-only | — | Plan vivo header refreshed to current enterprise cadence (v1.14.0 shipped, v1.15.0 target); D1–D10 RATIFICADAS bloque; 5 open questions resolved with recommended defaults; sub-fase table marked executable. Memory entry `project_fase_29_plan.md` created. |
| 29.b Vertical-aware diagnostic policy | ✅ SHIPPED 2026-05-12 (axon-enterprise commit `645324b` on `feature/29b-vertical-diagnostic-policy`) | ~835 (module + tests) | Python | New `axon_enterprise.diagnostics.policy` module: closed-catalog `TenantVertical` StrEnum {GENERIC, HIPAA, LEGAL, FINTECH} with per-vertical default `DiagnosticPolicy` (HIPAA+legal → strict+telemetry; fintech → recovery+telemetry; generic → OSS Fase 28 verbatim per D9). Frozen+slots dataclass + RLock-guarded tenant registry + current-tenant resolution helper + `to_parse_args()` projecting to OSS `axon parse --strict` flag (D5 — axon-lang unchanged). Module-load assertion enforces every variant has a default (closed-catalog pin). **36 tests** across §1 catalog closure + §2 per-vertical defaults + §3 from_str fallback + §4 override semantics + §5 CLI projection + §6 registry CRUD + §7 D8 multi-tenant isolation + §8 current-tenant resolution + §9 thread safety stress test + §10 D9 OSS-default invariant pin + §11 extra_keywords plumbing + §12 equality/hashability. All pass in 8.89s. |
| 29.c Diagnostics-to-telemetry sink | ✅ SHIPPED 2026-05-12 (axon-enterprise commit `32e53a8` on `feature/29b-vertical-diagnostic-policy`) | ~893 (module + tests + audit event + Prom counter) | Python | New `axon_enterprise.diagnostics.telemetry` module + Prometheus counter `PARSER_ERRORS_TOTAL` in `observability/metrics.py` + new `AuditEventType.COMPLIANCE_PARSE_ERROR`. **D4 privacy boundary baked into the type**: `ParserDiagnostic` frozen+slots dataclass has only `code / file_path / line / column / severity` — no source/snippet/content/text/body field. `emit_parser_error()` fans out to 3 sinks (OTel span `axon.diagnostics.parse_error` + Prometheus counter `axon_parser_errors_total{tenant_id, vertical, code}` + audit-log entry via injectable `AuditSink` Protocol). Best-effort sink isolation (one sink's exception doesn't block others). D9 gate: `telemetry_enabled=False` → no-op across all sinks. **22 tests** across §1 closed-catalog severity + §2 D4 privacy boundary (type has no source field + frozen) + §3 D9 telemetry-disabled no-op + §4 three-sink fan-out + §5 D8 multi-tenant isolation + §6 explicit policy override + §7 audit sink hooks + §8 best-effort sink isolation + §9 InMemoryAuditSink helpers + §10 severity propagation + §11 forward-compat tenant_id. All pass in 5.07s. Combined 29.b + 29.c: 58 tests green. |
| 29.d Vertical-aware suggest dictionaries | ✅ SHIPPED 2026-05-12 (axon-enterprise commit `f58c1f7` on `feature/29b-vertical-diagnostic-policy`) | ~1019 (module + 3 JSON dicts + tests + `dicts/__init__.py`) | Python + JSON | New `axon_enterprise.diagnostics.suggest_dicts` module + 3 version-controlled dictionaries in `axon_enterprise/diagnostics/dicts/`: `hipaa.json` (52 terms, 45 CFR Parts 160/164 + Safe Harbor §164.514(b)(2) + PSQIA), `legal.json` (51 terms, Upjohn + Hickman + FRE 408/502/801/901 + FRCP 26-65 + ABA Model Rules 1.1-1.10/4.1/5.3), `fintech.json` (51 terms, BSA + USA PATRIOT §§311-314 + FinCEN SAR/CTR + FATF placement/layering/integration + OFAC SDN + PCI DSS Req 3/4/10/12 + ISO 13616/9362/20022 + MiFID II + PSD2). **Total 154 curated terms** with D3-mandated provenance per entry. **D3 enforced at 2 layers** (`DictEntry.__post_init__` raises on empty provenance + raw-file shape test). **D7 enforced via PR labels** + CODEOWNERS (path established for deploy-time reviewer assignment). **D8 enforced at 3 layers** (per-file `vertical` declaration check + `assert_no_cross_vertical_contamination()` CI gate helper + pairwise-disjoint tests for all 3 combinations). **D9 enforced**: GENERIC has no dict file → loads to empty `VerticalDictionary` → OSS Fase 28 surface verbatim. `policy_with_suggest_dict(policy)` + `resolve_policy_with_dict_for_vertical(vertical)` wire the 29.b `extra_keywords` hook — `DiagnosticPolicy.extra_keywords` now populated from the resolved vertical's term tuple. Type-level invariants: `DictEntry` + `VerticalDictionary` frozen+slots; loader cached per-process for O(1) re-resolution. **29 tests** across §1 closed-catalog loadability + §2 D3 provenance discipline + §3 first-cut size (≥50 terms/vertical) + semver shape + §4 D8 multi-vertical safety (5 tests) + §5 duplicate detection + §6 loader cache + §7 DiagnosticPolicy integration (4 tests) + §8 accessors + §9 validation (3 tests) + §10 raw-file shape pin + §11 immutability + §12 identifier-shape pin. All pass in 4.98s. Combined 29.b + 29.c + 29.d: **87 diagnostics tests green**. |
| 29.e Adopter diagnostic dashboard endpoint | ✅ SHIPPED 2026-05-12 (axon-enterprise commit `6bc0fd4` on `feature/29b-vertical-diagnostic-policy`) | ~1336 (store module + HTTP route + 33 tests) | Python | New `axon_enterprise.diagnostics.store` module + `GET /api/v1/tenant/diagnostics/recent` route. **Store layer**: `RecentDiagnosticsStore` per-process, per-tenant ring buffer (capacity 500 default, RLock-guarded); `DiagnosticRecord` frozen+slots dataclass with **D4 baked into the type** (no `source`/`snippet`/`content`/`text`/`body` field); `AggregatedDiagnostic` grouping by `(file_path, code, line_bucket, vertical)` sorted by `(count, last_seen)` desc; `StoreBackedAuditSink` is the 29.c `AuditSink` Protocol impl that feeds the store automatically when wired at bootstrap. **HTTP route**: query params `since` (ISO-8601 cursor, strict >), `limit` (clamped `[1,500]`, default 50), `aggregated` (default true), `bucket_size` (clamped `[1,1000]`, default 10), `file_path`/`code` (raw-mode filters). Response envelope: `{tenant_id, vertical, mode, limit, bucket_size, entries}`. **D4 enforced at 3 layers**: type has no source field + `_record_to_json`/`_aggregated_to_json` only emit declared fields + test pack pins forbidden-key disjointness across both modes. **D8 enforced**: every query keyed on `require_principal().tenant_id`; cross-tenant retrieval structurally impossible (every plausible param-tampering vector tested). **D9 enforced**: generic tenants surface as `vertical: "generic"` with empty entries (telemetry-disabled by 29.b default). **Q4 enforced**: auth via existing `require_principal()` only; no new `diagnostics:read` RBAC slug (deferred to v1.15.x if demand surfaces). **33 tests** across §1 D4 record boundary + §2 store basic ops (6 tests: empty/round-trip/newest-first/limit/clamping) + §3 ring buffer capacity + §4 aggregation grouping (4 tests) + §5 D8 store isolation (2 tests) + §6 StoreBackedAuditSink round-trip + D9 silence + §7 HTTP auth gate + §8 HTTP response shape + D4 + D8 + pagination + filters (12 tests) + §9 store hooks. All pass in 6.17s. Combined 29.b + 29.c + 29.d + 29.e: **120 diagnostics tests green**. |
| 29.f Vertical compliance gate (CI integration) | ✅ SHIPPED 2026-05-12 (axon-enterprise commit `c99c9e5` on `feature/29b-vertical-diagnostic-policy`) | ~1819 (gate verdict module + CLI subcommand + composite action + 52 tests) | Python + YAML | New `axon_enterprise.diagnostics.gate` pure-verdict module + `axon-enterprise diagnostics gate` Typer subcommand + GitHub Actions **composite action** at `.github/actions/axon-enterprise-ci-gate/action.yml` (per Q5). **Verdict layer**: `GateVerdict` closed catalog `{PASS, FAIL_EXCEEDED, FAIL_INPUT}` with exhaustive exit-code projection `0/1/2`; `GateConfig` (max_errors, max_warnings, fail_on_hint, require_mode); `GateResult` with `SeverityCounts` (errors/warnings/hints/unknown) + `format_summary()` D4-safe human projection; `evaluate(payload, config)` is pure, never raises — malformed payloads surface as `FAIL_INPUT`. **CLI layer**: `axon-enterprise diagnostics gate` registered under parent Typer app via `add_typer`; flags `--endpoint` / `--token` (with `AXON_ENTERPRISE_ENDPOINT` / `AXON_ENTERPRISE_TOKEN` env fallback) + `--max-errors` / `--max-warnings` / `--fail-on-hint` / `--since` (ISO-8601 OR relative duration `<N>{s,m,h,d}`) / `--limit` (1-500) / `--mode` (aggregated/raw) / `--file-path` / `--code` / `--bucket-size` (1-1000) / `--timeout` / `--json`. **Composite action**: Q5 ratificada — composite (not reusable workflow) for one-line adopter integration; inputs mirror CLI flag set 1:1; outputs `verdict` + `exit-code` for downstream-step branching; steps `setup-python@v5` + `pip install axon-enterprise` + run-gate. **D4 enforced at 3 layers**: type has no source field + `format_summary`/`_result_to_json` only project declared fields + integration test pins forbidden keys NEVER reach stdout. **D5 enforced**: gate runs AFTER axon-lang (axon-lang's `axon parse` exit-code contract preserved verbatim); CLI lives in axon-enterprise, never modifies upstream. **D9 enforced**: composite action is opt-in; generic tenants pass trivially. **Q5 ratificada**: composite action chosen for one-line adopter integration ergonomics. **52 tests** across §1 closed verdict catalog + exit-code projection (2) + pure verdict logic PASS/FAIL_EXCEEDED/FAIL_INPUT (16) + format_summary D4 (2) + §2 _parse_since (9) + §3 CLI argv + env-var (6) + §4 E2E via stubbed fetcher (6) + §5 composite-action YAML lint (4) + §6 transport via httpx.MockTransport (3). All pass in 8.96s. **Combined 29.b + 29.c + 29.d + 29.e + 29.f: 172 diagnostics tests green**. |
| 29.g CI matrix: vertical diagnostic gate | ⏳ pending | ~200 (YAML + tests) | YAML + Python | New `.github/workflows/fase_29_vertical_diagnostics.yml` in axon-enterprise: 3 parallel lanes — vertical-policy (HIPAA / legal / fintech / generic resolution), telemetry-sink (OTel + Prom + audit log emit), suggest-dict (vertical-aware Levenshtein hints). Each lane runs against a curated `tests/fixtures/fase29_vertical_corpus.json` corpus. |
| 29.h Adopter guide: vertical diagnostic recipes | ⏳ pending | ~400 (Markdown) | Docs | Extension of existing `axon-enterprise/docs/INTEGRATION_GUIDE.md` with new section "Vertical Diagnostic Policy" covering: (1) tenant vertical resolution + default policies; (2) opting into / out of strict mode per vertical; (3) configuring the telemetry sink; (4) consuming `/v1/diagnostics/recent`; (5) installing the CI gate; (6) common vertical-suggest patterns. D10 — extend existing doc, no new file. |
| 29.i Coordinated release | ⏳ pending | release | — | bump-my-version minor bump 1.14.0 → 1.15.0; PR + merge + tag via refspec mapping `enterprise/v1.15.0:refs/tags/v1.15.0`; GitHub Release with content-first notes (NOT "Fase 29 release" — describe what it includes per versioning discipline); axon-lang dep pin **STAYS at `>=1.24.0`** (no upstream change required — Fase 29 is pure enterprise R&D). |

**Tests target**: ~80 new tests covering vertical policy resolution
+ telemetry sink shape + privacy boundaries + suggest dictionary
loading + dashboard endpoint authn + CI gate exit codes.

---

## D-letters RATIFICADAS 2026-05-12 (bloque, founder verbatim "Te ratifico todos los D-Letters")

### D1 — Vertical default-strict policy

**Proposal:** HIPAA + legal verticals default to `--strict` mode
in `axon parse` invocations (no surprise diagnostic noise that
might inadvertently surface PHI / privileged content fragments
in CI logs). Fintech defaults to recovery + telemetry-on (full
diagnostic surface needed for audit trail). Generic tenants
unchanged from OSS default.

**Status:** ✅ RATIFICADA 2026-05-12 (bloque).
**Recommendation:** Ratify. Aligns with regulated-vertical risk
posture; per-vertical default keeps tenant-aware behavior without
forcing every tenant to remember to set the flag.

### D2 — Telemetry sink shape

**Proposal:** Three sinks emitted in parallel for every parser
error: (a) OTel span with `axon.diagnostics` instrumentation
namespace; (b) Prometheus counter
`axon_parser_errors_total{vertical, code, tenant}`; (c) audit-log
entry (HMAC-chained, existing audit_engine path). All three sinks
are opt-out per tenant via existing `tenant_settings.telemetry_*`
toggles (no new config surface).

**Status:** ✅ RATIFICADA 2026-05-12 (bloque).
**Recommendation:** Ratify. Every existing axon-enterprise
observability mechanism is reused; no new telemetry plumbing.

### D3 — Vertical-suggest dictionary curation

**Proposal:** Each vertical dictionary entry carries an explicit
provenance tag (source URL or canonical reference) reviewed by
compliance counsel for legal vertical, by the security team for
HIPAA vertical, and by AML team for fintech. Dictionaries live
in version control as JSON files; updates go through PR review.

**Status:** ✅ RATIFICADA 2026-05-12 (bloque).
**Recommendation:** Ratify. Provenance traceability is a regulated-
vertical baseline expectation; PR review keeps the supply chain
auditable.

### D4 — Diagnostic dashboard privacy posture

**Proposal:** `/v1/diagnostics/recent` emits ONLY: file path
(relative to repo root), line + column, error code, vertical,
timestamp. **NEVER source text content**. Adopter clients fetch
the source separately via existing repo access controls if they
need the full block. This keeps the dashboard tenant-isolated and
privacy-preserving even when adjacent verticals share a deployment.

**Status:** ✅ RATIFICADA 2026-05-12 (bloque).
**Recommendation:** Ratify. Privacy boundary identical to existing
audit-log discipline (no source content in long-retention storage).

### D5 — Compliance gate enforcement layer

**Proposal:** The vertical compliance gate (29.f) runs at CI
integration time as a separate composite action, NOT inside
axon-lang itself. axon-lang's `axon parse` continues to be a
diagnostic tool that exits 0/1/2/3 per the OSS contract; the
enterprise gate adds an enforcement layer ON TOP using
`/v1/diagnostics/recent` as the query interface.

**Status:** ✅ RATIFICADA 2026-05-12 (bloque).
**Recommendation:** Ratify. Preserves OSS contract (D9 from Fase 28
survives intact); enterprise adopters get hard enforcement via
the integration layer.

### D6 — Telemetry retention

**Proposal:** Audit-log diagnostic entries follow the existing
per-tenant retention policy (no special treatment). OTel spans
default to 7-day retention (matches existing OTel pipeline);
Prometheus counters are persistent (cardinality-bounded by the
vertical/code label set).

**Status:** ✅ RATIFICADA 2026-05-12 (bloque).
**Recommendation:** Ratify. Reuses existing retention infrastructure.

### D7 — Vertical-suggest dictionary update process

**Proposal:** Dictionary updates ship as separate PRs labeled
`vertical-dict:<vertical>`. Legal-vertical updates require sign-off
from a designated compliance reviewer. Medical/fintech updates
require sign-off from the respective vertical's tech lead.
Sign-off is enforced via CODEOWNERS file in the dictionaries
directory.

**Status:** ✅ RATIFICADA 2026-05-12 (bloque).
**Recommendation:** Ratify. Aligns with the v1.7.0 vertical Shield
R&D supply-chain discipline established for HIPAA/legal/AML
patterns.

### D8 — Multi-vertical safety

**Proposal:** Vertical X policy / dictionary / telemetry MUST
NEVER affect vertical Y tenants. Per-tenant scoping verified by
explicit isolation tests in 29.b/d/g. No cross-vertical alias
shadowing (mirrors the v1.7.0 Shield R&D multi-vertical-safe
ratification).

**Status:** ✅ RATIFICADA 2026-05-12 (bloque).
**Recommendation:** Ratify. Non-negotiable for multi-tenant SaaS;
existing axon-enterprise isolation primitives extend cleanly.

### D9 — Backwards compat for non-vertical tenants

**Proposal:** Tenants with `vertical = null` (generic) get
EXACTLY the OSS Fase 28 surface unchanged. No telemetry sink, no
default-strict, no extra suggest dictionaries. The enterprise
layer is invisible to generic tenants.

**Status:** ✅ RATIFICADA 2026-05-12 (bloque).
**Recommendation:** Ratify. Mirrors the OSS-default-preserved
discipline from D9 of Fase 28.

### D10 — Documentation strategy

**Proposal:** Extend existing `axon-enterprise/docs/INTEGRATION_GUIDE.md`
with a new "Vertical Diagnostic Policy" section. Do NOT create a
separate `ENTERPRISE_DIAGNOSTICS.md` file. Cross-link from
`axon-lang/docs/ADOPTER_DIAGNOSTICS.md` to the new section so OSS
adopters considering enterprise can discover the path.

**Status:** ✅ RATIFICADA 2026-05-12 (bloque).
**Recommendation:** Ratify. Single source of truth for enterprise
adopter docs; INTEGRATION_GUIDE.md is the canonical entry point
since Fase 21.i.

---

## Open questions — resolved 2026-05-12 with bloque ratification

The bloque ratification implicitly resolves the 5 open questions
along the **recommended** path documented in each D-letter section.
Captured here verbatim for execution clarity:

1. **HIPAA + legal default-strict** → **resolved YES (D1)**.
   HIPAA + legal verticals default to `--strict` mode; risk posture
   reasoning intact (noisy diagnostic logs in CI = separate risk
   class from compile-time fragments, but both mitigated by strict).
   Tenants can opt out via explicit `diagnostic_policy.strict = false`
   per-tenant override.

2. **Fintech telemetry-on default** → **resolved YES (D2)**.
   Fintech tenants get full telemetry by default — BSA / OFAC /
   MiFID II audit trail expectation is non-negotiable; opt-out
   available via existing `tenant_settings.telemetry_*` toggles
   (no new config surface per D2).

3. **Vertical-suggest dictionary first-cut size** → **resolved
   ~50 per vertical (D3)**. Start with ~50 high-confidence terms
   per vertical (curated from canonical glossaries with provenance
   tags); subsequent dictionary updates via PR review per D7.
   Broader coverage (~200+) deferred to v1.15.x patches.

4. **Dashboard endpoint authentication scope** → **resolved
   existing tenant-context middleware only (D4)**. `/v1/diagnostics/recent`
   goes through the Fase 21.c tenant-context middleware exclusively;
   no new RBAC permission slug introduced (avoids cross-fase
   coupling). If adopter demand for finer-grained
   `diagnostics:read` permission surfaces post-v1.15.0, a follow-up
   patch can add it without breaking the v1.15.0 contract.

5. **CI gate as composite action vs reusable workflow** → **resolved
   composite action (D5)**. Composite action is simpler for adopters
   to integrate (one-line workflow snippet); evolution path is
   feasible via versioned tags on the action itself. Reusable
   workflow deferred to follow-up if multi-step orchestration becomes
   necessary.

---

## Out of scope (future fases)

- **LSP server enterprise extension** — vertical-aware diagnostics
  in the IDE via axon-lsp. Requires axon-lsp integration of
  `to_lsp_diagnostic` first (already shipped in axon-lang Fase 28),
  then enterprise overlay. Deferred to Fase 30 candidate.
- **IR-level diagnostics with vertical context** — extending the
  recovery surface from parser to type-checker / IR-generator stages
  with vertical-aware error categories. Requires baseline IR-level
  recovery in axon-lang first (not yet shipped). Deferred.
- **Real-time diagnostic dashboard UI** — JS / React frontend
  consuming `/v1/diagnostics/recent`. Backend endpoint ships in
  29.e; UI is a separate axon-enterprise-frontend project.

---

## Why minor release (SemVer minor bump)

New observable surfaces (vertical policy, telemetry sink, dashboard
endpoint, CI gate) are pure additions. axon-lang stays at v1.20.0+
unchanged. Existing axon-enterprise integrations work verbatim;
generic tenants see no behavior delta (D9). Minor bump signals new
features without breaking changes — exact version number depends
on the cadence of preceding releases (see § Versioning convention
at the top of this doc).

---

## How to apply (when shipped)

When an enterprise adopter on a regulated vertical reports diagnostic
noise / privacy concerns, point them at the new
`INTEGRATION_GUIDE.md` "Vertical Diagnostic Policy" section. The
default policy (D1) handles 90% of cases; per-tenant override via
`tenant_settings.diagnostics_policy` covers the rest. CI gate
(29.f) is the contract enforcement layer for adopters who want
hard "no parse errors merged" guarantees.
