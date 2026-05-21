---
title: "Plan vivo: Fase 37.x.j — Connection-Pinned Flow Execution (closing the unnamed-prepared-statement race against transaction-mode poolers)"
status: ⏳ OPEN 2026-05-20 — adopter regression; awaiting execution.
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
| **37.x.j.4** | `axon-rs/src/runner.rs` — `ExecContext.pinned_conns: HashMap<String, PinnedConn>`; eagerly acquire one per axonstore referenced in the flow body at execution start; pass through to every `wire_integrations::*` call site. Drop releases on `ExecContext` drop (sync runner is single-task, no Drop ordering subtlety). | D1 | ⏳ |
| **37.x.j.5** | `axon-rs/src/flow_dispatcher/dispatch_ctx.rs` — `DispatchCtx.pinned_conns` parity. Acquire eagerly at dispatcher startup (`run_streaming_via_dispatcher` before the flow walk loop); release on `DispatchCtx` drop. PoolConnection is `Send` so threading across `.await` is sound. | D2 | ⏳ |
| **37.x.j.6** | `axon-rs/src/flow_dispatcher/par_handler.rs` — D6.a default: spawn each `par` branch with its OWN sub-pin map (acquire on first store touch per branch). Implement `par(serialized: true)` D6.b opt-in: AST + parser surface + AsyncMutex over parent's pin in dispatch path. Emit D6.c branch_index tracing on every sub-pin acquire/release. | D6 | ⏳ |
| **37.x.j.7** | `axon-rs/src/store/pin_observability.rs` — central `tracing::info!` emitter (D4); call sites in postgres backend at acquire + release. Format: `target = "axon::store::pin"`, structured fields per D4 spec. | D4 | ⏳ |
| **37.x.j.8** | New anchor `axon-rs/tests/fase37xj_connection_pinning.rs` — 7 §-assertions per the test surface table below. STATIC grep §S pinning `acquire_pinned` exists on every backend impl. | D5 | ⏳ |
| **37.x.j.9** | Coordinated release axon-lang **v1.39.0** + axon-frontend **v0.20.0** (workspace catch-up bump). axon-enterprise **v1.30.0** catch-up per the standing rule. | — | ⏳ |

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
