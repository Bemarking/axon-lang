---
title: "Plan vivo: Fase 38.x — Pooler-coherent transactions (closing the Gap-3 leak inside `pool.begin()`)"
status: ✅ CLOSED 2026-05-20 — axon-lang v1.38.1 patch live cross-stack. D1–D4 ratified.
owner: AXON Language + Runtime Team
created: 2026-05-20
target: axon-lang v1.38.1 (PATCH — bug fix; axon-frontend stays 0.19.0; D4 absolute — pre-pooler adopters byte-identical to v1.38.0)
depends_on: |
  Fase 37.x CLOSED 2026-05-19 (the 9-D-letter Pooler-Coherent Store Contract).
  Fase 38 CLOSED 2026-05-20 (the Declared & Compile-Time-Typed Store Schema).
  Smoke 16 (kivi adopter, 2026-05-20 post-v1.38.0): the `axonstore postgresql`
  data plane re-broke behind Supabase Supavisor transaction-mode pooler with
  `prepared statement "sqlx_s_N" already exists` — the EXACT regression
  class v1.36.4 closed with `statement_cache_capacity(0)` and v1.37.x's
  9-D-letter contract was supposed to make impossible.

charter_class: |
  OSS end to end. The fix lives in `axon-rs/src/store/postgres_backend.rs`
  + `axon-rs/src/store/row_stream.rs` + `axon-rs/src/store/introspect_cli.rs`
  — pure runtime substrate, vertical-agnostic.

# ▶ 1. The smoke 16 evidence (kivi adopter, 2026-05-20)

```
[axon-server] deploy starting (axonstore: tenants, schema_dir=./schemas)
[axon-server] WARM  store=tenants → ERR  prepared statement "sqlx_s_1" already exists
[axon-server] WARM  store=audit   → ERR  prepared statement "sqlx_s_2" already exists
[axon-server] WARM  store=events  → ERR  prepared statement "sqlx_s_3" already exists
[axon-server] (retry) WARM store=tenants → ERR prepared statement "sqlx_s_1" already exists
[axon-server] (retry) WARM store=audit   → ERR prepared statement "sqlx_s_2" already exists
[axon-server] (retry) WARM store=events  → ERR prepared statement "sqlx_s_3" already exists
[axon-server] deploy OK (warmups soft-failed — see warnings)

[axon-server] POST /flows/diag/run
  → store.retrieve(tenants, where: "tenant_id = ${tenant_id}", bindings: {…})
  → ERR  current transaction is aborted, commands ignored until end of transaction block
  → ERR  retrieve(tenants): runtime store error
  → 500 Internal Server Error
```

Six warmups against three stores (two attempts each) ALL collided. The
operation smoke that followed died on a SECONDARY error — "transaction
aborted" — because the *primary* error (the `sqlx_s_N already exists`
that ABORTED the transaction) was **swallowed silently** by an `Err(_)`
match arm in `postgres_backend.rs::query` line 1336.

# ▶ 2. Root-cause analysis (the two-layer leak)

## Layer A — `statement_cache_capacity(0)` does NOT prevent prepared-statement collision behind transaction-mode poolers

`PgConnectOptions::statement_cache_capacity(0)` set in
`connect_named_with_namespace` (line 1256) disables sqlx's per-connection
LRU **cache** of prepared statements. It does NOT change the
PARSE protocol: every `sqlx::query(...)` with `persistent = true`
(the sqlx 0.8 default) still allocates a monotonic name
(`sqlx_s_1`, `sqlx_s_2`, …) and sends `PARSE sqlx_s_N`.

Behind a transaction-mode pooler (Supabase Supavisor `:6543`, PgBouncer
`pool_mode=transaction`, Neon, RDS Proxy) the **physical Postgres
connection persists across logical sessions**. Prepared statements that
the previous logical session created stay alive on the physical conn
until the physical session closes — which is hours/days, not the
~milliseconds of one axon transaction. When sqlx's per-connection counter
restarts at 1 for a new logical session and the SAME physical conn
serves both sessions, `PARSE sqlx_s_1` collides with the residual
`sqlx_s_1` from the previous session → Postgres `42710`
`duplicate_prepared_statement` → transaction aborted.

This is a property of transaction-mode poolers, not a sqlx bug. v1.36.4's
fix was incomplete: it prevented sqlx from auto-deallocating, but it
NEVER prevented sqlx from issuing named PARSEs in the first place.

## Layer B — `Transaction<'_, Postgres>` from `pool.begin()` widens Layer A's blast radius

Fase 37.x.d (commit `c0977ed`, v1.37.0, 2026-05-19) wrapped the
cache-MISS path in `pool.begin()` so the schema introspection and the
operation execute inside ONE transaction (D3 pooler-coherent guarantee).
Inside that transaction, `introspect_conn` runs **two** `sqlx::query(...)`
calls (Stage 1 `to_regclass` + Stage 2 fallback scan) — each with
`persistent = true` — BEFORE the operation's own `sqlx::query`. So a
single cache-MISS warmup issues 2–3 named PARSEs against the same
physical conn within milliseconds; every one is a collision risk.

Fase 38.f (v1.38.0, 2026-05-20) extended this same pattern to
`verify_postgres_schemas_with_manifest`, which runs at every deploy.

## Layer C — The observability collapse

`query`, `persist`, `mutate`, `purge`, and `row_stream::drain_stream`
each contain:

```rust
let (schema, column_types) = match &resolved {
    Ok(r) => (Some(r.schema.as_str()), &r.column_types),
    Err(_) => (None, &no_types),   // ← five sites, all silent
};
```

A `42710` from `introspect_conn` becomes `(None, no_types)` and the
operation proceeds with a BARE-TABLE SQL (no schema qualification, no
column type map). That bare-table SQL then runs against the ALREADY
ABORTED transaction → Postgres `25P02` `in_failed_sql_transaction`.

The adopter sees ONLY the cascade error. The root cause — the prepared
statement collision — is **literally invisible**. This made the kivi
smoke take 3 round-trips to diagnose what should have been one.

# ▶ 3. The Pooler-coherent Transactions Contract (the heart)

For every `sqlx::query` / `sqlx::query_as` call against a Postgres
connection or pool managed by axon-lang's store substrate:

**D1 — UNNAMED prepared statements, always.** Every `sqlx::query(...)`
and `sqlx::query_as(...)` call against a pool, a `PoolConnection`, a
`Transaction`, or a `PgConnection` carries `.persistent(false)`. sqlx
issues `PARSE` with an empty name `""`, which Postgres
auto-discards/replaces on the next unnamed PARSE. Cross-session collision
is structurally impossible. ENFORCED by D5's grep gate.

**D2 — `DEALLOCATE ALL` after every connection release (belt-and-suspenders).**
The pool's `PoolOptions::after_release` hook runs `DEALLOCATE ALL` on
every connection returned to the pool. If a future code path
accidentally omits `.persistent(false)`, the named statements it
allocated are wiped from the physical conn before it heads back to the
pooler — the next logical session sees a clean slate. Composes with D1
without conflict (an unnamed PARSE has nothing to deallocate).

**D3 — Honest observability at every cache-MISS path.** Every
`match &resolved { Err(_) => … }` site converts to `Err(e) => {
tracing::warn!(target: "axon::store", …, error = %e, …); … }`
emitting:

- `table` — the store table name
- `op` — `"introspect_in_tx"` (the operation that failed)
- `error` — the actual `StoreError` Display
- `d_letter` — `"D3+38.x.a"`
- a human-readable hint naming the likely root cause

The adopter's operator now sees the PRIMARY failure in their journald /
CloudWatch / Loki, not the SECONDARY cascade.

**D4 — Absolute backwards-compat.** An adopter NOT behind a
transaction-mode pooler (direct connection / in_memory backend / a
session-mode pooler) sees behavior **byte-identical** to v1.38.0.
The unnamed prepared statement protocol is a strict subset of the
named protocol; Postgres treats both identically for routing,
EXPLAIN, statement_timeout, etc. Performance overhead is
**measurable but small**: an unnamed prepared statement is re-prepared
on every call (no cache), so a hot SELECT inside a tight loop pays
~1 extra round-trip per call vs. the cached-named protocol. Adopters
hitting that hot path WILL be guided to the cache-HIT path
(which lives on top-level pool, no transaction) where sqlx's per-call
auto-cache (separate from `statement_cache_capacity`) reuses the same
unnamed prepared statement within one connection acquisition.

# ▶ 4. Sub-fases (38.x.a — single-cycle patch, topologically ordered)

| Sub-fase | What | D-letters | Status |
|---|---|---|---|
| **38.x.a.1** | Apply `.persistent(false)` on EVERY `sqlx::query(...)` / `sqlx::query_as(...)` call site in `axon-rs/src/store/`: 11 sites in `postgres_backend.rs` (2 in `introspect_conn`, 8 in retrieve/persist/mutate/purge cache-HIT + cache-MISS, 1 in `ping`), 2 in `row_stream.rs`, 3 in `introspect_cli.rs`. | D1 | ✅ |
| **38.x.a.2** | `PoolOptions::after_release` hook in `connect_named_with_namespace` runs `DEALLOCATE ALL` on every released conn. Hook itself uses `.persistent(false)` (the meta-invariant — even the cleanup is unnamed). | D2 | ✅ |
| **38.x.a.3** | Replace the 5 silent `Err(_) => (None, &no_types)` swallows in `query` / `persist` / `mutate` / `purge` / `row_stream::drain_stream` with structured `tracing::warn!` carrying the primary error + the D-letter anchor. | D3 | ✅ |
| **38.x.a.4** | New anchor test `axon-rs/tests/fase38x_a_pooler_prepared_statement_regression.rs` — 5 §-assertions inverting in place: §1 pins the kivi 6-warmup collision corpus, §2 pins the `25P02` cascade error path, §3 pins the observability collapse, §4 pins the `.persistent(false)` invariant via a `grep` over the source tree, §5 pins the `after_release` hook installation. The grep §-assertion enforces D1 statically in CI so a future regression PR cannot land without an inversion. | D1, D3, D5 | ✅ |
| **38.x.a.5** | Extend the PgBouncer transaction-mode integration test (`axon-rs/tests/fase37x_i_pgbouncer_integration.rs`) with `t5_sequential_transactions_across_pooled_connections` — 10 transactions in series exercising `retrieve` × `persist` × `mutate` × `purge` against the SAME table through PgBouncer `pool_mode=transaction` with `DEFAULT_POOL_SIZE=2` (forces aggressive connection multiplexing). Test FAILS pre-fix with `42710`; PASSES post-fix. | D1, D2, D7 | ✅ |
| **38.x.a.6** | Coordinated patch release v1.38.0 → v1.38.1 (bumpversion patch). axon-frontend stays 0.19.0 — the Pooler-coherent Transactions Contract lives entirely in axon-rs runtime; no AST or type-checker change. axon-enterprise v1.29.1 catch-up (dep pin advance + bundles the admin migration M1 schema-namespacing fix). | — | ✅ |

# ▶ 5. The §4 grep §-assertion (D5 — static enforcement)

`axon-rs/tests/fase38x_a_pooler_prepared_statement_regression.rs` §4
runs a recursive `walk_source_tree("axon-rs/src/store")` looking for
the regex pattern `sqlx::query(?:_as)?\(` and asserts every match is
followed within ±5 lines by `.persistent(false)`. The walker has a
small allow-list (1 entry: the doc-comment example in the module-level
`//!` block). If a future PR adds a new `sqlx::query` call without
`.persistent(false)`, the test goes red.

This is the same discipline as Fase 38.b's cross-stack drift gate and
Fase 33.b's hollow-wire diagnostic: **a structural invariant becomes a
test invariant** so reviewers + CI catch the regression class
*automatically*. The bug Fase 38.x.a fixes shipped in v1.37.0 and v1.38.0
because no test pinned the invariant; that gap closes here.

# ▶ 6. What is intentionally NOT in v1.38.1

- **Simple-query mode for hot retrieve paths.** Re-preparing every
  unnamed PARSE adds ~1 round-trip vs. the cached protocol. A future
  Fase 38.x.b can opt into `Executor::execute_many` for top-of-the-loop
  hot paths IF profiling shows it matters. Today the cache-HIT path
  (which avoids the transaction entirely) is the hot path adopters land
  on after the first warmup; the cache-MISS / introspection path is
  cold by construction.

- **Per-connection counter reset.** sqlx does not expose a hook for
  this. Solving Layer A "at the source" would require an upstream sqlx
  change (PgConnection re-uses the SAME counter across acquisitions
  through a pool — there's no per-acquire reset). `.persistent(false)`
  sidesteps the counter entirely.

- **Detection of "you are behind a pooler" at runtime.** A
  diagnostic that probes the connection on first use and emits a single
  `tracing::info!` "axon detected a transaction-mode pooler at DSN
  *redacted*, prepared statement collision mitigations active" would
  be nice. Deferred to a 38.x.b follow-on; today the mitigation is
  unconditional (D4 says zero observable difference for direct-conn
  adopters).

# ▶ 7. Forward-compatibility commitments

- `PoolOptions::after_release` is a **forward** hook — composes with any
  future per-connection initialization the runtime needs (TLS
  re-negotiation, search_path stamping, etc.) WITHOUT colliding with
  the `DEALLOCATE ALL` cleanup. The hook ordering is documented inline
  so a future Fase 39.x.b that adds a second hook knows to compose
  rather than replace.
- The `.persistent(false)` invariant is grep-enforceable on EVERY new
  store-touching crate. When the planned 38.x.b ships
  `axon-rs/src/store/sqlite_backend.rs`, the same grep §-assertion
  applies (sqlite doesn't have the prepared-statement-name issue, but
  the discipline keeps the source tree uniform).
- `StoreError::Query.source` now reliably carries the Postgres error
  message; downstream test instrumentation that pattern-matches against
  the `source` field (e.g. enterprise audit-chain forensics) continues
  to work.

# ▶ 8. Relationships to other plans

- **Closes** the Layer-A-leak that Fase 36 (Backend Resolution Contract),
  Fase 37 (Request Binding Contract), Fase 37.x (Pooler-Coherent Store
  Contract), and Fase 38 (Declared & Compile-Time-Typed Store Schema)
  all assumed was already closed by v1.36.4. The 9-D-letter contract of
  37.x stands; **38.x.a fixes a leak in the contract's
  IMPLEMENTATION**, not the contract itself.
- **Bridges to** Fase 38 (the manifest-anchored compile-time half) —
  v1.38.1 makes the runtime side of 38.f's `verify_postgres_schemas_with_manifest`
  cycle equally pooler-coherent. Adopters who use `axon serve --schemas-dir`
  no longer see the warmup-collision symptom kivi reported on 2026-05-20.
- **Names** the future Fase 39 enterprise cycle: the admin migration M1
  schema-isolation fix (`public.tenants` → `axon_admin.tenants`) ships
  bundled in axon-enterprise v1.29.1 as scope of this same fix cycle.
  No new fase code needed in axon-lang.

# ▶ 9. The trigger sources (the receipts)

- 2026-05-20 11:47 UTC — kivi adopter smoke 16 logs (axon-server deploy
  output paste, 9 lines: 6 collisions + 1 cascade + 2 hint lines).
- 2026-05-20 11:48 UTC — kivi adopter handoff: "Tres cosas para llevar
  al equipo axon" enumerating REGRESIÓN crítica + Observabilidad +
  pre-existing M1 migration scope.
- Founder framing: "axon es un lenguaje para el mundo; con axon se
  deben poder crear agentes multitenant, aplicaciones, y todo tipo de
  software impulsado por LLMs. Estos detalles definitivamente debemos
  cubrirlos de forma muy amplia." → the Pooler-coherent Transactions
  Contract is the load-bearing primitive that every multitenant axon
  deploy depends on.

Closed 2026-05-20 same day as the report — the contract said it would
work, the contract has to work.
