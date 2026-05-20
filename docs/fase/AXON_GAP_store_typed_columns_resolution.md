# AXON_GAP_store_typed_columns — resolution note

> **Status:** **RESOLVED in axon-lang v1.37.0** by Fase 37.x — The
> Pooler-Coherent Store Contract.
>
> **Reporter:** kivi (early adopter), smoke iterations 13–15,
> 2026-05-18/19.
>
> **Resolved:** 2026-05-19 (sub-fases 37.x.a–37.x.j SHIPPED on `master`;
> v1.37.0 coordinated release in 37.x.k).
>
> **D-letters ratified:** D1–D9 (founder bloque, 2026-05-19).

---

## What the gap report named

A typed-column `retrieve` / `mutate` / `purge` on an `axonstore
postgresql` store, behind a transaction-mode pooler (Supabase
Supavisor `:6543`, PgBouncer `pool_mode=transaction`, Neon, RDS Proxy),
died:

```
operator does not exist: uuid = text
```

(or `text = bigint`, `<= timestamptz`, … depending on the column's
typed PK / index column).

The gap was the *sixth* iteration on the typed-column store I/O
surface — patches 1.36.1–1.36.5 each fixed a real healthy-session
defect, but the smoke chain at iterations 13–15 was the founder's cue
that the path itself was conditional on the session ("pieza de
arquitectura que necesita su propio cycle"), not another 1.36.x
hotfix.

---

## Root cause (three findings — A + B + C)

A. **`column_types()` introspected on its own `&self.pool` checkout,
   separate from the operation's checkout.** Behind a transaction-mode
   pooler the two land on different physical backends; the pooler does
   not pin one to the logical client.

B. **Introspection resolved the table via `to_regclass`, which honors
   ambient `search_path`** — a pooler-volatile per-connection GUC.
   A checkout that could not see the table → `to_regclass` NULL →
   empty type map.

C. **An empty type map made `build_pg_where` emit a bare `"col" =
   $N`** — and a request-bound equality filter on a typed PK
   (`uuid`/`int4`/`timestamptz`) dies `operator does not exist`. A
   healthy-session introspection populated the map and rendered the
   correct cast; an unhealthy-session introspection (the pooler split)
   did not.

The bug was *structural*, not a missed edge case. Five patches in
sequence fixed five surfaces, but every patch addressed a path on the
*healthy* session — they could not detect that the session itself was
the variable.

---

## What v1.37.0 ships — the contract, nine D-letters

| D-letter | Guarantee |
|---|---|
| **D1** | A store table is resolved via `pg_catalog` — `to_regclass($1)` primary + a search-path-INDEPENDENT cross-schema `relname` fallback. **Never** the ambient `search_path` |
| **D2** | Every operation's SQL is schema-qualified — `"schema"."table"`. Resolves on any session regardless of `search_path` |
| **D3** | On a cache miss, schema introspection AND the operation execute inside ONE `pool.begin()` transaction. A transaction-mode pooler pins ONE physical backend for both |
| **D4** | When the column type is genuinely unknown an equality filter falls back to `"col"::text = $N` — the column-side `::text` cast. Ordering / `LIKE` keep the bare `$N` (fail-loud — better than a silent lexicographic miscast) |
| **D5** | The contract holds symmetrically across `retrieve` / `persist` / `mutate` / `purge` / `Stream<Row>`. The four public async signatures are byte-unchanged. A direct-connection or `in_memory` path is byte-identical to v1.36.5 |
| **D6** | An unresolvable / ambiguous table is a *typed, actionable* failure — names the table, the schemas searched, the masked DSN, and the concrete remedy; structured `tracing::error!` reaches the operator's logs |
| **D7** | The CI lane `.github/workflows/fase_37x_pooler_coherent_store.yml` exercises the WHOLE contract through PgBouncer `pool_mode=transaction` on every PR + master push |
| **D8** | `POST /v1/deploy` **eagerly resolves and introspects** every declared `postgresql` store; a missing table on a reachable database FAILS the deploy. An unreachable database is a non-fatal warning |
| **D9** | The `(dsn, table)` schema cache is bounded (10 000 entries, oldest-first eviction) and **self-healing** — a cache-hit operation that fails with a schema-drift SQLSTATE (`42P01` / `42703` / `42804` / `42883`) evicts the entry and retries once against fresh introspection |

---

## How the original gap is closed end to end

Reading the gap's failing path against the new contract:

1. **Smoke-15 sends a request** binding a `uuid` value via the Fase 37
   Request Binding Contract to a `retrieve claims { where: "id =
   ${claim_id}" }`.
2. **D3** — the operation calls `cached_schema("claims")`; on a cold
   process this misses, so `pool.begin()` opens a transaction.
3. **D1** — inside that one transaction, `introspect_conn` runs
   `to_regclass('"claims"')` followed by — only on NULL — a cross-
   schema `relname` scan against `pg_catalog.pg_class`. The table is
   found in `legacy_v2`, regardless of the pooled session's
   `search_path`.
4. **D2** — the operation SQL is `SELECT * FROM "legacy_v2"."claims"
   WHERE "id" = $1::uuid`. The `::uuid` cast comes from the column-type
   map populated in step 3 — D4's `::text` fallback is only the
   degraded path; the load-bearing typed cast is here.
5. **The transaction commits.** The schema is cached in the
   process-global `(dsn, "claims")` cache.
6. **The next 20 000 retrieves** hit the cache — one round trip per
   operation, schema-qualified SQL, typed cast intact.
7. **If a live `ALTER TABLE` runs**, the first post-`ALTER` retrieve
   fails SQLSTATE 42883 (`operator does not exist`); D9 evicts the
   entry, fresh introspection runs, the retry succeeds.
8. **If `claims` is dropped** between deploys, the next `POST
   /v1/deploy` fails per D8 — the operator sees a typed deploy error
   naming the store, the masked DSN, the schemas searched, the
   actionable remedy. The failure is in CI, not production.

---

## Verifying the resolution locally

```sh
cd docs/fixtures/pgbouncer-transaction-mode
docker compose up -d

export AXON_TEST_DATABASE_URL="postgresql://axon:axon@localhost:6432/axon_store_test"
cd ../../axon-rs

# Faithful smoke-15 reproduction — what the gap report named.
cargo test --test fase37x_i_pgbouncer_integration -- --nocapture

# Broader regression corpus through the pooler.
cargo test --test fase35_l_postgres_integration -- --nocapture
cargo test --test fase37x_a_pooler_coherent_diagnostic -- --nocapture
```

All four `fase37x_i_pgbouncer_integration` tests pass:

- `t1_smoke15_uuid_pk_in_non_default_schema_canonical_agent_flow`
  — the gap's literal "retrieve ×3 → persist" agent flow on a uuid-PK
  table in a non-default schema, behind the pooler. **PASS.**
- `t2_pool_churn_two_tables_twenty_ops_all_succeed` — 20 ops across
  two tables with `default_pool_size=5` forcing multiplexing. **PASS.**
- `t3_forced_cache_miss_introspect_and_operate_pin_one_backend` —
  every iteration forces a cache miss (so D3 is exercised every
  time). **PASS.**
- `t4_d9_self_heal_after_alter_table_under_pooler` — a live `ALTER
  COLUMN … TYPE text` is recovered by D9 without restarting the
  server. **PASS.**

The CI lane `transaction-pooler-integration` in
[`fase_37x_pooler_coherent_store.yml`](../../.github/workflows/fase_37x_pooler_coherent_store.yml)
runs the same suite on every PR + master push — the permanent
regression guard.

---

## What the founder's two-question gate added

When the gap report was first triaged, the plan was strengthened
against the founder's philosophy gate:

1. **Is the solution market-standard, or superior?**
2. **Is it the minimum to run well, or robust + complete for complex
   adopters?**

The plan-vivo §9 answers both in writing. The summary:

- **Superior to market.** D1+D3+D9 together are not "the standard for
  a transaction-mode pooler" — they're the standard for a *cognitive
  data plane that must hold under one*. No other agent runtime
  guarantees pooler-coherent typed introspection + a self-healing
  bounded schema cache.
- **Robust + complete.** Every D-letter is symmetric across the 5 ops
  (D5 absolute) and visible through the CI lane (D7); the closed
  drift SQLSTATE set is the *full* parse-time read+write set
  (`42P01`/`42703`/`42804`/`42883`); the deploy-time gate (D8) closes
  the loop at the only point an operator can act.

---

## What is intentionally NOT in v1.37.0 (deferred to Fase 38)

The genuinely-superior end-state — column-type proof at **compile
time** — is committed as **Fase 38: The Declared & Compile-Time-Typed
Store Schema**.

Specifically:

- An optional `schema:` declaration on `axonstore` (incl. `schema:
  env:TENANT_SCHEMA` for per-tenant multi-schema layouts).
- An `axon check`-time column-type proof against the declared schema,
  so a `where: "id = ${claim_id}"` is type-checked against
  `claims.id: Uuid` BEFORE the runtime sees a request.
- The multi-schema remedy from §11.4 of ADOPTER_AXONSTORE.md becomes
  a declaration, not an `ALTER ROLE`.

37.x is the **runtime + deploy** half of the typed-column story;
Fase 38 is the **compile-time** half. Adopters ship 37.x today; 38 is
additive (opt-in, backwards-compatible).

---

## References

- **Plan vivo:**
  [`docs/fase/fase_37x_pooler_coherent_store.md`](fase_37x_pooler_coherent_store.md)
- **Adopter manual:**
  [`docs/ADOPTER_AXONSTORE.md`](../ADOPTER_AXONSTORE.md)
  §11.2 (the contract), §11.3 (legacy-schema recipe), §11.4 (multi-
  schema recipe), §11.5 (deploy-time verification)
- **Migration guide:**
  [`docs/MIGRATION_v1.37.md`](../MIGRATION_v1.37.md)
- **CI workflow:**
  [`.github/workflows/fase_37x_pooler_coherent_store.yml`](../../.github/workflows/fase_37x_pooler_coherent_store.yml)
- **Local repro fixture:**
  [`docs/fixtures/pgbouncer-transaction-mode/`](../fixtures/pgbouncer-transaction-mode/)
- **Diagnostic anchor:**
  [`axon-rs/tests/fase37x_a_pooler_coherent_diagnostic.rs`](../../axon-rs/tests/fase37x_a_pooler_coherent_diagnostic.rs)
- **Faithful smoke-15 reproduction:**
  [`axon-rs/tests/fase37x_i_pgbouncer_integration.rs`](../../axon-rs/tests/fase37x_i_pgbouncer_integration.rs)
- **Property/fuzz pack:**
  [`axon-rs/tests/fase37x_i_property_fuzz.rs`](../../axon-rs/tests/fase37x_i_property_fuzz.rs)
- **Trigger context:** the founder's framing at Fase 33 — "pieza de
  arquitectura que necesita su propio cycle" — applied here verbatim.

---

*Resolution authored 2026-05-19 by the AXON Language + Runtime team.
Triggered by adopter gap report `AXON_GAP_store_typed_columns` (kivi),
smoke iterations 13–15, 2026-05-18/19.*

---

## Closing — the compile-time half (v1.38.0)

The deferred compile-time end-state landed in **axon-lang v1.38.0**
as the Fase 38 cycle — *The Declared & Compile-Time-Typed Store
Schema*. Ten ratified D-letters (D1-D10), ten sub-fases (38.a-j),
five parallel CI lanes, three closed `schema:` declaration forms
(inline / manifest-ref / per-tenant env-var), seven new diagnostic
codes (T801-T807), one new CLI (`axon store introspect`), one new
flag (`axon serve --schemas-dir`).

The full v1.37.x runtime contract is now book-ended at compile time
+ deploy time:

| Layer | Surface | What v1.37.x said | What v1.38.0 adds |
|---|---|---|---|
| **Compile time** (`axon check`) | column existence + type matching in `where:` / `persist into { … }` / `mutate SET { … }` | Silent — every typo + type mismatch compiled fine | **T801** unknown column in where, **T802** type mismatch, **T803** persist NOT-NULL omission, **T804** unknown field in block. Levenshtein composite suggestions: `Did you mean column \`email\` (Text)?` |
| **Deploy time** (`POST /v1/deploy`) | declared columns vs live introspection | Silent — only table existence was proven (37.x D8) | **T805** manifest hash mismatch, **T806** missing per-tenant env var, **T807** declared-vs-live drift. The deploy fails with structured `phase: store_schema_verification` + `d_letter: D8`. |
| **Runtime** (pooled session) | typed I/O on a typed column | Works on every session (37.x D1+D3+D4) | Unchanged — D5 absolute |

**Adopter-visible surfaces:**

- **Migration guide:** [`docs/MIGRATION_v1.38.md`](../MIGRATION_v1.38.md) (6 scenarios A-F)
- **Adopter recipes:** [`docs/ADOPTER_AXONSTORE.md`](../ADOPTER_AXONSTORE.md) §17 (5 recipes)
- **Deep-dive:** [`docs/ADOPTER_TYPED_STORE.md`](../ADOPTER_TYPED_STORE.md) (the five-pillar architectural story)
- **CI workflow:** [`.github/workflows/fase_38_typed_store_schema.yml`](../../.github/workflows/fase_38_typed_store_schema.yml) (5 lanes)
- **Plan vivo:** [`docs/fase/fase_38_declared_compile_time_typed_store_schema.md`](./fase_38_declared_compile_time_typed_store_schema.md)
- **Reverse CLI:** `axon store introspect <store>` — live → manifest
- **Boot flag:** `axon serve --schemas-dir <path>` (or `AXON_SCHEMAS_DIR=<path>`)

A v1.37.x adopter who never adopts Fase 38's compile-time schema
observes ZERO behavior change — **D5 absolute** is preserved at the
boot flag, at the manifest-load surface, at the verify call.
TypedColumn is opt-in by store, by directory, by deploy.

*Compile-time half closed 2026-05-20 by axon-lang v1.38.0. The
typed-column store's SHAPE is now a declared, verifiable, compile-
time-proven property — completing the contract whose runtime half
v1.37.x established.*
