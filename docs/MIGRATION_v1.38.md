# AXON Migration Guide — v1.37.x → v1.38.0

> **Scope:** the Fase 38 *Declared & Compile-Time-Typed Store Schema*
> cycle introduced in v1.38.0. Adopters upgrading from v1.37.x read
> this doc to decide which migration scenario applies + execute the
> recipe.
>
> **TL;DR:** v1.37.x made a typed-column `axonstore postgresql` work
> at runtime, on every pooled session. **v1.38.0 makes its SHAPE a
> declared, verifiable, compile-time-proven property.** Schema drift
> between an adopter's declared columns and the live database moves
> from a first-failing `persist` (caught at runtime by SQLSTATE 23502
> / 42703) to the `axon check` AND to the deploy itself. A column
> name typo, a type mismatch in a `where:` clause, a missing NOT-NULL
> column on a `persist` — every one is now a compile-time error with
> a Levenshtein composite suggestion (`Did you mean column `email`
> (Text)?`). Three closed `schema:` declaration forms cover the full
> taxonomy: inline column block (form a), manifest file reference
> (form b), per-tenant env-var (form c, `schema: env:TENANT_SCHEMA`).
> Backwards-compatible by design (**D5 absolute**) — an `axonstore`
> without a `schema:` declaration, and a `serve` invocation without
> `--schemas-dir`, are byte-identical to v1.37.x.

---

## What changed in v1.38.0

| Surface | v1.37.x | v1.38.0 |
|---|---|---|
| A `where:` clause with a column name typo (`where: "emial = $email"`) | Compiled fine; failed at the first `retrieve` with a Postgres `column "emial" does not exist` (D6 in 37.x — honest but late) | **`axon check` error (T801)** — `unknown column "emial" in where on store \`users\`. Did you mean column \`email\` (Text)?` |
| A `where:` clause whose value type disagrees with the column (`tenant_id: Int` against a `Uuid` column) | Compiled fine; failed at runtime with `operator does not exist: uuid = integer` (or worked silently with `"col"::text` if 37.x.e equality fallback fired) | **`axon check` error (T802)** — `type mismatch on store \`users\` column \`tenant_id\`: where value is \`Int\`, column declared \`Uuid\`` |
| A `persist into` block that omits a NOT-NULL column | Compiled fine; failed at runtime with `null value in column "tier" violates not-null constraint` (SQLSTATE 23502) | **`axon check` error (T803)** — `persist into store \`users\` omits required NOT-NULL columns: [tier]` |
| A `persist into { … }` block with a typo on a field name | Compiled fine; failed at runtime with `column "tiar" does not exist` | **`axon check` error (T804)** — `unknown field \`tiar\` in persist block on store \`users\`. Did you mean column \`tier\` (Text)?` |
| A `schema:` declaration on an `axonstore` | Did not exist | Three closed forms (D1) — inline `schema: { columns: { … } }` (a), manifest reference `schema: "qualified.name"` (b), per-tenant `schema: env:TENANT_SCHEMA` (c) |
| A canonical store-schema manifest on disk (`*.axon-schema.json`) | Did not exist | Hand-rolled FIPS 180-4 SHA-256 + canonical (key-sorted, no whitespace) JSON; round-trip byte-identical; `content_hash` field optional but verified when present (T805) |
| A deploy where the declared columns disagree with the live DB | Did not exist (no declared schema) | **Fails the deploy** (T807) — `axonendpoint` URL gives `{"phase": "store_schema_verification", "d_letter": "D8", "missing_tables": [{ "store": "users", "detail": "declared-vs-live drift: missing on live database: {…}; type mismatches: [tier — declared Text, live tier_enum]" }]}` |
| `axon serve --schemas-dir <path>` | Did not exist | New flag (D7) — loads + merges every `*.axon-schema.json` under the directory; threads the merged manifest into deploy-time verification. Also: `AXON_SCHEMAS_DIR` env var |
| `axon store introspect <store>` | Did not exist | New CLI (D10) — reverse of `axon check`; reads live introspection and emits a canonical manifest with honest `# omitted: column \`X\` (pg type \`Y\`) — …` comments for types outside the closed 15-type catalog |
| Every `axonstore` without a `schema:` declaration + every adopter who never sets `--schemas-dir` | Established | **Byte-identical** (D5) |

---

## The intended behavior changes

Five, each a direct consequence of closing the compile-time half:

1. **A column name typo is caught at `axon check`.** The Levenshtein
   composite suggestion (`Did you mean column `email` (Text)?`) makes
   the diagnostic actionable: you see the typo AND the canonical
   column type that confirms the fix.

2. **A type mismatch in a `where:` clause is caught at `axon check`.**
   The value-side cast (37.x.e `"col"::text = $N`) was a runtime
   safety net for *unknown* types; declared columns now disagree at
   compile time. A `tenant_id: Int` against a `Uuid` column is a
   compile error, not a Postgres-side `operator does not exist`.

3. **A missing NOT-NULL column on `persist into` is caught at `axon
   check`.** Pre-v1.38 this failed at runtime with SQLSTATE 23502 on
   the first failing insert. Now: T803 lists the omitted columns by
   name. T803 covers form (a) inline columns only — manifest-ref +
   per-tenant forms defer NOT-NULL parity to a 38.f.2 follow-on (the
   live introspection used by form b/c does not currently capture
   `attnotnull`; this is documented honest scope, not a silent gap).

4. **Drift between a declared manifest and live introspection is
   caught at deploy.** With `axon serve --schemas-dir <path>` set, a
   manifest column missing on the live database OR a declared type
   that does not match the live `pg_type` raises T807 at `POST
   /v1/deploy`. **The failure moves from the first failing production
   request to CI.**

5. **A per-tenant deployment can declare its schema namespace as an
   env var.** Form (c) — `schema: env:TENANT_SCHEMA` — resolves the
   namespace at deploy + stamps it on the connection's
   `application_name` (`axon-store/<store>/<namespace>` — Gap-3
   inheritance) so a DBA sees the resolved tenant on every session.
   First-match resolution: an exact `<env_var>.<store_name>` manifest
   entry wins; otherwise any `*.<store_name>` entry under the
   namespace prefix.

No adopter with a *working* v1.37.x setup regresses. `D5 absolute`:
an `axonstore` without `schema:`, an `axon serve` without
`--schemas-dir`, every existing flow — byte-identical. The intended
changes convert silent runtime fail-modes into honest compile-time +
deploy-time errors.

---

## Migration scenarios

### Scenario A — you don't use `axonstore` at all

**v1.38.0:** nothing changes. Fase 38 is the compile-time-typed half
of the `axonstore` contract; flows without stores are untouched.

**Action:** none.

### Scenario B — you use `axonstore` but never set `--schemas-dir`

**v1.38.0:** byte-identical to v1.37.x. With no `--schemas-dir` (and
no `AXON_SCHEMAS_DIR` env var), the deploy handler runs the exact
v1.37.0 verification path — D5 is absolute. `axon check` is byte-
identical too — no declared columns means no compile-time column-
proof to enforce.

**Action:** none — but you can opt in incrementally. Drop a single
`.axon-schema.json` under `schemas/` and add `--schemas-dir schemas`
to your `axon serve` invocation; only the stores named in that
manifest are subject to T807 drift verification. Stores you have not
declared keep working unchanged.

### Scenario C — you adopt form (a) inline columns

**Before:**
```axon
axonstore users {
  backend: postgresql
  connection: env:DATABASE_URL
  table: "users"
}
```

**After (form a inline):**
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

**Effect:** every `where:`, every `persist into { … }` against this
store is now compile-time-proven (T801/T802/T803/T804) AND deploy-
time-proven against the live database (T807). A column name typo is
caught at `axon check`, not at the first failing request.

**Action:** add the `schema:` block. The 15-type catalog is closed
(`Uuid | Text | Int | BigInt | Float | Double | Bool | Timestamptz |
Timestamp | Date | Time | Jsonb | Json | Bytea | Numeric`) — types
outside it (custom enums, geographic, network) need form (b) +
manifest emitter, OR they remain unmapped (a column without a
declared `type:` is silently skipped by the proof, preserving D5 for
mixed-shape stores).

### Scenario D — you adopt form (b) manifest reference

**Use case:** you have a tightly-controlled schema generated by an
external migration tool, or you want a single canonical file the
operator + the compiler + a contract test all read.

**Workflow:**

1. **Generate the manifest from your live DB:**
   ```bash
   axon store introspect users > schemas/users.axon-schema.json
   ```
   This emits a canonical JSON manifest with a verified `content_hash`
   for every `users` store table the running server can see. Columns
   whose `pg_type` is outside the closed catalog are dropped with an
   `# omitted: column \`X\` (pg type \`Y\`) — …` honest comment in the
   stream (not in the JSON itself; the JSON stays strict).

2. **Reference it from your `.axon`:**
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

3. **Wire `--schemas-dir` at boot:**
   ```bash
   axon serve --schemas-dir schemas
   # or set AXON_SCHEMAS_DIR=schemas in your environment
   ```

**Effect:** identical compile-time proof to form (a), plus the
manifest is a single canonical source for compiler + operator + CI.
Editing the manifest by hand requires recomputing the `content_hash`
(T805 catches a stale hash); the round-trip through `axon store
introspect` regenerates it.

**Action:** the three commands above. T805/T807 errors at deploy
become your contract gate.

### Scenario E — you adopt form (c) per-tenant env-var

**Use case:** schema-per-tenant deployments (the canonical SaaS
multi-tenant shape — every tenant has its own Postgres schema,
populated by a CI-driven migration). The same `.axon` source serves
every tenant; the live namespace is decided per-deploy via env var.

**Workflow:**

1. **Adopt form (c) on the store:**
   ```axon
   axonstore usage {
     backend: postgresql
     connection: env:DATABASE_URL
     table: "usage"
     schema: env:TENANT_SCHEMA
   }
   ```

2. **Emit one manifest per tenant** (under `schemas/`):
   ```bash
   TENANT_SCHEMA=tenant_alpha axon store introspect usage \
     > schemas/usage.tenant_alpha.axon-schema.json
   TENANT_SCHEMA=tenant_beta axon store introspect usage \
     > schemas/usage.tenant_beta.axon-schema.json
   ```
   The manifests live under the resolved namespace key
   (`tenant_alpha.usage`, `tenant_beta.usage`).

3. **At deploy, set the env var per pod:**
   ```bash
   TENANT_SCHEMA=tenant_alpha \
     axon serve --schemas-dir schemas
   ```

**Effect:**

- The deploy-time verification resolves `usage` against the
  `tenant_alpha.usage` manifest entry — first-match heuristic prefers
  the exact `<namespace>.<store_name>` key; falls back to any
  `*.<store_name>` if exact-match fails.
- The connection's `application_name` is stamped
  `axon-store/usage/tenant_alpha` (Gap-3 inheritance), so a DBA on
  the database side sees the resolved tenant on every session.
- A missing `TENANT_SCHEMA` env var raises T806 with the variable
  name in the diagnostic.

**Action:** the three commands above. A new tenant onboarding adds
ONE manifest file + ONE env var on the pod; no `.axon` source
changes.

### Scenario F — your deploy now fails with `phase: store_schema_manifest_load`

```text
POST /v1/deploy → 200 OK
{
  "success": false,
  "error": "failed to load store-schema manifests from `schemas`:
            store-schema manifest `content_hash` mismatch (axon-T805)…",
  "phase": "store_schema_manifest_load",
  "d_letter": "D3+D8",
  "schemas_dir": "schemas"
}
```

**Cause:** a `*.axon-schema.json` under `--schemas-dir` is malformed,
declares a stale `content_hash`, or declares the SAME store name as
another file in the directory (cross-file duplicate).

**Action — pick one:**

- **T805 hash mismatch:** the file was hand-edited without
  recomputing the hash. Regenerate it: `axon store introspect <store>
  > <file>`. The introspect emitter computes the canonical hash for
  you. A manifest without a `content_hash` field is also valid —
  drop the field if you don't need tamper-evidence on disk.
- **DuplicateStore across files:** two files declare the same store
  name (e.g. `users.axon-schema.json` AND `audit.axon-schema.json`
  both have a `users` entry). Resolve by giving each file a unique
  `stores` map. The error names the offending store + both file
  paths.
- **Malformed JSON / unknown column type:** the error message names
  the offending file + the parse failure. The closed 15-type catalog
  is the canonical reference; a column type outside it must be
  dropped from the manifest (the runtime keeps the column — the
  manifest only declares the columns the compile-time proof tracks).

After fixing, redeploy. If you want to disable form (b)/(c) entirely
for a single deploy without removing the manifests, drop the
`--schemas-dir` flag — the deploy reverts to the v1.37.0 verification
path verbatim (D5 absolute).

---

## CI integration

Fase 38 ships a dedicated GitHub Actions workflow:
`.github/workflows/fase_38_typed_store_schema.yml`. **Five parallel
lanes:** pure-column-proof (no DB), manifest-roundtrip (parse →
canonical → SHA-256), per-tenant-resolution (env-var first-match +
`application_name` Gap-3 stamping), declared-vs-live-drift (the 38.j
plumbing pack — `axon serve --schemas-dir` end-to-end), d5-zero-
regression (Fase 35 + 37.x corpora unchanged).

Adopters mirroring this workflow into their own CI gain the same
guarantees: a column name typo never reaches a code review, let alone
production.

---

## Closing — what stays the same

Everything outside the declared-schema contract. The `axonstore`
shape, the `connection: env:VAR` convention, the `where:` clause
language, the four `axonstore` ops (`retrieve` / `persist` /
`mutate` / `purge`) + `stream` cursor, every Fase 37.x pooler-
coherence guarantee, every Fase 35 cognitive-data-plane invariant.
v1.38.0 layers a declared, verifiable shape on top of a contract
that already works at runtime — it does not redefine the contract.
