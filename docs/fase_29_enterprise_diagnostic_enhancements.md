---
title: "Plan vivo: Fase 29 — Enterprise Diagnostic Enhancements"
status: IN PROGRESS 2026-05-12 — D1–D10 RATIFICADAS bloque (founder verbatim "Te ratifico todos los D-Letters"); 9 sub-fases 29.a-i ejecutables; target axon-enterprise v1.15.0 (next minor after the Fase 33 catch-up at v1.14.0)
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
| 29.a Engineering spec + D-letter ratification | 🔄 IN PROGRESS 2026-05-12 (this commit) | doc-only | — | This doc updated: status header refreshed to current enterprise cadence (v1.14.0 shipped, v1.15.0 target); D1–D10 RATIFICADAS bloque; 5 open questions resolved with recommended defaults; sub-fase table marked executable. 29.b–29.i may now proceed. |
| 29.b Vertical-aware diagnostic policy | ⏳ pending | ~400 | Python | New `axon_enterprise.diagnostics.policy` module: per-tenant `DiagnosticPolicy` resolved from tenant's vertical (HIPAA / legal / fintech / generic); HIPAA + legal default to strict mode; fintech defaults to recovery + telemetry-on; generic tenants unchanged. Hooks into `axon parse` invocation via wrapper that injects policy into args (no axon-lang code change — pure adapter). Test pack covers all 4 vertical defaults + override semantics + multi-tenant isolation (D8). |
| 29.c Diagnostics-to-telemetry sink | ⏳ pending | ~500 | Python | New `axon_enterprise.diagnostics.telemetry` module: every parser error → OTel span (with vertical/tenant/severity attributes) + Prometheus counter (`axon_parser_errors_total{vertical, code, tenant}`) + audit-log entry (HMAC-chained per tenant per existing audit_engine). Privacy discipline: NO source text in OTel/Prom labels; audit log includes file path + line + col + error code only. Tests cover happy path + privacy boundary (no source leak) + telemetry-disabled tenant (opt-out). |
| 29.d Vertical-aware suggest dictionaries | ⏳ pending | ~350 | Python | Extends OSS `_TOP_LEVEL_KEYWORD_NAMES` + `_FLOW_BODY_KEYWORD_NAMES` with vertical-specific aliases (no upstream change — wrapper layer). Curated from public-domain medical/legal/fintech terminology glossaries (verifiable provenance per dictionary entry, ~50 terms per vertical first-cut per D3 resolution). Wired via a `DiagnosticPolicy.extra_keywords` hook the policy module passes into the parser invocation. Multi-vertical safe: `medical` policy loads medical dict only, never legal/fintech. |
| 29.e Adopter diagnostic dashboard endpoint | ⏳ pending | ~400 | Python | New `/v1/diagnostics/recent` HTTP endpoint: returns last-N parse errors per tenant aggregated by file + error code + line range. Privacy posture (D4): NO source text in response; only counts + line/col + error code + vertical + timestamps. Pagination via `?since=` cursor. Authenticated via existing tenant-context middleware (Fase 21.c, per Q4 resolution — no new RBAC slug). |
| 29.f Vertical compliance gate (CI integration) | ⏳ pending | ~250 | Python + YAML | New `axon-enterprise-ci-gate` Python script + GitHub Actions **composite action** (per Q5 resolution): queries `/v1/diagnostics/recent` for the tenant's repo, asserts zero parse errors (or ≤ N depending on tenant's policy), exits non-zero if gate fails. Adopter installs via single line in their workflow. The gate is enforced AT CI INTEGRATION TIME, NOT inside axon-lang itself (D5 — OSS contract preserved). |
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
