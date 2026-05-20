---
title: "Plan vivo: Fase 38 — The Declared & Compile-Time-Typed Store Schema (an `axonstore`'s columns become a COMPILE-TIME type the type-checker proves every `where:`, every `persist`, every `mutate`, every `purge` against — the genuinely-superior compile-time half of Fase 37.x's runtime+deploy contract, named and committed there as the immediate next cycle)"
status: ⏳ OPEN — created 2026-05-19, the moment Fase 37.x closed (v1.37.0 live cross-stack + axon-enterprise v1.28.0 catch-up live). D1–D10 RATIFIED (founder bloque, 2026-05-19). **Sub-fases 38.b + 38.a SHIPPED** 2026-05-19 (inversion order — 38.b parser surface first, 38.a anchor on top per the plan-vivo §38.a honest-scope clause). 38.c–38.k ⏳ pending. Triggered by the §7 commitment Fase 37.x landed on 2026-05-19: *"the genuinely-superior axon end-state — the type-checker proves every `where:` column and every `persist`/`mutate` field against a declared/verified column schema, exactly as Fase 35 Pillar IV proves the store CAPABILITY and Fase 37 proves the request BINDING — is Fase 38: The Declared & Compile-Time-Typed Store Schema, named and committed here as the immediate next cycle."* Target axon-lang **v1.38.0** (minor — opens a new `schema:` field on `axonstore` + adds a new `axon check`-time column-type proof gate; SemVer-strict, a new declarable surface that affects compile output earns a minor). Rust-canonical (per the founder directive 2026-05-15 *"todo encaminado a ser 100% Rust + C, 0 Python"*) — the cycle lives in `axon-frontend/` (the Rust type-checker) + adds a thin runtime hook in `axon-rs/src/store/`.
owner: AXON Language + Runtime Team
created: 2026-05-19
target: axon-lang v1.38.0 (minor — new optional `schema:` field on `axonstore` + new `axon check` column-type proof + new `axon store introspect` manifest export + extended `POST /v1/deploy` gate; D5 absolute — an `axonstore` without a `schema:` declaration behaves byte-identically to v1.37.0).
depends_on: |
  Fase 37.x CLOSED 2026-05-19 (v1.37.0 — The Pooler-Coherent Store Contract; D1 search-path-independent resolution via `pg_catalog`; D2 schema-anchored operation SQL; D3 one coherent introspect-and-operate transaction; D4 equality type-agnostic fallback; D5 symmetric + backwards-compat; D6 honest typed failure with actionable Display; D7 PgBouncer transaction-mode CI lane; D8 eager deploy-time schema verification; D9 self-healing bounded LRU schema cache; `resolve_from_rows` + `is_schema_drift_sqlstate` already `pub` — the surface Fase 38's compile-time gate proves against IS the surface 37.x proves at deploy + runtime). Fase 37 SHIPPED (v1.36.0 — The Request Binding Contract; `${param}` from the request body reaches a store `where:` clause as a `$N` bind parameter — Fase 38 extends the binding's totality to its column-type compatibility). Fase 35 SHIPPED (v1.30.0 — `axonstore` substrate; `IRAxonStore` IR node, `PostgresStoreBackend`, the 4 pure SQL builders, the `parse_filter` AST, `confidence_floor` Pillar I, audit-chain Pillar II, `Stream<Row>` Pillar III, capability-typed Pillar IV — the four pillars Fase 38 layers a fifth on top of: typed columns). Fase 28 SHIPPED (v1.20.0 — diagnostic robustness; rustc-style source-context blocks + Levenshtein "Did you mean X?" hints + `axon check` JSON output — Fase 38's column-suggestion diagnostics inherit this surface).
charter_class: |
  OSS end to end. The `schema:` declaration grammar, the `axon check`-time column-type proof, the manifest format, the introspection export — all are core compile-time / runtime infrastructure and adopter-agnostic. Per-tenant + per-vertical store policy and vertical-specific schema R&D already layer ON TOP of the OSS substrate (axon-enterprise vertical shields consume an OSS-typed store, never the other way) and remain untouched. 38.k is **SPLIT** only mechanically — axon-lang v1.38.0 (OSS) plus an axon-enterprise version-bump catch-up (v1.29.0 — dep pin advance, no enterprise code change), the same lean-catch-up shape as every minor since v1.9.0.
strategic_direction: Rust-canonical, per the founder directive 2026-05-15 (*"todo encaminado a ser 100% Rust + C, 0 Python"*). The compile-time proof lives in `axon-frontend/src/` (Rust); the runtime hook lives in `axon-rs/src/store/`. The Python frontend stays at its v1.33.0 interpolation mirror — Fase 38's `schema:` declaration parses harmlessly in Python (a flow that does not use the compile-time gate still runs); the type-checker's column-type proof is Rust-canonical and surfaces via `axon check` / `POST /v1/deploy`.

pillars: |
  An agent's memory is a database. Fase 35 made the store real (Pillar I
  epistemic, Pillar II audit-chained, Pillar III streaming, Pillar IV
  capability-typed). Fase 37 made the agent SEE its request and bind a
  `${param}` to a `$N`. Fase 37.x made the typed-column read/write
  unconditionally pooler-coherent — every pooled session resolves, every
  pooled session succeeds.

  But the COLUMN itself remained an untyped string from the language's
  perspective. A `where: "tenant_id = ${tenant_id}"` against a table that
  spells the column `tenantid` (no underscore) compiled clean and failed
  at runtime — exactly the regression-class Fase 32 closed for route
  bodies (typed `body: T`) and Fase 36 closed for backends (declared,
  resolved, observable). The store column was the last untyped surface in
  the cognitive data plane.

  Fase 38 closes it. An `axonstore`'s columns become a COMPILE-TIME type
  the type-checker proves every `where:`, every `persist`, every `mutate`,
  every `purge` against — the FIFTH pillar of the cognitive data plane:

  - **DECLARED.** An `axonstore` may declare its column schema directly
    (an inline `columns { tenant_id: Uuid, tier: Text, created_at:
    Timestamptz }` block) OR by reference (`schema: "public.tenants"`
    pointing at a verified manifest entry) OR by per-tenant resolution
    (`schema: env:TENANT_SCHEMA` — a fixed schema name resolved at deploy
    from the named environment variable, in the same shape as
    `connection: "env:DATABASE_URL"`). All three forms are optional —
    D5 absolute, an undeclared `schema:` is byte-identical to 37.x.

  - **PROVEN.** When a `schema:` is declared, `axon check` proves every
    `where:` column reference, every `persist`/`mutate` field name + value
    type, every `purge` `where:` column against the declared columns. An
    unknown column is a compile error with a Levenshtein "Did you mean
    X?" hint (Fase 28 inheritance). A type mismatch — a `String` flow
    parameter bound to a `Uuid` column — is a compile error naming the
    parameter, the column, and the expected vs. observed type.

  - **VERIFIED.** When a `schema:` is declared, `POST /v1/deploy` extends
    the 37.x D8 eager schema-verification: the declared columns must
    MATCH the live database's introspected columns (column names, types,
    nullability). A drift between declared and live FAILS the deploy
    honestly — the axon signature move applied to typed columns.

  - **CAPTURABLE.** A new `axon store introspect <store>` CLI exports
    the live schema as a checked-in `.axon-schema.yml` manifest — an
    adopter who runs `axon store introspect tenants > tenants.schema.yml`
    captures the live schema at a moment in time + commits it, then
    `axon check` against the captured manifest off line (no database
    required for compile-time correctness).

  The result: a `where: "tenant_id = ${tenant_id}"` against a typo'd
  column is a compile error, named at line + column with a suggestion.
  A `persist into tenants { tenant_id: ${tenant_id} tier: ${tier} }`
  against a `tier: enum('standard', 'premium')` column whose flow binds
  `tier: String` is a compile error. The failure moves from runtime
  (pre-37.x) → deploy (37.x D8) → **compile time** (Fase 38).

  This is the FIFTH pillar — the load-bearing axon claim made literal at
  the store substrate: every adopter dimension that matters (epistemic
  trust, audit chains, streaming, capability, **column type**) is proven
  before a request is served.

# ▶ 1. The triggering commitment (Fase 37.x §7, 2026-05-19)

Fase 37.x's plan vivo §7 named Fase 38 explicitly + scoped it:

> *"The genuinely-superior axon end-state — the type-checker proves
> every `where:` column and every `persist`/`mutate` field against a
> declared/verified column schema, exactly as Fase 35 Pillar IV proves
> the store CAPABILITY and Fase 37 proves the request BINDING — is
> **Fase 38: The Declared & Compile-Time-Typed Store Schema**, named and
> committed here as the immediate next cycle. Fase 38 adds the optional
> `schema:` declaration on `axonstore` (and `schema: env:VAR`, for the
> schema-per-tenant topology a large multi-tenant adopter runs) plus the
> `axon check` / deploy-time column-type proof. 37.x's `resolve_table`
> is built forward-compatible — it consumes a declared schema the moment
> Fase 38 supplies one."*

37.x's `StoreError::AmbiguousTable` Display already explicitly points
at this cycle:

> *"…either narrow the role's `search_path` so exactly one of the
> resolving schemas is visible, or declare the target schema explicitly
> on the `axonstore` (the Fase 38 `schema:` declaration, incl. `schema:
> env:VAR` per-tenant)."*

And the published MIGRATION_v1.37 / ADOPTER_AXONSTORE §11.4 / AXON_GAP
resolution note ALL point adopters at the same future:

> *"§11.4 …declare the target schema on the `axonstore` (the
> genuinely-superior remedy, the multi-schema case anchored to its
> compile-time half). Available in axon-lang Fase 38 — the
> compile-time-typed schema companion to 37.x."*

Fase 38 is not new scope — it is the second half of a contract 37.x
shipped the first half of. The adopter docs already promise this. The
plan exists to honor that promise on a calendar.

# ▶ 2. The three findings 37.x left for 38 to close

37.x made the runtime+deploy correct. Three things 37.x INTENTIONALLY
deferred — every one a compile-time concern by nature:

**Finding 38-A — column-name typos pass `axon check`.** Today, `where:
"tenantid = ${tenant_id}"` (the column is actually `tenant_id`) parses
clean, type-checks clean, deploys clean. The failure surfaces at the
first runtime request as a `column "tenantid" does not exist` from
Postgres. Fase 37.x's D6 makes the *table*-resolution failure
actionable; it does NOT catch a column typo because at the language
level the column is just a string token inside the `where:` expression.

**Finding 38-B — type mismatches between a flow parameter and the
column it binds pass `axon check`.** Today, a flow parameter
`tenant_id: String` bound into `where: "tenant_id = ${tenant_id}"`
against a `tenant_id UUID` column type-checks clean. The 37.x runtime
casts (`$N::uuid` from D4's introspected map), so the operation
*succeeds* — but if the parameter type is incompatible (e.g. an `Int`
parameter against a `Text` column with non-numeric values), the
runtime cast fails. The language never told the developer.

**Finding 38-C — `persist`/`mutate` field-block columns are not
proven against the table's columns until deploy (37.x D8) or runtime
(pre-37.x).** A `persist into tenants { tenantid: ${tenant_id} }` —
a typo — fails at deploy under 37.x D8 (eager schema verification
catches the typo against the live introspection). But D8 needs a
reachable database; in CI without a live DB, the typo passes. Fase 38
makes the proof offline: an adopter checks in their schema manifest;
`axon check` proves against it without a database.

These three are deliberate 37.x deferrals — 37.x is the
runtime+deploy half; Fase 38 is the compile-time half. The two halves
together make the cognitive-data-plane's typed-column surface complete.

# ▶ 3. The Declared & Compile-Time-Typed Store Schema Contract (the heart)

For every `axonstore` Postgres declaration:

**DECLARED (D1).** An `axonstore` may carry an optional `schema:` field
in three forms:

- **Inline column block** — the column schema declared in-source:
  ```axon
  axonstore tenants {
      backend: postgresql
      connection: "env:DATABASE_URL"
      schema: {
          tenant_id: Uuid
          tier:      Text
          created_at: Timestamptz
      }
  }
  ```
- **Manifest reference** — the column schema declared in a separate
  checked-in `.axon-schema.yml` (or `.axon-schema.json`), referenced by
  qualified name:
  ```axon
  axonstore tenants {
      backend: postgresql
      connection: "env:DATABASE_URL"
      schema: "public.tenants"   // resolves against the manifest entry
  }
  ```
- **Per-tenant env-var resolution** — the *schema namespace* (not the
  column schema) declared via env-var, in the same shape as `connection:
  "env:VAR"`:
  ```axon
  axonstore tenants {
      backend: postgresql
      connection: "env:DATABASE_URL"
      schema:     env:TENANT_SCHEMA
  }
  ```
  This last form is the schema-per-tenant topology — `TENANT_SCHEMA`
  resolves to e.g. `tenant_42` at deploy, and the column schema is
  proven against the manifest entry for `tenant_42.tenants`.

Per-tenant + manifest forms compose: a manifest can declare schemas for
multiple per-tenant namespaces, and `schema: env:TENANT_SCHEMA` resolves
into the right one.

**PROVEN (D2).** When a `schema:` is declared, `axon check` proves:

- **`where:` column references** — every column name in every `where:`
  clause exists in the declared schema (a typo is a compile error with
  a Levenshtein "Did you mean X?" hint).
- **`where:` value type compatibility** — the value side of every
  comparison is type-compatible with the column's declared type (a
  `String` parameter into a `Uuid` column is a compile error, naming
  both types).
- **`persist`/`mutate` field-block names** — every field name on the
  left of a `persist { col: value }` or `mutate { col: value }` block
  exists in the declared schema (a typo is a compile error).
- **`persist`/`mutate` field-block value types** — every value side
  is type-compatible with the named column's declared type.
- **`purge`/`mutate` `where:` columns** — same proof as `where:` above.
- **NOT-NULL discipline** — a `persist` that omits a NOT-NULL column
  with no default is a compile error.

The proof is TOTAL — every store operation in every flow in the
deployed source surface is type-checked end-to-end before deploy can
proceed.

**VERIFIED (D3 + extending 37.x D8).** When a `schema:` is declared,
`POST /v1/deploy` extends 37.x's D8 eager-resolution gate: the live
database's introspected columns must MATCH the declared columns. A
drift — a column present in the manifest but missing in the live DB, a
type that doesn't match, a NOT-NULL that's actually NULLABLE — FAILS
the deploy honestly with a precise `SchemaDeclaredColumnMismatch`
diagnostic. The 37.x D8 gate is generalized: an undeclared `schema:`
runs the unchanged D8 (existence check); a declared `schema:` runs the
stricter declaration-vs-live check.

**CAPTURABLE (D10).** A new `axon store introspect <store>` CLI
exports the live schema:

```sh
axon store introspect tenants > tenants.schema.yml
```

The exported manifest is canonical YAML (or JSON via `--json`) with a
content-hash header so a CI can verify the captured manifest didn't
drift since the last `axon check`. An adopter commits the manifest,
then `axon check` against the manifest off line: no database needed
for compile-time correctness, and the manifest IS the typed contract
between the language and the live database.

**The contract in one line:** an `axonstore` declares its columns,
`axon check` proves every store reference against the declaration,
`POST /v1/deploy` verifies the declaration matches the live database
— so the failure of an unknown column or a type mismatch moves from
runtime to compile time, the axon signature move applied to the store
substrate.

# ▶ 4. D-letters (D1–D10 — DRAFTED 2026-05-19, awaiting founder ratification)

| D | Decision |
|---|---|
| **D1** | **`schema:` declaration grammar — three closed forms.** An `axonstore` carries an OPTIONAL new `schema:` field with exactly three allowed shapes: (a) **inline column block** — `schema: { col: Type, ... }` with the closed type catalog `{Uuid, Text, Int, BigInt, Float, Double, Bool, Timestamptz, Timestamp, Date, Time, Jsonb, Json, Bytea, Numeric}` (the v1.30.0 supported catalog, mirrored as a language-level type for the first time); each column may carry an optional `not null` / `nullable` annotation (default: `nullable` — Postgres default); (b) **manifest reference** — `schema: "<qualified.name>"` resolving against `.axon-schema.yml` manifest entries (the schema-resolver searches `./`, `./schemas/`, and a path declared in `axonproject.toml`); (c) **env-var schema namespace** — `schema: env:VAR` declares the *schema namespace* (the SQL schema name like `public` / `tenant_42`), resolved at deploy from the env var — the COLUMN schema then comes from a manifest entry keyed on the resolved namespace + the table name. Forms (a) + (b) are mutually exclusive on the same `axonstore`; form (c) composes with (b) (the env-var resolves the namespace, the manifest declares the columns). |
| **D2** | **Column-type proof at `axon check`.** The type-checker grows a new `StoreColumnProof` pass that runs after `parse_filter` (Fase 37 D2) and before backend resolution (Fase 36 D4). For every `IRAxonStoreOp` (`retrieve`/`persist`/`mutate`/`purge`/`stream_retrieve`), the pass: (i) resolves the store's declared column schema (D1) — when ABSENT, skips the proof (D5 absolute); (ii) parses the `where:` clause's column references via the existing 35.b `parse_filter` AST (no new parser surface); (iii) proves every referenced column exists in the declared schema; (iv) proves the value side of every comparison is type-compatible with the column type (the type lattice: a flow parameter `tenant_id: String` is compatible with `Uuid` IFF the value is a canonical-form UUID literal at compile time, otherwise it's a compile error suggesting a `Uuid` parameter type); (v) for `persist`/`mutate`, proves every field-block column exists + its value type is compatible. Every proof failure is a typed `axon-T8xx` error with line+column, the offending column, the declared columns sorted by Levenshtein distance, the actionable remedy. |
| **D3** | **Per-tenant `schema: env:VAR`.** The `schema: env:VAR` form follows the v1.36.3 `connection: env:VAR` precedent — the env var resolves at DEPLOY (not at every request: a per-request schema name is a deliberate non-feature; the schema is a contract, the per-request dimension is the request body). The resolved value is validated against the closed identifier alphabet `[A-Za-z_][A-Za-z0-9_]*` (≤ 63 bytes — Postgres `NAMEDATALEN-1`), and the value is then plugged into the manifest's per-namespace lookup. A missing env var at deploy is a typed `StoreError::MissingSchemaEnv` failure — the deploy fails, never falls back silently. The resolved schema is stamped into the `application_name` (`axon-store/<store>/<schema>`) so a DBA can see at a glance which tenant a session belongs to (Gap-3 inheritance). |
| **D4** | **Manifest format — adopter-authored OR introspected, same shape.** `.axon-schema.yml` is a canonical YAML document with a closed top-level structure: `version: 1`, `stores: <store_name>: { columns: { col: { type: <CatalogType>, nullable: bool, default: <literal?> } } }`. The format is canonical (key-sorted at every level + UTF-8 + LF newlines) so `axon store introspect` and an adopter-authored file produce byte-identical output when they describe the same columns — diffs are real, never reorder noise. A `--content-hash` line on top binds the manifest to its content; `axon check` verifies the hash matches before consuming it (so a hand-edit gets flagged unless `--recompute-hash` is passed). JSON is supported as an alternative (`.axon-schema.json`) with the same canonical-ordering discipline. Both shapes are produced by `axon store introspect` (D10) and consumed by `axon check` (D2). |
| **D5** | **Absolute backwards-compatibility — an undeclared `schema:` is byte-identical to v1.37.0.** Every `axonstore` declaration that doesn't carry `schema:` runs the exact 37.x runtime+deploy path unchanged: D8 eager existence check at deploy, D1+D2+D3+D4+D9 at runtime. The `IRAxonStore` IR node gains an optional `column_schema: Option<StoreColumnSchema>` field; absent means "operate as 37.x" verbatim. No flow that doesn't opt into the `schema:` declaration regresses. The published 37.x adopter guarantee (D5 absolute against v1.36.5 and prior) extends transitively. |
| **D6** | **Honest failure with Levenshtein suggestions (Fase 28 inheritance).** Every Fase 38 compile error inherits the Fase 28 diagnostic shape — rustc-style source-context (line + caret + 2 lines before/after), Levenshtein "Did you mean X?" suggestions (≤ 2 edit distance, max 3 candidates), structured JSON when `--json` flag is passed, machine-readable error codes (`axon-T801` unknown column, `axon-T802` column-type mismatch, `axon-T803` persist NOT-NULL omission, `axon-T804` mutate field-name typo, `axon-T805` manifest hash mismatch, `axon-T806` per-tenant env-var unset, `axon-T807` declared-vs-live drift at deploy). Every error surfaces structurally to the LSP (the axon-lsp project consumes this surface in its v0.2.0). |
| **D7** | **The production gate — dedicated CI lane.** A new CI workflow `.github/workflows/fase_38_typed_store_schema.yml` with FIVE parallel lanes: (1) **pure-column-proof** — `axon check` against a manifest matrix (typo / type-mismatch / NOT-NULL omission / unknown column / good-case) covering every D2 error code, no DB; (2) **manifest-roundtrip** — `axon store introspect` against a Postgres service container produces a manifest, then a smoke `axon check` consumes it back and proves a sample flow — both directions must be byte-identical to a checked-in golden; (3) **per-tenant resolution** — `schema: env:TENANT_SCHEMA` resolving across 3 tenant namespaces in one source surface; (4) **declared-vs-live drift** — `POST /v1/deploy` against a database whose introspected columns intentionally drift from the declared manifest, asserting the deploy FAILS with `axon-T807`; (5) **D5 zero-regression** — every Fase 35 + Fase 37 + Fase 37.x test target re-run with the new IR field present-but-empty, byte-identical results. A `fase-38-summary` gate job needs all five. |
| **D8** | **Extending 37.x D8 — declared-vs-live deploy verification.** 37.x D8 verifies a declared `postgresql` store's table EXISTS on a reachable database. Fase 38 D8 strengthens it: when a `schema:` declaration is present, the verification proves every declared column EXISTS in the live introspection AND its type MATCHES AND its `not null` annotation MATCHES (the manifest's `default` is informational — Postgres provides the default, axon doesn't override it). A drift fails the deploy with `axon-T807` naming the column, the declared shape, the live shape, the actionable remedy (run `axon store introspect <store>` to refresh the manifest, run the missing migration, or fix the declaration). An unreachable store at deploy remains a non-fatal warning (37.x's "deploy is honest, never brittle" preserved). The verified-then-warm-the-cache property of 37.x D8 continues — the live introspection becomes the warm cache the first runtime operation hits, and the declared schema is used to pre-render schema-qualified SQL templates without an introspection round-trip at all. |
| **D9** | **Cross-stack parity — Python frontend is informed but not load-bearing.** The Rust frontend (`axon-frontend`) is the authoritative type-checker for the D2 column-type proof. The Python frontend (per the founder Rust-canonical directive 2026-05-15 + the `feedback_axon_for_axon`-style charter) parses the `schema:` field cleanly (so a `.axon` source is portable) but does NOT run the D2 proof. A drift-gate corpus (`tests/fase38_cross_stack_drift.rs`) asserts Python's IR for a `schema:`-carrying source is structurally compatible with Rust's IR (same node names, same children); the *proof verdict* is Rust-authoritative. The Python runtime executes flows using its v1.33.0 interpolation mirror unchanged — Fase 38 is a compile-time gate, not a runtime behavior change for the Python side. |
| **D10** | **`axon store introspect <store>` CLI — manifest export.** A new CLI command exports the live schema of a declared `postgresql` store: `axon store introspect <store_name> [--manifest=<path>] [--json]` opens the store's resolved DSN (37.x infrastructure), introspects via `pg_catalog` (37.x's `introspect_conn`), maps every introspected Postgres type to the closed catalog of D1 (an unmappable type — `enum`, `domain`, array, `citext`, PostGIS — is an HONEST `UnsupportedColumnType` error with the type name; the column is OMITTED from the manifest with a comment line, never silently lossily mapped), writes the canonical-format manifest with a content hash. The introspection is itself bounded — `axon store introspect *` against a database with 10 000 tables exports all of them, but each individual call is one round-trip per table; the existing per-`(dsn, table)` cache (37.x D9) accelerates a refresh. A `--diff` mode prints just the columns that drifted vs. the existing manifest, for CI use. |

# ▶ 5. Sub-fases (38.a–38.k — topologically ordered)

| Sub-fase | What | Class | D-letters | Status |
|---|---|---|---|---|
| **38.b** | **`schema:` grammar — parser + AST cross-stack.** Add the new `schema:` field to `axonstore` in both frontends (Rust authoritative per D9; Python parses-but-skips-proof). New AST node `StoreColumnSchema` (inline) + `StoreSchemaRef` (manifest ref) + `StoreSchemaEnvVar` (env-var namespace). Closed type catalog (D1): exactly the 15 types `{Uuid, Text, Int, BigInt, Float, Double, Bool, Timestamptz, Timestamp, Date, Time, Jsonb, Json, Bytea, Numeric}`. Grammar enforces the three closed forms — anything else is a parse error with a precise message. The `IRAxonStore` IR node gains an `Option<StoreColumnSchema>`. The schema:-declared AST surfaces in Fase 28's diagnostic infrastructure (every parse error is a Fase 28 source-context block + JSON output). NO type-checking yet — the AST is captured, downstream passes are still 37.x semantics. | OSS | D1, D5 | ✅ SHIPPED — landed FIRST (the plan-vivo §5 38.a honest-scope correction was applied: 38.a's §1-§3 anchors require the 38.b parser surface to synthesize their inputs, so 38.b ships before 38.a in implementation order). NEW `axon-frontend/src/store_schema.rs` (~300 LOC): `StoreColumnType` enum with `canonical_name` / `from_token` (alias map covering `int`/`integer`/`int4`→`Int`, `boolean`→`Bool`, `decimal`→`Numeric`, `varchar`/`string`→`Text`, etc.) / `ALL` slice; `StoreColumn` struct with constraints (primary_key/auto_increment/not_null/unique/default); `StoreColumnSchema` enum with 3 variants + `is_inline`/`inline_columns`/`loc`/`form_name` helpers. `axon-frontend/src/ast.rs` — `AxonStoreDefinition.column_schema: Option<StoreColumnSchema>` field added. `axon-frontend/src/ir_nodes.rs` — `IRAxonStore.column_schema: Option<IRStoreColumnSchema>` field + tagged-union mirror types (`IRStoreColumnSchema::{Inline, ManifestRef, EnvVar}` with `#[serde(tag = "form", rename_all = "snake_case")]`) + `IRStoreColumn`. `axon-frontend/src/parser.rs` — REMOVED the pre-38 skip-structurally hook; added `parse_store_schema_declaration` dispatcher (LBRACE → inline; COLON + STRING → manifest_ref OR env_var-quoted; COLON + `env:VAR` → env_var-unquoted). `axon-frontend/src/ir_generator.rs` — `lower_column_schema` + `lower_column` thread the 3 AST variants to IR; `visit_axonstore` populates `column_schema`. Python side: `axon/compiler/ast_nodes.py` — `STORE_COLUMN_TYPE_CATALOG` constant + `STORE_COLUMN_TYPE_ALIASES` map + `canonicalize_store_column_type` helper + new `StoreSchemaRefNode` + `StoreSchemaEnvVarNode` dataclasses; `AxonStoreDefinition.schema` typed as the union. `axon/compiler/parser.py` — new `_parse_store_schema_declaration` dispatcher (mirror of Rust's); `_parse_store_column` enforces the closed catalog with Levenshtein hint on miss + normalises to canonical PascalCase. `axon/compiler/ir_nodes.py` — new `IRStoreSchemaRef`/`IRStoreSchemaEnvVar`; `IRAxonStore.schema` typed as the union. `axon/compiler/ir_generator.py` — `_visit_axonstore` lowers via isinstance dispatch. 7 axon-rs literal call-sites updated with `column_schema: None,` (3 src + 4 tests). D9 cross-stack drift gate: new `tests/fixtures/fase38_b_schema_drift/corpus.json` (7 canonical entries: inline minimal / inline constraints / alias normalisation / manifest ref / env-var unquoted / env-var quoted / D5 no-schema) + new `axon-frontend/tests/fase38_b_schema_drift_gate.rs` (Rust side, 1 test walking the corpus) + new `tests/test_fase38_b_schema_drift.py` (Python side, 7 parametrised tests). Drift between stacks fails exactly one pack. **Verification**: 270 axon-frontend lib (+8 from `store_schema::tests`) + 11 fase38_b_schema_grammar + 1 fase38_b_schema_drift_gate (Rust) + 7 fase38_b_schema_drift (Python) + 2077 axon-rs lib + 48 axon-rs integration (fase35_l 17 + fase37x_a 5 + fase35_fuzz 6 + fase37_d 9 + fase37_g 3 + fase37x_i_pgbouncer 4 + fase37x_i_property_fuzz 4) + 74 Python contract/cli/golden sweep = **~2488 tests green**. Zero regressions. **D5 absolute upheld** — the IR JSON of an undeclared-schema store is byte-identical to v1.37.0 (`#[serde(skip_serializing_if = Option::is_none)]` on `column_schema`). |
| **38.a** | **Diagnostic anchor** — a committed test pinning the pre-Fase-38 broken state, so every later sub-fase inverts a §-assertion. Tests `axon-frontend/tests/fase38_a_typed_store_diagnostic.rs`. §1 pins finding 38-A: a flow with `where: "tenantid = ${tenant_id}"` against a `tenants` store with `schema: { tenant_id: Uuid }` declared currently passes `axon check` (the column-typo proof does not exist yet) — 38.d inverts. §2 pins 38-B: `where: "tenant_id = ${some_int}"` with `tenant_id: Uuid` declared and `some_int: Int` parameter currently passes — 38.d's type-mismatch arm inverts. §3 pins 38-C: `persist into tenants { tenantid: ${tenant_id} }` currently passes `axon check` (no field-name proof) — 38.e inverts. §4 pins the absence of a `schema:` parser surface — currently a parser error or silent drop — 38.b adds the grammar. §5 pins the absence of `axon store introspect` — 38.h adds it. Honest scope: §1-§3 require the 38.b parser surface to even synthesize the inputs; this anchor lives as a 38.b-dependent commit, NOT a pre-38.b standalone (the runtime-only 37.x.a precedent doesn't apply — Fase 38 is a compile-time cycle, the inputs need the grammar). | OSS | — | ✅ SHIPPED — `axon-frontend/tests/fase38_a_typed_store_diagnostic.rs` (5 tests, all green). §1 **finding 38-A**: `where: "tenantid = ${tenant_id}"` typo + declared `schema { tenant_id: Uuid }` — `axon check` currently passes; 38.d's `axon-T801` unknown-column-with-Levenshtein-hint inverts in place. §2 **finding 38-B**: `where: "tenant_id = ${tenant_id}"` with parameter `Int` + declared `Uuid` — currently passes; 38.d's `axon-T802` type-mismatch arm inverts in place. §3 **finding 38-C**: `persist into tenants { tenantid: "${tenant_id}" }` field-name typo — currently passes; 38.e's `axon-T804` inverts in place. §4 **regression guard (already inverted by 38.b)**: the 3 closed `schema:` declaration forms (inline / manifest_ref / env_var) parse + lower to the right IR variant with the right `form` discriminator. §5 **§-assertion observing absence**: `axon::store_introspect` module is absent; 38.h flips this to a presence-guard the moment the CLI lands. Each §-assertion documents its inversion contract verbatim so the test author flipping it has a script. **Inversion-as-implementation-order correction**: the plan-vivo's natural-order table (a then b) was inverted in implementation order (b first, a on top) per 38.a's honest-scope clause — the inputs need the grammar. Both sub-fases shipped 2026-05-19. 5/5 anchor + 11/11 grammar + 1/1 drift + 7/7 Python drift all green. |
| **38.c** | **Manifest format + resolver.** Define the canonical `.axon-schema.yml` shape (D4) — closed top-level structure, key-sorted at every level, UTF-8+LF, optional `--content-hash` header. New `axon-frontend/src/store_schema_manifest.rs` provides `parse_manifest`, `lookup(manifest, store_name) -> StoreColumnSchema`, `canonical_serialize(schema) -> String` (the byte-deterministic output `axon store introspect` produces). JSON variant supported (`.axon-schema.json`) with the same canonical discipline. Manifest discovery: `./`, `./schemas/`, and a `[axon] schema_path` in `axonproject.toml`. Content-hash verification (SHA-256 over canonical content); `axon check` flags a stale hash with `axon-T805`. 12+ unit tests covering canonical ordering, hash verification, multi-store manifests, JSON↔YAML parity. | OSS | D4, D6 | ⏳ pending |
| **38.d** | **`axon check` column-type proof for `where:` (D2 first half).** New `axon-frontend/src/store_column_proof.rs` ships `StoreColumnProof::check_filter(filter_ast, declared_columns)`. Reuses the existing 35.b `parse_filter` AST (no new parser surface). Three error codes: `axon-T801` (unknown column) with Levenshtein ≤2 "Did you mean X?" suggestions (max 3); `axon-T802` (column-type mismatch) naming declared vs observed type + the parameter or literal that caused the mismatch; `axon-T805` (manifest hash mismatch — fires before the column proof, so a stale manifest gives the right error). The proof skips silently when no `schema:` is declared (D5 absolute). Every error is a Fase 28 source-context block + JSON output + LSP-compatible. 30+ unit tests covering known-good × unknown-column × type-mismatch × NULL-comparison × bound-`${param}` × literal × LIKE × `IS NULL` × all 15 catalog types. Anchor §1 + §2 INVERTED in place. | OSS | D2, D6, D5 | ⏳ pending |
| **38.e** | **`axon check` column-type proof for `persist`/`mutate`/`purge` (D2 second half).** Extend `store_column_proof.rs` with `check_persist(fields, declared_columns)`, `check_mutate(set_fields, where_filter, declared_columns)`, `check_purge(where_filter, declared_columns)`. Three new error codes: `axon-T803` (`persist` omits a NOT-NULL column with no default), `axon-T804` (field-name typo in `persist`/`mutate` with suggestions). `check_mutate` runs `check_filter` on the `where:` clause + the new field-block proof. `check_purge` is `check_filter` only (no fields). 25+ unit tests covering all 4 store ops × all 9 proof error codes × the 15-type catalog. Anchor §3 INVERTED in place. | OSS | D2, D6, D5 | ⏳ pending |
| **38.f** | **Per-tenant `schema: env:VAR` resolution (D3).** The deploy-time resolver in `axon-rs/src/store/registry.rs` extends 37.x's `verify_postgres_schemas` to honor a declared `schema: env:VAR` — the env var resolves to a SQL schema name (the namespace), the manifest is looked up by `<namespace>.<store_name>`, the proof runs against the resolved columns. A missing env var → `axon-T806` deploy failure (never a silent fallback). The resolved namespace is stamped into the `application_name` (Gap-3 inheritance: `axon-store/<store>/<namespace>`) so DBA tooling sees the tenant. 8+ deploy-handler tests + a 3-tenant CI lane (D7 lane 3). | OSS | D3, D6 | ⏳ pending |
| **38.g** | **Suggest dictionary integration — Levenshtein hints.** The Fase 28 Levenshtein "Did you mean X?" infrastructure is already in `axon-frontend/src/suggest.rs`. 38.g wires the column-name proof through it: the suggestion source is the declared schema's columns (a stable, closed set per store — not the Fase 29 vertical dictionary, which is for natural-language top-level keywords). Max 3 candidates within edit distance ≤2. Composite suggestions when a column AND a type both mismatch ("Did you mean column `tenant_id` (Uuid)?"). The vertical-aware dictionary path (Fase 29) layers ON TOP — e.g. an enterprise HIPAA vertical can register `medical_record_number` as a high-frequency synonym for `mrn`, which Fase 28's mechanism already supports. 12+ tests covering the Levenshtein boundary cases + multi-candidate ordering + composite-suggestion shape. | OSS | D6 | ⏳ pending |
| **38.h** | **`axon store introspect` CLI — manifest export (D10).** New subcommand `axon store introspect <store_name> [<store_name>...] [--manifest=<path>] [--json] [--diff]`. Opens the store's resolved DSN (37.x infrastructure), introspects via `pg_catalog` (37.x's `introspect_conn`), maps every Postgres type to D1's 15-type catalog. An unmappable Postgres type is an honest `UnsupportedColumnType` — the column is OMITTED from the manifest with a `# omitted: enum 'tier_enum'` comment, never silently lossily mapped (`enum` ≠ `Text`, even though they look alike at the wire). Writes canonical YAML by default, JSON with `--json`, `--diff` mode emits only the columns that changed vs. an existing manifest. `*` glob support — `axon store introspect *` introspects every declared `postgresql` store. The 37.x D9 schema cache speeds repeat calls. Anchor §5 INVERTED in place. 20+ unit tests + 5 integration tests (real Postgres). | OSS | D10, D6 | ⏳ pending |
| **38.i** | **Integration + property/fuzz tests.** Two new test targets. (a) `axon-frontend/tests/fase38_i_integration.rs` — end-to-end: parse a multi-store source with mixed inline/manifest/env-var declarations, run `axon check` against a curated 5-tenant manifest, assert every D2 error code fires for the right input + every good-case passes. (b) `axon-frontend/tests/fase38_i_property_fuzz.rs` — ~6 000 deterministic LCG iters across three surfaces: Surface A (`parse_manifest` totality — random YAML bodies including malformed; never panic, deterministic error mapping); Surface B (`StoreColumnProof::check_filter` totality — random parsed filter ASTs × random declared schemas; never panic, every verdict is a deterministic combination of declared columns + filter columns + parameter types); Surface C (`canonical_serialize` is a fixed point — serializing a parsed manifest then re-parsing yields a structurally-equal manifest; the hash matches its content). | OSS | D7, D5 | ⏳ pending |
| **38.j** | **CI lane + adopter docs.** `.github/workflows/fase_38_typed_store_schema.yml` with 5 parallel lanes (per D7): pure-column-proof, manifest-roundtrip, per-tenant resolution, declared-vs-live drift, D5 zero-regression. Adopter docs: `docs/ADOPTER_AXONSTORE.md` new top-level §17 "The Compile-Time-Typed Store Schema (v1.38.0)" with the 5 recipes (inline column block / manifest reference / per-tenant env-var / introspect-then-commit / migration-induced drift detection); `docs/MIGRATION_v1.38.md` with 6 scenarios A-F (no `schema:` — no change / opt into inline / opt into manifest / opt into per-tenant / `axon check` now reports column typos / deploy now fails on declared-vs-live drift); a new `docs/ADOPTER_TYPED_STORE.md` deep-dive on the 5-pillar story (the COLUMN pillar joining Epistemic + Audit + Streaming + Capability + **TypedColumn**); the `AXON_GAP_store_typed_columns_resolution.md` from 37.x extended with a closing paragraph naming the compile-time half delivered here. | OSS | D7, D6 | ⏳ pending |
| **38.k** | **Coordinated release** — axon-lang **v1.38.0** cross-stack (`bump-my-version` minor 1.37.0→1.38.0; crates.io + PyPI + GitHub Release + binaries). `axon-frontend` BUMPS to **0.19.0** — Fase 38 IS a frontend AST + type-checker change (the first since v1.37.0 left axon-frontend at 0.18.0). axon-enterprise catch-up — **v1.29.0** (image bump, dep pin `>=1.37.0`→`>=1.38.0`; same lean-catch-up shape as every minor since v1.9.0). | SPLIT | — | ⏳ pending |

**Total estimate: ~3 000–4 000 LOC** (the AST surface for the three
`schema:` declaration shapes + the manifest format + the
`StoreColumnProof` pass for the 4 store ops × 9 error codes + the
`axon store introspect` CLI + the per-tenant resolver hook + the 5-lane
CI + the property/fuzz pack + 3 adopter docs). Larger than 37.x in
sub-fase weight because the compile-time half is grammar + type-checker
+ manifest format + CLI + diagnostics — every one a new surface — while
37.x was a focused runtime correctness cycle. D5 zero-regression
absolute; built Rust-canonical.

# ▶ 6. OSS / ENTERPRISE / SPLIT classification

Fase 38 is **OSS** end to end — the `schema:` grammar, the
`StoreColumnProof` type-checker pass, the manifest format, the
introspection CLI, the per-tenant resolution mechanism — all are core
compile-time / runtime infrastructure and adopter-agnostic. There is
NO enterprise-only work in this cycle: vertical-specific store policies
(HIPAA PHI column annotations, FRE 502 privileged-column flagging, BSA
sanctions-screen-column tagging) are documented as a FUTURE Fase
38.x.enterprise once 38 ships, layered ON TOP of the OSS schema
declaration. 38.k is **SPLIT** only mechanically — axon-lang v1.38.0
(OSS) plus an axon-enterprise version-bump catch-up (v1.29.0, dep pin
advance, no enterprise code change — same lean-catch-up shape as every
minor since v1.9.0).

# ▶ 7. Honest scope

- **38 makes a column's type a compile-time type.** It does NOT make
  axon a full relational query language. A `where:` clause remains the
  Fase 35 filter grammar (one column = one value comparison, AND/OR
  composition, `IS [NOT] NULL`, `LIKE`); joins, subqueries, aggregations
  are NOT in scope. A flow that needs a join composes multiple
  `retrieve` operations (or uses a view declared at the database side).
  The "make axon a SQL-language replacement" line is deliberately not
  crossed — axon is a *cognitive* language; SQL is a data language; the
  store substrate is the *bridge*.
- **The closed catalog of 15 types is the v1.30.0 supported catalog,
  lifted to compile time.** Postgres types outside it — `enum`,
  `domain`, array, `citext`, PostGIS `geometry`, custom composites —
  remain `UnsupportedColumnType`. Broadening the catalog (38+) is a
  distinct robustness frontier; named here, not silently scoped out.
  The most common enterprise ask is `enum`; the cleanest path is to
  map a Postgres `enum` to a closed `Text` set (a closed-catalog
  `Enum<["standard", "premium"]>` type), proven at compile time. A
  future fase.
- **The `schema:` declaration is OPTIONAL.** D5 absolute. The 37.x
  runtime+deploy is the floor for stores that don't opt in. Adopters
  migrate one store at a time at their own pace; introspecting + adding
  a `schema:` block is incremental.
- **`axon store introspect`'s `enum`-omission rule.** When the live
  database has a column whose type doesn't map to the 15-type catalog,
  the manifest OMITS the column with a comment naming the type — never
  silently lossily maps it (`tier_enum` ≠ `Text` even though they look
  alike at the wire; an `enum` column has a closed value set the
  language doesn't yet model). The adopter sees the omitted column +
  decides: hand-author the manifest entry (the type system today only
  supports `Text`, accept the loss) OR wait for the `Enum<>` catalog
  extension.
- **Per-request schema is intentionally OUT of scope.** `schema:
  env:VAR` resolves at DEPLOY — once per process lifetime. A
  per-request schema name (the request body carries the tenant
  namespace, route the operation accordingly) is a distinct surface, a
  future fase; it changes the unit of compile-time proof (per-request
  proofs aren't pre-computable) and is a much larger design.
- **Manifest format is YAML/JSON, not `.axon` source.** The manifest is
  configuration data; axon source is executable language. Keeping them
  separate keeps the type-checker's input surface narrow + the
  introspection-export CLI a simple emitter. A future fase may add an
  inline `schema(...)` block as a sugared form, but the canonical
  format stays declarative.
- **The Python frontend is informed but not load-bearing.** Per the
  founder Rust-canonical directive 2026-05-15. A `.axon` source with a
  `schema:` declaration parses cleanly in Python (D9); the proof is
  Rust-authoritative; a flow that depends on the Python runtime (a
  legacy adopter) still RUNS — but the compile-time proof requires
  `axon check` via the Rust binary. A drift-gate corpus protects this
  contract.

# ▶ 8. Why this matters

Fase 35 made the store real. Fase 37 made the agent see its request.
Fase 37.x made the typed-column store I/O unconditionally
pooler-coherent — the failure mode of "passes on a laptop, fails in
staging behind Supavisor" is closed.

But the COLUMN itself was still an untyped string from the language's
perspective. A `where: "tenantid = ${tenant_id}"` typo'd the column
and the compiler had nothing to say — Postgres caught it on the first
request, the operator triaged it, the adopter shipped a patch. The
last untyped surface in the cognitive data plane.

Every other typed adopter surface in axon — the request `body: T`
(Fase 32), the flow parameter binding (Fase 37), the backend
declaration (Fase 36), the algebraic-effects stream policy (Fase 33),
the IRFlowNode catalog (Fase 33.y) — is proven at compile time, before
a request is served. The store column was the outlier. Fase 38 brings
it into the fold.

The result is the FIFTH pillar of the cognitive data plane: an
adopter writes `where: "tenant_id = ${tenant_id}"`, `axon check`
proves the column exists and the parameter's type fits, deploy
verifies the declaration matches the live database, the runtime serves
the request — every layer typed, every layer honest, every failure
caught at the earliest possible point. The axon signature move applied
to the store substrate, fully.

That is the cycle this surface needed since v1.30.0 shipped the
store. Fase 35 + 37 + 37.x were the runway. Fase 38 is the landing.

# ▶ 9. The axon-philosophy gate — the two questions, answered

Every axon implementation must answer two questions (the founder's
recurring quality gate). Fase 38 answers them in writing so the plan
can be held to its own bar.

**1 — Is this the market standard, or superior to what other languages
offer?**

Superior on three axes; deliberately at parity on one.

- *The store column is a COMPILE-TIME type (superior — delivered by
  D2).* The market gives you an ORM with a typed schema (the ORM is in
  your language — it knows the column types) OR a query builder over a
  raw connection (typed in the builder, untyped at the cost of
  abandoning ORM ergonomics) OR raw SQL with no type-checking. AXON
  gives a STRING-shaped `where: "tenant_id = ${tenant_id}"` that the
  type-checker proves against a declared column schema — the safety of
  the typed ORM with the syntactic clarity of the SQL filter. Nothing
  on the market gives you both.
- *The schema declaration is OPTIONAL (superior — delivered by D5).*
  Every typed ORM forces an upfront commitment to the schema definition
  IN the application language (TypeORM entities, Django models,
  SQLAlchemy declarative). AXON makes the declaration optional and
  late-bindable — opt in one store at a time, capture an existing
  schema via `axon store introspect` and commit it, or hand-author
  inline. The 37.x runtime+deploy is the floor; the compile-time proof
  is the elective ceiling.
- *The declaration is VERIFIED against the live database at DEPLOY
  (superior — delivered by D8).* Every ORM trusts its declaration;
  drift between the declaration and the live database is detected at
  the first failing request. AXON detects the drift at DEPLOY,
  honestly — a column added to the manifest that isn't in the database,
  a column whose type was migrated server-side without a matching
  manifest update — fails the deploy with a precise `axon-T807`
  diagnostic and a named remedy (run `axon store introspect`, run the
  migration, fix the declaration). The axon signature move.
- *The per-tenant schema (parity — delivered by D3).* Multi-tenant
  ORMs already support schema-per-tenant routing (Django's
  `db_for_read`, SQLAlchemy's `session_factory`). D3's `schema:
  env:VAR` is at parity with that — declarative, resolved at deploy,
  with proper credential isolation. Not a step past the market; matching
  it cleanly is the point.

There is no axis on which Fase 38 is BELOW market. There is one axis
where the market is bigger and Fase 38 deliberately stays narrow —
relational query expressiveness (joins, aggregations, subqueries).
That's a deliberate non-feature; axon is a *cognitive* language, the
store substrate is the data bridge, and the bridge stays narrow on
purpose.

**2 — Minimum to run, or robust and complete for large, complex
adopters?**

Robust — explicitly engineered past the obvious adopter shapes.

- *The single-table single-schema adopter* (one logical schema, one
  `axonstore`): D1 inline column block makes it deterministically typed
  — `axon check` catches column typos before the deploy runs.
- *The legacy-schema adopter* (an existing Postgres with hundreds of
  tables and no inclination to hand-author manifests): D10 `axon store
  introspect *` captures every store in one command, manifests
  committed in one PR, `axon check` proves against them. Onboarding is
  one command.
- *The multi-tenant adopter (schema-per-tenant)*: D3 + D4 — a
  per-tenant `schema: env:VAR` resolves at deploy to the right
  namespace, the manifest carries every tenant's schemas; one
  declaration per store works across N tenants.
- *The active-migration adopter* (the schema changes weekly): D8
  detects every drift at deploy; D10 `--diff` mode lets the migration
  pipeline emit "these columns drifted" in one line; the manifest
  update is a one-PR concern, not a "the code already deployed and
  broke" concern.
- *The CI-without-a-database adopter*: D4's hash-bound manifest +
  `axon check` against it offline means the compile-time proof runs in
  CI without any database access — the database is needed for
  introspection (a manual step at PR review) and deploy verification
  (one CI step), nothing else.
- *The enterprise-with-30-engineers-touching-the-codebase adopter*: D6
  Levenshtein suggestions catch the inevitable column typo at a
  developer's editor (LSP) before review; D9 cross-stack parity means
  the Python runtime team and the Rust runtime team see the same IR;
  D5 absolute means a non-typed store path stays byte-identical, so
  rollout is one team at a time.

The minimum-to-run version of Fase 38 is D1+D2 alone (the smoke
passes, column typos caught at compile time). 38 ships D1–D10 because
"the smoke passes" is not the bar. "Every adopter shape, from the
single-table laptop to the 30-engineer multi-tenant cloud, gets a
typed-column compile-time proof that doesn't make their day harder" is.

# ▶ 10. Forward-compatibility commitments

Three things Fase 38 deliberately keeps the door open on:

- **`Enum<["standard", "premium"]>` closed-set Text** — for Postgres
  `enum` columns. Implementation is one new catalog type + a Levenshtein
  proof that a bound parameter's runtime value is in the closed set;
  the manifest format carries the set. Targeted for a Fase 38.x
  point-release.
- **`StoreColumnProof` as an enterprise-vertical-aware pass** — the
  Fase 28 vertical suggest dictionary (HIPAA / legal / fintech /
  government) registers high-frequency column synonyms (`mrn` ↔
  `medical_record_number`, `pii_email` ↔ `customer_contact_email`,
  `swift_bic` ↔ `bank_identifier_code`). A future Fase 38.x.enterprise
  registers a vertical-aware suggester ON TOP of the OSS Levenshtein,
  matching the Fase 29 enterprise-only pattern.
- **`axon store check` as a server-side health probe** — at runtime an
  operator wants to know "does the deployed manifest still match the
  live database?" without forcing a redeploy. A future `GET
  /v1/store/check` endpoint runs the D8 verification on demand; the
  diagnostic surface is already structured (D6). Targeted for the LSP +
  observability surface in Fase 38.x.

These are NOT in 38.k. Naming them protects the architecture: D1's
closed type catalog, D4's manifest format, and D10's introspection CLI
are designed to accept each one additively, without breaking the v1.38.0
adopter contract.

# ▶ 11. Relationships to other plans

- [[project_fase_37x_plan]] — the runtime+deploy half this cycle is
  the compile-time companion of. 37.x's `resolve_from_rows`,
  `introspect_conn`, `cached_schema`, `evict_schema`, `SchemaCache`,
  `SchemaVerifyReport`, `verify_postgres_schemas` — every one is a
  building block Fase 38 plugs into. 37.x's
  `StoreError::AmbiguousTable` Display literally points at this plan.
- [[project_fase_37_plan]] — the Request Binding Contract. Fase 38's
  D2 type-mismatch arm extends Fase 37's binding totality (a `${param}`
  reaches a column; that path is total at runtime — Fase 38 makes it
  total at compile time too).
- [[project_fase_35_plan]] (Fase 35 / v1.30.0) — the four pillars Fase
  38 layers the fifth (TypedColumn) on top of.
- [[project_fase_36_plan]] — the Backend Resolution Contract. Same
  shape (declared / resolved / observable property), applied here to
  store columns. Both phases are instances of the "make every adopter
  dimension a typed compile-time property" doctrine.
- [[project_fase_32_plan]] — the Axonendpoint REST primitive. Body
  schema validation (Fase 32 D4) at the request boundary; Fase 38 D2
  is the same shape at the store boundary. The two together close the
  bidirectional typed surface — request body ↔ store column.
- [[project_fase_28_plan]] — diagnostic robustness. Fase 38's
  Levenshtein column suggestions (D6) inherit Fase 28's `axon-Wnnn` /
  `axon-Tnnn` namespace + source-context blocks + JSON output + LSP
  surface.
- [[project_axon_lsp]] — Fase 38's typed errors surface to the LSP
  in axon-lsp v0.2.0+ via the structured JSON output (D6); the LSP
  consumes the `StoreColumnProof` verdict as a diagnostic stream.
- [[feedback_no_shortcuts]] — every D-letter answered against the bar.
- [[feedback_axon_for_axon]] — typed columns make axon better as a
  language, independent of who adopts it.

# ▶ 12. The trigger sources (the receipts)

This plan is not speculation. Three published Fase 37.x artifacts
already commit to it by name:

1. **`docs/fase/fase_37x_pooler_coherent_store.md` §7** (the plan vivo
   honest-scope note): *"the genuinely-superior axon end-state … is
   **Fase 38: The Declared & Compile-Time-Typed Store Schema**, named
   and committed here as the immediate next cycle."*

2. **`StoreError::AmbiguousTable` Display** (the user-facing runtime
   error message, in `axon-rs/src/store/postgres_backend.rs`):
   *"…declare the target schema explicitly on the `axonstore` (the
   Fase 38 `schema:` declaration, incl. `schema: env:VAR`
   per-tenant)…"*

3. **`docs/MIGRATION_v1.37.md` Scenario E** + **`docs/ADOPTER_AXONSTORE.md`
   §11.4** + **`docs/fase/AXON_GAP_store_typed_columns_resolution.md`
   §"What is intentionally NOT in v1.37.0"** — every one points the
   adopter at the same calendar promise.

The plan exists to honor those promises. The work begins with 38.a's
diagnostic anchor.

---

*Fase 38 plan vivo — created 2026-05-19, the day Fase 37.x closed.
Drafted by the AXON Language + Runtime Team. D-letters drafted in §4
awaiting founder bloque ratification. Target axon-lang v1.38.0.
Rust-canonical. D5 zero-regression absolute.*
