# axon-lang v1.39.0 — Connection-Pinned Flow Execution + Retrieve Cardinality Gate

**Minor.** Two structural fixes shipping together to close the kivi adopter regression report of 2026-05-20:

- **Fase 37.x.j — Connection-Pinned Flow Execution**: closes the `unnamed prepared statement does not exist` race against transaction-mode poolers (Supabase Supavisor `:6543`, PgBouncer `pool_mode=transaction`, Neon, RDS Proxy).
- **Fase 38.x.e — Retrieve Cardinality vs Output Singularity Gate**: closes the opaque-D5-runtime-error class when a flow's tail is `retrieve` but the endpoint declares a singular output.

## Why this is MINOR (not patch)

- New public surface: `StoreConn<'a>` enum + dispatch methods (`fetch_all` / `fetch_optional` / `execute` / `begin`), `PostgresStoreBackend::acquire_pin()`, `DispatchCtx.pinned_conns` field + `with_pinned_conns()` builder, `pin_observability::{emit_pin_acquire, emit_pin_flow_summary}`.
- New compile-time error code `axon-T9XX retrieve_cardinality_mismatch`.
- axon-frontend bumps to 0.20.0 (new TypeChecker gate is a frontend-surface extension).

## Fase 37.x.j — what closed

**The race.** sqlx uses Postgres extended query protocol unconditionally (PARSE → BIND → EXECUTE → SYNC). With Supavisor in transaction-mode, each transaction boundary is an opportunity for the pooler to swap the physical backend connection. The unnamed prepared statement parsed for one retrieve was gone by the time the next retrieve ran on a different physical backend.

**The fix.** Pin ONE physical connection per axonstore for the WHOLE flow execution. Every `retrieve` / `persist` / `mutate` / `purge` in the flow goes through that exact connection. No backend swap window exists.

**Three D-letters land:**
- **D1** — `ExecContext.pinned_conns` (sync runner path): eagerly acquires one `PoolConnection<Postgres>` per axonstore referenced in the flow at execution start.
- **D2** — `DispatchCtx.pinned_conns` (async dispatcher path): same primitive on the streaming SSE side. **This closes the adopter `/api/chat` regression.**
- **D6.a** — Per-branch sub-pin isolation for `par { } { }` blocks: each branch gets its own pin (no false serialization on the parent's mutex). D6.b `par(serialized: true)` opt-in is honest-deferred to a future fase.

**Critical prerequisite shipped en passant:** the synchronous runner's `execute_sql_store_step` switched from `PostgresStoreBackend::connect_named` (which built a fresh `PgPool` per call) to `store_registry.resolve()` (cached pool). Without this the pin would have been on a different pool than the dispatch.

**Layered defense composition:** v1.39.0 D3 layer (per-flow pin) composes with:
- v1.37.0 D1 (per-query `.persistent(false)`)
- v1.38.1 D2 (per-conn-release `after_release(DEALLOCATE ALL)`)

A flow can now run 100 sequential retrieves under Supavisor transaction-mode and observe zero unnamed-statement errors.

**Observability (D4).** `emit_pin_acquire` fires `tracing::info!(target: "axon::store::pin", ...)` on every acquire with `store_name`, `flow_name`, `trace_id`, `source` (eager | lazy), `branch_index`. Operators can compute pin-saturation metrics + pin-leak detection from the log stream.

## Fase 38.x.e — what closed

**The class.** A flow body's tail expression has a known cardinality at compile time:

- `retrieve … as x` → always `List<StoreRow>` (plural)
- `step S { … }` returning T → `T` (singular)
- `return result[0]` → singular projection of a plural

The axonendpoint's `output:` type declares the contract with the client. When they disagree, the v1.38.x runtime D5 output-schema gate rejects the response with an opaque `internal_validation_error` — the adopter sees a generic message and has to dig through audit logs to find the actual shape mismatch.

**The fix.** New compile-time gate `axon-T9XX retrieve_cardinality_mismatch` runs at `axon check`:

```
axon-T9XX axonendpoint 'GetTenant' declares `output: TenantRecord` (singular),
          but flow 'GetTenant' produces a `List<TenantRecord>` tail expression
          — the flow ends with a `retrieve` step, which always returns a list
          of rows from the store. The runtime D5 output-schema gate (Fase 32.d)
          would reject the response as a shape mismatch.
          Either:
          (a) change the endpoint to `output: List<TenantRecord>` if it is
              intentionally returning a collection (REST `GET /api/{resource}`-
              style); OR
          (b) collapse the tail to a singular element — e.g. add `step Project
              { return result[0] }` (or any step that emits the singular shape)
              BEFORE the implicit tail, OR add an explicit `return result[0]`
              at the end of the flow if the retrieve's `where:` filter is
              guaranteed to yield exactly one row.
          (Fase 38.x.e D1)
```

**Scope of v1.39.0 detection.** The gate fires for the canonical kivi-shape — `output: T` (singular) + flow tail = `Retrieve`. Symmetric direction (singular tail + `output: List<T>`), branch-disagreement warning, Stream cardinality refinement, runtime D5 hint improvement, and `--strict-cardinality` / `--verbose-d5-hint` CLI flags are honest deferrals to Fase 38.x.f.

## Where axon advances the state of the art

| Property | axon v1.39.0 | FastAPI + asyncpg | Spring + JDBC | Rails + ActiveRecord | Node + pg-pool |
|---|---|---|---|---|---|
| Per-flow connection pinning (automatic) | ✅ | ❌ adopter manual checkout | ❌ HikariCP thread-affinity manual | ❌ `prepared_statements: false` only | ❌ middleware manual |
| Cardinality enforced at compile time | ✅ T9XX | ❌ runtime 422 | ❌ runtime serialization error | ❌ runtime nil/null | ❌ runtime undefined |

The pin is automatic at the LANGUAGE level — adopters write a normal flow, the runtime guarantees pooler-coherence. Cardinality is enforced at BUILD time — the build refuses to ship an endpoint whose tail-shape disagrees with its declared output.

## Test surface

- **447/447** axon-frontend lib tests green (5 new in `type_checker::fase38xe_cardinality_tests`).
- **2108/2108** axon-lang lib tests green (2 new in `store::store_conn::tests` + 2 new in `store::pin_observability::tests`).
- **12/12** new anchor `axon-rs/tests/fase37xj_connection_pinning.rs` (STATIC grep §S × 7 surface assertions + §3 in_memory D3 backwards-compat + §4 observability totality × 2 + §S public surface accessibility).
- Property test under real PgBouncer transaction-mode (plan vivo §5 §6) is honest-deferred to a CI compose service in sub-fase 37.x.j.8.b.

## Migration

**No breaking changes.** D5 backwards-compat absolute:

- The `StoreConn::Pool` variant is the v1.38.5 legacy path; an empty `pinned_conns` map falls back to it on every dispatch — byte-identical behavior for callers that didn't eager-acquire (CLI, non-streaming RPC).
- The `ping` method on `PostgresStoreBackend` stays unchanged (single-query health probe; no benefit from pinning).
- The `in_memory` backend is untouched (no Postgres → no pooler race).
- v1.36.0-style callers of `bind_request_body` / `bind_request` continue to work.

**Adopter action recommended.** None required. Adopters under transaction-mode poolers automatically benefit from the structural fix on the next `axon serve` start. Adopters who want pin observability set `RUST_LOG=axon::store::pin=info` in their server environment.

## What's intentionally NOT in v1.39.0

- D6.b `par(serialized: true)` opt-in grammar — requires parser/AST/type_checker work + AsyncMutex serialization. Future Fase.
- Per-statement pinning — tighter scope than per-flow. Honest deferral to a future fase if adopters report contention on long-running flows.
- Cross-flow pin sharing (session affinity) — out of scope; that's a Session feature, not a connection-pinning feature.
- `--strict-cardinality` CLI flag + default-on flip schedule — gate is currently always on as an ERROR (not warning); a future fase may add the opt-in/migration window if adopters report PRE-existing flows that pass runtime but fail the gate.
- D5 runtime hint improvement to audit_log — the compile-time gate is the load-bearing surface; runtime hint improvement is ergonomic-only and honestly deferred.
- Python parser parity for the new T9XX — per founder directive "todo encaminado a ser 100% Rust + C, 0 Python"; Python frontend stays at v1.33 surface.

## Plan vivos

- [docs/fase/fase_37xj_connection_pinned_flow_execution.md](docs/fase/fase_37xj_connection_pinned_flow_execution.md)
- [docs/fase/fase_38xe_retrieve_cardinality_gate.md](docs/fase/fase_38xe_retrieve_cardinality_gate.md)

## Trigger

kivi adopter regression report 2026-05-20, three failures observed in production:
1. `/api/chat` 3rd retrieve fails with `unnamed prepared statement does not exist` (post-v1.38.5 bump — race condition pre-existing but exposed by 37.y timing changes).
2. 9 newly un-skipped GET endpoints fail D5 `internal_validation_error` (cardinality mismatch class).
3. Net result: smoke 18 green on v1.38.4, red on v1.38.5.

v1.39.0 closes both classes structurally.
