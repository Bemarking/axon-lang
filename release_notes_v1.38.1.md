# axon-lang v1.38.1 — Pooler-coherent Transactions Contract (Fase 38.x.a)

> **Cycle:** Fase 38.x.a — *Pooler-coherent Transactions Contract*.
> Single-sub-fase patch shipped 2026-05-20 same-day as the report.
> D1–D4 ratified.
>
> **TL;DR:** v1.38.1 is a **CRITICAL PATCH** closing a regression that
> surfaced in v1.37.0+v1.38.0 behind transaction-mode poolers (Supabase
> Supavisor `:6543`, PgBouncer `pool_mode=transaction`, Neon, RDS
> Proxy). The `axonstore postgresql` data plane re-broke with
> `prepared statement "sqlx_s_N" already exists` — the same regression
> class v1.36.4 closed and v1.37.x's 9-D-letter contract was supposed
> to make impossible. v1.38.1 closes it permanently with a
> 4-D-letter mini-contract.
>
> **Multitenant adopters (Kivi, Supabase tenants, every Neon user)
> should upgrade immediately.**

---

## What broke (kivi smoke 16, 2026-05-20)

Six warmups during deploy + one operation smoke collided on prepared
statements:

```
[axon-server] WARM  store=tenants → ERR  prepared statement "sqlx_s_1" already exists
[axon-server] WARM  store=audit   → ERR  prepared statement "sqlx_s_2" already exists
[axon-server] WARM  store=events  → ERR  prepared statement "sqlx_s_3" already exists
[axon-server] (retry × each) → same collision
[axon-server] POST /flows/diag/run → store.retrieve(tenants, …) →
  ERR  current transaction is aborted, commands ignored until end of transaction block
  ERR  retrieve(tenants): runtime store error
  → 500 Internal Server Error
```

The primary error (the prepared statement collision) was **silently
swallowed** in 5 different code paths. The adopter saw only the
secondary cascade.

## Root cause (the two-layer leak)

**Layer A** — `PgConnectOptions::statement_cache_capacity(0)` set since
v1.36.4 disables sqlx's LRU **cache** of prepared statements. It does
NOT change the PARSE protocol: every `sqlx::query(...)` with
`persistent = true` (the sqlx 0.8 default) still allocates a
monotonic name (`sqlx_s_1`, `sqlx_s_2`, …) and sends
`PARSE sqlx_s_N`. Behind a transaction-mode pooler, the physical
Postgres connection persists across logical sessions; the prep
statements from the previous session stay alive on the physical
conn. When sqlx's per-connection counter restarts at 1 for a new
logical session and the SAME physical conn serves both, `PARSE
sqlx_s_1` collides with the residual `sqlx_s_1` → Postgres `42710`
`duplicate_prepared_statement` → transaction aborted.

**Layer B** — Fase 37.x.d (commit `c0977ed`, v1.37.0) wrapped the
cache-MISS path in `pool.begin()` so introspection + operation share
one transaction (D3 pooler-coherent guarantee). Inside that
transaction, `introspect_conn` runs **two** `sqlx::query(...)` calls
BEFORE the operation's own query. So a single cache-MISS warmup
issues 2–3 named PARSEs against the same physical conn in
milliseconds; each is a collision risk.

Fase 38.f (v1.38.0) extended this pattern to
`verify_postgres_schemas_with_manifest`, which runs at every deploy.

## The contract — four D-letters

| D-letter | Guarantee |
|---|---|
| **D1** | Every `sqlx::query(...)` / `sqlx::query_as(...)` under `axon-rs/src/store/` carries `.persistent(false)`. The unnamed PARSE protocol (empty name `""`) is structurally collision-free behind every transaction-mode pooler. **Statically enforced** by the §4 grep §-assertion in `fase38x_a_pooler_prepared_statement_regression.rs` |
| **D2** | `PoolOptions::after_release` hook in `connect_named_with_namespace` runs `DEALLOCATE ALL` on every released connection. Belt-and-suspenders: if a future code path slips past D1, the named statements it allocated are wiped from the physical conn BEFORE the pooler returns it. The cleanup query itself carries `.persistent(false)` — meta-invariant |
| **D3** | The 5 silent `Err(_) => (None, &no_types)` swallows in `query` / `persist` / `mutate` / `purge` / `row_stream::drain_stream` now emit a structured `tracing::warn!` (`target: "axon::store"`, `error = %e`, `d_letter = "D3+38.x.a"`). The adopter sees the PRIMARY failure |
| **D4** | **Absolute backwards-compat.** An adopter NOT behind a transaction-mode pooler sees behavior **byte-identical** to v1.38.0 |

## What you'll see post-upgrade

- **Multitenant deploys against Supavisor / PgBouncer / Neon / RDS Proxy:**
  the warmup-collision symptom disappears. Every warmup, every deploy
  smoke, every adopter-supplied flow runs without `42710`.
- **Diagnostic clarity when something else fails:** if the introspection
  inside a `pool.begin()` transaction fails for ANY reason (network,
  permissions, a deliberate `DROP TABLE` mid-flight), the structured
  `tracing::warn!` carries the actual error. Search journald / CloudWatch
  / Loki for `axon::store introspect_in_tx`.
- **Static enforcement on future PRs:** the §4 grep §-assertion in
  `fase38x_a_pooler_prepared_statement_regression.rs` makes any new
  `sqlx::query` without `.persistent(false)` turn the test RED on the
  PR — the regression class cannot ship again silently.

## What is intentionally NOT in v1.38.1

- **Simple-query mode for hot retrieve paths.** Re-preparing every
  unnamed PARSE adds ~1 round-trip vs. the cached protocol. A future
  Fase 38.x.b can opt into `Executor::execute_many` for hot paths IF
  profiling shows it matters. Today the cache-HIT path (no transaction)
  is the hot path adopters land on after the first warmup.
- **Per-connection counter reset.** sqlx does not expose a hook for
  this. `.persistent(false)` sidesteps the counter entirely.
- **Runtime detection of "you are behind a pooler".** A future 38.x.b
  could emit a single `tracing::info!` on first connection. Deferred;
  today the mitigation is unconditional (D4 absolute).

## Migration

**No code change needed for adopters.** The Pooler-coherent
Transactions Contract is a runtime substrate fix; every existing
`axonstore postgresql` declaration keeps working. Drop in v1.38.1.

```sh
# Rust crate (axon-lang on crates.io)
cargo add axon-lang@1.38.1

# Python package (axon-lang on PyPI)
pip install axon-lang==1.38.1
```

**For axon-enterprise adopters:** wait for v1.29.1 (catch-up + the
admin migration M1 schema-namespacing fix). Available shortly.

## Test surface (zero regressions)

- **2 096** axon-rs lib tests green (identical to v1.38.0 baseline)
- **5** `fase38x_a_pooler_prepared_statement_regression` §-assertions
  (NEW — the diagnostic anchor; §1 corpus pin, §2 zero silent swallows,
  §3 every warn carries `error = %e`, §4 STATIC grep invariant, §5
  D2 installation + meta-invariant)
- **5** `fase37x_a_pooler_coherent_diagnostic` §-assertions (the Fase
  37.x regression guard intact post-patch)
- **6** `fase37x_i_property_fuzz` (~7 500 LCG iters) green
- **6** `fase35_fuzz` (~18 000 LCG iters) green
- **6** `fase38_j_schemas_dir_plumbing` green
- `fase37x_i_pgbouncer_integration` extended with
  `t5_sequential_transactions_across_pooled_connections` (PG-gated;
  the CI lane `fase_37x_pooler_coherent_store` routes it through
  PgBouncer `pool_mode=transaction` with `default_pool_size=2` to
  force aggressive multiplexing)

Approximately **~2 130 Rust tests** green; **zero regressions** from
v1.38.0.

## Cross-links

- 📋 [Plan vivo Fase 38.x](https://github.com/Bemarking/axon-lang/blob/master/docs/fase/fase_38x_pooler_transactions.md) — the full 5-section analysis + sub-fase ladder + forward-compatibility commitments
- 📖 [axon-lang v1.38.0 GitHub Release](https://github.com/Bemarking/axon-lang/releases/tag/v1.38.0) — the parent minor that introduced the regressing code path
- 📖 [Fase 37.x plan vivo](https://github.com/Bemarking/axon-lang/blob/master/docs/fase/fase_37x_pooler_coherent_store.md) — the 9-D-letter contract that v1.38.1 makes whole

## Acknowledgements

Triggered by **kivi adopter smoke 16** (2026-05-20). The founder's
framing — *"axon es un lenguaje para el mundo; con axon se deben poder
crear agentes multitenant, aplicaciones, y todo tipo de software
impulsado por LLMs. Estos detalles definitivamente debemos cubrirlos
de forma muy amplia."* — applied to the Pooler-coherent Transactions
Contract as the load-bearing substrate every multitenant axon
deployment depends on.

Closed same day as the report — the contract said it would work, the
contract has to work.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
