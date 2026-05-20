# AXON Adopter Guide — `axonstore`, the Cognitive Data Plane

> **Audience:** engineers building AI applications and agents on
> axon-lang who need **persistent data** — an agent's memory, a
> tenant table, an event log, a knowledge store.
>
> **Scope:** the full Fase 35 surface introduced in axon-lang
> **v1.30.0**. A `axonstore` declaration with `backend: postgresql`
> now executes **real SQL** against the declared database — and that
> SQL store is not a plain table. It is a **cognitive data plane**: a
> relation enriched in four orthogonal dimensions the relational model
> never carried.
>
> **Founder principle:** *the `axonstore` declaration is a cognitive
> contract — the runtime honors every field.* `confidence_floor`,
> `on_breach`, `capability` are not decoration; each one means
> something the moment you write it.

---

## Table of Contents

1. [What changed in v1.30.0](#1-what-changed-in-v1300)
2. [Your first axonstore](#2-your-first-axonstore)
3. [The `axonstore` declaration — every field](#3-the-axonstore-declaration--every-field)
4. [The four store operations](#4-the-four-store-operations)
5. [The `where` grammar](#5-the-where-grammar)
6. [Pillar I — the epistemic data plane (`confidence_floor`)](#6-pillar-i--the-epistemic-data-plane-confidence_floor)
7. [Pillar II — audit-chained mutations (`on_breach`)](#7-pillar-ii--audit-chained-mutations-on_breach)
8. [Pillar III — `retrieve` is a `Stream<Row>`](#8-pillar-iii--retrieve-is-a-streamrow)
9. [Pillar IV — capability-typed access (`capability`)](#9-pillar-iv--capability-typed-access-capability)
10. [The `in_memory` backend](#10-the-in_memory-backend)
11. [Connecting to Postgres](#11-connecting-to-postgres)
    - [11.1 Transaction-mode poolers (v1.36.3+)](#111-transaction-mode-poolers--works-out-of-the-box-v1363)
    - [11.2 The Pooler-Coherent Store Contract (v1.37.0+)](#112-the-pooler-coherent-store-contract-v1370)
    - [11.3 Recipe — legacy-schema table](#113-recipe--a-table-living-behind-a-legacy-schema)
    - [11.4 Recipe — multi-schema same-name table (D6)](#114-recipe--a-same-name-table-in-multiple-schemas-d6)
    - [11.5 Recipe — deploy-time verification (D8)](#115-recipe--deploy-time-store-schema-verification-d8)
12. [Honest scope boundaries (v1.30.0)](#12-honest-scope-boundaries-v1300)
13. [Production checklist](#13-production-checklist)
14. [Troubleshooting](#14-troubleshooting)
15. [Where to file bugs](#15-where-to-file-bugs)
16. [Streaming the agent pattern (v1.35.0)](#16-streaming-the-agent-pattern-v1350)
17. [The Compile-Time-Typed Store Schema (v1.38.0)](#17-the-compile-time-typed-store-schema-v1380)
    - [17.1 Recipe — form (a) inline `schema:` block](#171-recipe--form-a-inline-schema-block)
    - [17.2 Recipe — form (b) manifest reference](#172-recipe--form-b-manifest-reference)
    - [17.3 Recipe — form (c) per-tenant `schema: env:VAR`](#173-recipe--form-c-per-tenant-schema-envvar)
    - [17.4 Recipe — `axon store introspect` for a live database](#174-recipe--axon-store-introspect-for-a-live-database)
    - [17.5 Recipe — wiring `--schemas-dir` on production `axon serve`](#175-recipe--wiring---schemas-dir-on-production-axon-serve)

---

## 1. What changed in v1.30.0

Before v1.30.0 the Rust runtime **ignored** `backend: postgresql` on an
`axonstore`. Every `persist` / `retrieve` / `mutate` / `purge` went to
an in-process key-value store regardless of what the declaration said.
The `confidence_floor` and `on_breach` fields the language designers
placed on `IRAxonStore` were inert.

v1.30.0 makes the declaration real. A `postgresql`-backed `axonstore`
executes parameterized SQL against the declared database — on **both**
execution paths (the streaming dispatcher and the synchronous runner),
identically. And it is not a faithful ORM port. The reframe: an
`axonstore` is a `Relation` enriched in **four orthogonal dimensions**,
each by joining an axon system that already exists:

| Pillar | Enrichment | The field |
|---|---|---|
| **I — Epistemic** | every retrieved row is born *untrusted*; sub-confidence rows are filtered | `confidence_floor` |
| **II — Audit-chained** | every mutation appends to a tamper-evident HMAC-Merkle log | `on_breach` |
| **III — Streaming** | `retrieve` is a lazy, backpressured `Stream<Row>` — large reads never OOM | (automatic) |
| **IV — Capability-typed** | store access requires a capability the type-checker enforces | `capability` |

No other language can offer this — not because of cleverness, but
because no other language has an epistemic lattice, an algebraic-effect
streaming runtime, an audit-chain primitive, and capability types to
*enrich a relation with*.

**Backwards compatibility (absolute):** a flow that uses only
in-memory / undeclared stores behaves **byte-identically** to pre-1.30.
The SQL path is entered *only* when a matching `axonstore` declares
`backend: postgresql`.

---

## 2. Your first axonstore

```axon
axonstore tenants {
    backend: postgresql
    connection: "env:DATABASE_URL"
}

flow OnboardTenant() -> Unit {
    let tenant_id = "acme-001"
    let plan = "enterprise"
    persist tenants
}

flow ListEnterprise() -> Unit {
    retrieve tenants { where: "plan = 'enterprise'" as: result }
}
```

- `persist tenants` writes the flow's current bindings (`tenant_id`,
  `plan`) as a row into the `tenants` table.
- `retrieve tenants { where: … }` runs a parameterized
  `SELECT * FROM "tenants" WHERE "plan" = $1` and binds the result
  under `result`.

The `tenants` table must already exist in your database — v1.30.0
operates against **existing tables** (see [§12](#12-honest-scope-boundaries-v1300)).

---

## 3. The `axonstore` declaration — every field

```axon
axonstore <Name> {
    backend:          postgresql          // {in_memory | postgresql}
    connection:       "env:DATABASE_URL"   // env:VAR or a literal DSN
    confidence_floor: 0.8                  // Pillar I — optional, [0.0, 1.0]
    isolation:        serializable         // {read_committed | repeatable_read | serializable}
    on_breach:        raise                // Pillar II — {log | raise | rollback}
    capability:       "tenant.read"        // Pillar IV — optional capability slug
}
```

| Field | Required | Meaning |
|---|---|---|
| `backend` | no (default `in_memory`) | The closed catalog is `{in_memory, postgresql}`. An empty / absent `backend` is `in_memory`. `sqlite` and `mysql` are **rejected at deploy** — they are a documented future fase. |
| `connection` | for `postgresql` | `"env:VAR"` resolves environment variable `VAR`; any other value is a literal DSN. Ignored by `in_memory`. |
| `confidence_floor` | no | Pillar I — the minimum epistemic confidence a row must carry. `[0.0, 1.0]`. See [§6](#6-pillar-i--the-epistemic-data-plane-confidence_floor). |
| `isolation` | no | Declared transaction isolation. Carried for forward-compatibility; v1.30.0 runs each op single-statement autocommit (see [§12](#12-honest-scope-boundaries-v1300)). |
| `on_breach` | no (default `log`) | Pillar II — the policy fired when audit-chain verification detects tampering. See [§7](#7-pillar-ii--audit-chained-mutations-on_breach). |
| `capability` | no | Pillar IV — the capability slug a flow must hold to access this store. See [§9](#9-pillar-iv--capability-typed-access-capability). |

The store **name** is the **SQL table name**. `axonstore tenants { … }`
operates on the table `tenants`.

---

## 4. The four store operations

| Operation | Syntax | SQL |
|---|---|---|
| **persist** | `persist [into] <store> { col: value … }` | `INSERT` — writes exactly the declared columns |
| **retrieve** | `retrieve <store> { where: "<expr>" as: <alias> }` | `SELECT * … WHERE <expr>` |
| **mutate** | `mutate <store> { where: "<expr>" col: value … }` | `UPDATE … SET <cols> WHERE <expr>` |
| **purge** | `purge <store> { where: "<expr>" }` | `DELETE … WHERE <expr>` |

- **`persist`** (v1.31.0+) takes a `{ col: value }` field block —
  the `INSERT` writes **exactly** the declared columns, with each
  value expression interpolated against the flow context (see
  [§4.1](#41-the-persist-field-block-v1310)). The optional `into`
  connector reads as documentation: `persist into chat { … }` ≡
  `persist chat { … }`.
- **`mutate`** (v1.32.0+) takes the same `{ col: value }` block —
  alongside `where:`, every other key is a `SET` assignment; the
  `UPDATE` SETs **exactly** the declared columns (see
  [§4.2](#42-the-mutate-set-block-v1320)).
- **`retrieve`** binds its result under the `as:` alias.
- A `mutate` / `purge` **without** a `{ where: }` block operates on the
  **whole store** (the runtime renders `WHERE TRUE`). Always write a
  `where:` clause unless you mean *every row*.

---

## 4.1 The `persist` field block (v1.31.0+)

A `persist` step declares the columns it writes as a `{ col: value }`
block:

```axon
flow ChatFlow(message, session_id, tenant_id, channel_kind) -> Unit {
    step GenerateResponse { ask: "reply to ${message}" }
    persist into chat_history {
        session_id: "${session_id}"
        sender:     "user"
        content:    "${message}"
        tenant_id:  "${tenant_id}"
    }
}
```

This compiles to `INSERT INTO chat_history (session_id, sender,
content, tenant_id) VALUES ($1, $2, $3, $4)` — **exactly** the four
declared columns. Every other binding the flow holds (`channel_kind`,
the `GenerateResponse` step result, …) is ignored.

- **Interpolation is `${name}` / `$name`** — the same syntax used
  everywhere else in axon. `"${session_id}"` substitutes the flow
  binding `session_id`. A literal value (`sender: "user"`) needs no
  `$`. (Note: `{{double-brace}}` is **not** axon interpolation — it is
  left literal.)
- **Column names** are the keys of the block; they must exist on the
  target table (v1.31.0 has no DDL — see [§12](#12-honest-scope-boundaries-v1300)).
- **No block ⇒ the v1.30.0 fallback.** A bare `persist <store>` (no
  `{ }`) still writes every user binding as a row — backward-compatible,
  but it fails against any table whose columns do not exactly match the
  flow's bindings. **Always declare a field block for a real table.**
- The `in_memory` backend snapshots flow state as key-value entries and
  is unaffected by the field block (it has no columns).

> Before v1.31.0 the `persist` block was parsed but **silently
> dropped**; the runtime wrote every binding, so `INSERT` failed on any
> flow with more bindings than the table has columns. v1.31.0 closes
> that gap — see [`docs/MIGRATION_v1.31.md`](MIGRATION_v1.31.md).

---

## 4.2 The `mutate` SET block (v1.32.0+)

A `mutate` step declares its `SET` assignments the same way `persist`
declares its columns — the block carries `where:` (the filter) plus
one `col: value` entry per column to update:

```axon
flow AdjustBalance(account_id, new_balance, tenant_id) -> Unit {
    mutate accounts {
        where:   "id = ${account_id}"
        balance: "${new_balance}"
        status:  "active"
    }
}
```

This compiles to `UPDATE accounts SET "balance" = $1, "status" = $2
WHERE id = $3` — **exactly** the two declared `SET` columns. Every
other binding the flow holds (`tenant_id`, `account_id`) stays out of
the `SET`.

- `where:` keeps its string-literal grammar ([§5](#5-the-where-grammar));
  every **other** key in the block is a `SET` column.
- Value interpolation is `${name}` / `$name` — exactly as for `persist`
  ([§4.1](#41-the-persist-field-block-v1310)).
- **No SET column ⇒ the v1.31.0 fallback.** A `mutate <store>
  { where: … }` with no `col:` entry still SETs every user binding —
  backward-compatible, but it fails against any table whose columns do
  not exactly match the flow's bindings. **Always declare the SET
  columns for a real table.**
- The `in_memory` backend is unaffected by the SET block (no columns).

> Before v1.32.0 the `mutate` block captured only `where:` and skipped
> every other key — the runtime built the `UPDATE … SET` from every
> flow binding, so it failed on any flow carrying a binding that is not
> a column. v1.32.0 closes that gap symmetrically to the v1.31.0
> `persist` fix — see [`docs/MIGRATION_v1.32.md`](MIGRATION_v1.32.md).

---

## 5. The `where` grammar

A `where` expression is a flat list of conditions joined by `AND` / `OR`:

```
where     := condition (connector condition)*
condition := column operator value
column    := [A-Za-z_][A-Za-z0-9_]*          (ASCII, ≤ 63 bytes)
operator  := = | == | != | <> | > | >= | < | <= | LIKE
connector := AND | OR                         (case-insensitive)
value     := 'string' | "string" | number | true | false | null
```

Examples:

```axon
retrieve accounts { where: "balance >= 1000 AND status = 'active'" }
retrieve events   { where: "created_at != null OR priority LIKE 'urgent%'" }
purge    sessions { where: "expired = true" }
```

**Injection-proof by construction (D4).** Every value compiles to a
`$N` bind placeholder; every column is double-quoted. A value like
`'; DROP TABLE accounts; --'` is bound as a harmless string parameter —
it can never reach SQL as code. There is no code path that interpolates
a user value into SQL text.

- `column = null` renders `"column" IS NULL`; `column != null` renders
  `"column" IS NOT NULL`. Ordering / `LIKE` against `null` is a compile
  error.
- Operator precedence is SQL's native precedence (`AND` binds tighter
  than `OR`). Parenthesised grouping is a documented future extension.
- An **empty** `where` matches every row.

---

## 6. Pillar I — the epistemic data plane (`confidence_floor`)

A retrieved row is **not a fact — it is a claim.** Every row from
`retrieve` is born `untrusted` (⊥) in axon's epistemic lattice; a
downstream `shield` / reasoning step must elevate it before it is
trusted.

`retrieve` therefore returns an **epistemic envelope**, not a bare row
array:

```json
{
  "taint": "untrusted",
  "confidence_floor": 0.8,
  "trusted_rows": 3,
  "below_floor_filtered": 1,
  "rows": [ { … }, … ],
  "stream": { … }
}
```

**`confidence_floor` enforcement.** When a store declares
`confidence_floor: f`, each row carries its stored confidence in a
reserved column named **`_confidence`** (a `NUMERIC` / `DOUBLE
PRECISION` column on your table).

- At **`retrieve`**: rows whose `_confidence` is below `f` are filtered
  out of `rows`; `below_floor_filtered` reports how many were dropped.
  A row with no `_confidence` value is at ⊥ — below any positive floor.
- At **`persist`**: writing a value whose `_confidence` is below `f`,
  or writing with no `_confidence` at all (an *un-elevated* write),
  into a confidence-floored store is a **typed error**. You cannot
  quietly write doubt into a believed store.

```axon
axonstore clinical_facts {
    backend: postgresql
    connection: "env:DATABASE_URL"
    confidence_floor: 0.9          // only high-confidence facts admitted
}
```

---

## 7. Pillar II — audit-chained mutations (`on_breach`)

Every `persist` / `mutate` / `purge` appends a delta to a
**tamper-evident HMAC-Merkle mutation chain**. The chain's complete
history is independently verifiable: given the chain and its HMAC key,
any alteration of any past delta is detectable. Regulatory replay
(PCI DSS Req 10, FedRAMP AU-2, 21 CFR Part 11 §11.10) is a language
primitive — not an event-sourcing framework you bolt on.

`on_breach` declares what happens when chain verification detects
tampering. The closed catalog:

| `on_breach` | Behavior on a detected tamper |
|---|---|
| `log` (default) | Record the breach; execution continues. |
| `raise` | Surface the breach as an error — fail loud. |
| `rollback` | Surface the breach **and** signal the mutation history must roll back. |

```axon
axonstore audit_trail {
    backend: postgresql
    connection: "env:DATABASE_URL"
    on_breach: raise               // a tampered history fails loud
}
```

In v1.30.0 the chain is in-process for the flow's lifetime. A
persistent, cross-process tamper-evident kernel + a court-admissible
evidence packager are part of the **axonstore Regulatory Hardening
Layer** (an axon-enterprise capability).

---

## 8. Pillar III — `retrieve` is a `Stream<Row>`

`retrieve from huge_table` does **not** load the whole result set into
memory. The rows flow off a lazy database cursor through a bounded,
cancel-aware drain — exactly like an LLM token stream.

The `retrieve` envelope's `stream` sub-object reports the disposition:

```json
"stream": {
  "policy": "pause_upstream",
  "total_seen": 12000,
  "dropped": 0,
  "truncated": true,
  "cancelled": false
}
```

- The drain is bounded by a default cap of **10 000 rows**. A result
  larger than the cap is **truncated** and `truncated: true` flags it —
  never silently dropped, never an OOM.
- The drain is **cancel-aware**: if the request is cancelled (the
  client disconnects), the cursor stops immediately.
- The backpressure policy catalog (`drop_oldest`, `pause_upstream`,
  `fail`, `degrade_quality`) is shared with axon's algebraic-effect
  streaming surface — a pg-backed `axonstore` is a first-class stream
  producer, unified with `Tool::stream()`.

---

## 9. Pillar IV — capability-typed access (`capability`)

Declare a `capability` slug on a store and access to it becomes a
**typed permission** — data isolation stops being an app-code
`if tenant_id == …` you must remember.

```axon
axonstore tenant_pii {
    backend: postgresql
    connection: "env:DATABASE_URL"
    capability: "pii.read"
}

axonendpoint ReadPii {
    method: GET
    path: "/pii"
    execute: FetchPii
    requires: [pii.read]           // MUST grant the store's capability
}
```

**Compile-time enforcement.** The type-checker walks every
`axonendpoint` → the flow it executes → the stores that flow accesses.
If a flow touches a `capability`-gated store, the executing endpoint's
`requires:` list **must grant** that capability. A program where an
under-privileged endpoint could reach a gated store **does not
type-check**. Data isolation is a language guarantee.

**Runtime re-check.** The streaming dispatcher re-verifies, against the
capabilities the request's JWT bearer actually carries, that a gated
store may be touched — defense-in-depth behind the static guarantee.

The capability **slug grammar** is the closed
`^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$` — shared with the Fase 32.g
`requires:` grammar (`admin`, `tenant.read`, `hipaa.phi.read`).

---

## 10. The `in_memory` backend

A store with `backend: in_memory` (or no `backend`, or one never
declared at all) uses an in-process key-value path. This is the
pre-1.30 behavior, **byte-identical** — a flow that uses only in-memory
stores is unaffected by v1.30.0.

`in_memory` is the right choice for ephemeral per-flow scratch state.
For data that must survive a process restart, declare
`backend: postgresql`.

---

## 11. Connecting to Postgres

```axon
axonstore orders {
    backend: postgresql
    connection: "env:DATABASE_URL"
}
```

- **`connection: "env:VAR"`** resolves environment variable `VAR` at
  first use. If `VAR` is unset, the store op fails with a clear named
  error — **never** a silent fallback to the key-value store. A
  misconfigured SQL store fails loud.
- **`connection: "postgresql://user:pass@host:5432/db"`** is a literal
  DSN.
- One connection pool is opened per distinct resolved DSN, lazily
  (no connection until the first operation), bounded (max 10
  connections), and reused. Stores that share a DSN share one pool.

### 11.1 Transaction-mode poolers — works out of the box (v1.36.3+)

Managed Postgres almost always sits behind a **transaction-mode
connection pooler** — PgBouncer `pool_mode=transaction`, Supabase
**Supavisor** (the `:6543` port), Neon, AWS RDS Proxy. These multiplex
many logical sessions over a few physical connections, so two
consecutive store operations can land on different backend sessions.

axonstore is **safe behind a transaction-mode pooler with no
configuration**. The connection pool disables the client-side named
prepared-statement cache (`statement_cache_capacity(0)`), so every
query uses the unnamed prepared statement — collision-free by
construction. You point `connection:` at the pooler DSN (e.g. the
Supabase `:6543` URL) and it just works. There is no knob to set and
no knob to get wrong.

Every axonstore connection also carries an `application_name` of
`axon-store/<store name>` — so an axon-owned session is identifiable
at a glance in `pg_stat_activity`, your pooler's logs, and DBA
dashboards.

### 11.2 The Pooler-Coherent Store Contract (v1.37.0+)

v1.36.3 closed *one* pooler-related defect — the prepared-statement
cache collision. v1.37.0 closes the deeper one: a typed-column
`retrieve`/`mutate`/`purge` on a session whose `search_path` did not
disambiguate the table would die `operator does not exist: uuid =
text` (or `text = bigint`, `<= timestamptz`, …). The five iterations
1.36.1–1.36.5 each fixed a real healthy-session defect but none
addressed that **the path itself was conditional on the session** —
column-type introspection ran on a *different* pooled connection than
the operation it typed.

v1.37.0 makes the store path **unconditionally pooler-coherent**.
Stated as a contract — the nine D-letters of Fase 37.x:

| D-letter | Guarantee |
|---|---|
| **D1** | A store table is resolved via `pg_catalog` (`to_regclass` primary + cross-schema `relname` fallback), **never** the ambient `search_path` — a pooler-volatile per-connection GUC the pooler does not preserve across checkouts |
| **D2** | Every operation's SQL is schema-qualified — `"schema"."table"` — so it resolves on **any** session regardless of `search_path` |
| **D3** | On a cache miss the schema introspection AND the operation execute inside **one** `pool.begin()` transaction — a transaction-mode pooler pins ONE physical backend for both, never two |
| **D4** | When the column type is genuinely unknown (introspection ran, returned no rows for that column) an equality filter falls back to `"col"::text = $N` — the column-side `::text` cast compares uniformly. Ordering / `LIKE` keep a bare `$N` (fail-loud) |
| **D5** | The contract holds symmetrically across `retrieve` / `persist` / `mutate` / `purge` / `Stream<Row>`. Public signatures are byte-unchanged; a healthy direct connection is byte-identical to pre-v1.37 |
| **D6** | An unresolvable or ambiguous table is a *typed, actionable* failure — the error names the table, the schemas searched, the masked DSN, and the concrete remedy; a structured `tracing::error!` lands in your logs |
| **D7** | The CI lane `fase_37x_pooler_coherent_store.yml` exercises every contract above through PgBouncer `pool_mode=transaction` on every PR + master push — the regression is FORCED to surface in CI |
| **D8** | `POST /v1/deploy` **eagerly resolves and introspects** every declared `postgresql` store — a missing table on a reachable database FAILS the deploy (not a request months later). An unreachable store is a non-fatal warning ("deploy is honest, never brittle") and the D9 runtime path still applies |
| **D9** | The process-global `(dsn, table)` schema cache is **bounded** (10 000 entries, oldest-first eviction) and **self-healing** — a cache-hit operation that fails with a schema-drift SQLSTATE (`42P01` / `42703` / `42804` / `42883`) evicts the entry and retries once against fresh introspection. Provably safe: every drift SQLSTATE is a parse-time rejection (the failed statement had zero side effects, so a retried `persist`/`mutate` cannot double-write) |

You do not configure any of this. The contract is the runtime; an
adopter who never reads this section gets exactly the same behavior as
one who memorizes it. The pooler-coherent contract is invisible when
it works — which it now does on every session.

> **What this means for an adopter:** drop in v1.37.0, point
> `connection:` at your transaction-mode pooler URL (Supabase
> `:6543`, RDS Proxy, Neon, PgBouncer transaction mode, …), and the
> typed-column read/write that previously needed a lucky
> direct-session smoke test now succeeds every time. The five
> patches 1.36.1–1.36.5 are subsumed; you do not need their
> workarounds.

### 11.3 Recipe — a table living behind a legacy schema

A common adopter shape: the application user's `search_path` is
`public, app, audit` but the table you want lives in `legacy_v2`. Pre-37,
this meant a `retrieve` from the table failed `relation "X" does not
exist` on first run, then sometimes succeeded if you happened to `SET
search_path` first.

```axon
axonstore claims {
    backend: postgresql
    connection: "env:DATABASE_URL"
}

flow LookupClaim(claim_id: String) -> Unit {
    retrieve claims { where: "id = ${claim_id}" as: result }
}
```

v1.37.0 — **`claims` resolves via `pg_catalog`** and finds the table
in `legacy_v2` regardless of where it falls in (or out of) the
session's `search_path`. The operation runs `SELECT * FROM
"legacy_v2"."claims" WHERE "id" = $1::uuid` (or `::int4`, etc.,
depending on `claims.id`'s introspected type). No DSN trick, no `SET
search_path` boilerplate.

Behind the scenes: the first request introspects + caches; the next
20 000 reads are cache hits with a single round-trip. A live `ALTER
TABLE legacy_v2.claims ALTER COLUMN id TYPE text` will cause the next
read to fail SQLSTATE 42883 — and **self-heal** — the cache evicts,
re-introspects, retries with `"id"::text = $1`, returns the row. No
adopter intervention.

### 11.4 Recipe — a same-name table in multiple schemas (D6)

Some applications have the SAME table name in two schemas (a tenant-
per-schema layout, a `staging.events` + `prod.events` topology). v1.37
detects this and FAILS with a precise, actionable error — never
silently picks the wrong one.

```text
axonstore table `events` is ambiguous — it exists in 2 schemas
(prod, staging) and the connection's `search_path` does not
disambiguate it; either narrow the role's `search_path` so exactly
one of the resolving schemas is visible, or declare the target
schema explicitly on the `axonstore` (the Fase 38 `schema:`
declaration, incl. `schema: env:VAR` per-tenant)
```

Two remedies, named for you:

1. **Narrow `search_path` for the role.** If exactly one of the
   resolving schemas should be visible to this connection, set the
   user's `search_path` to that schema only (`ALTER ROLE …`).
2. **Declare the schema on the `axonstore`** (the genuinely-superior
   remedy, the multi-schema case anchored to its compile-time half).
   *Available in axon-lang Fase 38 — the compile-time-typed schema
   companion to 37.x* (`axonstore claims { backend: postgresql ...
   schema: env:TENANT_SCHEMA }`).

Behind a transaction-mode pooler, remedy #1 is necessary anyway: the
pooler does not preserve a session-local `SET search_path` across
checkouts. Remedy #2 will let an adopter declare the schema *in
source*, validated at compile time, per-tenant when the schema is an
`env:` reference. Until then, narrow `search_path` at the role level.

### 11.5 Recipe — deploy-time store-schema verification (D8)

v1.37.0 wires the schema check into `POST /v1/deploy` (the `axon
deploy` flow). A missing table on a reachable database now fails the
**deploy**, not the first production request:

```text
POST /v1/deploy → 400 Bad Request
{
  "error": "deploy-time store-schema verification failed: 1 declared
            postgresql store table(s) do not resolve on a reachable
            database: `claims` — axonstore could not resolve table
            `claims` to a relation in any schema of the database —
            verify the table exists in the target database (a
            deploy-time migration is the usual remedy) and that the
            configured credentials can SELECT from it; … (database:
            postgresql://app:***@db.host/prod)",
  "phase": "store_schema_verification",
  "d_letter": "D8"
}
```

A store *unreachable* at deploy (the database is transiently down,
the `env:` var is unset) is a NON-fatal warning — the deploy proceeds
and the D9 runtime path still resolves the schema on the first live
operation. "Deploy is honest, never brittle": a transient outage at
deploy time does not block a rollout that an operator can re-resolve
the moment the database returns.

```json
{
  "deployed": true,
  "store_warnings": [
    { "store": "audit_log",
      "diagnostic": "axonstore could not reach the database: ... (database: postgres://app:***@audit.host/prod)" }
  ]
}
```

The successful-resolution side-effect — the schema is now **warm in
the process cache**, so the first runtime operation against a
verified store is a cache hit. Cold-start latency for the first
request after a deploy is one less round-trip.

---

## 12. Honest scope boundaries (v1.30.0)

v1.30.0 is the cognitive data plane — these boundaries are stated, not
silently omitted:

- **No DDL.** `axonstore` carries no column schema, so v1.30.0 operates
  against **existing tables**. There is no `CREATE TABLE` / `migrate` /
  `CREATE INDEX`. You provision your tables; axon reads and writes
  them. A schema-carrying `axonstore` is a documented follow-on.
- **Single-statement autocommit.** Each `persist` / `retrieve` /
  `mutate` / `purge` is one autocommit statement. A multi-statement
  `transact { … }` block is a documented future fase. The `isolation`
  field is carried for that fase.
- **Supported column types.** `retrieve` maps these Postgres types to
  JSON-safe values: `BOOL`, `INT2/4/8`, `FLOAT4/8`, `NUMERIC` (→
  precision-safe string), `TEXT`/`VARCHAR`/`BPCHAR`/`NAME`, `UUID` (→
  string), `TIMESTAMPTZ`/`TIMESTAMP`/`DATE`/`TIME` (→ string), `JSON`/
  `JSONB`, `BYTEA` (→ base64 string). A column outside this catalog is
  a clear `UnsupportedColumnType` error — never a silent miss.
- **Backend catalog.** `{in_memory, postgresql}`. `sqlite` and `mysql`
  parse but fail registry build with a named error.
- **`mutate` / `purge` without a `where`** operate on every row. This
  is intentional, not a bug — but write the `where` unless you mean it.

---

## 13. Production checklist

- [ ] The target tables exist in your database with the columns your
      flows bind.
- [ ] `connection` uses `env:` — secrets are never in source.
- [ ] A `confidence_floor` store's tables carry a `_confidence` column.
- [ ] Every `mutate` / `purge` has a `where:` clause (unless a
      whole-store op is intended).
- [ ] Every `capability`-gated store's capability is granted by the
      `requires:` of the endpoint executing the flow (the type-checker
      enforces this — a clean `axon check` confirms it).
- [ ] Large `retrieve`s expect the `stream.truncated` flag at 10 000+
      rows.

---

## 14. Troubleshooting

| Symptom | Cause + fix |
|---|---|
| `axonstore registry: unknown backend 'sqlite'` | `sqlite`/`mysql` are not in the v1.30.0 catalog. Use `postgresql` or `in_memory`. |
| `environment variable 'X' is not set` | `connection: "env:X"` and `X` is unset. Export it; never falls back to KV. |
| `unsafe table identifier` / `unsafe column identifier` | A table or binding name is not `[A-Za-z_]\w*` / ≤ 63 bytes. |
| `column 'X' does not exist` (from Postgres) | A `persist`/`mutate` is writing a binding that is not a table column. Declare a `{ col: value }` block — for `persist` ([§4.1](#41-the-persist-field-block-v1310), v1.31.0+) the `INSERT` is scoped to exactly those columns; for `mutate` ([§4.2](#42-the-mutate-set-block-v1320), v1.32.0+) the `UPDATE … SET` is. axonstore operates against existing tables — the columns must already exist. |
| `persist … blocked: un-elevated write` | A `confidence_floor` store received a `persist` with no `_confidence`. Bind a `_confidence` ≥ the floor. |
| Endpoint fails `axon check` with "requiring capability" | A flow touches a `capability`-gated store; add the capability to the endpoint's `requires:`. |
| `column 'X' has Postgres type 'Y', outside the v1.30.0 supported catalog` | See [§12](#12-honest-scope-boundaries-v1300) for the supported type catalog. |
| `prepared statement "sqlx_s_1" already exists` | A transaction-mode pooler in front of an axonstore older than v1.36.3. Upgrade — v1.36.3+ disables the named-statement cache, so axonstore is pooler-safe with no configuration ([§11.1](#111-transaction-mode-poolers--works-out-of-the-box-v1363)). |
| `operator does not exist: uuid = text` (or `text = bigint`, `<= timestamptz`, …) on a `retrieve`/`mutate`/`purge` `where:` | The `where`-clause value is not cast to the column's type behind a transaction-mode pooler. Upgrade to **v1.37.0+** — the *Pooler-Coherent Store Contract* makes the introspection + the operation share ONE pooled session and resolves the table via `pg_catalog` (never `search_path`), so the typed cast lands every time, not just on a lucky session ([§11.2](#112-the-pooler-coherent-store-contract-v1370)). The patch chain 1.36.1–1.36.5 is subsumed. |
| `axonstore could not resolve table 'X' to a relation in any schema of the database` ([D6](#112-the-pooler-coherent-store-contract-v1370)) | The table genuinely does not exist on the target database, **or** the credential cannot `SELECT` from it (no schema USAGE / table SELECT GRANT). A deploy-time migration is the usual remedy. v1.37 introspects through `pg_catalog`, so `search_path` is NOT the culprit — the search is independent of it. |
| `axonstore table 'X' is ambiguous — it exists in N schemas` ([D6](#114-recipe--a-same-name-table-in-multiple-schemas-d6)) | The same table name exists in ≥2 schemas this role can see. Either narrow the role's `search_path` so exactly one resolving schema is visible (`ALTER ROLE … SET search_path = …`), or declare the target schema on the `axonstore` (the Fase 38 `schema:` declaration). |
| `axonstore 'X' hit live schema drift (SQLSTATE 42703/42804/42883/42P01)` ([D9](#112-the-pooler-coherent-store-contract-v1370)) | A live `ALTER TABLE` ran since the schema was cached. v1.37.0+ **self-heals**: the cache entry evicts, fresh introspection runs, the operation retries once and succeeds. If you see this error reach your client, the retry also failed — likely because the new schema is *itself* incompatible with the operation. Investigate the latest `ALTER`. |
| `POST /v1/deploy → 400 deploy-time store-schema verification failed` ([D8](#115-recipe--deploy-time-store-schema-verification-d8)) | A declared `postgresql` store's table does not resolve on a *reachable* database — the deploy is failing on purpose. Run the schema migration, or fix the `connection:`/credentials, then re-deploy. An *unreachable* database at deploy is a non-fatal warning (the deploy proceeds; the D9 runtime path resolves later). |

---

## 15. Where to file bugs

Open an issue at the axon-lang repository. Include the `axonstore`
declaration, the failing flow step, and the exact error — every
`axonstore` failure surfaces as a typed, named error.

---

## 16. Streaming the agent pattern (v1.35.0)

> Introduced in **v1.35.0** (Fase 36.x — *Mixed-Flow Streaming
> Integrity*). A real AI agent is not a single LLM call — it is a
> SHAPE: **retrieve context → deliberate → persist the result**. In
> axon that is a flow which mixes `axonstore` operations with a
> `step`. v1.35.0 makes that shape a first-class, verified,
> locally-runnable streaming primitive.

### 16.1 The canonical agent flow

```axon
axonstore mem { backend: in_memory }

flow ChatFlow() -> Unit {
    retrieve mem { where: "kind = 'history'" as: history }
    step Deliberate { ask: "Given ${history}, answer the user"
                      output: Stream<Token> }
    persist into mem { kind: "reply" content: "${Deliberate}" }
}

axonendpoint Chat {
    method:    POST
    path:      "/api/chat"
    execute:   ChatFlow
    backend:   stub          # a real provider in production (Fase 36)
    transport: sse
}
```

Deploy it, `POST /api/chat` with `Accept: text/event-stream`, and the
endpoint streams the deliberation token-by-token — the `retrieve` and
`persist` execute as real steps around it.

### 16.2 `backend: in_memory` — runnable with zero infrastructure

Before v1.35.0 a source-declared `axonstore` had to name `postgresql`
— so the agent flow above could not run, or be tested, without a live
database. v1.35.0 makes **`in_memory` a first-class declarable
backend**: `axonstore mem { backend: in_memory }` type-checks and
resolves to the in-process key-value path. `connection:` is optional
for it. Develop and test the whole agent shape on a laptop; swap in
`backend: postgresql` for production persistence with zero flow
changes.

### 16.3 The data threads — `${interpolation}`

The agent pattern is a data pipeline, and the data flows through the
flow's bindings:

- a `retrieve … as: history` binds `history`;
- a `step`'s `ask:` interpolates `${history}` (and `$history`) from
  those bindings before it becomes the prompt;
- a `step`'s output is bound under the **step name** — `${Deliberate}`
  above resolves to what `step Deliberate` produced;
- a `persist` field block interpolates `${…}` the same way.

Interpolation is identical on the streaming dispatcher path and the
synchronous path — an unknown `${name}` is left literal, never an
error.

### 16.4 The wire contract — exactly one terminator

Every streaming response ends with **exactly one terminator**:

- `event: axon.complete` — the flow ran to its end;
- `event: axon.error` — a step (or a store op) failed.

Never both, never neither. A store operation that fails mid-flow ends
the stream with a single `axon.error`; it never emits a trailing,
contradictory `axon.complete`. The `retrieve` / `persist` steps
execute but add no wire frames of their own — a mixed flow's SSE
event vocabulary is identical to a pure-step flow's (`axon.token` +
the one terminator), so existing SSE clients are unaffected.

### 16.5 Honest failure

If a store cannot resolve — a `postgresql` store whose
`connection:` env var is unset, or a backend with no runtime
implementation — the flow fails with a structured `axon.error`
naming the cause. It never silently degrades to an empty result.
`in_memory` has no external dependency and never fails to resolve.

---

## 17. The Compile-Time-Typed Store Schema (v1.38.0)

v1.37.x made a typed-column `axonstore postgresql` work at runtime
on every pooled session (§11.2). v1.38.0 makes its **SHAPE a
declared, verifiable, compile-time-proven property**. Schema drift
between an adopter's declared columns and the live database moves
from a first-failing `persist` to `axon check` AND to the deploy
itself. A column name typo, a type mismatch in a `where:` clause,
a missing NOT-NULL column on a `persist` — every one is now a
compile-time error with a Levenshtein composite suggestion (`Did
you mean column \`email\` (Text)?`).

The contract has three closed `schema:` declaration forms:

| Form | Shape | Use case |
|---|---|---|
| **(a) inline** | `schema: { columns: { … } }` directly on the `axonstore` | Single store, columns hand-declared in the `.axon` source |
| **(b) manifest reference** | `schema: "<namespace>.<store_name>"` | Tightly-controlled schema generated by an external migration tool; one canonical file the compiler + operator + CI all read |
| **(c) per-tenant env-var** | `schema: env:TENANT_SCHEMA` | Schema-per-tenant SaaS deployment — the same `.axon` source serves every tenant; the live namespace is decided per-deploy via env var |

The **15-type closed catalog**, lifted from v1.30.0's runtime
`PgTypeClass`, is the universe of declarable column types:

```text
Uuid | Text | Int | BigInt | Float | Double | Bool | Timestamptz |
Timestamp | Date | Time | Jsonb | Json | Bytea | Numeric
```

Types outside this set (custom enums, geographic, network) are
honestly omitted by `axon store introspect` with a `# omitted:
column \`X\` (pg type \`Y\`) — …` comment. **A column without a
declared `type:` is silently skipped by the compile-time proof** —
this preserves D5 absolute backwards-compat for mixed-shape stores.

### 17.1 Recipe — form (a) inline `schema:` block

```axon
axonstore users {
  backend: postgresql
  connection: env:DATABASE_URL
  table: "users"
  schema: {
    columns: {
      user_id:    { type: Uuid, primary_key: true, not_null: true }
      tenant_id:  { type: Uuid, not_null: true }
      email:      { type: Text, not_null: true, unique: true }
      tier:       { type: Text, not_null: true }
      created_at: { type: Timestamptz, not_null: true }
    }
  }
}

flow ChargeFlow(tenant_id: Uuid) -> Unit {
  retrieve users { where: "tenant_id = $tenant_id" as: u }
  persist into users {
    tenant_id: "${tenant_id}"
    email:     "ops@example.com"
    tier:      "enterprise"
  }
}
```

**Effect:** every operation against `users` is now compile-time-
proven:

- `where: "tenant_id = $tenant_id"` ↦ proven (column exists, types
  match, parameter is `Uuid`). Mistype `tenant_id` as `tnant_id` →
  T801 `unknown column "tnant_id" in where on store \`users\`. Did
  you mean column \`tenant_id\` (Uuid)?`
- The `persist into` block omits `user_id` + `created_at` — both
  are NOT-NULL → T803 `persist into store \`users\` omits required
  NOT-NULL columns: [user_id, created_at]`
- Mistype `tier` as `tiar` → T804 `unknown field \`tiar\` in
  persist block on store \`users\`. Did you mean column \`tier\`
  (Text)?`

At deploy, the declared columns are also proven against the live
introspection (T807) — a column declared `Text` whose live
`pg_type` is `tier_enum` fails the deploy with a structured
`missing_tables` entry.

### 17.2 Recipe — form (b) manifest reference

**Step 1 — emit the manifest from your live DB:**

```bash
$ axon store introspect users
# Manifest generated by `axon store introspect` (v1.38.0).
# omitted: column `geom` (pg type `geometry`) — outside closed type catalog
{
  "version": 1,
  "content_hash": "sha256:c4d1a8…",
  "stores": {
    "users": {
      "columns": {
        "created_at": { "type": "Timestamptz", "not_null": true },
        "email":      { "type": "Text", "not_null": true, "unique": true },
        "tenant_id":  { "type": "Uuid", "not_null": true },
        "tier":       { "type": "Text", "not_null": true },
        "user_id":    { "type": "Uuid", "primary_key": true, "not_null": true }
      }
    }
  }
}
```

The emitter computes a canonical hash you can persist into your
repo. Pipe it to a file:

```bash
$ axon store introspect users > schemas/users.axon-schema.json
```

**Step 2 — reference it from the `axonstore`:**

```axon
axonstore users {
  backend: postgresql
  connection: env:DATABASE_URL
  table: "users"
  schema: "public.users"
}
```

The qualified name (`<namespace>.<store_name>`) keys into the
manifest's `stores` map.

**Step 3 — boot with `--schemas-dir`:**

```bash
$ axon serve --schemas-dir schemas
```

Or set the env var:

```bash
$ AXON_SCHEMAS_DIR=schemas axon serve
```

`axon serve --schemas-dir <path>` loads + merges every
`*.axon-schema.json` under the directory at every deploy. The CLI
flag wins when both surfaces are set.

### 17.3 Recipe — form (c) per-tenant `schema: env:VAR`

```axon
axonstore usage {
  backend: postgresql
  connection: env:DATABASE_URL
  table: "usage"
  schema: env:TENANT_SCHEMA
}
```

**One manifest per tenant** under `schemas/`:

```bash
$ TENANT_SCHEMA=tenant_alpha axon store introspect usage \
    > schemas/usage.tenant_alpha.axon-schema.json
$ TENANT_SCHEMA=tenant_beta  axon store introspect usage \
    > schemas/usage.tenant_beta.axon-schema.json
```

**At deploy, set the env var per pod:**

```bash
$ TENANT_SCHEMA=tenant_alpha axon serve --schemas-dir schemas
```

**Effect:**

1. The deploy resolves `usage` against the `tenant_alpha.usage`
   manifest entry. The **first-match heuristic** prefers an exact
   `<namespace>.<store_name>` match; if none exists it falls back
   to any `*.<store_name>` entry under the namespace prefix.
2. The connection's `application_name` is stamped
   `axon-store/usage/tenant_alpha` (**Gap-3 inheritance**), so a
   DBA sees the resolved tenant on every pooled session.
3. A missing `TENANT_SCHEMA` env var raises **T806** with the
   variable name in the diagnostic.

Onboarding a new tenant adds **one** manifest file + **one** env
var on the pod. No `.axon` source change.

### 17.4 Recipe — `axon store introspect` for a live database

The introspect CLI is the reverse of `axon check` — read live, emit
manifest. Useful for:

- **First adoption** — generate the manifest for an existing table.
- **CI contract gate** — diff the committed manifest against a
  fresh introspect; a non-empty diff = schema drift on the wrong
  side of the gate.
- **Drift forensics** — when T807 fires at deploy, run `axon store
  introspect` to see exactly what the live DB shows.

```bash
# Introspect a single store
$ axon store introspect users

# Introspect every declared postgresql store
$ axon store introspect --all

# Emit to a path (no STDOUT)
$ axon store introspect users --output schemas/users.axon-schema.json

# Diff two manifests (live → committed)
$ axon store introspect users --diff schemas/users.axon-schema.json
```

The CLI sets `application_name = axon-store/<store>/introspect` so
the DBA can distinguish introspection sessions from runtime
sessions in their session log. Output is canonical (key-sorted, no
whitespace) — diffs are stable.

### 17.5 Recipe — wiring `--schemas-dir` on production `axon serve`

In `systemd`:

```ini
[Service]
Environment=DATABASE_URL=postgres://app@host:6432/db
Environment=AXON_SCHEMAS_DIR=/etc/axon/schemas
ExecStart=/usr/local/bin/axon serve --port 8420
```

In Kubernetes:

```yaml
spec:
  containers:
    - name: axon
      image: ghcr.io/bemarking/axon-lang:1.38.0
      command: [axon, serve, --port=8420, --schemas-dir=/etc/axon/schemas]
      volumeMounts:
        - name: axon-schemas
          mountPath: /etc/axon/schemas
          readOnly: true
  volumes:
    - name: axon-schemas
      configMap:
        name: axon-schemas
```

In a Dockerfile dev image:

```dockerfile
COPY schemas/ /app/schemas/
ENV AXON_SCHEMAS_DIR=/app/schemas
CMD ["axon", "serve", "--host", "0.0.0.0", "--port", "8420"]
```

**Failure modes the operator sees at `POST /v1/deploy`:**

| Body shape | Meaning |
|---|---|
| `"phase": "store_schema_manifest_load"`, `"d_letter": "D3+D8"`, includes echoed `schemas_dir` | Manifest load failed — T805 hash mismatch, DuplicateStore across files, or malformed JSON. Operator-visible; `schemas_dir` is echoed so the operator can locate the offending dir. |
| `"phase": "store_schema_verification"`, `"d_letter": "D8"`, `"missing_tables"[…]"detail"` starts with `declared-vs-live drift` | **T807** — the declared columns disagree with live introspection. The detail names the missing columns + the type-mismatched ones. |
| `"phase": "store_schema_verification"`, `"d_letter": "D8"`, classic 37.x.h-style `to_regclass` failure | Pre-38 behavior — the table itself does not resolve on a reachable DB. Independent of Fase 38. |

Drop `--schemas-dir` to revert to the v1.37.0 verification path
verbatim (D5 absolute) — useful for a single bisect-style deploy
when you suspect a manifest drift is masking a real bug.
