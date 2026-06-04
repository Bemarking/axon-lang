# [INFRA-DEBT] Remediación Sistémica de Arity Drift y Test-Rot en `cargo test`

> **Status:** ✅ **RESOLVED 2026-06-03** (sprint executed right after the §54/§55
> release). A default `cargo test` on `axon-rs` is now **strictly green** — the rot
> was REPAIRED (not gated): every quarantined target was fixed against the current
> v2.7.0 contract, the `quarantined-rot` Cargo feature + every `#![cfg(...)]` gate
> were removed, and the 4 Postgres/pooler integration targets were restored to the
> default suite (they skip-pass hermetically via `pg_or_skip!` and run for real in
> the DB CI lane). **Zero residual** — the 2 obsolete cross-stack Rust↔Python IR
> parity tests were RETIRED (Python is purged; there is no second stack) and REPLACED
> by a Rust-native IR regression snapshot (see below), so IR-shape regression coverage
> is preserved without the dead premise.
> **Scope:** `axon-rs` integration test suite (`axon-rs/tests/`).

## Resolution (2026-06-03)

- **18 non-DB targets repaired** (FlowEnvelope-shape JSON paths, axon-E039
  `output: FlowEnvelope<T>` wraps, §37.y arity, stale `[stub-stream]` tokens, stale
  version strings, `BodyValidationError` new fields). No assertion weakened — stale
  expectations were re-pointed to the current correct contract.
- **12 `#[ignore]` tests un-ignored + fixed** (integration.rs ×11 + fase30 ×1);
  **2** kept `#[ignore]` (the Python-IR goldens — needs golden regen, tracked below).
- **4 DB targets restored** (fase35_l / fase37x_a / fase37x_i / fase38x_a): the real
  compile rot was §Fase 37.x.j adding a leading `conn: &mut StoreConn` to the
  `PostgresStoreBackend` methods; the test call sites were threaded with a `StoreConn`.
  They skip-pass without a DB and run for real when `AXON_TEST_DATABASE_URL` is set.
- A couple of error-path streaming tests were re-grounded on a dead-port `postgresql`
  store (the closed axonstore catalog removed `sqlite`) — deterministic, no live DB.
- `cargo test --no-fail-fast` → **strictly green** (~4.5k passed, 0 failed, only the 2
  Python goldens ignored). No `src/` or `Cargo.toml`-version changes; test files only.

### Residual — RESOLVED (2026-06-03, founder-QA'd)
The QA established: the §Fase 8.2.h tests were a Rust↔**Python** IR cross-stack parity
gate, but the Python axon implementation is **purged** (the package is a thin native
launcher) — there is no second stack to be parity with, and `python.ir.json` was a
frozen May-20 fossil of the pre-v2.0.0 contract. Decision (founder): retire the dead
tests, but DON'T lose IR-shape regression coverage. Done:
- DELETED the 3 obsolete tests (`parity_fase1_5_{emit,byte_identical,structural}`) +
  `python.ir.json` + `rust.ir.json`.
- ADDED `integration.rs::fase1_5_rust_ir_regression_snapshot` — a Rust-native byte
  snapshot of the comprehensive fase1–5+compliance fixture's IR against a committed
  `tests/parity/fase1_through_5_plus_compliance.ir.golden.json` (strictly stronger than
  the old structural gate). One-command regen on intentional IR change:
  `AXON_REGEN_IR_GOLDEN=1 cargo test --test integration fase1_5_rust_ir_regression_snapshot`.
- `cargo test --test integration` → 860 passed, **0 ignored**. Ticket fully closed.

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
