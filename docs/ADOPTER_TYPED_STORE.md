# ADOPTER_TYPED_STORE.md — The Five-Pillar Cognitive Data Plane

> **Scope:** the cognitive-data-plane story across the full Fase 28
> → Fase 38 arc, framed as **five orthogonal pillars on the same
> store substrate**. This is the architectural companion to the
> recipe-driven [`ADOPTER_AXONSTORE.md`](./ADOPTER_AXONSTORE.md);
> read this when you want the "why each pillar exists + what
> failure mode each closes" view.

```text
   ┌──────────────────────────────────────────────────────────────┐
   │      I  Epistemic        — `confidence_floor` (v1.30)        │
   │     II  Audit-chained    — `on_breach` (v1.30)               │
   │    III  Streaming        — `retrieve: Stream<Row>` (v1.30)   │
   │     IV  Capability-typed — `capability:` (v1.30)             │
   │      V  TypedColumn      — `schema:` (v1.38) ← NEW           │
   │ ───────────────────────────────────────────────────────────  │
   │            ↑ the same `axonstore` declaration                │
   │     ────────────────────────────────────────────────         │
   │       Pooler-Coherent Store Contract (v1.37) substrate       │
   └──────────────────────────────────────────────────────────────┘
```

Each pillar closes a class of silent failure mode at the **same
load-bearing surface** — the `axonstore` declaration. Adoption is
**ordinal** (any subset is valid) and **commutative** (the order
of adoption does not matter). The four v1.30 pillars are runtime
contracts; v1.38's TypedColumn is the **compile-time** + **deploy-
time** pillar that closes the loop.

---

## Pillar I — Epistemic data plane (`confidence_floor`)

**Failure mode closed:** an opinion that *looks* like a fact.

**Surface:**

```axon
flow ChargeFlow() -> Unit {
  step Classify { ask: "is_premium?" output: Confidence<Bool> }
  persist into users {
    is_premium: "${Classify}"
    confidence_floor: 0.85
  }
}
```

A `Confidence<T>` value below the declared floor is **silently
dropped** from the persist — it never enters the store. The
opinion is honest about its own uncertainty; the store keeps facts.

**Why it lives on `axonstore`:** the floor is a *property of the
data plane*, not of the model that produced the value. A second
model later writing to the same store inherits the same floor — the
store, not the model, is the line.

**Composes with Pillar V?** Yes. Declare the `is_premium` column
as `Bool` in the `schema:` block — TypedColumn's T802 catches a
type drift (`is_premium: "yes"` against a `Bool` column) at
compile time, BEFORE the confidence threshold even fires.

---

## Pillar II — Audit-chained mutations (`on_breach`)

**Failure mode closed:** a critical mutation whose audit trail is
*conceptually mandatory but operationally optional*.

**Surface:**

```axon
flow EscalateFlow(case_id: Uuid, override: Text) -> Unit {
  mutate cases SET { status: "escalated" }
    where "case_id = $case_id"
    on_breach: append_to audit_log {
      kind: "escalation"
      case_id: "${case_id}"
      override_reason: "${override}"
    }
}
```

`on_breach:` is a **co-mutation** — the `cases` table update and
the `audit_log` append run in the SAME transaction. If the audit
append fails, the mutate is rolled back. The two operations are
atomic by construction.

**Why it lives on `axonstore`:** the audit chain is a *property of
the operation*, not of the application logic. An `on_breach:`
clause cannot be forgotten because it is co-located with the
mutate; a code reviewer sees it next to the SET.

**Composes with Pillar V?** Yes. The audit_log target store can
itself declare `schema:` — TypedColumn's T803 catches a NOT-NULL
omission in the audit-append block at compile time. A claim ever
made to a regulator (`"the audit entry was recorded"`) is now
provable at compile time + at runtime in the same transaction.

---

## Pillar III — Streaming (`retrieve: Stream<Row>`)

**Failure mode closed:** a `retrieve` that materialises 10M rows in
memory because someone forgot to add a `LIMIT`.

**Surface:**

```axon
flow ExportFlow() -> Unit {
  retrieve users { where: "1 = 1" as: u }
  step EmitRows { ask: "${u}" output: Stream<Token> }
}
```

`retrieve` returns a `Stream<Row>` — every `Row` is yielded
lazily, the consumer drives the back-pressure. A 10M-row retrieve
threads through without spiking RSS.

**Why it lives on `axonstore`:** the *shape* of the retrieve
result is a property of the store. A consumer downstream can rely
on the stream-shape regardless of which backend the store points
to (`postgresql` cursor or `in_memory` iterator).

**Composes with Pillar V?** Yes. TypedColumn's `where:` proof
(T801/T802) makes the streaming retrieve's filter clause
compile-time-correct. A typo in a 10M-row export query is now
caught at `axon check`, not at the consumer's third hour of
processing.

---

## Pillar IV — Capability-typed access (`capability:`)

**Failure mode closed:** a read operation that *should never have
been performed* given the current execution context.

**Surface:**

```axon
axonstore claims {
  backend: postgresql
  connection: env:DATABASE_URL
  table: "claims"
  capability: env:CLAIMS_TOKEN
}

flow LookupFlow(claim_id: Uuid) -> Unit {
  retrieve claims { where: "claim_id = $claim_id" as: c }
  step Reply { ask: "${c.summary}" }
}
```

`capability:` ties access to a runtime-typed token. The token's
type encodes WHAT the holder can do (`read`, `write`, `audit`).
A flow with no token gets no access — there is no ambient
authority on the data plane.

**Why it lives on `axonstore`:** the capability is the *property
of the store*, not of the model that holds the token. A
restructured flow inherits the capability gate automatically;
there is no place to forget it.

**Composes with Pillar V?** Yes. TypedColumn's T807 deploy-time
drift verification stamps the `application_name` with
`axon-store/<store>/<namespace>` (Gap-3 inheritance) — so on the
database side, the DBA's session log distinguishes a
capability-gated runtime session from an introspect session, from
a per-tenant session. Capability + tenant + role all observable
to the substrate.

---

## Pillar V — TypedColumn (`schema:`) — v1.38.0

**Failure mode closed:** a typed-column store I/O whose SHAPE
disagrees with the live database. A column name typo, a type
mismatch in a `where:` clause, a missing NOT-NULL column on a
`persist`, schema drift between an adopter's declared shape and
the live table.

Pre-v1.38 these surfaced at the first failing runtime operation:

| Defect | Pre-v1.38 surface |
|---|---|
| `where: "emial = $email"` typo | Postgres `column "emial" does not exist` at the first retrieve |
| `where: "tenant_id = $bad"` with `Int` against `Uuid` column | `operator does not exist: uuid = integer` at the first retrieve (or silent miscast via 37.x.e equality fallback) |
| `persist into users { … }` omits NOT-NULL `tier` | `null value in column "tier" violates not-null constraint` (SQLSTATE 23502) at the first insert |
| `persist into users { tiar: "x" }` field typo | `column "tiar" does not exist` at the first insert |
| `schema:` declared `tier: Text` but live `pg_type` is `tier_enum` | Silent — every op succeeds until a value violates the enum constraint |

**Surface:**

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
```

**Effect — five compile-time + deploy-time gates:**

| Code | Stage | What it catches | Sample message |
|---|---|---|---|
| **T801** | `axon check` | unknown column in `where:` | `unknown column "emial" in where on store \`users\`. Did you mean column \`email\` (Text)?` |
| **T802** | `axon check` | type mismatch in `where:` / `persist into { … }` | `type mismatch on store \`users\` column \`tenant_id\`: where value is \`Int\`, column declared \`Uuid\`` |
| **T803** | `axon check` | persist NOT-NULL omission | `persist into store \`users\` omits required NOT-NULL columns: [user_id, created_at]` |
| **T804** | `axon check` | unknown field in `persist`/`mutate` block | `unknown field \`tiar\` in persist block on store \`users\`. Did you mean column \`tier\` (Text)?` |
| **T805** | manifest parse | `content_hash` mismatch on a `*.axon-schema.json` | `store-schema manifest \`content_hash\` mismatch (axon-T805). The hash on disk is \`…\`, but the canonical content currently hashes to \`sha256:…\`` |
| **T806** | deploy | missing per-tenant env var (form c) | `missing per-tenant schema env var \`TENANT_SCHEMA\` for store \`usage\`` |
| **T807** | deploy | declared columns disagree with live introspection | `declared-vs-live drift on store \`users\`: missing on live database: {created_at}; type mismatches: [tier — declared Text, live tier_enum]` |

**Three closed `schema:` declaration forms:**

1. **Inline (a)** — `schema: { columns: { … } }` directly on the
   `axonstore`. Single store, columns hand-declared.
2. **Manifest reference (b)** — `schema: "<namespace>.<store_name>"`.
   The qualified name keys into a `*.axon-schema.json` manifest under
   `--schemas-dir`.
3. **Per-tenant env-var (c)** — `schema: env:TENANT_SCHEMA`. The
   live namespace is decided per-deploy via env var; the same
   `.axon` source serves every tenant.

The **15-type closed catalog** (`Uuid | Text | Int | BigInt |
Float | Double | Bool | Timestamptz | Timestamp | Date | Time |
Jsonb | Json | Bytea | Numeric`) is the universe of declarable
types. Types outside it are honestly omitted by `axon store
introspect` with a `# omitted: …` comment.

**Why it lives on `axonstore`:** the column shape is the
*property of the store*, not of the model. A second flow against
the same store inherits the same shape verification; the proof is
on the substrate, not on the consumer.

**Composes with Pillars I-IV?** Yes — **explicitly**. The four
v1.30 pillars are runtime contracts on the same substrate;
TypedColumn moves their compile-time half forward. Every
`confidence_floor`, `on_breach`, `retrieve as:`, `capability:`
clause now sits on a column catalog the compiler reads.

---

## The substrate — Pooler-Coherent Store Contract (v1.37.0)

Below the five pillars sits the **Pooler-Coherent Store Contract**.
A typed-column store I/O behind a transaction-mode pooler now
works on every session, not just a lucky one. The contract:

- **D1** search-path-independent resolution (`pg_catalog`, never
  `search_path`)
- **D2** schema-qualified operation SQL
- **D3** one coherent `introspect + operate` transaction (pooler
  pins one backend)
- **D4** equality type-agnostic fallback (`"col"::text = $N`)
- **D5** absolute backwards-compat
- **D6** honest unresolved-table failure
- **D7** transaction-pooler CI lane
- **D8** eager deploy-time schema resolution
- **D9** self-healing capacity-bounded LRU cache

Without the substrate, TypedColumn's deploy-time verification
(T807) would observe a non-deterministic introspection — which is
exactly the defect v1.37.x closed. Fase 38 builds on a substrate
that no longer leaks.

---

## Adoption ladder

There is no *required* order — each pillar is independent — but a
common path:

1. **Start with the substrate.** Adopt `backend: postgresql` + the
   v1.37.0 pooler-coherent surface. A direct connection works too.
2. **Add Pillar III streaming.** Most flows want bounded RSS.
3. **Add Pillar V TypedColumn.** Inline form (a) on your most-
   touched store; the compile-time proof pays back the cost in
   the first review cycle.
4. **Add Pillar I/II epistemic + audit-chained.** These pillars
   are domain-specific — `confidence_floor` for opinion-bearing
   data, `on_breach` for regulatory-grade mutations.
5. **Add Pillar IV capability-typed.** When the multi-tenant
   surface needs in-substrate access gating.

A v1.30 adopter who never adopts Pillar V is unaffected (D5
absolute). A Pillar V adopter who never adopts Pillars I-IV is
also unaffected — the column catalog is orthogonal.

---

## CI gates

Each pillar ships its own dedicated workflow under
`.github/workflows/`:

| Pillar | Workflow |
|---|---|
| I-IV (v1.30) | `fase_35_axonstore.yml` (broad cognitive-data-plane regression guard) |
| Substrate (v1.37) | `fase_37x_pooler_coherent_store.yml` |
| V (v1.38) | `fase_38_typed_store_schema.yml` (5 lanes — pure-column-proof, manifest-roundtrip, per-tenant-resolution, declared-vs-live-drift, d5-zero-regression) |

Adopters mirroring these workflows into their own CI gain a
deterministic guard surface — a column typo is impossible to
merge, an audit chain cannot be forgotten, a typed retrieve
cannot OOM, a capability gate cannot be bypassed, a column type
drift is caught at deploy.

---

## Closing — what each pillar costs

- **Pillar I** — `confidence_floor:` on the persist (one line).
- **Pillar II** — `on_breach: append_to <store> { … }` on the
  mutate (one block).
- **Pillar III** — already on by default for `retrieve`; the
  consumer drives.
- **Pillar IV** — `capability: env:VAR` on the store (one line) +
  a token-emitting auth surface.
- **Pillar V** — `schema: …` on the store + (form b/c) a
  `*.axon-schema.json` under `--schemas-dir`. One declaration
  per store; the introspect CLI emits the manifest for you.

The shared substrate (v1.37.0) is paid for once, by the runtime.
The five pillars compose on top of it without paying it again.

> **Founder principle, 2026-05-15:** *"Hacer que una aplicación
> AI sea determinista y fundada en nuestros cuatro pilares como
> lenguaje es el aporte a la humanidad."* — five, now.
