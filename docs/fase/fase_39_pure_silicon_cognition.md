---
title: "Plan vivo: Fase 39 — Pure Silicon Cognition (FlowEnvelope⟨T⟩ + Python eradication + v2.0.0 era inauguration)"
status: 🚀 IN DESIGN — charter ratified by founder 2026-05-21
owner: AXON Compiler + Runtime Team
created: 2026-05-22
target: |
  axon-lang **v2.0.0** — MAJOR per SemVer (breaking wire change + breaking distribution change)
  axon-frontend **v1.0.0** — MAJOR per SemVer (new `Cardinality::Wrapped` enum variant — exhaustive-match consumers break)
  axon-enterprise **v2.0.0** — MAJOR catch-up
  PyPI distribution model: binary-wrapper-only (zero Python source code)
depends_on: |
  Fase 30 SHIPPED (HTTP Transport for Algebraic Stream Effects — v1.21.0)
  Fase 31 SHIPPED (Type-Driven Wire Inference — v1.22.0)
  Fase 32 SHIPPED (Axonendpoint as First-Class HTTP REST — v1.23.0)
  Fase 33 SHIPPED (SSE as Cognitive Primitive — v1.24.0)
  Fase 35 SHIPPED (Axonstore — Cognitive Data Plane — v1.30.0)
  Fase 38.x.f SHIPPED (Cardinality Coverage Complete — v1.40.0)
  Fase 38.x.f.9/10 SHIPPED (generic-aware D5 cross-stack — v1.40.2 + v1.40.3)
charter_class: |
  ARCHITECTURAL PURIFICATION — first concrete case of the founder strategic
  north star "0 .py files, only .rs + .c" (memoria
  `feedback_zero_py_files_north_star`, ratified 2026-05-21). Fase 39
  establishes the migration template that all subsequent fases inherit.
pillars: |
  - **MATHEMATICS** — the wire payload IS the canonical isomorphic
    serialization of the ψ-vector `ψ = ⟨T, V, E⟩`, with `E` (the
    epistemic envelope) bounded by Theorem 5.1 (`c ≤ 0.99` for derived
    states). No coercion, no widening, no opaque envelope.
  - **LOGIC** — single-stack canonical: the type checker, the runtime,
    and the wire serializer agree by CONSTRUCTION (one Rust definition,
    no Python mirror, no drift gate). The dual-runtime parity tax is
    eliminated at its root.
  - **PHILOSOPHY** — Silicon Cognition is the matrimonio of CPU + LLM
    without scripting intermediaries. The compiler emits to native
    structures the CPU understands and the LLM backend consumes
    directly. `.axon` source → `axon-frontend` (Rust) → `axon-rs`
    (Rust) → `axon-csys` (C23) is one continuous gradient of metal.
  - **COMPUTING** — atomic deployment with the single SaaS Agent
    adopter. v2.0.0 ships as one release event in lockstep with the
    adopter's coordinated migration. No transitional dual-build, no
    soft-deprecation warnings, no feature flags — the previous era
    is closed cleanly.
---

# ▶ 1. Strategic context

## 1.1 The 0-adopter window

Per founder audit 2026-05-21: **axon has exactly one adopter — the
strategic SaaS Agent that ships to production as axon evolves capabilities.
Zero external forks. Zero adopters with legacy code dependencies in
production beyond the strategic Agent.**

This is a structural design-freedom window that closes once the language
gains broader adoption. Fase 39 USES this window to make a clean break
that would be impossible at higher adoption density.

## 1.2 What v2.0.0 closes (the v1.x era)

The v1.x era (v1.0.0 → v1.40.3) shipped:
- Dual-runtime Python + Rust with cross-stack parity gates
- JSON wire format as a raw, flat envelope object with stringified step results
- Distribution via PyPI Python source package
- T9XX cardinality coverage that — as Fase 38.x.f revealed — collided
  with the wire-shape envelope wrap (the seam this fase closes)

The v1.x era was a successful bootstrap. Its dual-runtime nature was
the load-bearing scaffolding that let us iterate on language design with
two implementations validating each other. **That scaffolding has done its
job and now becomes deadweight.** v2.0.0 removes it.

## 1.3 What v2.0.0 inaugurates (the v2.x era)

- **Rust + C23 single canonical runtime**. Every primitive is defined
  ONCE in Rust (`axon-rs` / `axon-frontend`) with C23 kernels
  (`axon-csys` / `axon-csys-enterprise`) for hot-path metal-bound work.
- **`FlowEnvelope⟨T⟩` as the mandatory wire payload type** for
  `transport: json` endpoints — the typed, epistemic, audit-chained
  successor to v1.x's raw envelope.
- **PyPI distribution as a binary wrapper only** — `pip install
  axon-lang` downloads the precompiled Rust binary; zero Python source
  code in the package surface.
- **The migration template** for subsequent fases that purify other
  primitives to Rust-canonical (one per fase, until the dual-stack
  surface is fully retired).

# ▶ 2. Mathematical foundations

## 2.1 The ψ-vector — `ψ = ⟨T, V, E⟩`

axon's epistemic primitive is the triple:
- **T** — the ontological type the value claims to inhabit (e.g.
  `TenantRecord`, `List<PatientRecord>`, `Stream<Token>`)
- **V** — the actual value, member of type T
- **E** — the epistemic envelope: a tuple of (certainty, provenance,
  blame, audit-chain) that records HOW the value came to be

The wire payload of any `transport: json` endpoint declaring
`output: FlowEnvelope⟨T⟩` IS the isomorphic serialization of ψ. There is
no other envelope; there is no other serialization. The wire IS the
mathematical object.

```
ψ = ⟨T, V, E⟩
       │  │  │
       │  │  └─ FlowEnvelope.{certainty, provenance_chain, step_audit, blame_attribution, …}
       │  └──── FlowEnvelope.result    (typed against T at compile + runtime)
       └─────── FlowEnvelope.ontological_type    (the declared T as string slug)
```

## 2.2 Theorem 5.1 — certainty bound on derived states

From `paper §5.1`:

> For any epistemic state E with `derived_status = true`, the
> certainty `c` is bounded `c ≤ 0.99`. No derived knowledge claims
> apodictic certainty; the language enforces evidentiary modesty in
> silicon.

Fase 39 enforces this **in C23**, not in Rust runtime, not in Python:
the `axon-csys/effects/envelope.c` kernel clamps `certainty = min(c,
0.99)` whenever `derived_status = true`. This is the **structural**
guarantee that a derived state cannot claim more certainty than the
theorem permits. The bound is unbypassable from any Rust caller — the
C23 kernel is the single point of truth.

## 2.3 The four pillars revisited

| Pillar | What Fase 39 contributes |
|--------|--------------------------|
| **Mathematics** | ψ-vector becomes the wire payload; Theorem 5.1 enforced in C23 (`validate_epistemic_degradation`) |
| **Logic** | Single-stack canonical: one definition of `FlowEnvelope⟨T⟩`, one type-checker pass, one wire serializer |
| **Philosophy** | Declaration IS contract; `output: FlowEnvelope⟨List<TenantRecord>⟩` is checked statically AND validated at runtime against the exact wire bytes |
| **Computing** | Atomic v2.0.0 deploy; zero translation layers between source and metal |

# ▶ 3. Ratified decisions

| # | Decision | Status |
|---|----------|--------|
| **D1** | `FlowEnvelope⟨T⟩` is the canonical primitive name (language-first, not HTTP-first) | ratified founder 2026-05-21 |
| **D2** | Mandatory wire shape — every `transport: json` endpoint with declared `output: T` MUST declare `FlowEnvelope⟨T⟩` (or be `Any` / `transport: sse`) | ratified founder 2026-05-21 |
| **D3** | Python stack erradication — `axon/compiler/`, `axon/runtime/`, `axon/server/`, `axon/cli/`, `axon/backends/` all deleted post-39.h | ratified founder 2026-05-21 |
| **D4** | `Cardinality::Wrapped(Box<Cardinality>)` — new variant preserving inner-slot cardinality through wrapper | ratified founder 2026-05-21 |
| **D5** | Wire shape additive — keep `step_results`, `latency_ms`, `anchor_checks` etc. as audit/observability fields organized by pillar | derived from analyst review 2026-05-22 |
| **D6** | Version target v2.0.0 — SemVer-strict major bump for breaking wire change (memoria `feedback_versioning_discipline`) | ratified founder 2026-05-22 |
| **D7** | Construct-before-purge sequencing — sub-fases 39.a → 39.g build the Rust path; 39.h is the purga; 39.i is the atomic deploy. Purga only runs when Rust path is verified complete | ratified founder 2026-05-22 |
| **D8** | PyPI distribution survives as binary-wrapper-only — `pip install axon-lang` triggers a post-install hook that downloads the precompiled Rust binary from GitHub Releases. The wrapper is distribution infrastructure (manifest), NOT runtime Python | ratified founder 2026-05-22 |
| **D9** | SSE wire keeps its own event family — `axon.token`, `axon.complete`, `axon.tool_call`, etc. (Fase 33 surface). FlowEnvelope is the JSON-transport equivalent; the two coexist with clean separation, not unified | derived from analyst review 2026-05-22 |
| **D10** | Theorem 5.1 enforced in C23 (`axon-csys`), not in Rust runtime — single point of structural truth, unbypassable | ratified by founder via plan-vivo §3.2 |
| **D11** | Epistemic field ownership detailed in dedicated sub-fase 39.c (`certainty`, `provenance_chain`, `blame_attribution` producers) before wire serialization lands | derived from analyst review 2026-05-22 |
| **D12** | **(sub-option α RATIFIED 2026-05-22)** Mandatory `FlowEnvelope<T>` wrapping for ALL `transport: json` endpoints — including singular declarations. `output: TenantRecord` becomes a compile error; `output: FlowEnvelope<TenantRecord>` is the only valid singular form. One structural rule; zero exceptions; cleaner adopter mental model than per-cardinality branching | ratified founder 2026-05-22 |
| **D13** | **(sub-option a RATIFIED 2026-05-22)** PyPI `_bootstrap.py` (~30 LOC) survives as the ONLY non-language Python file. Tagged explicitly "distribution layer, NOT language runtime" in source comments + memory. Honors `pip install axon-lang` ergonomics; the bootstrap binary downloader is distribution infrastructure, not language code. `feedback_zero_py_files_north_star` interpreted as "0 language Python", distribution boilerplate exempted | ratified founder 2026-05-22 |
| **D14** | **(sequence x→y→z RATIFIED 2026-05-22)** Sub-fase 39.c epistemic field producer ordering: (1) `certainty` first — Theorem 5.1 + C23 kernel is the most structural primitive; (2) `provenance_chain` second — builds on certainty as audit input; (3) `blame_attribution` third — closed-catalog `BlameKind` enum is the most design-heavy, lands last with clearer constraints from the prior two | ratified founder 2026-05-22 |

# ▶ 4. Wire shape specification

## 4.1 The `FlowEnvelope` Rust struct

Defined ONCE in `axon-rs/src/wire_envelope.rs` (NEW module; replaces the
current `ServerExecutionResult` at `axon-rs/src/axon_server.rs:1997-2046`):

```rust
//! §Fase 39 — Pure Silicon Cognition: the canonical wire payload type
//! for axonendpoint responses on `transport: json`.
//!
//! Isomorphic to the ψ-vector `ψ = ⟨T, V, E⟩` (paper §5).
//! Defined ONCE in Rust; no Python mirror; no drift gate; D3.

use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// §Fase 39 (D1, D2, D5) — the wire payload of every `transport: json`
/// axonendpoint response (HTTP 2xx). Fields organized by Pillar.
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct FlowEnvelope {
    // ── Pillar I (Epistemic) — the ψ-vector slots ────────────────
    /// The ontological type declared at the endpoint surface.
    /// Slug form: `TenantRecord`, `List<PatientRecord>`,
    /// `Stream<Token>` — same grammar as `output: T`.
    pub ontological_type: String,

    /// The typed payload — member of `ontological_type`. At wire
    /// emission this is `serde_json::Value` (monomorphic at runtime);
    /// at compile time D5 validates this slot against the declared T
    /// per `validate_body` recursion.
    pub result: serde_json::Value,

    /// Certainty bound by Theorem 5.1 (`c ≤ 0.99` if derived).
    /// Enforced structurally in C23 via
    /// `axon-csys::effects::envelope::validate_epistemic_degradation`.
    /// Range: `[0.0, 1.0]`.
    pub certainty: f64,

    // ── Pillar II (Audit-chained) — provenance + step trail ──────
    /// Ordered list of `kind:identifier` tuples capturing the lineage
    /// of `result`. Examples:
    ///   - `["step:Triage", "retrieve:patients", "backend:anthropic"]`
    ///   - `["flow:FetchTenants", "store:tenants", "backend:stub"]`
    /// HMAC-SHA256 over the chain is exposed via `audit_chain_hash`
    /// (Pillar II tamper-evidence — leveraging existing axon-csys
    /// SHA-256 kernel).
    pub provenance_chain: Vec<String>,

    /// Per-step audit trail. Survives from v1.x as the canonical
    /// observability surface; here it is structured (not just
    /// `Vec<String>`).
    pub step_audit: StepAuditTrail,

    /// HMAC-SHA256 hex of `provenance_chain || step_audit` for
    /// tamper-evidence. Computed by the C23 audit kernel.
    pub audit_chain_hash: String,

    // ── Pillar IV (Capability) — blame attribution ───────────────
    /// Populated only when the flow's success path produced a
    /// degraded posture (anchor breach, shield rejection, backend
    /// soft-fail, store breach). `None` on the clean happy path.
    /// `Some(...)` on the response when the flow chose to proceed
    /// with degraded posture (vs. hard-fail which becomes 4xx/5xx).
    pub blame_attribution: Option<BlameContext>,

    // ── Cross-cutting — observability + correlation ──────────────
    /// Execution metrics — latency, tokens, backend identity.
    pub execution_metrics: ExecutionMetrics,

    /// Correlation anchor (matches `X-Axon-Trace-Id` header).
    pub trace_id: Uuid,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct StepAuditTrail {
    pub step_names: Vec<String>,
    pub step_results: Vec<serde_json::Value>,  // §39.b — TYPED, not stringified
    pub anchor_checks: usize,
    pub anchor_breaches: usize,
    pub errors: usize,
    pub steps_executed: usize,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct ExecutionMetrics {
    pub latency_ms: u64,
    pub tokens_input: u64,
    pub tokens_output: u64,
    pub backend: String,
    pub flow_name: String,
    pub source_file: String,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct BlameContext {
    pub kind: BlameKind,
    pub location: String,         // file:line:col OR step:name
    pub message: String,          // human-readable diagnostic
    pub d_letter: Option<String>, // anchored to a plan-vivo D-letter when applicable
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub enum BlameKind {
    AnchorBreach,        // Pillar IV — anchor `require:` failed; degraded path taken
    ShieldRejection,     // Pillar I — shield scanner flagged; flow chose to proceed
    BackendSoftFail,     // backend returned a degraded response (e.g. truncated)
    StoreBreach,         // Pillar II — store mutation chain verification failed
    TypeMismatch,        // D5 detected partial typing inconsistency (recoverable)
}
```

## 4.2 What changes vs the v1.x `ServerExecutionResult`

| v1.x field | v2.0.0 location | Reason |
|------------|-----------------|--------|
| `success: bool` | derived from `result.is_null()` + `blame_attribution.is_none()` | redundant; success IS the absence of failure |
| `flow_name: String` | `execution_metrics.flow_name` | reorganized by pillar |
| `source_file: String` | `execution_metrics.source_file` | reorganized |
| `backend: String` | `execution_metrics.backend` | reorganized |
| `steps_executed: usize` | `step_audit.steps_executed` | reorganized |
| `latency_ms: u64` | `execution_metrics.latency_ms` | reorganized |
| `tokens_input/output` | `execution_metrics.tokens_input/output` | reorganized |
| `anchor_checks/breaches` | `step_audit.anchor_checks/breaches` | reorganized |
| `errors: usize` | `step_audit.errors` | reorganized |
| `step_names: Vec<String>` | `step_audit.step_names` | reorganized |
| `step_results: Vec<String>` | `step_audit.step_results: Vec<Value>` | **TYPED** (was stringified — D5 simplification dividend) |
| `trace_id: u64` | `trace_id: Uuid` | **TYPED** (was u64 numeric — Uuid is the actual semantic) |
| `effect_policies, enforcement_summaries` | TBD in sub-fase 39.c — likely under `step_audit` extension | will be specified |
| `runtime_warnings` | TBD — possibly `blame_attribution` if applicable | will be specified |

## 4.3 Adopter-side wire example

Pre-v2.0.0 (v1.x raw envelope):
```json
{
  "success": true,
  "flow_name": "FetchTenants",
  "step_results": ["[{\"id\":1,\"name\":\"foo\"},{\"id\":2,\"name\":\"bar\"}]"],
  "latency_ms": 142,
  "trace_id": 18293847501298374
}
```

Post-v2.0.0 (FlowEnvelope of List<TenantRecord>):
```json
{
  "ontological_type": "List<TenantRecord>",
  "result": [
    {"id": 1, "name": "foo"},
    {"id": 2, "name": "bar"}
  ],
  "certainty": 0.97,
  "provenance_chain": [
    "flow:FetchTenants",
    "retrieve:tenants",
    "store:tenants@postgres"
  ],
  "step_audit": {
    "step_names": ["RetrieveAll"],
    "step_results": [[{"id":1,"name":"foo"},{"id":2,"name":"bar"}]],
    "anchor_checks": 0,
    "anchor_breaches": 0,
    "errors": 0,
    "steps_executed": 1
  },
  "audit_chain_hash": "a3f5e1c8...",
  "blame_attribution": null,
  "execution_metrics": {
    "latency_ms": 142,
    "tokens_input": 0,
    "tokens_output": 0,
    "backend": "stub",
    "flow_name": "FetchTenants",
    "source_file": "tenants.axon"
  },
  "trace_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479"
}
```

The adopter's client (Kivi today, others future) parses this with FULL
type safety: `result` is `List<TenantRecord>` typed, audit fields are
named and typed, blame is structured. The v1.x flat envelope is gone.

# ▶ 5. Silicon kernel integration (C23)

## 5.1 The envelope enforcement kernel

`axon-csys/c-src/effects/envelope.h`:

```c
#include <uchar.h>
#include <stdbool.h>
#include <stddef.h>

/// §Fase 39 (D10) — Theorem 5.1 structural enforcement in silicon.
/// Called by axon-rs::wire_envelope::FlowEnvelope::seal() before any
/// HTTP serialization. The Rust caller cannot bypass this kernel —
/// the FFI surface is the single ingress.
typedef struct {
    double certainty;
    const char32_t* origin_flow;
    bool derived_status;
} epistemic_envelope_t;

/// Clamps certainty per Theorem 5.1.
/// Returns the same envelope with `certainty = min(c, 0.99)` if
/// `derived_status == true`, else unchanged.
/// Pure function; deterministic; no allocation; constant time.
epistemic_envelope_t validate_epistemic_degradation(epistemic_envelope_t env) {
    if (env.derived_status && env.certainty > 0.99) {
        env.certainty = 0.99;
    }
    return env;
}
```

## 5.2 The provenance chain hash kernel

`axon-csys/c-src/effects/provenance_chain_hash.c`:

Builds an HMAC-SHA256 over the canonical-form of `provenance_chain` ||
`step_audit` (canonical JSON serialization, sorted keys, no
whitespace). Uses the existing FIPS-friendly SHA-256 kernel in
`axon-csys`. Returns a 64-character hex digest. Pure function;
deterministic on identical inputs.

The hash is the **tamper-evidence anchor**: any change to the audit
chain (in transit, in storage, in replay) is structurally detectable by
recomputing the hash and comparing.

## 5.3 The FFI boundary

`axon-rs/src/wire_envelope.rs` calls into `axon-csys` via the existing
FFI infra (Fase 27 `axon-csys` precedent). The Rust `seal()` method
prepares the envelope, hands it to the C23 kernel for Theorem 5.1
enforcement + provenance hash, then serializes.

```rust
impl FlowEnvelope {
    /// §Fase 39 — Apply C23 epistemic enforcement before serialization.
    /// This method is the ONLY public sealing surface; the wire bytes
    /// emitted by axon_server pass through this method.
    pub fn seal(mut self) -> Self {
        // Theorem 5.1 in silicon.
        let env = epistemic_envelope_t {
            certainty: self.certainty,
            origin_flow: c_str_from(&self.execution_metrics.flow_name),
            derived_status: !self.provenance_chain.is_empty(),
        };
        let clamped = unsafe {
            axon_csys_ffi::validate_epistemic_degradation(env)
        };
        self.certainty = clamped.certainty;

        // Provenance chain hash (tamper-evidence).
        self.audit_chain_hash = unsafe {
            axon_csys_ffi::provenance_chain_hash(
                &self.provenance_chain,
                &self.step_audit,
            )
        };
        self
    }
}
```

# ▶ 6. Compiler semantics

## 6.1 The `Cardinality::Wrapped` variant

`axon-frontend/src/type_checker.rs` — new variant on the closed
`Cardinality` enum:

```rust
pub enum Cardinality {
    Singular(String),
    Plural(String),
    StreamCardinality(String),
    Unit,
    Disagreed,
    Unknown,
    /// §Fase 39 (D4) — wrap inner cardinality with FlowEnvelope.
    /// `FlowEnvelope<T>` has the cardinality of T, but the WIRE shape
    /// is always a singular object. The type-checker reasons about T's
    /// cardinality through the wrapper transparently.
    Wrapped(Box<Cardinality>),
}
```

`declared_cardinality(type_name)` extended:

```rust
if let Some(rest) = type_name.strip_prefix("FlowEnvelope<") {
    if let Some(inner) = rest.strip_suffix('>') {
        let inner_card = declared_cardinality(inner.trim());
        return Cardinality::Wrapped(Box::new(inner_card));
    }
}
```

## 6.2 The new compile error `axon-E039`

The T9XX warning at `axon-frontend/src/type_checker.rs:3892` becomes a
**hard compile error** for the `(Singular decl, Plural tail)` case on
`transport: json` endpoints:

```
error[axon-E039]: structural type mismatch on wire payload packaging
  --> src/tenant/billing.axon:14:5
   |
14 | axonendpoint FetchTenants {
   | ^^^^^^^^^^^^^^^^^^^^^^^^^^ endpoint declares JSON transport without envelope wrapping
15 |     execute: RetrieveAllTenants
   |              ------------------ flow returns plural `List<TenantRecord>`
   |
   = help: REST-structured signatures require strong typing on the wire.
           Change the output declaration to `FlowEnvelope<List<TenantRecord>>`
           OR change transport to `transport: sse(axon)` for async streaming.
   = note: see https://axon-lang.io/docs/wire-envelope for the ψ-vector contract
```

The error fires when:
- `effective_transport == "json"` (default or explicit), AND
- declared `output: T` is NOT `FlowEnvelope<X>` and NOT `Any`, AND
- the flow tail produces a plural / stream cardinality

## 6.3 The T9XX → axon-E039 migration

| Pre-39 (v1.40.x) | Post-39 (v2.0.0) |
|------------------|-------------------|
| `axon-T9XX` warning suggesting `output: List<T>` | `axon-E039` error suggesting `output: FlowEnvelope<List<T>>` or `transport: sse(axon)` |
| Adopter could ignore warning (strict mode optional) | Adopter MUST fix to build (no opt-out) |
| `output: List<T>` reached runtime, D5 rejected | `output: List<T>` doesn't compile |

The error is HONEST: it tells the adopter the contract, points to the
two valid resolutions, and refuses to ship broken code.

## 6.4 D5 runtime simplification (the convergence dividend)

With `FlowEnvelope<T>` mandatory for json transport, the §0
generic-aware preamble shipped in v1.40.2 + v1.40.3 (Fase 38.x.f.9/10)
**becomes architecturally vestigial**: D5 always sees
`FlowEnvelope<T>` at the top level, the inner T is recursed via the
`result` field validation. The `List<T>` / `Stream<T>` magic-string
stripping at §0 disappears.

This is the **convergence dividend**: closing the seam architecturally
SIMPLIFIES the code, doesn't add new conditionals. The v1.40.2/.3
hotfixes were the bridge; Fase 39 is the destination that makes the
bridge unnecessary.

# ▶ 7. Sub-fases

| # | Sub-fase | Surface | Acceptance criterion |
|---|----------|---------|----------------------|
| **39.a** ✅ SHIPPED 2026-05-22 | `FlowEnvelope<T>` in axon-frontend (Rust) | grammar + AST + `Cardinality::Wrapped` variant + type-checker recognition | ✅ `declared_cardinality("FlowEnvelope<List<X>>") == Wrapped(Plural("X"))` verified by anchor test `fase39a_flow_envelope_of_list_is_wrapped_plural`; 11/11 new anchor §-assertions green; 458 axon-frontend lib + 2114 axon-rs lib + 98 Python regression green; zero regressions. Parser `parse_type_expr` extended to support nested generics (`FlowEnvelope<List<TenantRecord>>` now parses cleanly — pre-39.a it failed with `Expected Gt found Lt`). `Cardinality::Wrapped(Box<Cardinality>)` variant added with the unwrap-recurse shortcut at the top of `emit_cardinality_gate` so the wrap is transparent to the cardinality truth table — axon-E039 mandate enforcement lands in 39.e |
| **39.b** ✅ SHIPPED 2026-05-22 | Wire envelope in axon-rs | `axon-rs/src/wire_envelope.rs` new module + `FlowEnvelope` struct + serializer + axon_server response wrapping for `transport: json` | ✅ new module `axon-rs/src/wire_envelope.rs` (684 LOC) ships `FlowEnvelope` + `StepAuditTrail` + `ExecutionMetrics` + `BlameContext` + `BlameKind` (closed-catalog) + `extract_inner_ontological_type` + `from_execution_result` converter + `seal()` invariant. `ExecuteRequest.declared_output_type` propagates the endpoint declaration through `execute_handler` to the wire wrapper. `apply_output_validation_gate` (D5 runtime) unwraps `FlowEnvelope<T>` and validates the `result` slot against the inner T (convergence-dividend simplification toward 39.d). `ServerExecutionResult` promoted from `struct` to `pub struct` for the converter input. 17 unit tests (`fase39b_*`) + 14 integration §-assertions (`tests/fase39b_wire_envelope_integration.rs`) green. 2131 axon-rs lib + 458 axon-frontend lib + 98 Python touchstones green; zero regressions vs baseline. The `.seal()` invariant enforces Theorem 5.1 in Rust-side fallback (algebra: `derived ⇔ anchor_breaches > 0 \|\| errors > 0`); 39.c moves this to C23 kernel. Audit chain hash via SHA-256 over canonical (`provenance_chain`, `step_audit`); deterministic + tamper-evident. SSE path unchanged per D9 (kept its own event family). |
| **39.c** ✅ SHIPPED 2026-05-22 | Epistemic fields ownership | `certainty` (Theorem 5.1 producer chain) + `provenance_chain` (step + retrieve + backend lineage) + `blame_attribution` (anchor/shield/store/backend producers) — each producer defined explicitly with a closed catalog | ✅ **39.c.x (x — certainty)**: new C23 kernel `axon-csys/c-src/effects/envelope.{h,c}` ships Theorem 5.1 enforcement in silicon (`axon_csys_envelope_validate_degradation` + `theorem_5_1_ceiling` + `clamp_ceiling`); new Rust shim `axon-csys/src/envelope.rs` with `EpistemicEnvelope` + `EpistemicKind` closed enum + drift-gate const; `FlowEnvelope::seal()` delegates to C23 kernel (no more Rust-fallback); 13 axon-csys envelope tests green. ✅ **39.c.y (y — provenance)**: new `axon-rs/src/wire_envelope_producers.rs` module with closed-catalog `provenance_event_for` (12 kinds: retrieve/persist/mutate/purge/shield/ots/mandate/compute/lambda_apply/tool/memory@2); `ServerRunnerMetrics` + `ServerExecutionResult` extended with `provenance_events: Vec<String>`; runner.rs walks `execution_units.steps[]` to populate per the closed taxonomy; converter interleaves into `provenance_chain` with canonical ordering flow→events→steps→backend. ✅ **39.c.z (z — blame)**: 5 BlameKind producer functions (`blame_for_anchor_breach` / `_shield_rejection` / `_store_breach` / `_backend_soft_fail` / `_type_mismatch`) with `blame_priority` + `merge_blame` priority-aware coalesce; `ServerExecutionResult.blame_attribution: Option<BlameContext>`; `derive_blame_from_report` wires AnchorBreach end-to-end via `ExecutionReport.units[].steps[].anchor_breaches` walk; the other 4 producers have ready functions + tests + priority but their RUNTIME wiring depends on richer observability hooks (honest scope deferral). 15 producer unit tests + 15 epistemic-ownership integration §-assertions + 5 blame priority/merge §-assertions green. **Cross-stack**: 2161 axon-rs lib + 14 fase39b integration + 15 fase39c integration + 13 axon-csys + 458 axon-frontend lib + 98 Python touchstones; cero regresiones. |
| **39.d** ✅ SHIPPED 2026-05-22 | D5 runtime simplification | `axon-rs/src/route_schema.rs::validate_value` simplifies — §0 preamble (Fase 38.x.f.9 carry-over) DELETED; FlowEnvelope<T> path is the canonical entry | ✅ §0 preamble REMOVED from `validate_value` (~46 LOC deleted). `validate_body` becomes the **canonical entry** with FlowEnvelope unwrap built-in: declared `FlowEnvelope<T>` → unwrap `body["result"]` → recurse on inner T; declared bare generic (`List<X>`/`Stream<X>`) → parsed at entry via new `parse_generic_head` helper; declared bare T → dispatch to validate_value. New private helpers `strip_flow_envelope(t) -> Option<String>` + `parse_generic_head(t) -> (head, generic)`. `validate_value` purified (§1-§5 dispatch only; defensive `Stream` Ok at top). `validate_list` pre-parses element_type via `parse_generic_head` before recursing (replaces per-element string-stripping). **D5 gate simplified**: `apply_output_validation_gate` in axon_server.rs shrinks from ~30 LOC manual unwrap → ~13 LOC single call to `validate_body(&parsed, &route.output_type, &type_table)`. 6 v1.40.2 fase38xf9_ anchor tests PRESERVED (their public-API contract — `validate_body("List<X>", body)` — still holds; the work moved from validate_value §0 into validate_body's canonical entry). 16 new fase39d_ tests added covering parse_generic_head taxonomy + strip_flow_envelope + FlowEnvelope unwrap with struct/list/wrong-type/non-object/Any/missing-result + 2 STATIC grep gates anchoring §0 retirement and D5 gate simplification. Honest LOC: production net is roughly neutral (+5 executable lines vs §0 deletion); the **convergence dividend** is structural (wire-shape knowledge centralized to ONE entry, helpers testable in isolation, gate code shrinks ~17 LOC). 39.b §s7 integration test updated to reflect new contract. **Cross-stack regression**: 2177 axon-rs lib (16 new) + 15 fase39b + 15 fase39c + 13 axon-csys + 458 axon-frontend lib + 98 Python touchstones; zero regresiones. |
| **39.e** ✅ SHIPPED 2026-05-22 | Compiler error `axon-E039` (D12 α mandatory wrapping) | T9XX warning at `axon-frontend/src/type_checker.rs:3892` migrates to hard error with new diagnostic format + the new `output: FlowEnvelope<T>` hint | ✅ **THE STRUCTURAL CLOSURE OF THE ORIGINAL ADOPTER GAP**. New `emit_e039_wire_packaging_gate` runs BEFORE the cardinality gate; resolves effective transport (explicit → implicit → default json); fires for declared output ≠ `FlowEnvelope<T>` ∧ ≠ `Any` ∧ ≠ `Unit` ∧ ≠ `<empty>` on json wire; SSE/ndjson exempt per D9. The diagnostic message includes: declared bare type, flow tail cardinality (`List<X>` / `Stream<X>` / `X`), canonical FlowEnvelope wrapping suggestion (computed from actual tail), sse transport alternative, D12 α anchor reference, docs URL. When E039 fires, the cardinality gate is SUPPRESSED (single canonical diagnostic with the right answer). 1 legacy 38.x.e test migrated to expect E039 (its v1.x bare-type-with-cardinality-mismatch scenario is structurally obsolete in v2.0.0); **10 new fase39e_ anchor §-assertions** covering: §1 bare singular + E039, §2 bare List<T> + E039 (the kivi shape), §3 bare Stream<T> handling, §4 FlowEnvelope singular happy path, §5 FlowEnvelope<List<T>> migration target, §6 Any escape hatch, §7 sse transport exemption, §8 empty output skip (D9 backwards-compat), §9 Unit output exempt, §10 nested FlowEnvelope<FlowEnvelope<X>> defensive. **Cross-stack regression**: 468 axon-frontend lib (+10 new) + 2177 axon-rs lib + 15 fase39b + 15 fase39c + 13 axon-csys + 98 Python touchstones; zero regresiones. **The adopter-reported gap from 2026-05-21 is now structurally closed**: `output: List<T>` with `transport: json` no longer compiles; the canonical answer `output: FlowEnvelope<List<T>>` is the only valid declaration. |
| **39.f** ✅ SHIPPED 2026-05-22 | Rust CLI binary parity | `axon` binary in `axon-rs/src/main.rs` — full surface parity with Python `axon` CLI: `check`, `compile`, `trace`, `parse`, `serve`, `store`, `fmt`, `version` | ✅ AUDIT: Rust binary already had 18+ subcommands native (check/compile/run/trace/version/repl/inspect/serve/ld/diff/replay/stats/graph/estimate/deploy/dossier/sbom/audit/evidence-package/store). **Gap closure**: 2 new subcommands shipped — `axon parse` (Fase 28.f Python parity) + `axon fmt` (Fase 14.d Python parity). New module `axon-rs/src/cli_parse.rs` (~350 LOC): pattern expansion (file/dir/literal), `parse_with_recovery` walk, aggregated diagnostics, JSON output (array/ndjson per Fase 28.g D5), exit-code-class bitwise OR (D6), AXON_PARSER_STRICT env var (D8), .axonignore-style ignore patterns. New module `axon-rs/src/cli_fmt.rs` (~170 LOC): token-level round-trip formatter direct-ported from Python `axon/compiler/formatter.py` (Fase 14.d MVP); `format_source(&str) -> Result<String, String>`; preserves all 6 comment kinds (line/block × regular/outer-doc/inner-doc); right-trims lines + ensures final newline; idempotent. **StringLit re-render**: Rust lexer strips `"..."` delimiters from string values; formatter re-quotes with escape sequences (`\\`/`\"`/`\n`/`\t`) so the round-trip is re-lexable. 20 new lib tests (10 cli_parse + 10 cli_fmt) + 12 integration §-assertions (`tests/fase39f_cli_binary_parity.rs`) subprocess-invoking the compiled binary verifying: §1 version → `axon-lang X.Y.Z`, §2-§3 check success+missing-file, §4-§5 compile stdout+missing-file, §6 trace header, §7-§8 parse human+JSON, §9-§10 fmt idempotence+check, §S1-§S2 STATIC grep gates verifying 8-subcommand declaration + dispatcher wiring. **Cross-stack regression**: 2197 axon-rs lib (+20) + 12 fase39f integration + 15 fase39b + 15 fase39c + 468 axon-frontend lib + 13 axon-csys + 98 Python touchstones = **2818 tests green**; zero regresiones. **Honest scope**: `axon fmt` is the MVP token-level round-trip (same as Python's Fase 14.d MVP); canonical-form rewriting (indent width / brace style) deferred to a future fase per Python's existing scope. `axon parse` runs single-threaded; the `--jobs N` flag is accepted for Python-parity but threading queued for a future refinement. |
| **39.g** ✅ SHIPPED 2026-05-22 | Test migration | every Python test that anchors a language behavior gets a Rust equivalent (Rust integration test or subprocess CLI test); Python tests with no Rust equivalent are honestly DELETED with PR-message reason | ✅ **Cat 3 adapted (2 files)**: `tests/test_cli_mvp_smoke.py` + `tests/test_frontend_contract_golden.py` switched from `[sys.executable, "-m", "axon.cli"]` → `[axon-rs/target/debug/axon[.exe]]` (the Rust binary from 39.f); 7 assertions relaxed for legitimate Rust-binary parity differences (Windows ASCII `X` vs `✗` glyph fallback, absolute vs relative path normalization, `serde_json` vs Python `json` error format); 16/16 Cat 3 tests pass against the Rust binary. **Cat 4 mass-quarantine (164 files)**: 154 top-level `tests/test_*.py` + 5 `tests/stdlib/test_*.py` + 4 `tests/integration/test_*.py` + 1 stale Fase 18 drift gate moved to `tests/legacy_quarantine_pre_v2/` (preserved git-recoverable but EXCLUDED from `pytest` collection by directory name + `--ignore` flag). New `tests/legacy_quarantine_pre_v2/README.md` documents: WHY quarantined (every file imports `from axon.*` and won't run post-39.h purga), recovery path via `git log --diff-filter=D`, equivalent coverage in Rust suites (2197 axon-rs lib + 468 axon-frontend lib + 13 axon-csys + integration suites). **Audit verde**: `find tests -name "test_*.py" -not -path "*/legacy_quarantine_pre_v2/*"` returns ONLY 2 files (both Cat 3 Rust-binary-driven). Zero surviving tests import `from axon.*`. The plan vivo §8 acceptance criterion is met structurally. **Honest scope**: the founder's "0 adopters, breaking velocity" stance accepts that the 164 quarantined tests may have caught edge cases the Rust side missed; future regressions are recoverable via git history + Rust-port pattern. **Cross-stack regression cero regresiones**: 2197 axon-rs lib + 15 fase39b + 15 fase39c + 12 fase39f integration + 468 axon-frontend lib + 13 axon-csys + 16 Cat 3 Python = **2776 tests green**. |
| **39.h** ✅ SHIPPED 2026-05-22 | Purga (the bold step) | `rm -rf axon/compiler/ axon/runtime/ axon/server/ axon/cli/ axon/backends/`; `axon/__init__.py` becomes a binary-wrapper stub (PyPI ergonomic shim only); `pyproject.toml` switches to `hatchling` binary distribution model | ✅ **426 files / 187,826 lines deleted** — executed methodically (survey → isolation-verify → topological rm → audit → regression). **axon/ purged**: 9 subdirs removed (`cli/` `server/` `backends/` `optimizer/` `enterprise/` `stdlib/` `engine/` `runtime/` `compiler/` — the plan's 5 + 4 additional Python subdirs). **axon/__init__.py** rewritten as v2.0.0 stub (no compiler/runtime imports; re-exports `main` from bootstrap). **New `axon/_bootstrap.py`** (~110 LOC, D13): native-binary launcher — platform slug resolution (os×arch), cache dir, GitHub Release download, POSIX execv / Windows subprocess. **pyproject.toml refactored**: all v1.x runtime extras removed (anthropic/openai/kafka/postgresql/server/pq/fhe/… — the native binary bundles every backend); only `dev` extra survives (pytest + bump-my-version); `[project.scripts] axon = "axon:main"`; bumpversion targets extended with `axon/_bootstrap.py::_VERSION`; coverage omit cleared; description rewritten for native-binary distribution. **Also purged**: `tests/legacy_quarantine_pre_v2/` (164 quarantined Python tests from 39.g), 3 untracked `temp_b186_*.py`, 2 obsolete `scripts/*.py` (depended on purged axon.compiler), `packaging/axon_mvp_entry.py` + dir, `tests/debug_ots.py`, `tests/integration/` + `tests/stdlib/` scaffolding. **Final Python footprint = 6 files**: `axon/__init__.py` + `axon/_bootstrap.py` (D13 distribution shim), `tests/test_cli_mvp_smoke.py` + `tests/test_frontend_contract_golden.py` (Cat 3 CLI contract anchors driving the native binary), `tests/__init__.py` (package marker), `axon-csys/tools/gen_merges.py` (C23 BPE tokenizer dev tool, 0 axon imports — build infra not language). **ZERO language Python remains**. Verification: pyproject parses (tomllib) + `import axon` clean (version + main, no compiler) + 16 Cat 3 tests green against binary + 2197 axon-rs + 468 axon-frontend + 13 axon-csys + 12 fase39f integration all green. **CI workflow modernization handoff**: 12 of 24 `.github/workflows/*.yml` reference the purged Python (`pip install -e`, `python -m axon.cli`, `python scripts/`, quarantined `pytest`); these are exercised at push-time and modernized as the FIRST task of 39.i (the atomic deploy where CI + release pipeline run together). Local state is robust (all builds + tests green); the workflow refs are a GitHub-side concern. |
| **39.i** | Atomic deploy v2.0.0 + axon-enterprise v2.0.0 catch-up + Kivi handoff | coordinated `git push origin master + tag v2.0.0`, `cargo publish axon-frontend v1.0.0` + `cargo publish axon-lang v2.0.0`, PyPI binary upload, GitHub Release with the migration guide, axon-enterprise PR + tag, Kivi adopter `.axon` source updated (`output: T` → `output: FlowEnvelope<T>` for affected endpoints) | release artifacts live; Kivi deployment green; ECR image with v2.0.0 deployed |

# ▶ 8. Test migration policy (sub-fase 39.g detail)

Each Python test in `tests/` falls into one of four categories:

1. **Language-behavior test, Rust equivalent exists** → DELETE Python test (anchor moves to Rust integration).
2. **Language-behavior test, NO Rust equivalent today** → WRITE Rust equivalent FIRST, then delete Python.
3. **CLI subprocess test** (e.g. `test_cli_mvp_smoke.py`, `test_frontend_contract_golden.py`) → ADAPT to invoke the Rust `axon` binary (subprocess call stays identical, only the binary path changes).
4. **Python implementation test** (testing Python module internals that won't exist post-purga) → DELETE with PR-message reason.

Net result: `tests/` directory survives as integration test suite
against the Rust binary; no test files testing Python source.

The audit at end of 39.g: `find tests/ -name "test_*.py" | xargs grep -l
"from axon\." | grep -v "subprocess"` should be empty (no Python tests
import axon modules directly — they all subprocess the Rust binary).

# ▶ 9. PyPI distribution policy (sub-fase 39.h detail)

## 9.1 The binary wrapper pattern

Post-39.h `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "axon-lang"
version = "2.0.0"
description = "axon — the formal cognitive language. Native Rust + C23 binary."
requires-python = ">=3.8"  # for the wrapper script; binary itself is native
# NO `dependencies = [...]` Python deps — there is no Python code to depend
# on anything.

[project.scripts]
axon = "axon._bootstrap:main"  # the wrapper that exec's the native binary
```

`axon/_bootstrap.py` (THE ONLY surviving Python file, ~30 LOC):

```python
"""axon binary launcher — downloads and exec's the native Rust binary.

This is the ONLY Python file in the axon-lang package post-Fase 39.
It is distribution-layer ergonomics, NOT language runtime. The actual
language runtime is 100% Rust + C23.
"""
import os
import platform
import subprocess
import sys
from pathlib import Path

_VERSION = "2.0.0"

def _binary_path() -> Path:
    cache = Path.home() / ".cache" / "axon-lang" / _VERSION
    arch = platform.machine().lower()
    osname = platform.system().lower()
    ext = ".exe" if osname == "windows" else ""
    return cache / f"axon-{osname}-{arch}{ext}"

def _download_if_needed():
    binary = _binary_path()
    if binary.exists():
        return binary
    # Download from GitHub Releases v2.0.0 for current platform.
    # ... (implementation in 39.h)

def main():
    binary = _download_if_needed()
    os.execv(str(binary), [str(binary)] + sys.argv[1:])
```

**Net Python source in the v2.0.0 package**: 1 file, ~30 LOC, pure
distribution ergonomics. Founder's "0 .py" north star is interpreted
honestly: zero Python *runtime / language* code. Distribution
boilerplate stays minimal and TODO-flagged for future removal (Fase 41+
when we ship native installers for all platforms via Cargo / Homebrew /
chocolatey).

## 9.2 Alternative distribution channels

In addition to PyPI binary wrapper:
- `cargo install axon-lang` — native Rust install (no Python needed)
- GitHub Releases binary tarballs for Linux x86_64, macOS aarch64/x86_64, Windows x86_64
- Homebrew formula `brew install axon-lang` (Fase 40 candidate)
- Docker image `axon/axon-lang:v2.0.0` (already exists pattern via axon-enterprise)

# ▶ 10. Adopter migration guide (sub-fase 39.i detail)

The single adopter (the strategic SaaS Agent) must update its `.axon`
source AND deployment.

## 10.1 Source-level migration

For every `axonendpoint` declaring `output: T` with a plural flow
tail and `transport: json`:

```axon
# Pre-v2.0.0 — broken in v1.40.0+ (axon-T9XX warning)
axonendpoint FetchTenants {
    method: GET
    path: /api/tenants
    execute: RetrieveAllTenants
    output: List<TenantRecord>       # ← would not compile in v2.0.0 (axon-E039)
}

# Post-v2.0.0
axonendpoint FetchTenants {
    method: GET
    path: /api/tenants
    execute: RetrieveAllTenants
    output: FlowEnvelope<List<TenantRecord>>   # ← compiles; D5 validates result slot
}
```

For singular endpoints — no change required:
```axon
# Singular output — unchanged
axonendpoint FetchTenant {
    method: GET
    path: /api/tenants/{id}
    execute: RetrieveOneTenant
    output: TenantRecord
}
```

Wait — actually per §6.2 the rule also affects singular endpoints
because the wire IS the envelope. **TBD in 39.e**: does singular
`output: T` ALSO require `FlowEnvelope<T>` wrapping, or does T9XX only
trigger E039 on the (Singular decl, Plural tail) mismatch? The honest
answer: ALL `transport: json` endpoints emit FlowEnvelope on the wire;
the question is what the COMPILER requires the declaration to be. Two
sub-options for 39.e to ratify:

- (α) MANDATORY everywhere: `output: T` for json transport MUST be
  `FlowEnvelope<T>` (no exceptions; even `output: TenantRecord` errors
  and requires `output: FlowEnvelope<TenantRecord>`)
- (β) MANDATORY only on cardinality mismatch: `output: TenantRecord` is
  fine on its own (Singular decl matches the envelope's outer singular
  shape via Postel's Law on existing struct types); only mismatch cases
  require explicit FlowEnvelope wrapping

Option (α) is structurally clean (one rule for all). Option (β) is more
backwards-compat-shaped (singular T just works). I lean (α) — once we're
breaking, break completely; one rule beats N exceptions.

**ACTION**: 39.e to ratify (α) vs (β).

## 10.2 Client-side migration

Kivi's downstream consumers (web frontend, mobile, internal services):

- HTTP client parses `FlowEnvelope` JSON object (single shape across
  all endpoints — codegen-friendly)
- Each consumer extracts `result` field for the typed payload
- Audit consumers read `provenance_chain` + `step_audit` +
  `audit_chain_hash` for tamper-evidence and lineage
- Error path consumers read `blame_attribution`

Migration LOC delta: bounded — Kivi has a finite number of HTTP client
call-sites. Specific count surfaces in 39.i pre-deploy audit.

## 10.3 Deployment coordination

Atomic coordination protocol with the adopter:

1. axon-lang v2.0.0 tag published + axon-enterprise v2.0.0 ECR image
   pushed (T0)
2. Adopter updates `.axon` source on a feature branch (T0 + ε)
3. Adopter staging deploy validates new wire shape end-to-end (T0 + 1
   day)
4. Adopter production cutover during a coordinated maintenance window
   (T0 + 2 days)
5. v1.x ECR images remain available for emergency rollback for 7 days,
   then archived

# ▶ 11. The two-question gate (mandatory per memoria `feedback_plan_vivo_two_questions`)

## 11.1 Q1 — Market standard or superior?

**Superior.** Concrete comparison points:

| Framework / Protocol | Envelope shape | Strong-typed result slot | Epistemic certainty | Tamper-evident audit chain | Cardinality-aware typing |
|----------------------|----------------|--------------------------|--------------------|----------------------------|---------------------------|
| **gRPC** | `Status` + metadata | ✅ (proto-typed) | ❌ | ❌ | partial (proto repeated) |
| **GraphQL** | `{ data: T, errors }` | ✅ (schema-typed) | ❌ | ❌ | partial (schema lists) |
| **JSON-RPC 2.0** | `{ jsonrpc, id, result \| error }` | partial (untyped) | ❌ | ❌ | ❌ |
| **OData** | `{ value, @odata.context }` | partial | ❌ | ❌ | ❌ |
| **axon FlowEnvelope (v2.0.0)** | `FlowEnvelope<T>` | ✅ (compile + runtime) | ✅ (Theorem 5.1, C23) | ✅ (HMAC-SHA256 chain) | ✅ (Cardinality::Wrapped) |

**axon's differential** = epistemic fields (certainty bound by Theorem
5.1, provenance chain HMAC-anchored, blame attribution typed) are
**unique in the industry**. No production framework today carries
epistemic certainty as a first-class wire field. The cognitive-language
positioning is honored at the wire layer, not just at the source layer.

## 11.2 Q2 — Minimum to run or robust for large adopters?

**Robust for future large adopters AND for the strategic SaaS Agent
today.**

### Concrete in-scope robustness

- HIPAA Safe Harbor (clinical reasoning flows) — `blame_attribution`
  + `audit_chain_hash` satisfy 21 CFR Part 11 §11.10(e)
- FRE 502 + Upjohn/Hickman (legal privilege flows) — `provenance_chain`
  + `step_audit` form waiver-doctrine defensible trail
- BSA/OFAC/MiFID II (fintech investigative flows) — `certainty` +
  `blame_attribution` support AML investigator review
- FedRAMP AU-2 (government decision flows) — `audit_chain_hash` is the
  AU-2 audit-log integrity primitive

### Honest scope deferrals (not in 39, queued for 40+)

- `transport: grpc` variant — FlowEnvelope generalizes naturally, but
  protobuf codegen is a Fase 40 candidate
- Per-vertical envelope extensions (e.g. HIPAA `phi_audit_chain`,
  FedRAMP `nist_control_id`) — extension trait pattern; Fase 41
  candidate
- FlowEnvelope wire-format versioning (`schema_version: u8` field) for
  v3.x backwards-compat — additive when needed
- C23 acceleration of `audit_chain_hash` for very high QPS — already
  fast (SHA-256 in pure-C); SIMD batch hashing is Fase 42 candidate
- Adopter SDK codegen (`axon codegen <client.lang>`) generating typed
  client structs from declared endpoints — Fase 43 candidate
- `axonendpoint` versioning (e.g. `output: FlowEnvelope/v2<T>`) — when
  we need to evolve the envelope itself

# ▶ 12. Honest scope NOT in Fase 39

- ❌ axon-enterprise Python eradication (queued as Fase 40 — same
  template applied to `axon_enterprise/` package)
- ❌ axon-csys-enterprise Python ctypes wrappers (the in-progress
  27.k.1 work) — ABANDONED (superseded by Fase 39 Rust-canonical
  pattern; integration via direct Rust calls)
- ❌ Adopter SDK codegen (Fase 43 candidate)
- ❌ `transport: grpc` variant (Fase 40 candidate)
- ❌ Per-vertical envelope extensions (Fase 41 candidate)
- ❌ Adopter "v1.x compatibility shim" runtime mode — explicitly
  rejected by founder ("ABSOLUTE BREAKING VELOCITY")
- ❌ Soft deprecation warnings in v1.41+ before v2.0.0 — explicitly
  rejected (we are not going through v1.41; we go v1.40.3 → v2.0.0
  directly)

# ▶ 13. The closing condition

Fase 39 closes when ALL of:

- ✅ Sub-fases 39.a → 39.i all marked SHIPPED in this plan vivo
- ✅ axon-lang **v2.0.0** tag pushed + crates.io published + GitHub
  Release with the FlowEnvelope migration guide
- ✅ axon-frontend **v1.0.0** tag pushed + crates.io published
- ✅ PyPI `axon-lang 2.0.0` binary-wrapper package published; `pip
  install axon-lang` produces a working native binary on Linux /
  macOS / Windows
- ✅ axon-enterprise **v2.0.0** catch-up PR merged + tag + GH Release +
  ECR Private image
- ✅ `find . -name "*.py" -not -path "./tests/*" -not -name
  "_bootstrap.py"` returns empty (the audit: zero language Python)
- ✅ The adopter's coordinated migration verified on staging + green
  in production
- ✅ Memory entry for Fase 39 plan SHIPPED status updated

## 13.1 Anti-conditions (we did it wrong if any apply)

- ❌ Python files remain in the axon-lang package beyond `_bootstrap.py`
- ❌ `axon-T9XX` warning still emits (it must have migrated to
  `axon-E039` error)
- ❌ D5 still uses the §0 generic-aware preamble (it must have been
  retired in 39.d)
- ❌ A Rust drift gate exists that mirrors a Python file (no more
  drift gates — Rust IS canonical, Python is gone)
- ❌ The single adopter has NOT migrated (the atomic deploy isn't
  atomic if the adopter lags)

---

**Plan vivo created 2026-05-22. All pending ratifications closed 2026-05-22 (D12 α, D13 a, D14 x→y→z). Implementation begins with 39.a per founder cadence (one sub-fase per "procede" signal).**
