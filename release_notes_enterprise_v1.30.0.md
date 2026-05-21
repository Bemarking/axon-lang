# axon-enterprise v1.30.0 — catch-up to axon-lang 1.39.0 (Connection-Pinned Flow Execution + Retrieve Cardinality Gate, Fase 37.x.j + 38.x.e)

**Minor catch-up.** Lifts the enterprise stack to axon-lang 1.39.0 + axon-frontend 0.20.0, inheriting transitively two structural fixes that close the kivi adopter regression report of 2026-05-20.

## What enterprise tenants get

### Fase 37.x.j — Connection-Pinned Flow Execution

Closes the `unnamed prepared statement does not exist` race against transaction-mode poolers (Supabase Supavisor `:6543`, PgBouncer `pool_mode=transaction`, Neon, RDS Proxy). The fix: PIN one `PoolConnection<Postgres>` per axonstore for the whole flow execution. All store ops in the flow share that exact physical backend conn — no swap window exists.

**Layered defense composition** (each layer ships as an enterprise catch-up):
- **v1.29.0** (axon-lang 1.37.0 D1) — per-query `.persistent(false)`
- **v1.29.1** (axon-lang 1.38.1 D2) — per-conn-release `DEALLOCATE ALL`
- **v1.30.0** (axon-lang 1.39.0 D3) — per-flow physical-conn pinning

A flow can now run 100 sequential retrieves under Supavisor transaction-mode and observe zero unnamed-statement errors.

### Fase 38.x.e — Retrieve Cardinality vs Output Singularity Gate

New compile-time error `axon-T9XX retrieve_cardinality_mismatch`: when a flow's tail is a `retrieve` step (always plural) but the endpoint declares `output: T` (singular), `axon check` rejects the build with an actionable hint instead of letting the runtime fail with an opaque D5 `internal_validation_error`.

## Vertical inheritance

- **HIPAA Safe Harbor + 21 CFR Part 11 §11.10(e)** — clinical multi-retrieve chains under Supavisor: `retrieve consent + retrieve history + retrieve medication` now share one physical backend per flow. T9XX catches `GET /api/patients/{id}` endpoints whose flow returns `List<PatientRecord>` from a retrieve at `axon check`, not at production runtime.
- **FRE 502 + Upjohn / Hickman + ABA Rule 1.6** — privilege-review chains `for doc in corpus { retrieve privilege_log }` against Neon pooler: each iteration's retrieves run on one physical conn (no prepared-statement collision); per-branch sub-pin isolation (D6.a). T9XX catches singular-output privilege endpoints whose flow ends with a list retrieve.
- **BSA / OFAC / MiFID II AML** — investigative flows under Aurora Cluster: multi-store AML scans share pin per store; pin map drops at flow end → `DEALLOCATE ALL` wipes all prepared statements before the conn returns to the pool. T9XX catches `GET /api/cases/{id}` endpoints with list-returning flow tail.
- **FedRAMP AU-2** — government decision flows on RDS Proxy: same pin semantics; the per-pin `tracing::info!` events (D4 observability surface) feed FedRAMP AU-2 audit-trail requirements directly.

## D-letters (inherited from axon-lang 1.39.0)

- **D1** — sync runner `ExecContext.pinned_conns` eager acquire + threading via `execute_real` + `execute_sql_store_step`. Critical prerequisite: `connect_named` → `registry.resolve()` switch.
- **D2** — async dispatcher `DispatchCtx.pinned_conns` parity via `Arc<Mutex<HashMap>>`; 4 wire_integrations sites with take/dispatch/return discipline. **Closes the `/api/chat` regression class.**
- **D3** — Backwards-compat absolute via `StoreConn::Pool` legacy fallback.
- **D4** — Observability via `pin_observability::emit_pin_acquire` (`tracing::info!(target: "axon::store::pin", ...)`).
- **D6.a** — Per-branch sub-pin isolation: `parallel.rs::ctx.clone()` replaces `pinned_conns` Arc with fresh empty; lazy on-miss acquire per branch.
- **38.x.e D1** — Compile-time `axon-T9XX retrieve_cardinality_mismatch` gate.

## Catch-up surface

- `pyproject.toml`: version 1.29.4 → 1.30.0, dep pin `axon-lang>=1.38.5` → `>=1.39.0`.
- `axon_enterprise/__init__.py`: `__version__` 1.29.4 → 1.30.0.

axon-frontend Rust crate dep bumps transitively from 0.19.3 → 0.20.0 (new TypeChecker T9XX gate + extended dispatch surface).

v1.30.0 is a lean catch-up — same shape as v1.29.0 / v1.29.1 / v1.29.2 / v1.29.3 / v1.29.4. Per the standing rule (every axon-lang release ships an axon-enterprise catch-up), this closes the v1.39.0 cycle in lockstep.

## Migration

**No breaking changes.** Adopters under transaction-mode poolers automatically benefit on the next `axon serve` start. Set `RUST_LOG=axon::store::pin=info` for pin observability tracing.

## Trigger

kivi adopter regression report 2026-05-20:
- `/api/chat` 3rd retrieve failing with `unnamed prepared statement does not exist` (race pre-existing but exposed by v1.38.5 task scheduling timing).
- 9 newly un-skipped GETs failing D5 `internal_validation_error` (cardinality mismatch class).

v1.30.0 inherits both fixes structurally.
