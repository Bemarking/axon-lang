# AXON Migration Guide — v1.36.x → v1.37.0

> **Scope:** the Fase 37.x *Pooler-Coherent Store Contract* cycle
> introduced in v1.37.0. Adopters upgrading from v1.36.x read this doc
> to decide which migration scenario applies + execute the recipe.
>
> **TL;DR:** v1.37.0 makes the `axonstore postgresql` data plane
> **unconditionally pooler-coherent**. The five patches 1.36.1–1.36.5
> each closed a real healthy-session defect but none addressed the
> deeper problem — column-type introspection ran on a *different*
> pooled connection than the operation it typed. v1.37.0 closes that
> permanently: D1 search-path-independent resolution via `pg_catalog`,
> D2 schema-qualified SQL, D3 one coherent introspect-and-operate
> transaction, D4 type-agnostic equality fallback, D8 eager deploy-time
> schema verification, D9 self-healing bounded LRU cache. **A typed-
> column read/write that previously needed a lucky session now succeeds
> every time, on every pooled session, behind every transaction-mode
> pooler.** Backwards-compatible by design (**D5 absolute**) — a flow
> on a direct connection or against an in-memory store is byte-
> identical to v1.36.x.

---

## What changed in v1.37.0

| Surface | v1.36.x | v1.37.0 |
|---|---|---|
| Behind a transaction-mode pooler, a typed-column `where:` value on a `retrieve`/`mutate`/`purge` | Sometimes died `operator does not exist: uuid = text` — column-type introspection landed on a different pooled session than the operation; the type map was empty, so the value-side cast (`$N::uuid`) never rendered (D1+D3) | Always works — introspection + operation execute inside ONE `pool.begin()` transaction (D3), the table resolves via `pg_catalog` (D1) so `search_path` is irrelevant, the SQL is schema-qualified (D2), and the typed cast renders (D4) |
| A store table living in a non-default-`search_path` schema | Resolved iff `to_regclass` could see it via the session's `search_path` — pooler-dependent | Resolved via `pg_catalog` (`to_regclass` primary + cross-schema `relname` fallback) regardless of `search_path` (D1) |
| An equality filter on a column whose type genuinely cannot be introspected | Bare `$N` — died `uuid = text` on a typed column | Falls back to `"col"::text = $N` (D4) — uniform-type comparison; ordering / `LIKE` keep the bare `$N` (fail-loud — better than a lexicographic miscast) |
| A live `ALTER TABLE` against a cached table | The cached schema went stale; subsequent operations failed with a drift SQLSTATE forever | **Self-heals** (D9) — the cache evicts on the first drift, fresh introspection runs, the operation retries once and succeeds. Bounded capacity (10 000 `(dsn, table)` entries, oldest-first eviction) |
| An unresolvable `postgresql` store table | Discovered only at the first runtime operation that hit it | Discovered at **deploy** (D8) — `POST /v1/deploy` eagerly resolves every declared `postgresql` store; a missing table on a reachable database FAILS the deploy. An unreachable database is a non-fatal warning |
| An unresolved / ambiguous table error | A generic SQL error from Postgres | A *typed, actionable* axon error (D6) — names the table, the schemas searched, the masked DSN, the concrete remedy; a structured `tracing::error!` lands in your logs |
| Every direct-connection use of `axonstore postgresql` + every `in_memory` flow + every public async signature | Established | **Byte-identical** (D5) |

---

## The intended behavior changes

Three, each a direct consequence of closing the gap:

1. **A typed-column store I/O behind a transaction-mode pooler now
   works on every session.** In v1.36.x a typical Supabase / Supavisor
   / RDS-Proxy / Neon deployment that hit a typed primary key (`uuid`,
   `int`, `timestamptz`) had a *non-deterministic* fail mode: the
   introspection might land on a pooled session that could see the
   table, or it might not. v1.37.0 makes the path deterministic: the
   introspection + operation share ONE backend, and the table is
   resolved via `pg_catalog` regardless. **If a v1.36.x adopter has a
   smoke test that occasionally fails behind a pooler, v1.37.0 fixes
   it.**

2. **An unresolvable table is a deploy-time failure, not a request-
   time failure.** Per D8, `POST /v1/deploy` now resolves every
   declared `postgresql` store; a missing table on a reachable
   database FAILS the deploy with a structured error naming the
   store, the masked DSN, and the actionable remedy. **The failure
   moves from production to CI.**

3. **A live `ALTER TABLE` self-heals.** Per D9, the schema cache
   evicts on the first drift SQLSTATE and re-introspects on the
   retry. **An adopter who ships a column-type migration to a long-
   running axon server no longer has to restart the server.**

No adopter with a *working* v1.36.x setup regresses. `D5 absolute`: a
flow on a direct connection, an `in_memory` store, every public async
signature — byte-identical. The intended changes convert silent
session-dependent failures into deterministic success, OR into honest
deploy-time errors.

---

## Migration scenarios

### Scenario A — you use `backend: in_memory` only

**v1.37.0:** nothing changes. The Pooler-Coherent Store Contract is
the `postgresql` substrate; the in-memory path is untouched.

**Action:** none.

### Scenario B — you use `backend: postgresql` on a direct connection

**v1.37.0:** byte-identical for a healthy direct session. The
introspection/operation split that v1.37.0 closes does not manifest on
a direct connection — D5 is absolute.

**Action:** none — but you can drop in v1.37.0 confident that future
operational moves (a migration to a managed Postgres with a built-in
pooler, a tenant-per-schema rollout) will be safe.

### Scenario C — you use `backend: postgresql` behind a transaction-mode pooler

**Pre-v1.37 (especially after the patch chain 1.36.1–1.36.5):** a
typed-column store I/O succeeded *sometimes* — when the introspection
happened to land on a pooled session that could see the table. A
smoke test that "passes on a laptop, fails in staging" was the canon-
ical signature.

**v1.37.0:** works on every session. The contract:

- **D1** resolves the table via `pg_catalog`, not `search_path`;
- **D2** emits schema-qualified `"schema"."table"`;
- **D3** binds introspection + operation to one `pool.begin()`
  transaction (pooler pins one backend);
- **D4** falls back to `"col"::text = $N` for an unknown-type
  equality;
- **D9** self-heals a drifted cache.

**Action:** upgrade to v1.37.0. The five patches 1.36.1–1.36.5 are
subsumed; you do not need their workarounds. Any
`SET search_path = …` boilerplate you added in 2026 to avoid the bug
can be deleted.

### Scenario D — you have tables in non-default-`search_path` schemas

**Pre-v1.37:** worked only if your session's `search_path` happened to
include the schema (and a transaction-mode pooler does not preserve
session-local `SET search_path` across checkouts, which made this
unreliable). The classic workaround: `ALTER ROLE app SET search_path
= …`.

**v1.37.0:** the table is resolved via `pg_catalog` across every
non-system schema this role can see, regardless of `search_path`. The
generated SQL is schema-qualified — `"legacy_v2"."claims"`, not bare
`"claims"`.

**Action:** none. The `ALTER ROLE` is no longer load-bearing — keep
it if it serves other purposes (e.g. a separate ORM in the same
process), drop it if it only existed to work around the axonstore
bug.

### Scenario E — you have the SAME table name in multiple schemas

**Pre-v1.37:** silently picked one (whichever the session's
`search_path` found first) — non-deterministic behind a pooler.

**v1.37.0:** detected as an *ambiguous* table and FAILS with a typed
`StoreError::AmbiguousTable` naming both schemas. The error names
two concrete remedies: narrow the role's `search_path`, or declare
the target schema on the `axonstore` (the Fase 38 `schema:`
declaration, the multi-schema compile-time-typed companion).

**Action:**

- Either **narrow `search_path`** for the role at the database side
  so exactly one of the resolving schemas is visible (`ALTER ROLE
  app SET search_path = prod`).
- **Wait for Fase 38** (the compile-time-typed schema companion to
  37.x) to declare `schema: "prod"` (or `schema: env:TENANT_SCHEMA`)
  directly on the `axonstore`.

A previously-passing v1.36.x deployment that *silently* picked the
wrong schema is also caught here — that is the bug surfacing
honestly.

### Scenario F — your deploy now fails with `phase: store_schema_verification`

```text
POST /v1/deploy → 400
{
  "error": "deploy-time store-schema verification failed: 1 declared
            postgresql store table(s) do not resolve on a reachable
            database: `claims` — axonstore could not resolve table
            `claims` to a relation in any schema of the database — …",
  "phase": "store_schema_verification",
  "d_letter": "D8"
}
```

**Cause:** a declared `postgresql` store's table is missing on a
*reachable* database — pre-v1.37 this would have surfaced at the first
production request that hit that store. v1.37.0 moves the failure
forward, to the deploy.

**Action — pick one:**

- Run the schema migration that creates the table (the usual
  remedy).
- Confirm the credential in `connection:` has `SELECT` permission on
  the schema and table (the `pg_catalog` scan only sees relations
  this role can see).
- If the store is intentionally optional + the database is
  intentionally unreachable at deploy time, switch the store's
  `backend:` accordingly — an *unreachable* database at deploy is a
  non-fatal warning (the deploy proceeds), but an unresolvable table
  on a reachable database is fatal by design.

### Scenario G — you orchestrate live column-type migrations

**Pre-v1.37:** an `ALTER TABLE … ALTER COLUMN x TYPE …` against a
long-running axon server invalidated the schema cache silently;
subsequent operations failed `uuid = text` (or similar) forever
without a restart.

**v1.37.0:** **self-healing**, per D9. The first failed operation
after the `ALTER` evicts the `(dsn, table)` cache entry, fresh
introspection runs, the retry succeeds. Bounded — the cache caps at
10 000 entries with oldest-first eviction.

**Action:** none. Your live-migration runbooks can drop any axon-
server-restart step.

---

## What does NOT change (D5 absolute)

- A flow on `backend: in_memory` — byte-identical.
- A flow on `backend: postgresql` against a direct (non-pooled)
  Postgres connection that was already healthy — byte-identical.
- The four public async signatures of `query` / `insert` / `mutate` /
  `purge` and `row_stream::stream_retrieve` — byte-identical.
- The pre-37 SQL shape for a healthy session (`SELECT * FROM
  "table" WHERE "col" = $1::uuid`) is now `SELECT * FROM
  "schema"."table" WHERE "col" = $1::uuid` — a schema prefix added,
  identical behavior. (Pre-1.36.4 SQL with NO type cast is the
  unhealthy-session shape v1.37.0 closes.)
- `POST /v1/execute`, every Fase 30–36 wire body — unchanged.
- The `axonstore` declaration grammar — unchanged. `connection:`,
  `confidence_floor:`, `on_breach:`, `capability:`, `isolation:` —
  all carry the same meaning. (The Fase 38 `schema:` declaration is
  a future, opt-in addition.)
- The four pillars (Epistemic, Audit-chained, Streaming, Capability)
  — unchanged. The Pooler-Coherent Store Contract enriches the
  *substrate*; the pillars layer on it untouched.

---

## What's coming in Fase 38

Fase 37.x is the **runtime + deploy** half of the typed-column store
story. Fase 38 — *The Declared & Compile-Time-Typed Store Schema* — is
the **compile-time** half:

- An optional `schema:` declaration on `axonstore` (incl.
  `schema: env:TENANT_SCHEMA` for per-tenant multi-schema layouts).
- `axon check`-time column-type proof against the declared schema, so
  a `where: "id = ${claim_id}"` is type-checked against
  `claims.id: Uuid` *before* the runtime sees a request.
- The ambiguous-table remedy of v1.37.4 (Scenario E above) becomes a
  declaration: `schema: "prod"` — no `ALTER ROLE` required.

Adopters can ship 37.x today; Fase 38 is additive (opt-in, backwards-
compatible).

---

## Upgrade checklist

- [ ] Upgrade to `axon-lang` v1.37.0 (`pip` / `cargo`). No grammar
      change — your `.axon` sources do not need edits.
- [ ] Re-run `axon check`. (No new compile error from 37.x — the
      contract is runtime + deploy.)
- [ ] Re-deploy. Any `phase: store_schema_verification` failure is
      Scenario F — address the underlying missing table / missing
      grant, re-deploy.
- [ ] Run your smoke tests behind your production pooler — the
      typed-column path should now be deterministic. If a smoke test
      that intermittently failed on v1.36.x continues to fail on
      v1.37.0, file an issue at the axon-lang repository with the
      pooler topology + the typed-column shape.
- [ ] If your runbooks include "restart axon-server after a column-
      type migration" — that step can come out (Scenario G).
- [ ] If you maintain an `ALTER ROLE … SET search_path` purely to
      work around the v1.36.x table-resolution issue (Scenario D), it
      can come out.

---

## How to reproduce the pre-37 failure locally (educational)

The fixture in
[`docs/fixtures/pgbouncer-transaction-mode/`](fixtures/pgbouncer-transaction-mode/)
brings up Postgres 16 + PgBouncer `pool_mode=transaction` with
`default_pool_size=5` ≪ the parallel test count, so cross-session
multiplexing is forced. Read its `README.md` for the `up -d` recipe
and the cargo invocations. The CI workflow
[`.github/workflows/fase_37x_pooler_coherent_store.yml`](../.github/workflows/fase_37x_pooler_coherent_store.yml)
exercises this stack on every PR + master push.

---

*Fase 37.x — The Pooler-Coherent Store Contract. D1–D9 ratified
2026-05-19. Full reference:
[`docs/fase/fase_37x_pooler_coherent_store.md`](fase/fase_37x_pooler_coherent_store.md).
Adopter manual: [`docs/ADOPTER_AXONSTORE.md`](ADOPTER_AXONSTORE.md)
§11.2–§11.5. Resolves
[`AXON_GAP_store_typed_columns`](fase/AXON_GAP_store_typed_columns_resolution.md)
(kivi, smoke iterations 13–15, 2026-05-18/19).*
