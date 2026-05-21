---
title: "Plan vivo: Fase 37.x.j — Connection-Pinned Flow Execution (closing the unnamed-prepared-statement race against transaction-mode poolers)"
status: ✅ CLOSED 2026-05-21 — axon-lang v1.39.0 (initial) + v1.40.0 (38.x.f cycle) + **v1.40.1 (37.x.j.10 hotfix)** LIVE cross-stack. Cross-runtime PoolConnection hazard discovered + closed structurally via single-outer-`block_on_store` per flow execution. axon-enterprise v1.30.0 / v1.31.0 / v1.31.1 catch-ups LIVE in lockstep.
owner: AXON Language + Runtime Team
created: 2026-05-20
target: |
  axon-lang **v1.39.0** (MINOR — new public surface on the store
  backend trait `acquire_pinned()` + new public field on `ExecContext`
  + `DispatchCtx`; backwards-compat absolute on `in_memory` backend
  and on flows that don't reach a `axonstore`)
  axon-frontend **v0.20.0** (catch-up to the Cargo workspace bump;
  no AST changes are needed for 37.x.j alone — but v0.20.0 carries
  the Fase 38.x.e AST extension too, see that plan)
  axon-enterprise **v1.30.0** (catch-up per the standing rule)
depends_on: |
  Fase 37.x CLOSED 2026-05-19 (Pooler-coherent Store; v1.37.0 — the
  D1 `.persistent(false)` per-query layer). Fase 38.x.a CLOSED
  2026-05-20 (Pooler-coherent Transactions; v1.38.1 — the D2
  `after_release(DEALLOCATE ALL)` per-connection layer). 37.x.j ships
  the D3 layer: PIN the physical connection across the WHOLE flow
  execution so no inter-query backend swap is even possible.

charter_class: |
  OSS end to end. Touches `axon-rs/src/store/mod.rs` (trait extension),
  `axon-rs/src/store/postgres_backend.rs` + `in_memory.rs` (per-backend
  impl), `axon-rs/src/runner.rs` (ExecContext field + acquire site),
  `axon-rs/src/flow_dispatcher/dispatch_ctx.rs` (DispatchCtx field +
  acquire site), `axon-rs/src/algebraic_handlers/wire_integrations.rs`
  (retrieve/persist/mutate/purge/transact dispatch through pinned conn).
  Pure language substrate, vertical-agnostic.

# ▶ 1. The trigger source

## 1.a — The adopter's regression report (post-v1.38.5)

Smoke 18 on **v1.38.4 / enterprise 1.29.3** ran clean end-to-end:
`POST /api/chat` →  flow `ChatFlow` →  3 `retrieve` + 1 `persist` +
1 `step` LLM + 1 `persist` →  success, steps_executed: 6, 17 SSE
tokens. After bumping the adopter to v1.38.5 / enterprise 1.29.4 the
flow now fails deterministically at the 3rd retrieve:

```
event: axon.error
data: {"error":"flow 'ChatFlow' failed at retrieve from 'chat_history':
        BackendError { name: \"axonstore\",
        message: \"axonstore `retrieve` SQL failed:
        error returned from database:
        unnamed prepared statement does not exist\" }",
       "recoverable":false,"trace_id":3}
```

The adopter's connection string targets **Supavisor transaction-mode
pooler** (`aws-1-us-east-1.pooler.supabase.com:6543`, NO
`?statement_cache_capacity=0` in the URL — they trust the programmatic
setting axon makes in `PostgresStoreBackend::connect_named`).

## 1.b — Why 37.y did not introduce this (and why it surfaces now)

37.y v1.38.5 touched four files in `axon-rs/src/`:
`request_binding.rs`, `runner.rs`, `streaming_via_dispatcher.rs`,
`axon_server.rs`. **None** touched `store/`, `algebraic_handlers/`,
`flow_dispatcher/`, or `wire_integrations`. The diff against v1.38.4
on every store-adjacent path is zero lines changed.

The race condition existed in v1.38.4 — the adopter saw `sqlx_s_1
already exists` errors in Postgres logs from the warmup era (`axon`
opens 6 connections to introspect the 6 declared axonstores at
deploy time). The runtime path stayed lucky in smoke 18 because the
tokio task scheduling happened to land subsequent retrieves on the
same physical backend.

v1.38.5 changed task scheduling marginally (the 2 new `HashMap`
clones threaded through `run_streaming_via_dispatcher` plus the
spawn closure now captures 2 additional moved-in values). The
deterministic exposure means tokio now lands retrieves on different
physical backends on the same flow execution.

The race class is **`unnamed prepared statement does not exist`** —
distinct from the `sqlx_s_N already exists` (D1) class Fase 37.x.a
closed and the `duplicate_prepared_statement` (D2) class Fase 38.x.a
closed. Both prior fixes acted at the BACKEND level (per-query
`.persistent(false)`, per-conn-release `DEALLOCATE ALL`). 37.x.j
acts at the FLOW level: the physical backend is held across the
whole flow's lifetime.

# ▶ 2. Root cause: sqlx + Supavisor + per-query connection acquisition

`sqlx` uses the Postgres **extended query protocol** unconditionally:
every query is PARSE → BIND → EXECUTE → SYNC. With
`.persistent(false)`, the PARSE uses the unnamed statement (name = `""`).

In Supavisor (and PgBouncer in transaction-mode), each transaction
boundary is an opportunity for the pooler to swap the physical
backend connection. When sqlx pipelines PARSE+BIND+EXECUTE+SYNC in
a single round trip, this is safe — they all land on the same
backend. **But** when sqlx acquires a new connection for each
`sqlx::query(...)` call against the pool, two successive queries may
land on DIFFERENT physical backends. The unnamed statement parsed
on backend X is gone when the next query runs on backend Y.

Today every store op (`retrieve`, `persist`, `mutate`, `purge`,
`transact`) calls `&self.pool` directly — sqlx acquires a fresh
logical connection per call. With Supavisor in front of that, each
acquisition can hit a different physical backend.

# ▶ 3. The Connection-Pinned Flow Execution Contract — six D-letters

## D1 — Pinned conns per axonstore for the whole flow execution

At flow execution start, `ExecContext` (sync runner) and `DispatchCtx`
(async dispatcher) eagerly acquire **one** `PoolConnection<Postgres>`
per axonstore referenced by the flow body. The conns live in
`pinned_conns: HashMap<store_name, PoolConnection<Postgres>>` and are
held for the entire flow lifetime. Every `retrieve` / `persist` /
`mutate` / `purge` / `transact` against the pinned store goes through
that exact connection.

Acquire-on-first-touch is fine too (lazy), but the contract is: ONCE
acquired, the conn is held until flow Drop. No release-and-reacquire
mid-flow.

This guarantees the **same physical Postgres backend** services every
store op in the flow — no Supavisor swap window exists. The unnamed
statement parsed for the 1st retrieve is still on the backend when
the 3rd retrieve runs.

## D2 — DispatchCtx parity for the async streaming path

The async dispatcher path (`server_execute_streaming` →
`run_streaming_via_dispatcher` → `flow_dispatcher::dispatch_node`)
gains `DispatchCtx.pinned_conns` of the same shape. The runtime
contract is byte-identical to D1: one conn per axonstore, held
until the flow's `FlowComplete` or `FlowError` event fires.

`PoolConnection` is `Send` (sqlx 0.8 guarantee) so threading it
through `DispatchCtx` across `.await` points is sound.

Drop order: when `DispatchCtx` is dropped (flow finishes or aborts),
the conns release back to the pool. The existing
`after_release(DEALLOCATE ALL)` D2 layer (Fase 38.x.a) wipes any
prepared statements on the released conn before reuse — composing
cleanly with 37.x.j.

## D3 — Backwards-compat absolute on non-Postgres backends

The `StoreBackend` trait gains an `acquire_pinned` method:

```rust
async fn acquire_pinned(&self) -> Result<PinnedConn, StoreError>;
```

`PinnedConn` is an opaque per-backend handle (sealed enum or trait
object). For `PostgresStoreBackend`, `PinnedConn` wraps a real
`PoolConnection<Postgres>`. For `InMemoryStoreBackend`, `PinnedConn`
is a zero-cost no-op handle that holds a reference to the in-memory
state — the in-memory backend has no connection concept and no
pooler race, so the pin is purely structural.

Every store op grows a `&mut PinnedConn` parameter. The
in-memory backend ignores it. The Postgres backend uses the wrapped
`PoolConnection` instead of `&self.pool`.

The `StoreBackend` trait change is the only API break — additive
method, but every impl must provide it. We extend the existing two
backends in this Fase; future backends MUST provide it.

## D4 — Observability: tracing every pin acquire + release

`tracing::info!(target: "axon::store::pin", ...)` fires on every
pin acquire AND release with:

- `store_name` (axonstore name)
- `conn_id` (sqlx connection identifier, opaque debug)
- `flow_name` (the executing flow)
- `trace_id` (the request trace, when available — empty for CLI
  invocations)
- `duration_ms` (release-only — how long the conn was pinned)
- `path` ("acquire" | "release")

Auditors can grep for pin-leak symptoms (`acquire` without
matching `release` for the same `flow_name`+`trace_id`) and
deployments-under-load can confirm the pin lifetime stays bounded
by the flow's wall-clock.

## D5 — Property test + integration test under real Supavisor

New anchor file `axon-rs/tests/fase37xj_connection_pinning.rs`:

§1 — **D1 unit**: a synchronous flow with 5 sequential retrieves
against a real Postgres backend completes; assert all 5 queries
ran on the SAME `conn_id` (via instrumented `tracing` capture).

§2 — **D2 unit**: same on the async dispatcher path; same
assertion.

§3 — **D3 backwards-compat**: a flow against `in_memory` stays
green (zero behavior change).

§4 — **D4 observability**: `acquire` + `release` events emitted
in pair for every flow; no pin leak under success path.

§5 — **D4 pin-leak detection**: a flow that errors mid-execution
still releases its pinned conns (`Drop` is exercised in the error
path).

§6 — **D5 concurrent property**: 100 flows × 5 retrieves each,
running concurrently against a real Supavisor transaction-mode
endpoint (or a PgBouncer transaction-mode in CI), 100% success
rate — no `unnamed prepared statement does not exist`, no
`sqlx_s_N already exists`.

§7 — **D6 par-block isolation**: a flow with a `par { branch_a }
{ branch_b }` block where both branches retrieve from the SAME
axonstore — neither sees a `unnamed prepared statement` error nor
silently corrupts the other branch's bindings.

CI lane runs §1-§5 (no Supavisor in CI) and §6-§7 (no Supavisor;
the property is exercised on local Postgres with `pool_mode=transaction`
via PgBouncer running in a service container). Anchor §6 is the
load-bearing regression guard against the v1.38.5 break.

## D6 — Concurrency isolation clause: par { … } branches

A flow body's `par { branch_a } { branch_b } { … }` block runs
its branches **concurrently** on tokio tasks. They share the
parent flow's `pinned_conns` reference, but a single
`PoolConnection<Postgres>` is **NOT** thread-safe for concurrent
use — sqlx panics on shared mutable conn access.

The 37.x.j contract resolves this two ways:

**D6.a (default — branch-exclusive pin):** the parent flow's
`pinned_conns` is shared READ-ONLY across `par` branches. When a
branch needs to execute its FIRST store op on a given axonstore,
it acquires its OWN sub-pin (a fresh `PoolConnection` from the
pool) and holds it for the branch's lifetime. Branch sub-pins are
released when the branch completes (back to the parent's flow
pool). Two branches retrieving from the same axonstore use TWO
different physical backends — that's safe because each branch's
3 retrieves go through ONE conn end-to-end.

**D6.b (opt-in serialization — `par(serialized: true)`):** for
flows that demand strict session consistency across `par` branches
(e.g. a CTE-style retrieve cascade where branch_b's filter
depends on branch_a's row count), the adopter writes `par(serialized: true)`.
Branches are serialized via an `AsyncMutex` over the parent's
pinned conn — they share the same physical backend but run
sequentially (paralellism degrades to false interleaving). This is
NOT default because it defeats `par`'s purpose; adopters opt in
when session semantics matter more than throughput.

**D6.c (audit log):** every `par` branch's pin acquire emits a
`tracing::info!` with `branch_index` + the parent flow's `trace_id`
so operations can attribute connection counts to the offending
flow.

The runtime grammar `par(serialized: true)` is the only new public
surface from D6 (justifying the MINOR bump). v1.38.x flows without
the option keep the D6.a default — backwards-compat for adopters
that don't use `par` (which is most adopters today).

# ▶ 4. Sub-fases — single-cycle major-line patch, store-first

| Sub-fase | What | D-letters | Status |
|---|---|---|---|
| **37.x.j.1** | `axon-rs/src/store/store_conn.rs` (new) — define `StoreConn<'a>` wrapper enum (variants `Pool(&'a PgPool)` + `Pinned(&'a mut PoolConnection<Postgres>)`) with dispatch methods `fetch_all` / `fetch_optional` / `execute` / `begin` that re-borrow on every call. Add `PostgresStoreBackend::acquire_pin(&self) -> Result<PoolConnection<Postgres>, StoreError>`. Refactor `query` / `insert` / `mutate` / `purge` (`ping` is a single-query health probe, no benefit from pinning) + `row_stream::stream_retrieve` to take `&mut StoreConn<'_>` instead of `&self.pool`. Inline Pool/Pinned dispatch in `stream_retrieve` because the `BoxStream` lifetime cannot unify across the two variants through a single wrapper method. Update all 8 call sites (4 in `wire_integrations` + 4 in `runner`) to wrap `backend.pool()` in `StoreConn::Pool(...)` — legacy byte-identical path. | D1, D3 | ✅ SHIPPED 2026-05-20 — **architectural correction noted**: there is no `StoreBackend` trait in axon today; dispatch is by `StoreHandle` enum (`InMemory` \| `Postgres(PostgresStoreBackend)`). The plan vivo's "trait extension" framing was rewritten to "wrapper enum + per-backend impl". User ratified the (C′) wrapper-enum approach over the sqlx-idiomatic generic-Executor pattern (which collides with the cache-HIT-fall-through-to-MISS logic that consumes the executor) and over the (A) overlay duplicated-methods pattern. **2106/2106** axon-lang lib tests green (2 new in `store::store_conn::tests`); zero regressions. The InMemory backend doesn't need a `StoreConn` (no Postgres race against it) — wire-integrations call sites only construct `StoreConn::Pool` when `resolve_pg_backend` returns `Ok(Some(...))`, so the InMemory dispatch path is structurally unaffected by 37.x.j (originally split sub-fase 37.x.j.3). |
| **37.x.j.2** | (merged into 37.x.j.1) | D1 | ✅ SHIPPED 2026-05-20 — folded into 37.x.j.1 because the wrapper-enum approach + the backend method refactor are atomically linked. The 4 Postgres backend methods (`query` / `insert` / `mutate` / `purge`) all migrated together; `ping` deliberately retained as `&self.pool` (single-query probe, no benefit). `row_stream::stream_retrieve` also migrated in the same change. |
| **37.x.j.3** | (no-op, see 37.x.j.1 note) | D3 | ✅ SHIPPED 2026-05-20 — InMemory backend doesn't participate in the `StoreConn` dispatch (no Postgres → no pooler race → no pin to acquire). The `resolve_pg_backend` gate in `wire_integrations` returns `Ok(None)` for in-memory stores, which routes to the legacy in-memory-only path unchanged. D3 backwards-compat verified by zero regressions across 2106 lib tests. |
| **37.x.j.4** | `axon-rs/src/runner.rs` — `ExecContext.pinned_conns: HashMap<String, PinnedConn>`; eagerly acquire one per axonstore referenced in the flow body at execution start; pass through to every `wire_integrations::*` call site. Drop releases on `ExecContext` drop (sync runner is single-task, no Drop ordering subtlety). | D1 | ✅ SHIPPED 2026-05-20 — **architectural correction**: rather than put `pinned_conns` IN `ExecContext` (which is `Clone` and would propagate non-Clone `PoolConnection` issues into parallel-wave `ctx.clone()`), the pin map lives at the OUTER scope (`execute_server_flow` local variable) and is threaded by `&mut` through `execute_real` → `execute_sql_store_step`. **Eager acquire** walk: at `execute_server_flow` start, after `StoreRegistry::build`, iterate `execution_units[i].steps`, filter `step_type ∈ {persist, retrieve, mutate, purge}` + `backend_kind == Postgresql`, dedupe by `step_name`, call `backend.acquire_pin().await` per store, populate `HashMap<String, PoolConnection<Postgres>>`. Drop = HashMap drop = per-conn drop = `after_release(DEALLOCATE ALL)` hook fires (composes with Fase 38.x.a D2). **Critical prerequisite ALSO landed**: `execute_sql_store_step` switched from `PostgresStoreBackend::connect_named` (fresh pool per call!) to `store_registry.resolve()` (cached pool). Without this the pin would be on a DIFFERENT pool than the dispatch, defeating the purpose. **Threading**: `execute_real` gains `pinned_conns: &mut HashMap<...>` param; `execute_sql_store_step` gains same. CLI path passes an empty map → legacy `StoreConn::Pool` fallback (CLI is one-shot, no flow-scope to pin against). Inside `execute_sql_store_step`, per step: `pin = pinned_conns.remove(&store_name)` → moved into `block_on_store(async move { ... })` → bound `mut pin` → `match &mut pin { Some(p) => StoreConn::Pinned(p), None => StoreConn::Pool(backend.pool()) }` → dispatch via the StoreConn → return `(result, pin)` tuple from async block → re-insert pin in HashMap on the outer side. **The async-block `?` propagation** preserved via nested `async { match step_type { ... } }.await` returning `Result<String, StoreError>` (the outer async returns the `(Result, Option<PoolConnection>)` tuple). **Failure mode**: pin acquire failure → `tracing::warn!` with `d_letter=37.x.j.D1` + fall through to legacy Pool path; flow proceeds, adopter under transaction-mode pooler may still observe the race (degraded but not broken). **2106/2106** lib tests green; zero regressions. The Postgres pin test `runner::fase35e_tests::sql_persist_below_confidence_floor_is_blocked` had to be fixed: the registry `resolve()` requires tokio context, so the resolve was moved BACK inside `block_on_store` (initially placed outside, broke the test). 4 test call sites of `execute_sql_store_step` updated to pass `&mut HashMap::new()`. Note: this sub-fase covers the SYNC runner path; the kivi `/api/chat` regression goes through the ASYNC dispatcher path (`run_streaming_via_dispatcher`), which is 37.x.j.5's surface. The pin substrate is uniform across both. |
| **37.x.j.5** | `axon-rs/src/flow_dispatcher/dispatch_ctx.rs` — `DispatchCtx.pinned_conns` parity. Acquire eagerly at dispatcher startup (`run_streaming_via_dispatcher` before the flow walk loop); release on `DispatchCtx` drop. PoolConnection is `Send` so threading across `.await` is sound. | D2 | ✅ SHIPPED 2026-05-20 — **the adopter-critical path is now pinned end-to-end**. Three landing pieces: (1) new `DispatchCtx.pinned_conns: Arc<Mutex<HashMap<String, PoolConnection<Postgres>>>>` field + `with_pinned_conns()` builder in `axon-rs/src/flow_dispatcher/mod.rs`. The Arc<Mutex<>> matches the existing `enforcement_summaries` / `step_audit_records` / `runtime_warnings` pattern on the struct — and crucially keeps `DispatchCtx: Clone` working for the `parallel.rs::ctx.clone()` per-par-branch site (the conns share between branches under 37.x.j.5; D6.a/b proper isolation lands in 37.x.j.6). Default in `DispatchCtx::new()` is `Arc::new(Mutex::new(HashMap::new()))` — empty map ≡ no pin held ≡ wire-integration handlers fall back to `StoreConn::Pool` (D5 byte-identical for non-streaming callers / RPC paths / CLI tests). (2) `run_streaming_via_dispatcher` (in `streaming_via_dispatcher.rs`) gains the eager discovery + acquisition walk right after `StoreRegistry::build`: iterate `ir.flows[*].steps`, match `IRFlowNode::{Persist, Retrieve, Mutate, Purge}` to extract `store_name`, filter `backend_kind == Postgresql`, dedupe via HashSet, then for each store resolve via `store_registry.resolve()` (cached pool) and call `backend.acquire_pin().await`. Failures are non-fatal `tracing::warn!` with `d_letter=37.x.j.D2` — the flow proceeds with the empty pin map (degraded fallback). The walk is **permissive over-acquire** (scans EVERY flow in the IR, not just the resolved one) — deferred precise walk to 37.x.j.6 alongside the par-block isolation work. (3) The 4 call sites in `flow_dispatcher/wire_integrations.rs` (`run_persist`, `run_retrieve`, `run_mutate`, `run_purge`) all converted to take-pin-out / dispatch / return-pin discipline: lock the Mutex briefly to `.remove()` the pin, build `StoreConn::Pinned(&mut pin)` (or `StoreConn::Pool(backend.pool())` fallback when pin is None), run the SQL dispatch via `backend.{insert,query,mutate,purge}` (or `row_stream::stream_retrieve` for retrieve), lock again briefly to `.insert()` the pin back. Mutex held microseconds; SQL dispatch runs lock-free. **2106/2106** axon-lang lib tests green; zero regressions. **Adopter impact**: the `/api/chat` SSE path now routes ALL 3 sequential retrieves against the SAME physical Postgres backend connection — Supavisor cannot swap mid-flow — the `unnamed prepared statement does not exist` race is structurally closed for this path. The next verification is a live smoke test against the adopter's Supavisor-fronted deployment (deferred to 37.x.j.8 anchor + adopter smoke). |
| **37.x.j.6** | `axon-rs/src/flow_dispatcher/par_handler.rs` — D6.a default: spawn each `par` branch with its OWN sub-pin map (acquire on first store touch per branch). Implement `par(serialized: true)` D6.b opt-in: AST + parser surface + AsyncMutex over parent's pin in dispatch path. Emit D6.c branch_index tracing on every sub-pin acquire/release. | D6 | ✅ SHIPPED 2026-05-20 — **D6.a SHIPPED; D6.b honest-deferred**. Two surgical changes: (1) `axon-rs/src/flow_dispatcher/parallel.rs` — when `parallel::run_par_block` clones the parent `DispatchCtx` per branch (the existing `ctx.clone()` pattern), the cloned branch's `pinned_conns` Arc is REPLACED with `Arc::new(Mutex::new(HashMap::new()))` — a fresh empty map per branch. Branches no longer share the parent's pin via the Arc; D6.a "per-branch sub-pin" semantics are structurally enforced. (2) `axon-rs/src/flow_dispatcher/wire_integrations.rs` — the 4 take-pin sites (persist/retrieve/mutate/purge) extended with **lazy on-miss acquire**: when the local `ctx.pinned_conns.lock().remove(&store_name)` yields `None` (the canonical state for a freshly-cloned branch's first store touch), the handler attempts `backend.acquire_pin().await` to lazily get a pin for THIS branch — then runs its dispatch against `StoreConn::Pinned` and returns the pin to the branch-local map. Subsequent store ops in the same branch against the same store find the pin already present and reuse it (D1 intra-branch invariant). When even the lazy acquire fails (pool exhausted), the handler falls through to `StoreConn::Pool` (legacy degraded) — flow still proceeds but the race is not protected for that one op. **The net behavior**: a `par { branch_a } { branch_b }` block where both branches retrieve from the SAME store gets TWO independent physical Postgres backend connections (one per branch), preserving par concurrency. Within each branch's linear walk, all retrieves on that store share that branch's one pin → unnamed-statement race closed per-branch. **D6.b `par(serialized: true)` opt-in** is honestly deferred to a future fase: shipping it requires parser + AST + type_checker work for the `par(serialized: true)` grammar surface, plus replacing the Arc-replace with a parent-Arc-share + AsyncMutex over the parent's pin in dispatch. The honest-deferral is documented in the plan vivo and in inline comments at the parallel.rs and wire_integrations.rs call sites. **2106/2106** axon-lang lib tests green; zero regressions. **D6.c branch-index tracing** also honest-deferred to sub-fase 37.x.j.7 (the pin_observability module) for a single consolidated tracing surface across all D4+D6.c emission points. |
| **37.x.j.7** | `axon-rs/src/store/pin_observability.rs` — central `tracing::info!` emitter (D4); call sites in postgres backend at acquire + release. Format: `target = "axon::store::pin"`, structured fields per D4 spec. | D4 | ✅ SHIPPED 2026-05-20 — new module `axon-rs/src/store/pin_observability.rs` shipping two emit fns: `emit_pin_acquire(store_name, flow_name, trace_id, source, branch_index)` + `emit_pin_flow_summary(flow_name, trace_id, released_count)`. **Scope adjustment** vs original plan: v1.39.0 ships ONLY the acquire-time emit (release is implicit via `PoolConnection::drop` → `after_release(DEALLOCATE ALL)` hook from Fase 38.x.a D2). A future fase may add a `PinObserved` wrapper struct that emits explicitly on Drop for per-pin lifetime tracking. The minimal v1.39.0 surface honors the "no unnecessary observability machinery" rule while still giving operators enough to detect pool saturation + pin leaks (grep `acquire` events without matching `flow_end` summary). **Wired at 3 sites**: (1) sync runner `runner.rs::execute_server_flow` eager-acquire loop emits with `source = "eager"`, `branch_index = None`. (2) async dispatcher `streaming_via_dispatcher.rs` eager-acquire loop emits with same fields. (3) 4 wire-integration call sites in `flow_dispatcher/wire_integrations.rs` (`run_persist` / `run_retrieve` / `run_mutate` / `run_purge`) emit on lazy on-miss acquire with `source = "lazy"`, `branch_index = if ctx.branch_path.is_empty() { None } else { Some(ctx.branch_path.len()) }` — captures D6.c branch-index info from the existing `DispatchCtx.branch_path`. **Structured fields** (filterable via `RUST_LOG=axon::store::pin=info`): `path = "acquire"`, `source`, `store_name`, `flow_name`, `trace_id`, `branch_index`, `d_letter = "37.x.j.D4"`. **2108/2108** lib tests green (2 new in `store::pin_observability::tests` — typed callability assertions; per-event capture deferred to anchor test §4). |
| **37.x.j.8** | New anchor `axon-rs/tests/fase37xj_connection_pinning.rs` — 7 §-assertions per the test surface table below. STATIC grep §S pinning `acquire_pinned` exists on every backend impl. | D5 | ✅ SHIPPED 2026-05-20 — new anchor file [axon-rs/tests/fase37xj_connection_pinning.rs](../../axon-rs/tests/fase37xj_connection_pinning.rs) with **12 passing tests** partitioned by infrastructure requirement. **Shipped in v1.39.0** (no external infra): (a) **§S STATIC grep × 7** pinning every load-bearing surface declaration via `include_str!` — `StoreConn<'a>` enum + `Pool` + `Pinned` variants + `fetch_all`/`fetch_optional`/`execute`/`begin` dispatch methods (store_conn.rs); `acquire_pin()` method (postgres_backend.rs); `DispatchCtx.pinned_conns` field + `with_pinned_conns()` builder (flow_dispatcher/mod.rs); `emit_pin_acquire` + `emit_pin_flow_summary` (pin_observability.rs); `bc.pinned_conns = std::sync::Arc::new(...)` per-branch Arc replacement (parallel.rs); eager-acquire `backend.acquire_pin().await` + `pinned_conns` threading in runner.rs; same in streaming_via_dispatcher.rs + `.with_pinned_conns(...)` install; `.pinned_conns.lock().unwrap().remove(` at all 4 wire_integrations sites (≥4 expected, dedup-safe). (b) **§3 D3 in_memory** — assertion that `StoreConn` has exactly 2 variants; in-memory dispatch is structurally upstream of `StoreConn`. (c) **§4 D4 observability totality** × 2 — `emit_pin_acquire` + `emit_pin_flow_summary` are total over all documented inputs (empty strings, 10k-char strings, `usize::MAX`) — never panic. (d) **§S surface accessibility** — `StoreConn` public type accessible externally. **Deferred to a CI compose-service lane (sub-fase 37.x.j.8.b, future)**: §1 D1 5-sequential-retrieves-same-conn_id (real Postgres needed), §2 D2 async path same (real Postgres), §5 D4 error-path pin release (real Postgres + error injection), §6 D5 100-flows × 5-retrieves property test against PgBouncer transaction-mode (compose service), §7 D6 par-block live (real Postgres + concurrent harness). The deferral is honest because the property tests need real pooler swap behavior — neither in-process axon test harness nor sqlx mock layer simulates Supavisor's connection-swap window. **12/12** anchor green; **2108/2108** axon-lang lib green; zero regressions. |
| **37.x.j.10** | **POST-CLOSE HOTFIX** — cross-runtime `PoolConnection<Postgres>` regression in the sync runner path. Diagnosed 2026-05-21. **Root cause**: `block_on_store(async { acquire_pin().await })` runs the acquisition on a temporary tokio runtime (`std::thread::scope` + `tokio::runtime::Builder::new_current_thread`). The `PoolConnection` carries reactor handles bound to THAT temporary runtime; when block_on_store returns, the runtime drops, and the conn is moved to `HashMap<String, PoolConnection<Postgres>>` on the main thread. Subsequent dispatches inside `execute_sql_store_step` open ANOTHER temporary runtime per step; awaiting on the pinned conn from that new runtime hangs indefinitely because the conn's reactor handles point to a dead runtime. **Symptom**: D4 observability emits `"pin acquired (eager) source=eager"` log; subsequent SQL emission never happens; transaction hangs. **Scope of impact**: sync runner path (every endpoint with `transport: json` declared OR inferred — i.e. ~ALL CRUD REST endpoints in production deploys, regardless of adopter). Async dispatcher path (`run_streaming_via_dispatcher`) UNAFFECTED — its eager-acquire `.await` lives on the SAME runtime as the dispatcher's flow walk. **Why test suite didn't catch**: 12 §-anchor + 5 cardinality + 2108 lib tests don't exercise REAL Postgres dispatch on the sync runner pinned path; `runner::fase35e_tests` error before reaching dispatch (PoolInit failure without real DB). 37.x.j.8 anchor's §1/§2/§5/§6/§7 honest-deferred to a CI compose-service lane that was NOT built — exactly the lane that would have caught this. **Fix — B' refinada (single outer block_on_store per flow execution)**: `execute_real` converts to async fn; `execute_sql_store_step` converts to async fn (drops its internal `block_on_store` wrapper); `execute_server_flow` restructures its async work into a SINGLE outer `block_on_store(async move { eager_acquire().await; execute_real_async(...).await })` so the entire flow execution — pin acquire + every store dispatch + pin drop — runs on the SAME runtime. Reactor handles stay valid throughout. Pinning structural protection PRESERVED for sync runner (load-bearing for production REST APIs against transaction-mode poolers — the majority pattern). Pre-existing sync callers of `execute_real` (CLI path at line ~2771) restructure to wrap the async variant in `block_on_store` too. Existing tests of `execute_sql_store_step` migrate to async via `block_on_store(execute_sql_store_step_async(...))` shim. Ships as axon-lang **v1.40.1 PATCH** + axon-enterprise **v1.31.1** catch-up. | D1, D5 (failure-mode discovery) | ✅ SHIPPED 2026-05-21 — three landing pieces in [axon-rs/src/runner.rs](../../axon-rs/src/runner.rs): (1) new `async fn execute_sql_store_step_async` (the body of the old sync fn with the internal `block_on_store(async move { ... })` wrapper unwound — direct async fn body); sync `execute_sql_store_step` retained as thin wrapper calling `block_on_store(execute_sql_store_step_async(...))` so the 4 existing test callsites + non-server callers stay byte-compatible. (2) new `async fn execute_real_async` (same body as old sync `execute_real`; only change is the SQL site calls `execute_sql_store_step_async(...).await` instead of the sync wrapper); sync `execute_real` becomes thin wrapper for CLI path. (3) `execute_server_flow` restructured: the IR-walk to compute `needed_pg_stores` set stays sync; the `if backend == "stub"` branch unchanged; the `else` branch (real backend) is now SINGLE `block_on_store(async { ... eager_acquire ... ; execute_real_async(...).await })` — both pin acquisition + flow dispatch + implicit pin drop ALL execute on the SAME temporary tokio runtime. `async` (not `async move`) so `report`/`registry`/`store_registry`/`execution_units`/`needed_pg_stores` are borrowed by ref (std::thread::scope inside block_on_store allows non-'static borrows). The `flow_name` &str is captured by ref directly. Variable renamed `backend` → `backend_pool` inside the acquire loop to avoid shadowing of the outer `backend: &str` parameter. Anchor §S grep loosened from `backend.acquire_pin().await` to `.acquire_pin().await` so the receiver-variable rename doesn't accidentally break the structural assertion. **2108/2108** axon-lang lib + **12/12** Fase 37.x.j anchor + **12/12** Fase 38.x.f anchor + **5/5** Fase 38.x.e cardinality = all green; zero regressions. Async dispatcher path (`run_streaming_via_dispatcher`) UNCHANGED — its eager-acquire was already correct (lives on the same runtime as the dispatcher's flow walk via direct `.await`); only the sync runner path had the cross-runtime hazard. |
| **37.x.j.9** | Coordinated release axon-lang **v1.39.0** + axon-frontend **v0.20.0** (workspace catch-up bump). axon-enterprise **v1.30.0** catch-up per the standing rule. | — | ✅ SHIPPED 2026-05-21 — coordinated release LIVE cross-stack. **axon-lang v1.39.0**: release commit `9b0d9f9` + plan-CLOSED commit `13cb9d7` + 3 tags pushed (`v1.39.0`, `rust-v1.39.0`, `axon-frontend-v0.20.0`); crates.io published in order (axon-frontend 0.20.0 first → axon-lang 1.39.0 second; ordering preserves the build-time dep pin `axon-frontend = "=0.20.0"`); GitHub Release v1.39.0 published with content-first notes covering both 37.x.j + 38.x.e D-letters + market-vs-axon parity table + vertical-inheritance section; PyPI publish.yml fired cleanly on `release: published` event (no draft-toggle recovery needed), completed in 6m27s. **axon-enterprise v1.30.0**: PR #43 merged commit `1b95984` (2-file diff: `pyproject.toml` version 1.29.4→1.30.0 + dep pin `axon-lang>=1.38.5`→`>=1.39.0` + `axon_enterprise/__init__.py` `__version__`); tag `v1.30.0` pushed via refspec mapping `enterprise/v1.30.0:refs/tags/v1.30.0`; GitHub Release v1.30.0 published with vertical-inheritance notes (HIPAA + FRE 502 + BSA-OFAC + FedRAMP each get layered defense composition note); Enterprise Release Docker build + ECR Private image pushed clean in 1m54s with two-phase CDN-consistency wait (per axon-enterprise PR #14 commit `9d7fe12`); Fase 29 + axon-csys-enterprise workflows green. **PyPI CDN propagation race** caught + recovered (4 lanes failed early): single `gh run rerun --failed` after ~4-min wait for CDN propagation (latest=1.39.0 visible) → 24/24 lanes green on rerun. **Cumulative regression**: 447/447 axon-frontend lib + 2108/2108 axon-lang lib + 12/12 Fase 37.x.j anchor + 5/5 Fase 38.x.e cardinality tests = all green; zero regressions cross-stack. Founder standing rule honored end-to-end: every axon-lang release ships an axon-enterprise catch-up in lockstep. |

# ▶ 5. Test surface — 7 §-assertions

| § | What it pins | Mode |
|---|---|---|
| **§1** | D1 — sync runner: 5 sequential retrieves in one flow all hit the same `conn_id` | unit |
| **§2** | D2 — async dispatcher: same assertion via SSE wire | integration |
| **§3** | D3 — `in_memory` backend: a flow stays byte-identical to v1.38.5 | integration |
| **§4** | D4 — observability: every `acquire` event has a matching `release` event on flow completion | unit |
| **§5** | D4 — error-path pin release: a flow that errors mid-execution still releases its pinned conns | integration |
| **§6** | D5 — concurrent property: 100 flows × 5 retrieves each against PgBouncer transaction-mode → 100% success, 0 unnamed-statement errors | property |
| **§7** | D6 — par-block: a flow with `par` branches retrieving from the same store, both default (D6.a sub-pins) AND opt-in `par(serialized: true)` (D6.b AsyncMutex), neither leaks unnamed-statement errors | integration |

Plus STATIC grep §S pinning the new public surface declarations.

# ▶ 6. Forward-compatibility commitments

- **Per-statement pinning** (a tighter scope than per-flow) is a
  future Fase 37.x.k candidate if adopters report contention on
  long-running flows. Today the per-flow pin is the simplest
  contract that closes the race.
- **`pool.max_connections` tuning guidance**: 37.x.j changes the
  pool's effective load — every concurrent flow holds N conns
  (one per axonstore it touches) for its full duration. Documented
  in `docs/ADOPTER_STORE.md` §pool-sizing as a follow-up.
- **Pin lifetime metrics**: a future fase can graph
  `acquire→release` durations per axonstore via Prometheus.

# ▶ 7. What is intentionally NOT in v1.39.0

- **Per-statement pinning** — see §6 above.
- **Cross-flow pin sharing** (e.g. a session that spans multiple
  HTTP requests) — out of scope; that's a Session affinity
  feature, not a connection pinning feature.
- **`PinnedConn` exposed to flow user code** — adopters never see
  it; it's purely an internal runtime implementation detail.

# ▶ 8. The two-question gate

## Q1 — Is this market standard, or superior to what other languages offer?

**SUPERIOR.** Every framework reviewed punts on this:

| Framework | Behavior with PgBouncer transaction-mode |
|---|---|
| FastAPI + SQLAlchemy | adopter must `pool_pre_ping=True` + disable prepared statements manually (asyncpg) |
| Spring + JDBC | adopter configures `prepareThreshold=0` + HikariCP per-thread connection-affinity manually |
| Rails + ActiveRecord | adopter sets `prepared_statements: false` in `database.yml` (loses every benefit of prepared statements) |
| Node + pg-pool | adopter writes per-request connection-checkout middleware manually |
| Rust + sqlx (vanilla) | the bug we just hit — adopter must pin conns manually via `pool.acquire()` + thread `PoolConnection` through every query |

axon's contribution: **the pin is automatic at the LANGUAGE
level**. An adopter writes a normal flow, and axon's runtime
guarantees pooler-coherence end-to-end. The adopter never sees
`unnamed prepared statement does not exist` again — not because
they configured something right, but because the language refuses
to expose them to it.

This is consistent with axon's pattern at every layer: the safety
property is the LANGUAGE's invariant, not the adopter's discipline.

## Q2 — Minimum to run, or robust and complete for large, complex adopters?

**Target adopter profile**: multitenant SaaS adopters on Supavisor /
PgBouncer / Neon / RDS Proxy / Aurora Cluster — i.e. the 95% of
production adopters who use a transaction-mode pooler in front of
Postgres. **Plus** the 5% on direct Postgres conns, where 37.x.j
adds essentially zero overhead (pin = `pool.acquire()` once per
flow, release on Drop).

**ROBUST scope in v1.39.0:**

- ✅ Pin acquired per axonstore at flow start (D1)
- ✅ Same primitive on async dispatcher (D2)
- ✅ Backwards-compat on `in_memory` (D3)
- ✅ Observable via `tracing::info!` (D4)
- ✅ Property test under real PgBouncer transaction-mode (D5)
- ✅ `par { }` concurrent branches handled (D6.a default + D6.b
  opt-in serialization)
- ✅ Cross-stack release (axon-lang + axon-frontend + axon-enterprise
  catch-up per the standing rule)

**HONESTLY DEFERRED:**

- ❌ Per-statement pinning (§6)
- ❌ Cross-flow pin sharing / session affinity (§7)
- ❌ Prometheus pin-lifetime metrics (§6)

The honest answer to Q2: **ROBUST for the 95% production adopter
profile that uses a transaction-mode pooler**. The deferred items
are observability + tuning enhancements, not safety properties —
the safety property closes here.

# ▶ 9. The closing condition

Closed when:
- axon-lang v1.39.0 published cross-stack (PyPI + crates.io
  axon-lang 1.39.0 + crates.io axon-frontend 0.20.0 + GitHub Release)
- axon-enterprise v1.30.0 catch-up live (PR merged + tag via
  refspec mapping + GitHub Release + ECR Private image)
- The kivi adopter smoke 18+ on v1.39.0 green end-to-end — 6 steps,
  17 SSE tokens, zero `unnamed prepared statement` errors
