# axon-enterprise v1.31.1 — catch-up to axon-lang 1.40.1 (cross-runtime PoolConnection hotfix, Fase 37.x.j.10)

**Patch catch-up.** Lifts the enterprise stack to axon-lang 1.40.1, inheriting the critical cross-runtime PoolConnection hotfix.

## What enterprise tenants get

Closes the production-affecting regression introduced by v1.30.0 / v1.31.0 (Fase 37.x.j Connection-Pinned Flow Execution): **sync runner pinned-conn dispatch was hanging on `.await`** because the `PoolConnection<Postgres>` was acquired on a different temporary tokio runtime than the one running the SQL dispatch.

## Production symptom (pre-v1.31.1)

Every `transport: json` flow with ≥1 store op (i.e. ~ALL CRUD REST endpoints in production) logged the `tracing::info!(target: "axon::store::pin", path = "acquire", source = "eager")` event and then **never** emitted the SQL. Transaction hung waiting for an I/O notification from a reactor on a dead runtime.

Scope of impact: every CRUD REST endpoint with ≥1 store op under any Postgres-backed adopter. **Async dispatcher path (`transport: sse`) was NOT affected** — its eager-acquire + dispatch already shared the same runtime.

## Vertical impact

All regulated-vertical enterprise tenants serving CRUD REST APIs against Postgres were affected by the hanging sync runner in v1.31.0:

- **HIPAA Safe Harbor + 21 CFR Part 11** clinical records CRUD endpoints
- **FRE 502 + Upjohn / Hickman** legal document store CRUD endpoints
- **BSA / OFAC / MiFID II AML** transaction-store CRUD endpoints
- **FedRAMP AU-2** government record store CRUD endpoints

v1.31.1 closes the hazard structurally via the single-outer-`block_on_store`-per-flow pattern. Re-deploy the Docker image; no source-code changes required for `.axon` flows.

## Fix architecture (inherited)

Three landing pieces in `axon-rs/src/runner.rs`:

1. **`execute_sql_store_step_async`** — new async fn; sync wrapper retained for tests.
2. **`execute_real_async`** — new async fn; sync wrapper retained for CLI path.
3. **`execute_server_flow`** restructured: SINGLE outer `block_on_store(async { eager_acquire; execute_real_async(...).await })` so pin acquisition + every SQL dispatch + implicit pin drop ALL execute on the SAME temporary tokio runtime. Reactor handles stay valid throughout.

## Catch-up surface

- `pyproject.toml`: version 1.31.0 → 1.31.1, dep pin `axon-lang>=1.40.0` → `>=1.40.1`.
- `axon_enterprise/__init__.py`: `__version__` 1.31.0 → 1.31.1.

axon-frontend Rust crate dep stays at **0.21.0** (frontend untouched; only `axon-rs/src/runner.rs` and one anchor test changed in axon-lang 1.40.1).

## Migration

**No source-code changes required.** v1.31.0 → v1.31.1 is a runtime-only Docker image update. Adopters whose deploys observed `pin acquired (eager)` log → no SQL emission → client timeout — update to v1.31.1 and the issue resolves immediately on next deploy.

Per standing rule (every axon-lang release ships an axon-enterprise catch-up): v1.31.1 closes the cycle in lockstep with axon-lang v1.40.1.

## Plan vivo

Fase 37.x.j REOPENED 2026-05-21 for sub-fase 37.x.j.10 (cross-runtime hotfix) — see [docs/fase/fase_37xj_connection_pinned_flow_execution.md §37.x.j.10](docs/fase/fase_37xj_connection_pinned_flow_execution.md) for full diagnostic + fix narrative.
