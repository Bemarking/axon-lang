# [INFRA-DEBT] Remediación Sistémica de Arity Drift y Test-Rot en `cargo test`

> **Status:** OPEN — opened 2026-06-03 (founder-directed, alongside the §Fase 55 cut).
> **Scope:** `axon-rs` integration test suite (`axon-rs/tests/`).
> **Priority:** dedicated cleanup sprint, scheduled immediately **after** the §54/§55
> coordinated release. Independent of the §54/§55 work.

## Summary

A full `cargo test` on `axon-rs` does **not** run clean: a set of integration-test
targets accumulated **pre-existing rot** — they were never updated when upstream
function signatures grew parameters (the §Fase 37.y request-binding additions), when
the v2.0.0 `FlowEnvelope<T>` wire-contract rule landed (§Fase 39 D2/D12, `axon-E039`),
or when struct fields / version strings / Python IR goldens moved. Because each broken
target aborts the build, the rot stayed invisible — **CI runs a curated green subset,
not the full `cargo test`**. This was surfaced during the §Fase 55 epistemic-wire work
(the new parity gate needed a clean lane to isolate real regressions).

## What was done at the §55 cut (gating, NOT remediation)

To keep a default `cargo test` **strictly green** for the type core + the
parity-envelope serialization + the §55 epistemic-wire validation — without letting
this external debt block the differential's release — the rot was **quarantined**
(founder-approved gating, 2026-06-03):

- **`tests/integration.rs`** (the CORE pipeline target) — the 2 `execute_server_flow`
  arity-drift call sites were **fixed** (it is core; it stays compiled + running, 851
  tests green). The **11** individual stale `#[test]` functions were marked
  `#[ignore = "INFRA-DEBT …"]` (not deleted) so the core lane is green while the stale
  cases stay visible.
- **5 fully-broken targets** were gated at the crate root with
  `#![cfg(feature = "quarantined-rot")]` (compiled out of a default `cargo test`):
  `fase32_body_schema`, `fase35_l_postgres_integration`, `fase36x_f_terminator_fuzz`,
  `fase37x_a_pooler_coherent_diagnostic`, `fase37x_i_pgbouncer_integration`.
  The `quarantined-rot` Cargo feature is defined in `axon-rs/Cargo.toml [features]`.

To **see** all quarantined work during the sprint:
```
cargo test --features quarantined-rot          # the 5 gated targets
cargo test --test integration -- --ignored     # the 11 ignored core cases
```

## Remediation checklist (the sprint)

### A. Arity drift (§Fase 37.y `request_path` / `request_query`)
- [ ] Audit every test call of `runner::execute_server_flow` (now 8 args) and
      `streaming_via_dispatcher::run_streaming_via_dispatcher` (now 13 args) — already
      repaired: `fase33z_d_parity_corpus`, `fase33z_production_fuzz`, `integration`
      (2 sites). Sweep the quarantined targets for the same pattern.

### B. `axon-E039` — bare `output:` on JSON endpoints (§Fase 39 v2.0.0 contract)
- [ ] Update test sources declaring `output: <BareType>` on a `transport: json`
      endpoint to `output: FlowEnvelope<BareType>` (or `transport: sse(axon)`).
      Affects the `integration.rs` `fase4_*` / `fase6_1_*` ignored cases.

### C. Stale fixtures / goldens / version strings
- [ ] `*_schema_header` tests assert `axon_version starts_with("1.")` — now `2.x`.
- [ ] `parity_fase1_5_*` Python IR goldens drifted — regenerate or re-pin.
- [ ] `StoreColumn` / `BodyValidationError` initializers missing fields
      (`identity`, `expected_cardinality`, …) — already fixed `fase38_i_property_fuzz`;
      repair `fase32_body_schema`.

### D. Real-infra integration targets (postgres / pgbouncer / pooler)
- [ ] These need a live Postgres + pooler; decide whether they belong in the default
      `cargo test` at all, or a dedicated infra CI lane. Repair the arity/field drift
      regardless.

### E. Exit criteria
- [ ] Remove every `#![cfg(feature = "quarantined-rot")]` gate + the `#[ignore]`
      markers + the `quarantined-rot` feature.
- [ ] A bare `cargo test` on `axon-rs` is strictly green (0 ignored for rot reasons).
- [ ] Wire the full `cargo test` into CI so this cannot silently re-accumulate.
