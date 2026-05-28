# axon-lang v1.40.1 — Cross-runtime PoolConnection hotfix (Fase 37.x.j.10)

**Patch.** Closes a critical cross-runtime hazard introduced by the v1.39.0 (Fase 37.x.j) Connection-Pinned Flow Execution cycle and inherited by v1.40.0. Sync runner pinned-conn dispatch was hanging indefinitely on `.await` because the `PoolConnection<Postgres>` was acquired on a different temporary tokio runtime than the one running the SQL dispatch.

## Symptom (production-facing)

Sync runner endpoints (any `transport: json` flow with ≥1 store op) would log the `tracing::info!(target: "axon::store::pin", path = "acquire", source = "eager")` event and then **never** emit the SQL. The transaction stayed hanging waiting for an I/O notification from a reactor on a runtime that had already dropped.

Scope of impact: every `transport: json` flow with `≥1` postgresql store op in production. Roughly **all CRUD REST endpoints** under any adopter using a Postgres-backed `axonstore`. Async dispatcher path (`run_streaming_via_dispatcher` — used for `transport: sse`) **was NOT affected** — its eager-acquire and dispatch already shared the same runtime.

## Root cause

`PoolConnection<Postgres>` carries internal reactor handles bound to the runtime that acquired it. Pre-hotfix:

1. `execute_server_flow`'s eager-acquire loop: `block_on_store(async move { backend.acquire_pin().await })` — pin acquired on temp-runtime-A.
2. `block_on_store` returns → temp-runtime-A drops.
3. Pin moved to outer-scope `HashMap<String, PoolConnection<Postgres>>` (still holds handles → dead runtime).
4. Each `execute_sql_store_step` call had its OWN `block_on_store` → temp-runtime-B (and -C, -D, ...).
5. SQL dispatch on temp-runtime-B awaits on the pin → reactor handles point to dead runtime-A → `await` hangs forever.

## Fix — B' refinada (single outer `block_on_store` per flow execution)

Three landing pieces in [axon-rs/src/runner.rs](axon-rs/src/runner.rs):

1. **New `async fn execute_sql_store_step_async`** — the body of the old sync fn with the internal `block_on_store(async move { ... })` wrapper unwound. Sync `execute_sql_store_step` retained as thin wrapper for the 4 existing test callsites + non-server callers.

2. **New `async fn execute_real_async`** — same body as old sync `execute_real`; only change is the SQL site calls `execute_sql_store_step_async(...).await` instead of the sync wrapper. Sync `execute_real` becomes thin wrapper for the CLI path.

3. **`execute_server_flow` restructured.** The IR-walk computing `needed_pg_stores` stays sync (no .await needed). The `if backend == "stub"` branch unchanged. The `else` branch (real backend) is now SINGLE `block_on_store(async { ... eager_acquire ... ; execute_real_async(...).await })` — pin acquisition + flow dispatch + implicit pin drop ALL execute on the SAME temporary tokio runtime. Reactor handles stay valid throughout.

The `async` block (NOT `async move`) borrows `report`/`registry`/`store_registry`/`execution_units`/`needed_pg_stores`/`flow_name` by reference. `std::thread::scope` inside `block_on_store` allows non-'static borrows. Variable renamed `backend` → `backend_pool` inside the acquire loop to avoid shadowing of the outer `backend: &str` parameter.

## Why our test suite didn't catch this

2108 axon-lang lib + 12 anchor §-assertions + 5 cardinality tests don't exercise REAL Postgres dispatch on the sync runner pinned path. The `runner::fase35e_tests` error before reaching dispatch (`PoolInit` without a real DB). The 37.x.j.8 anchor §1/§2/§5/§6/§7 were honest-deferred to a CI compose-service lane that was NOT built — exactly the lane that would have caught this. Future fase will add the compose service.

## Migration

**No source-code changes for adopters.** v1.40.0 → v1.40.1 is a runtime-only patch. Re-deploy with the new binary. Sync runner endpoints that were hanging will now complete normally.

Adopters whose deploys block `axon serve` and have observed `/api/whatever` → "pin acquired (eager)" log → no progress → 30-second client timeout — update to v1.40.1 and the issue resolves immediately.

## Test surface

- **2108/2108** axon-lang lib green.
- **447/447** axon-frontend lib green (unchanged from v1.40.0).
- **12/12** Fase 37.x.j anchor green (one §S grep loosened from `backend.acquire_pin().await` to `.acquire_pin().await` to be receiver-variable-name agnostic).
- **12/12** Fase 38.x.f anchor green (unchanged).
- **5/5** Fase 38.x.e cardinality tests green (unchanged).
- Zero regressions cross-stack.

## Plan vivo

37.x.j.10 sub-fase appended to [docs/fase/fase_37xj_connection_pinned_flow_execution.md](docs/fase/fase_37xj_connection_pinned_flow_execution.md) — full diagnostic + fix narrative for traceability.

## Trigger

Diagnosed 2026-05-21 from adopter operational report. Cross-runtime `PoolConnection` hazard is a known sqlx pitfall the v1.39.0 cycle introduced inadvertently because the original Fase 37.x.j architecture didn't enforce single-runtime invariant. v1.40.1 makes the single-runtime invariant structural at the API level.

axon-frontend stays at 0.21.0 (frontend untouched; only `axon-rs/src/runner.rs` and the test anchor changed).
