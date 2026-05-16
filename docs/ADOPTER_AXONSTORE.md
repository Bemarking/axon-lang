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
12. [Honest scope boundaries (v1.30.0)](#12-honest-scope-boundaries-v1300)
13. [Production checklist](#13-production-checklist)
14. [Troubleshooting](#14-troubleshooting)
15. [Where to file bugs](#15-where-to-file-bugs)

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

---

## 15. Where to file bugs

Open an issue at the axon-lang repository. Include the `axonstore`
declaration, the failing flow step, and the exact error — every
`axonstore` failure surfaces as a typed, named error.
