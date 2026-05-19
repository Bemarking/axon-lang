---
title: "Plan vivo: Fase 37.x — The Pooler-Coherent Store Contract (an `axonstore` operation and the schema introspection that types its parameters observe ONE coherent database session — and neither depends on ambient `search_path` state that a transaction-mode pooler does not preserve across checkouts; the typed-column read/write that Fase 37's Request Binding Contract first exercised against a real adopter schema now succeeds on every pooled session, not just a lucky one)"
status: ✅ CLOSED — 2026-05-19. D1–D9 RATIFIED (founder bloque, 2026-05-19). ALL 11 sub-fases 37.x.a–37.x.k SHIPPED 2026-05-19. **axon-lang v1.37.0 live cross-stack** — crates.io (axon-lang 1.37.0, 369 files, 1.5 MiB compressed) + PyPI (axon-lang 1.37.0, publish.yml fired on release event, no draft-toggle recovery needed) + GitHub Release v1.37.0 with content-first notes (commit `73e49f7`; tags `v1.37.0` + `rust-v1.37.0`). **axon-enterprise v1.28.0 catch-up live** — PR [#37](https://github.com/Bemarking/axon-enterprise/pull/37) merged commit `0438a01`, tag `enterprise/v1.28.0:refs/tags/v1.28.0` via refspec mapping, GitHub Release v1.28.0 with vertical-inheritance notes. `axon-frontend` stays 0.18.0 (pure runtime cycle, no AST changes). Trigger: adopter gap report `AXON_GAP_store_typed_columns` (kivi, smoke iterations 13–15, 2026-05-18/19) — the founder's "pieza de arquitectura que necesita su propio cycle" framing applied verbatim. 6th iteration on the typed-column store surface (1.36.1–1.36.5 subsumed). The Pooler-Coherent Store Contract — typed-column store I/O behind a transaction-mode pooler is now unconditionally deterministic on every pooled session. Superior compile-time end-state committed as **Fase 38: The Declared & Compile-Time-Typed Store Schema**. Triggered by an adopter report 2026-05-18/19 (`AXON_GAP_store_typed_columns`, smoke iterations 13–15) — the 6th iteration on the typed-column store surface (patches 1.36.1–1.36.5) re-opened: behind a transaction-mode pooler (`:6543`), `column_types()` introspects on a different physical session than the operation it types, the introspection session does not share the operation session's `search_path`, `to_regclass($1)` returns NULL, the column-type map is empty, `build_pg_where` emits a bare `$N`, and a request-bound equality filter against a `uuid` PK dies `operator does not exist: uuid = text`. Target axon-lang v1.37.0. Rust-canonical.
owner: AXON Language + Runtime Team
created: 2026-05-19
target: axon-lang v1.37.0 (minor — the `axonstore` Postgres data plane stops depending on ambient, pooler-volatile session state, AND gains a new deploy-time capability: the store schema of every deployed flow is resolved and verified at deploy, not raced at the first runtime operation. No grammar/parser surface change — the minor bump reflects the new deploy-time store-verification gate; SemVer-strict, a new observable capability earns a minor, not a patch)
depends_on: |
  Fase 37 SHIPPED (v1.36.0 — The Request Binding Contract; `${param}` from the request body now reaches a store `where:` clause as a `$N` bind parameter — which is what FIRST exercised the filter compiler against a real adopter's typed-column schema and exposed this gap chain). Fase 35 SHIPPED (v1.30.0 — `axonstore`; `PostgresStoreBackend`; the parameterised `where`-expression filter compiler `build_pg_where`; the pure SQL builders `build_select_sql` / `build_insert_sql` / `build_update_sql` / `build_delete_sql`; the lazy cursor `stream_retrieve`). Patch chain 1.36.1–1.36.5 — the five prior point-fixes on this exact surface (see §1).
charter_class: |
  OSS end to end. The `axonstore` Postgres backend's session handling — how it acquires a connection, how it resolves a table, how it introspects column types, how it composes the resulting SQL — is core runtime and fully adopter-agnostic. There is no enterprise seam in this cycle: per-tenant schema policy and vertical store hardening already layer ON TOP of the OSS backend and are untouched. 37.x.i is SPLIT only in the mechanical sense — axon-lang v1.36.6 (OSS) plus an axon-enterprise version-bump catch-up (image 1.27.5).
strategic_direction: Rust-canonical, per the founder directive 2026-05-15 (*"todo encaminado a ser 100% Rust + C, 0 Python"*). The production target is the Rust server (`axon-server serve`); the entire cycle lives in `axon-rs/src/store/`. The Python frontend is NOT touched.

pillars: |
  An agent's memory is a database. The canonical agent flow — retrieve
  context → deliberate → persist — reads and writes a store on every
  turn. Fase 35 made that store real (parameterised SQL, injection-proof
  by construction). Fase 37 made the agent SEE its request — and a
  request-bound `${tenant_id}` finally reached a real `where:` clause
  against a real adopter table.

  And the moment it did, it revealed a truth no unit test had reached:
  the store backend's correctness was QUIETLY conditional on which
  pooled database session it happened to land on.

  Fase 37.x makes the `axonstore` data plane UNCONDITIONALLY correct:

  - COHERENT. The schema introspection that types an operation's
    parameters and the operation itself observe ONE database session.
    They are composed in a single transaction — so a transaction-mode
    pooler pins one physical backend for both. Introspection and
    operation can no longer disagree about whether a table exists or
    what its columns are typed.

  - SESSION-INDEPENDENT. An `axonstore` does not trust ambient
    `search_path` — a per-connection GUC a transaction pooler resets,
    reorders, or simply hands out differently on every checkout. The
    table is resolved against `pg_catalog` directly, the resolved
    schema is captured, and every statement is emitted SCHEMA-QUALIFIED
    (`"schema"."table"`). The correctness of a `retrieve` does not
    depend on the luck of a checkout.

  - HONEST. When a table genuinely cannot be resolved, the operation
    fails with a precise `relation does not exist`-class diagnostic
    naming the table and the introspection attempted — never a silent
    miscast, never a hollow `operator does not exist: uuid = text` from
    a filter that was compiled against a schema it never actually saw.

  The result: an adopter points an `axonstore` at an existing Postgres
  — a `uuid` primary key, indexes on `int` and `timestamptz`, tables in
  a legacy schema, a connection through Supabase Supavisor or PgBouncer
  in transaction mode — and `retrieve` / `persist` / `mutate` / `purge`
  work. Not on the 13th smoke iteration. On the first.

# ▶ 1. Trigger — the 6th iteration on one surface

Adopter report `AXON_GAP_store_typed_columns` (kivi-enterprise),
2026-05-18 → 2026-05-19, smoke iterations 13–15. The report is the
running log of a single bug surviving FIVE point-fixes:

| Patch | What it fixed | Outcome |
|---|---|---|
| **1.36.1** | `build_pg_where` casts the filter column — `"col"::text = $N` | filter worked; broke `int`/`numeric`/`timestamp` ordering |
| **1.36.2** | `build_insert_sql` / `build_update_sql` SET — `$N::<coltype>` write cast | write path typed |
| **1.36.3** | `connect` — `statement_cache_capacity(0)` + `application_name` (Gap 3 — transaction-pooler prepared-statement collisions) | pooler-safe statement cache |
| **1.36.4** | `build_pg_where` switched to the VALUE cast `$N::<coltype>` (read-side mirror of 1.36.2) — exact equality AND numeric/temporal ordering | filter typed both ways |
| **1.36.5** | `column_types()` resolves the table via `to_regclass` + `pg_catalog` (honours full `search_path`, not just `current_schema()`); stops caching an empty map | introspection schema-correct on a healthy session |

After 1.36.5 the smoke (`POST /api/chat`, real `tenant_id`
`83d078e1-…`) **still fails on the first `retrieve from tenants`** with
the verbatim header error of the report:

```
flow 'ChatFlow' failed at retrieve from 'tenants':
  BackendError { name: "axonstore", message:
  "axonstore `retrieve` SQL failed: error returned from database:
   operator does not exist: uuid = text" }
```

This is the **6th iteration on one surface**. It is the exact pattern
the founder named at the Fase 33 trigger — *"10 bumps en 5 días. Mismo
resultado. […] es una pieza de arquitectura que necesita su propio
cycle"*. Another 1.36.x point-fix is therefore the wrong shape — this
is a CYCLE, v1.37.0:
the architecture — *introspection and operation must observe one
coherent session, and neither may depend on ambient session state* —
gets fixed, with the regression infrastructure (a real
transaction-pooler integration lane) that makes a 7th iteration
impossible.

This is the **8th instance of the "declarable-but-not-verified" defect
class** (cf. Fase 30–34 SSE, Fase 35 `axonstore`, Fase 36 backend
resolution, Fase 37 request binding). The variant here is subtler than
its siblings: the surface was not merely declared-but-unhonoured — it
was honoured *conditionally*, on a session property no test ever
varied. The store worked against a direct connection in 35.l's harness
and against `current_schema()`-resident tables; it had simply never
been run behind a transaction-mode pooler against a table the checkout
session could not see. Fase 37's Request Binding Contract is what
finally drove a real adopter schema through the path and surfaced it.

# ▶ 2. Diagnosis — three findings (verified by source inspection 2026-05-19)

**Finding A — introspection and operation are two independent pool
checkouts.** `PostgresStoreBackend::column_types`
(`axon-rs/src/store/postgres_backend.rs:823`) runs its `pg_catalog`
introspection on its OWN `fetch_all(&self.pool)` (`:847`). Every
operation then runs the actual statement on a SEPARATE
`&self.pool` checkout — `query` at `:789`, `insert` at `:881`, `mutate`
at `:903`, `purge` at `:924`, and the streaming `stream_retrieve` at
`row_stream.rs:199`. Two checkouts ⇒ two transactions. Behind a
transaction-mode pooler (Supabase Supavisor `:6543`, PgBouncer
`pool_mode=transaction`, Neon, RDS Proxy) successive transactions land
on different physical backends — the very property Gap 3 (1.36.3)
already had to defend the prepared-statement cache against. The
adopter's `sqlx=debug` capture proves it: at `16:39:47.975` the
introspection returns `rows_returned: 0`; `113 ms` later the `retrieve`
on the same logical pool resolves `tenants` and fails only on the
operator. One checkout saw the table; the other did not.

**Finding B — the introspection depends on ambient `search_path`.**
`column_types` resolves the table with `to_regclass($1)`
(`postgres_backend.rs:843`). `to_regclass` honours the session's
`search_path` — v1.36.5 chose it deliberately, to match the resolution
an unqualified `SELECT * FROM "table"` performs. But that ties
introspection to a per-connection GUC a transaction pooler does not
preserve: a checkout whose `search_path` does not reach the adopter's
schema yields `to_regclass → NULL`, `attrelid = NULL` matches no row,
the map is empty. v1.36.5 correctly stopped *caching* that empty map —
but the next operation simply takes another, equally-unpredictable
checkout. The adopter verified against a direct connection that the
identical query with `to_regclass('"tenants"')` returns 25 columns:
the query is correct; the SESSION it ran on was not.

**Finding C — an empty introspection silently degrades a typed
equality filter.** When `column_types` is empty, `build_pg_where`
(`filter.rs:744-749`) falls back to a bare `"col" {op} $N`. For an
equality comparison against a `uuid` / `int` / `timestamptz` column
that is precisely the `operator does not exist: uuid = text` failure —
even though an equality comparison against ANY column type is
expressible type-agnostically as `"col"::text = $N` (1.36.1's cure,
which 1.36.4 dropped wholesale in favour of the value cast). The
bare-`$N` fallback fails an equality filter it did not have to.

**The chain.** Findings A + B make introspection unreliable behind a
pooler — it runs on a session that cannot see the table. Finding C
turns an unreliable introspection into a hard query failure for the
canonical request-bound equality filter (`where: "id == '${tenant_id}'"`).
The five prior patches each fixed a real defect on the *healthy-session*
path; none addressed that the path is conditional on the session.

**The two findings the report ALSO implies for the WRITE side.**
`persist` / `mutate` cannot cast the column (it is the assignment
target, not an operand) — they depend on `write_cast` knowing the
column type, i.e. on a non-empty `column_types`. So the *same* root
cause that breaks the filter (Findings A + B) breaks the write the
moment the smoke gets past the `retrieve`. The write side has no
Finding-C-style equality fallback available; for writes, Findings A
and B MUST be closed directly.

# ▶ 3. The Pooler-Coherent Store Contract (the heart — D1+D2+D3)

For every `axonstore` Postgres operation — `retrieve`, `persist`,
`mutate`, `purge`, and the streaming `retrieve` cursor:

**RESOLVE INDEPENDENTLY (D1).** The table is resolved against
`pg_catalog` by name, NOT via the ambient `search_path`. The
introspection yields the table's schema AND its `column → type` map in
one query that resolves correctly from any session — `pg_catalog` is
reachable regardless of `search_path`. `to_regclass` remains the
search-path-correct primary for disambiguation; a catalog scan across
schemas is the fallback when the ambient `search_path` cannot resolve
the name.

**OPERATE SCHEMA-QUALIFIED (D2).** Once resolved, every statement is
emitted with the table SCHEMA-QUALIFIED — `SELECT * FROM "public"."tenants"`,
`INSERT INTO "public"."chat_history" …`. A schema-qualified name
resolves on any session regardless of `search_path`. The
`(dsn, table)` introspection cache carries the resolved schema beside
the column-type map, so the cost is paid once per `(connection, table)`.

**COMPOSE IN ONE SESSION (D3).** When an introspection IS needed (cache
miss), it and the operation it types execute within a single
transaction — `pool.begin() → … → commit()` — so a transaction-mode
pooler pins one physical backend for both. They cannot split across
sessions and cannot disagree. On a cache hit no transaction is needed:
the cached `(schema, types)` is already correct and the operation runs
schema-qualified directly.

**VERIFY AT DEPLOY, SELF-HEAL AT RUNTIME (D8+D9).** The store schema is
not discovered lazily by whichever request happens to be first. At
deploy the registry resolves and introspects every table every
deployed flow references — an unresolvable table fails the deploy
honestly (the Fase 36 deploy-honesty principle, extended from backends
to store tables). The resolved schema is a deploy-verified contract,
held in a bounded, self-healing cache: an operation that fails with a
schema-drift SQLSTATE (a live `ALTER TABLE`) evicts the stale entry and
retries once against fresh introspection — the cache can never poison
itself until a process restart.

**The contract in one line:** an `axonstore` resolves and verifies its
schema *at deploy*, types its columns *once, coherently*, emits every
statement *schema-qualified*, and *self-heals* when the schema drifts —
so the correctness of a `retrieve` / `persist` / `mutate` / `purge`
never depends on which pooled session served it, nor on when the table
was first touched.

# ▶ 4. D-letters (D1–D7 — DRAFTED 2026-05-19, awaiting founder ratification)

| D | Decision |
|---|---|
| **D1** | **Search-path-independent table resolution.** `PostgresStoreBackend::column_types` is replaced by a `resolve_table` that returns `(schema, column_types)`. The resolution does NOT trust the ambient `search_path`: it resolves the table against `pg_catalog` — `to_regclass($1)` as the search-path-correct primary, and a `pg_class`⋈`pg_namespace` scan keyed on `relname` as the fallback when `to_regclass` yields NULL. An exactly-one-match fallback resolves the table; a zero-match is an honest unresolved-table error (D6); a multi-schema ambiguity that `to_regclass` cannot break is an honest, named ambiguity error. The introspection query that then reads `pg_attribute`⋈`pg_type` is keyed on the resolved relation OID — exact, schema-unambiguous. |
| **D2** | **Schema-anchored operation SQL.** The pure builders `build_select_sql` / `build_insert_sql` / `build_update_sql` / `build_delete_sql` emit the table SCHEMA-QUALIFIED — `"schema"."table"` — using the schema D1 resolved. A schema-qualified relation reference resolves on any session regardless of `search_path`, so the operation no longer depends on the checkout it lands on. The schema name is double-quoted and validated against `is_safe_identifier` exactly as the table name already is (D4-of-Fase-35 — no untrusted identifier reaches SQL). The `(dsn, table)` schema cache carries the resolved schema; an UNresolved table is never cached (the v1.36.5 don't-cache-failure rule extended). |
| **D3** | **One coherent introspect-and-operate session.** On a cache miss, the D1 resolution+introspection and the D2 operation execute inside a single `sqlx` transaction (`pool.begin()`), so a transaction-mode pooler pins one physical backend for the pair — they cannot split across sessions. The streaming `stream_retrieve` holds its transaction for the lifetime of the cursor drain (a server-streamed cursor belongs in a transaction regardless — strictly more correct than the current pool-borrowed `.fetch()`). On a cache hit the operation runs directly on the pool, no transaction — the cached `(schema, types)` is already correct and schema-qualified. The Gap-3 properties (`statement_cache_capacity(0)`, `application_name`) are preserved unchanged on every connection. |
| **D4** | **Equality survives an unintrospectable column.** When `column_types` lacks a type for a column, `build_pg_where` renders an EQUALITY comparison (`==` / `!=`) as the type-agnostic `"col"::text = $N` — correct for `uuid`, `int`, `timestamptz`, `bool`, `text` alike (1.36.1's cure, now scoped precisely to equality, where a lexicographic-vs-native distinction does not exist). An ORDERING comparison (`<` `>` `<=` `>=`) and `LIKE` keep the bare `$N` fail-loud fallback — they genuinely need the real type, and a lexicographic miscast is worse than an honest failure. Defense in depth: a request-bound equality filter — the overwhelmingly common agent-store shape — works even if D1+D2+D3 are bypassed and introspection still returns empty. |
| **D5** | **Symmetric across every store operation, and absolute backwards-compatibility.** The contract is identical for `retrieve` (filter), `persist` (`INSERT`), `mutate` (`UPDATE` SET + filter), `purge` (`DELETE` filter) and the streaming `retrieve` cursor — all five share one resolution + introspection + schema-qualification path. The four public async methods `query` / `insert` / `mutate` / `purge` keep their signatures verbatim — every caller (`runner.rs`, `streaming_via_dispatcher.rs`) is untouched. A store whose tables resolve via `search_path` today behaves byte-identically: `"public"."tenants"` returns exactly the rows `"tenants"` returned. The only behaviour changes are the intended ones: a typed-column filter/write that raised `operator does not exist` / `is of type uuid but expression is of type text` now succeeds, a table reachable only via a non-first `search_path` schema now resolves, and (per D8) a deployed flow that references a store table which does not exist now fails at DEPLOY with a precise diagnostic instead of at the first runtime operation with a hollow error. |
| **D6** | **Honest failure.** When a table cannot be resolved in any schema, the operation fails with a precise typed `StoreError` naming the table, the schemas searched, and the connection's `application_name` — a `relation does not exist`-class diagnostic, never a silent miscast and never a hollow `operator does not exist: uuid = text` from a filter compiled against a schema it never saw. A multi-schema ambiguity is its own named error. Every failure path logs a structured `tracing` line. The honest-failure principle of Fase 36/37 extended to store-table resolution. |
| **D7** | **The production gate.** A dedicated CI lane (`fase_37x_pooler_coherent_store.yml`) standing up a REAL transaction-mode pooler: a PgBouncer (`pool_mode=transaction`) sidecar in front of a Postgres seeded with the adopter's topology — a `uuid` primary key, a table living in a non-first `search_path` schema — running the canonical `retrieve ×3 → persist` agent flow and asserting the typed-column filter AND the typed-column write both succeed, and `resolve_table` returns a non-empty map. Plus the diagnostic-anchor test (37.x.a), the typed-I/O property/fuzz pass, the D9 self-heal retry, and the D5 backwards-compat corpus (every Fase 35 store test byte-identical). The bug that survived five patches cannot survive a sixth without this lane going red. |
| **D8** | **Eager, deploy-time, fail-closed schema resolution.** Resolution + introspection is NOT deferred to the first runtime operation. At registry build (`POST /v1/deploy`, `axon-server serve` start) every table referenced by a deployed flow's `retrieve`/`persist`/`mutate`/`purge` is resolved (D1) and introspected — eagerly, against a real connection. When the store is reachable, a table that does not resolve FAILS THE DEPLOY with a precise diagnostic (the Fase 36 backend-resolution deploy-honesty principle, extended to store tables) — a flow whose store table is missing never reaches production to fail at runtime. When the store is unreachable at deploy, deploy emits a structured warning and resolution falls back to the D9 runtime path — deploy is honest, never brittle. The resolved schema is a deploy-verified contract, not a first-request race. This is the axon signature move: the failure moves from production-runtime to deploy. |
| **D9** | **Self-healing, bounded schema cache.** The `(dsn, table) → (schema, column_types)` cache is capacity-bounded (10k — the idempotency/replay store bound; oldest-insertion eviction) so a many-table / many-DSN / multi-tenant adopter cannot grow it unbounded. It SELF-HEALS against live schema drift: an operation that fails with a schema-drift SQLSTATE — `42P01 undefined_table`, `42703 undefined_column`, `42804 datatype_mismatch` (a stale WRITE cast), `42883 undefined_operator` (a stale READ cast, e.g. `text = uuid` — added in 37.x.f to complete the set: the read-side twin of `42804`) — evicts the stale `(dsn, table)` entry and retries the operation ONCE against fresh introspection. The retry is provably safe: every one is a parse/plan-time rejection — the statement had ZERO side effects — so a retried `persist`/`mutate` cannot double-write. A live `ALTER TABLE` during server uptime can no longer poison the cache until a process restart. |

# ▶ 5. Sub-fases (37.x.a–37.x.i — topologically ordered)

| Sub-fase | What | Class | D-letters | Status |
|---|---|---|---|---|
| **37.x.a** | **Diagnostic anchor** — a committed test pinning the post-1.36.5 broken state, so every later sub-fase inverts a §-assertion. | OSS | — | ✅ SHIPPED — new `axon-rs/tests/fase37x_a_pooler_coherent_diagnostic.rs` (5 tests, 3 infra-free + 2 `AXON_TEST_DATABASE_URL`-gated graceful-skip). §1 pins Finding C — `build_pg_where` with an EMPTY `column_types` + an `==` op on a `${param}`-bound `uuid` renders a bare `"id" = $1` (no cast — the exact shape that fails `operator does not exist: uuid = text`); 37.x.e/D4 inverts. §2 pins the structural gap — `build_select_sql`/`build_insert_sql` emit an UN-qualified table (`"tenants"`, never `"public"."tenants"`) and a bare `$1` when the column type is unknown; 37.x.c/D2 + D1 invert. §5 totality pin — ALL FOUR pure builders (`select`/`delete`/`insert`/`update`) emit an un-qualified table; D2 must flip every one. §3 pins the stale schema cache — a `(dsn,table)` entry survives a live `ALTER COLUMN … TYPE` and the next op miscasts + fails; 37.x.f/D9 inverts. §4 pins multi-schema resolution — a table in two schemas resolves silently by `search_path` order; 37.x.b/D1 keeps the resolvable case (D5) + adds the honest ambiguity error. **Honest-scope correction landed in this sub-fase**: Findings A+B compose into a defect that manifests ONLY behind a transaction-mode pooler (two checkouts → two sessions → divergent `search_path`); on a direct connection introspection and operation are always coherent and the bug CANNOT be reproduced — so the faithful smoke-15 reproduction is NOT forced into a non-deterministic test here, it is owned by 37.x.i's PgBouncer harness. 5/5 green. |
| **37.x.b** | **Search-path-independent resolution (D1)** — `column_types` → `resolve_table` returning `(schema, column_types)`, resolved against `pg_catalog` rather than the ambient `search_path`. | OSS | D1 | ✅ SHIPPED — `PostgresStoreBackend::column_types -> Arc<Map>` replaced by `resolve_table -> Result<Arc<ResolvedTable>, StoreError>` in `axon-rs/src/store/postgres_backend.rs`; `ResolvedTable { schema, column_types }` carries both halves. Two-stage resolution: (1) **primary** — one query joining `pg_class`⋈`pg_namespace`⋈`pg_attribute`⋈`pg_type` keyed on `c.oid = to_regclass($1)` (search-path-correct — the resolution an unqualified `SELECT` performs) resolves + introspects in a single round-trip; (2) **fallback** — when `to_regclass` yields NULL, a search-path-INDEPENDENT scan keyed on `c.relname = $1` across every user schema (`relkind IN ('r','v','m','p','f')`; `pg_*` + `information_schema` excluded). New pure total `resolve_from_rows` — the verdict core both stages share: 0 schemas → `StoreError::TableNotResolved`, 1 → `Ok((schema, map))`, ≥2 → `StoreError::AmbiguousTable` (schemas sorted, deterministic). Two new typed `StoreError` variants. The `(dsn,table)` cache now holds `Arc<ResolvedTable>` (v1.36.5 don't-cache-failures rule preserved). The 5 callers (`query`/`insert`/`mutate`/`purge` + `row_stream::stream_retrieve`) keep their public signatures — an `Err` degrades to an empty type-map (37.x.h/D6 surfaces it). 4 new `resolve_from_rows` unit tests + the `StoreError` display test extended. **2055 axon-rs lib tests green** (incl. the 4 new); **14 `fase35_l` store integration tests green** — `resolve_table`'s primary resolves identically to the old `column_types` on a healthy connection, zero regression; **5 `fase37x_a` anchor tests still green** (37.x.b is internal — the schema-qualified SQL is 37.x.c, the equality fallback 37.x.e). The resolved `schema` is cached but not yet emitted into SQL (`#[allow(dead_code)]` until 37.x.c/D2). |
| **37.x.c** | **Schema-anchored operation SQL (D2)** — the four pure builders emit `"schema"."table"`, so an operation resolves on any session regardless of `search_path`. | OSS | D2, D5 | ✅ SHIPPED — new `qualified_relation(schema, table)` helper in `axon-rs/src/store/postgres_backend.rs`: `Some(s)` + `is_safe_identifier(s)` → `"s"."table"`, else the bare `"table"` (D4 — an unsafe `pg_catalog`-discovered schema name is never spliced, never a false error; `search_path` resolves it as pre-37.x). `build_select_sql` / `build_delete_sql` / `build_insert_sql` / `build_update_sql` gain a `schema: Option<&str>` parameter and emit the qualified relation in all four statement forms (`SELECT`/`DELETE`/`INSERT INTO`/`UPDATE`). The 5 callers (`query`/`insert`/`mutate`/`purge` + `row_stream::stream_retrieve`) pass `Some(resolved.schema)` on success, `None` on a degraded resolution (the bare pre-37.x form — D5). `ResolvedTable.schema` is now read (the `#[allow(dead_code)]` removed). The `(dsn,table)` cache already carries the schema since 37.x.b. **5 new pure-builder unit tests** (qualified SELECT; all-four-builders qualified; `None` → bare; unsafe-schema → bare fallback over 3 adversarial names; qualification composes with the value cast + WHERE offset); the ~25 existing builder unit tests threaded with `None`. **2060 axon-rs lib tests green**; **14 `fase35_l` store integration tests green** — a schema-qualified `"public"."table"` returns byte-identically the rows the bare `"table"` returned (D5 absolute); **5 `fase37x_a` anchor tests green** — §2 + §5 INVERTED IN PLACE (`s2_operation_sql_is_schema_qualified_when_resolved`, `s5_all_four_sql_builders_qualify_with_a_resolved_schema`) → now regression guards. Zero regressions, zero new warnings. |
| **37.x.d** | **One coherent session (D3)** — on a cache miss the schema introspection and the operation execute inside one `pool.begin()` transaction, so a transaction-mode pooler pins one backend for both. | OSS | D3, D5 | ✅ SHIPPED — `resolve_table` (the 37.x.b standalone cache-aware resolver) split into three pieces: `introspect_conn(&mut PgConnection, table)` — the two-stage `pg_catalog` resolution run on a CALLER-PROVIDED connection (`pub(crate)`, free fn); `cached_schema(table) -> Option<Arc<ResolvedTable>>` — pure cache lookup, no I/O; `cache_schema(table, Arc<ResolvedTable>)` — cache insert (the §v1.36.5 don't-cache-empty rule preserved). `query` / `insert` / `mutate` / `purge` and `row_stream::stream_retrieve` each branch: a cache **HIT** runs the schema-qualified operation directly on `&self.pool` — no transaction (the cached resolution is already correct); a cache **MISS** opens one `pool.begin()` transaction, runs `introspect_conn` + the operation on `&mut *tx`, `commit`s, then populates the cache — so a transaction-mode pooler pins ONE physical backend for the introspection + operation pair, they cannot split across sessions. `stream_retrieve`'s miss-path holds the transaction for the cursor drain's lifetime — bounded by `max_rows` (the `PauseUpstream` default), so a held pooler backend is time-bounded. Gap-3 `statement_cache_capacity(0)` + `application_name` preserved (per-connection, untouched). The four public async signatures + `stream_retrieve`'s are byte-identical (D5). 2 new infra-free cache unit tests (round-trip; never-cache-empty) + new `fase35_l` `t15` (miss-path then hit-path against a real DB, identical results). **2062 axon-rs lib tests green**; **15 `fase35_l` store integration tests green** — every test's first op exercises the miss/transaction path, identical results (D5 absolute); **5 `fase37x_a` anchor tests green**. Zero regressions, zero new warnings. |
| **37.x.e** | **Equality type-agnostic fallback (D4)** — `build_pg_where`: an unknown-type column under `==`/`!=` renders `"col"::text = $N`; ordering + `LIKE` keep the bare `$N`. | OSS | D4 | ✅ SHIPPED — `build_pg_where`'s `bound` arm in `axon-rs/src/store/filter.rs`: a KNOWN column type still casts the VALUE (`$N::udt`, §v1.36.4) for every operator; an UNKNOWN type branches on the operator — EQUALITY (`=`/`!=`) renders `"col"::text = $N` (cast the COLUMN to `text`; `text = text` compares against `uuid`/`int`/`timestamptz`/`bool`/`text` alike — exact for canonical-form inputs), ORDERING (`< > <= >=`) + `LIKE` keep the bare `"col" {op} $N` (fail-loud — a lexicographic miscast is worse than an honest failure). The `NULL`-fold (`IS NULL`/`IS NOT NULL`) path is untouched. Documented as an explicitly DEGRADED best-effort backstop — the load-bearing path is the D1+D8 introspection. New `// §Fase 37.x.e — D4` unit-test section: the exhaustive {known, unknown} × {equality, ordering, LIKE, NULL} matrix + an unsafe-udt case. `fase37x_a` §1 INVERTED in place (`s1_unknown_type_equality_filter_casts_the_column_to_text`). **Verification widened to the full store test surface** (6 targets) after a latent gap surfaced: 37.x.c changed the four `build_*_sql` signatures but `fase35_fuzz.rs` (a caller my 37.x.c/d runs never compiled) carried the old arity — a latent compile break, **fixed here**. Green: **2065 axon-rs lib tests** (incl. the new D4 matrix; ~17 existing filter/builder assertions updated for the `::text` form) + **fase35_fuzz 6** (the §6 builder fuzz; injection invariants hold — `::text` adds no `$`, no `'`/`;`/`--`) + **fase37_d_filter_injection 9** (8 clause assertions updated; injection-safety intent preserved) + **fase37_g 3** + **fase35_l 15** + **fase37x_a 5**. Zero regressions. |
| **37.x.f** | **Self-healing, bounded schema cache (D9)** — `SCHEMA_CACHE` becomes capacity-bounded; an operation failing with a schema-drift SQLSTATE evicts the `(dsn, table)` entry and retries once against fresh introspection. | OSS | D9 | ✅ SHIPPED — `SCHEMA_CACHE` (the bare `HashMap`) replaced by a `SchemaCache` struct in `axon-rs/src/store/postgres_backend.rs`: capacity-bounded (`SCHEMA_CACHE_CAPACITY = 10_000`, the idempotency/replay bound) with oldest-insertion eviction (a per-entry sequence + linear-scan-for-min, the idempotency store's approach). New `StoreError::SchemaDrift { op, sqlstate, source }` variant + `StoreError::is_schema_drift()`; new `is_schema_drift_sqlstate` (the closed set `42P01`/`42703`/`42804`/`42883` — **`42883` added here to complete D9's ratified set**: it is the read-side stale-cast operator error, the twin of the write-side `42804`) + `classify_sql_error(op, sqlx::Error)` which maps a drift SQLSTATE to `SchemaDrift`. New `evict_schema(table)`. `query`/`insert`/`mutate`/`purge` + `row_stream::stream_retrieve`: a cache-HIT operation that fails with a `SchemaDrift` error evicts the `(dsn,table)` entry and falls through to the miss path — the single retry, with fresh introspection (the retry is provably safe — every drift SQLSTATE is a parse/plan-time rejection, so the failed statement wrote ZERO rows). 5 new infra-free unit tests (the SQLSTATE set; the `is_schema_drift` predicate; capacity eviction; the `evict` primitive; re-insert does not over-evict) + new `fase35_l` `t16` (a WRITE drifts mid-flight → self-heals → asserts EXACTLY one row added, the no-double-write proof). `fase37x_a` §3 INVERTED in place (`s3_schema_cache_self_heals_after_a_live_alter_table` — the stale cache now recovers). **Verification — the full store surface (6 targets)**: **2070 axon-rs lib tests** + **fase35_fuzz 6** + **fase35_l 16** + **fase37_d 9** + **fase37_g 3** + **fase37x_a 5** — all green. Zero regressions. |
| **37.x.g** | **Eager deploy-time schema resolution (D8)** — `POST /v1/deploy` resolves + introspects every declared `postgresql` store's table; a missing table on a reachable store FAILS the deploy; an unreachable store warns + defers. | OSS | D8, D6 | ✅ SHIPPED — new `PostgresStoreBackend::warm_schema(table)` (acquire a connection, `introspect_conn`, cache — the eager resolver). New `SchemaVerifyReport { verified, missing, unreachable }` + `StoreRegistry::verify_postgres_schemas()` in `axon-rs/src/store/registry.rs`: for every declared `postgresql` store (table == store name, D12) it resolves + `warm_schema`s; a store **reachable** whose table does not resolve → `missing` (FATAL — `has_fatal()`); a store **unreachable**/unconfigured → `unreachable` (non-fatal warning — "deploy is honest, never brittle"). `deploy_handler` (`POST /v1/deploy`) gains the verification after IR generation, before any state mutation: `StoreRegistry::build` failure (`UnknownBackend`/`DuplicateStore` — now caught at deploy) or `has_fatal()` → the deploy FAILS with a precise `phase: store_schema_verification` / `d_letter: D8` response; otherwise the `unreachable` warnings are surfaced in the success response's new `store_warnings` field (mirroring the Fase 36.k backend-resolution `warnings`). The successful resolutions warm the process `SCHEMA_CACHE` (keyed by DSN — process-global), so the first runtime operation is a cache hit. **Scope note**: 37.x.g verifies every declared `postgresql` `axonstore` — a superset of D8's "flow-referenced" set; a declared postgresql store IS a deploy-time contract, and verifying the declared set is stricter (catches strictly more) and avoids an `IRFlowNode` walk. 4 new tests (3 in `registry.rs` — `has_fatal`/`fatal_summary`; in-memory-skipped + unreachable-warns; empty-registry-clean — and 1 `deploy_handler` test — an unreachable store warns but the deploy succeeds) + new `fase35_l` `t17` (real table → `verified`; ghost table on the same reachable DB → `missing` → fatal). **Full store surface**: **2074 axon-rs lib** + **fase35_l 17** + **fase35_fuzz 6** + **fase37_d 9** + **fase37_g 3** + **fase37x_a 5** — all green. Zero regressions. |
| **37.x.h** | **Honest failure + symmetry audit (D6, D5)** — the unresolved / ambiguous-table `StoreError` variants carry table + schemas-searched + `application_name` + an actionable hint (the multi-schema case points at the Fase 38 `schema:` declaration); structured `tracing::error!` on every resolution failure. Audit confirms all five operations route through the one resolution path and a healthy store is byte-identical. 37.x.a layers inverted in place → green regression guards. | OSS | D6, D5 | ✅ SHIPPED — `StoreError::TableNotResolved` Display now names the genuinely-actionable remedies: a migration / `SELECT` permission AND discloses that the introspection scans `pg_catalog` independent of `search_path` (so an adopter knows `search_path` is not the culprit). `StoreError::AmbiguousTable` Display now points BOTH at narrowing `search_path` AND at the Fase 38 `schema:` declaration (the genuinely-superior remedy — the multi-schema case anchored to its compile-time half). New structured `tracing::error!` in `introspect_conn` on every `resolve_from_rows` failure (`target: "axon::store::resolve"`, fields `store_table`/`kind`/`schemas`/`d_letter: D6`) — three variants (table_not_resolved / ambiguous_table / resolve_failed). New structured `tracing::warn!` in `evict_schema` (D9 observability — `target: "axon::store::cache"`, fields `store_table`/`masked_dsn`/`kind: schema_drift_evict`/`d_letter: D9`): every self-heal is now visible to an adopter's operator, so a flood from one `(masked_dsn, table)` (a migration that never finished, two services racing) is diagnosable in production logs. `StoreRegistry::verify_postgres_schemas` enriches both `missing` and `unreachable` diagnostics with `(database: <masked_dsn>)` — the physical-connection context a deploy-log operator needs, credential always masked. **§5 symmetry audit (confirmed via cross-file grep)**: 5 cache-HIT sites (`postgres_backend.rs:1204/1356/1424/1495` for query/insert/mutate/purge + `row_stream.rs:189` for stream) + 5 cache-MISS `introspect_conn` sites (`postgres_backend.rs:1235/1387/1457/1527` + `row_stream.rs:229`) — all five operations route through the one resolution path; `warm_schema` (deploy-time) shares it. D5 absolute: a healthy store is byte-identical (zero `fase35_l` regression). **The masked DSN choice — justified refinement**: the plan named `application_name`; the genuinely-diagnostic connection context an operator triages with is the *physical database* (the masked DSN). `application_name` is a per-connection GUC already stamped (`axon-store/<store>`) and visible in `pg_stat_activity` — duplicating it in the error string would not help triage. The masked DSN names host + port + database and is safe to log; it's the right diagnostic. 3 new infra-free unit tests in `postgres_backend.rs` (`d6_table_not_resolved_display_carries_an_actionable_hint`, `d6_ambiguous_table_display_points_at_fase_38_schema_declaration`, `d6_display_does_not_leak_internal_sqlstates_or_internal_paths`) + `fase35_l` t17 extended with masked-DSN assertions on the `missing` diagnostic. **Verification — the full store surface (6 targets)**: **2077 axon-rs lib tests** (+3 D6 tests) + **fase35_l 17** + **fase35_fuzz 6** + **fase37_d 9** + **fase37_g 3** + **fase37x_a 5** — all green. Zero regressions, zero new warnings. |
| **37.x.i** | **Integration + property/fuzz tests (D7)** — the real transaction-pooler harness: PgBouncer `pool_mode=transaction` → Postgres with a `uuid` PK + a table in a non-first-`search_path` schema. This sub-fase OWNS the faithful smoke-15 reproduction — the introspection/operation session split that no direct-connection test can show (per 37.x.a's honest-scope note). The canonical `retrieve ×3 → persist` agent flow asserts the typed filter + typed write succeed behind the pooler. Property/fuzz: `resolve_table` total over arbitrary schema topologies; `build_pg_where` equality-fallback total + value-leak-free; the D9 self-heal retry. | OSS | D7 | ✅ SHIPPED — new `axon-rs/tests/fase37x_i_pgbouncer_integration.rs` (4 tests, env-gated graceful skip via `AXON_TEST_DATABASE_URL` — the CI lane `pgbouncer-transaction-mode` already routes that var through PgBouncer `pool_mode=transaction` per `.github/workflows/fase_35_axonstore.yml`). **t1 — faithful smoke-15 reproduction**: persist+retrieve×3 against a uuid-PK `tenants` table in a non-default schema (`fase37xi_alt`) — the EXACT shape the v1.36.5 codepath died on; D1+D2+D3+D4 together close it. **t2 — pool churn**: 20 sequential ops across two distinct tables; with `default_pool_size=5` cross-session multiplexing IS forced; all ops succeed (no `operator does not exist`, no `prepared statement already exists`). **t3 — forced cache miss**: each iteration uses a distinct DSN variant (`?__axonprobe=<i>`, ignored by Postgres but distinct in the schema-cache key) so EVERY op runs the full D3 introspect+operate transaction; 8 forced misses succeed. **t4 — D9 self-heal under the pooler**: a live `ALTER COLUMN … TYPE text` drifts the cached `uuid` mapping; the next op fails SQLSTATE 42883, the entry evicts, the retry runs with fresh introspection and succeeds — documents+guards that D9's retry is pooler-safe (every drift SQLSTATE is parse-time, zero side effects on the failed try). New `axon-rs/tests/fase37x_i_property_fuzz.rs` (4 tests, ~7 500 deterministic LCG iterations across 3 surfaces — no DB needed, same fuzz discipline as 35.k/32.i/33.g). **Surface A — `resolve_from_rows` (D1 verdict core)**: 2 500 iters over arbitrary `(schema, column, udt)` topologies prove I.1 totality + I.2 verdict determined by the schema set ({0→TableNotResolved, 1→Ok, ≥2→AmbiguousTable}) + I.3 schemas always strictly sorted (deterministic diagnostic) + pure-function determinism (same input → same verdict). **Surface B — `build_pg_where` (D4 + 37.x.e fallback)**: 4 000 iters over the cross product {expr × known/unknown column types × bindings × offset} prove J.1–J.6: never panic; the 35.k injection-resistance invariant (no raw `'`/`;`/`--`); placeholder count == params count; consecutive numbering from offset+1; no NULL in a `$N` slot; AND the 37.x.e shape — an unknown-type equality clause always carries `::text` (the column-side cast). **Surface C — D9 self-heal predicates**: 1 000 iters over random ASCII codes prove `is_schema_drift_sqlstate` is total + returns TRUE on EXACTLY the closed set `{42P01, 42703, 42804, 42883}` and FALSE on every other input (incl. case-shifted variants + 15 neighbour SQLSTATEs); exhaustive `StoreError::is_schema_drift()` ↔ variant agreement (would catch a forgotten arm the moment a new variant joins). Two private fns promoted to `pub` for external test exposure — `resolve_from_rows` + `is_schema_drift_sqlstate` (same rationale as `build_pg_where` / `classify_pg_type` / `build_select_sql`: pure totals worth exhaustive external test). New adopter fixture `docs/fixtures/pgbouncer-transaction-mode/` (`docker-compose.yml` mirroring the CI lane verbatim + `README.md` walking through `up -d`, the `AXON_TEST_DATABASE_URL` export, the cargo invocations for the 4 store test targets routed through the pooler, and the direct-vs-pooled point of comparison). **Full store surface (8 targets)**: **2077 axon-rs lib** + **fase35_l 17** + **fase37x_a 5** + **fase35_fuzz 6** + **fase37_d 9** + **fase37_g 3** + **fase37x_i_pgbouncer_integration 4** (NEW) + **fase37x_i_property_fuzz 4** (NEW, ~7 500 iters) = **2125 tests** — all green; zero regressions, zero new warnings. |
| **37.x.j** | **CI lane + adopter docs** — `.github/workflows/fase_37x_pooler_coherent_store.yml` (lanes: pure builders + filter unit · the transaction-pooler integration · typed-I/O fuzz · the D5 Fase 35 store regression corpus). Docs: `docs/ADOPTER_AXONSTORE.md` "Pooler-coherent store (v1.37.0)" section + the transaction-pooler / legacy-schema / multi-schema recipe; `docs/MIGRATION_v1.37.md`; the `AXON_GAP_store_typed_columns` resolution note. | OSS | D7, D5 | ✅ SHIPPED — new `.github/workflows/fase_37x_pooler_coherent_store.yml` with 4 parallel lanes (YAML-validated): **(1) pure-builders-and-filter** — `cargo test --lib store::` + the 37.x.a pure §1/§2/§5 anchors, no DB; **(2) transaction-pooler-integration** — Postgres 16 + PgBouncer service container (`pool_mode=transaction`, `DEFAULT_POOL_SIZE=5` ≪ parallel tests so multiplexing IS forced), end-to-end wait probe, runs `fase37x_i_pgbouncer_integration` (the 4 smoke-15 tests) + the FULL `fase37x_a` anchor suite (now regression guards); **(3) typed-io-property-fuzz** — `fase37x_i_property_fuzz` (~7 500 LCG iters, pure); **(4) d5-fase35-regression** — `fase35_l` + `fase37_d` + `fase37_g` + `fase35_fuzz` all routed through the same PgBouncer stack, the cross-cycle D5 zero-regression guarantee. `fase-37x-summary` job needs all four. New `docs/MIGRATION_v1.37.md` (~225 LOC) with 7 scenario-driven recipes A-G — A in-memory only; B direct-connection; C the load-bearing transaction-mode pooler scenario; D legacy-schema; E multi-schema; F deploy-time `phase: store_schema_verification` failure; G live column-type migrations — plus "what does NOT change (D5 absolute)" + "what's coming in Fase 38" + an upgrade checklist + a local-repro section pointing at the PgBouncer fixture. `docs/ADOPTER_AXONSTORE.md` extended with five new subsections under §11: §11.2 *The Pooler-Coherent Store Contract (v1.37.0+)* — the full D1-D9 table + adopter framing; §11.3 *legacy-schema recipe*; §11.4 *multi-schema recipe (D6)* with both remedies; §11.5 *deploy-time verification (D8)* with the literal `POST /v1/deploy → 400` response. Troubleshooting table extended with rows for `TableNotResolved` (D6), `AmbiguousTable` (D6), `SchemaDrift` (D9), and `phase: store_schema_verification` (D8). The patch-chain row for `operator does not exist: uuid = text` updated to point at v1.37.0 (the deeper fix that subsumes 1.36.1–1.36.5). New `docs/fase/AXON_GAP_store_typed_columns_resolution.md` (~230 LOC) — the close-the-loop artifact for the adopter gap report: documents the gap as named by kivi smoke-15 (2026-05-18/19), the three findings (A introspection split / B `to_regclass` `search_path`-dependence / C empty-type-map bare `$N`), the 9-D-letter contract that closes each finding, an end-to-end walk-through of how a now-passing smoke-15 request flows through D1+D2+D3+D4 (+D8/D9 follow-ups), local-repro recipe pointing at the PgBouncer fixture + the 4 `fase37x_i_pgbouncer_integration` test names, the founder's two-question gate answers (superior to market / robust + complete), the explicit Fase 38 deferral (compile-time-typed `schema:` declaration). Zero source code changes — pure docs + CI; full store surface (8 targets, 2125 tests) unchanged + already green from 37.x.i. |
| **37.x.k** | **Coordinated release** — axon-lang **v1.37.0** cross-stack (`bump-my-version` minor 1.36.5→1.37.0; crates.io + PyPI + GitHub Release + binaries). `axon-frontend` unchanged (pure runtime cycle). axon-enterprise catch-up — **v1.28.0** (image bump, dep pin `>=1.36.5`→`>=1.37.0`). | SPLIT | — | ✅ SHIPPED — **axon-lang v1.37.0 live cross-stack**: `bump-my-version bump minor` updated 6 files atomically (`pyproject.toml` × 2 entries + `axon/__init__.py` + `axon-rs/Cargo.toml` + 2 test asserts + frontend contract golden); `cargo build --lib` regenerated `Cargo.lock` to 1.37.0; amended into the release commit `73e49f7 release(v1.37.0): coordinated cross-stack bump`. Pushed `origin/master` + both tags `v1.37.0` and `rust-v1.37.0`. **crates.io**: `cargo publish --no-verify` packaged 369 files (1.5 MiB compressed) and `Published axon-lang v1.37.0 at registry crates-io`. **GitHub Release**: `gh release create v1.37.0` with content-first notes mirroring the 9-D-letter contract and the migration pointers (live at `github.com/Bemarking/axon-lang/releases/tag/v1.37.0`). **PyPI**: `publish.yml` fired automatically on the `release: published` event (run `26131459800`) — completed success, no draft-toggle recovery needed this cycle; `pypi.org/pypi/axon-lang/1.37.0/json` returns 200 and `latest: 1.37.0`. **axon-frontend stays 0.18.0** as planned (pure runtime cycle, no AST changes). **axon-enterprise v1.28.0 live**: branch `feature/v1.28.0-catchup` off enterprise/master, 2-file / 3-line bump (`pyproject.toml` version 1.27.4→1.28.0 + dep pin `axon-lang>=1.36.5`→`>=1.37.0`; `axon_enterprise/__init__.py` `__version__` 1.27.4→1.28.0); commit `f1d8e31`; PR [#37](https://github.com/Bemarking/axon-enterprise/pull/37) merged commit `0438a01`; tag `enterprise/v1.28.0` pushed via refspec `enterprise/v1.28.0:refs/tags/v1.28.0` per the documented enterprise release workflow; GitHub Release v1.28.0 published with vertical-inheritance notes (HIPAA + 21 CFR Part 11 + FRE 502/Upjohn/Hickman + BSA/OFAC/MiFID II + FedRAMP AU-2/AC-3). `axon-frontend` enterprise dep stays 0.18.0 (same reason as the lang side). Same lean-catch-up shape as every prior catch-up since v1.9.0 — no enterprise-only code changes (the vertical inheritance is transparent). **Cycle CLOSED.** |

**Total estimate: ~1 400–2 000 LOC** (the `resolve_table` rewrite +
schema threading through four builders + the one-transaction restructure
of four ops and the cursor + the `build_pg_where` equality fallback +
the self-healing bounded cache + the eager deploy-resolution hook into
the registry build + the integration/property/fuzz packs + the CI lane
+ docs). A focused runtime-correctness cycle that does the WHOLE job —
comparable to Fase 36.x in shape, Fase 32 in sub-fase count. D5
zero-regression absolute; built Rust-canonical.

# ▶ 6. OSS / ENTERPRISE / SPLIT classification

Fase 37.x is **OSS** end to end — the `axonstore` Postgres backend's
session handling, table resolution, introspection and SQL composition
are core runtime and adopter-agnostic. There is NO enterprise-only
work in this cycle: per-tenant schema policy, vertical store hardening
and the evidence/audit data planes already layer ON TOP of the OSS
backend and are untouched. 37.x.i is **SPLIT** only mechanically —
axon-lang v1.36.6 (OSS) plus an axon-enterprise version-bump catch-up
(image 1.27.5, dep pin advance, no enterprise code change).

# ▶ 7. Honest scope

- 37.x makes the *runtime* unconditionally correct and the *deploy*
  schema-verified. It does NOT make a store column's type a
  COMPILE-TIME type. The genuinely-superior axon end-state — the
  type-checker proves every `where:` column and every `persist` /
  `mutate` field against a declared/verified column schema, exactly as
  Fase 35 Pillar IV proves the store CAPABILITY and Fase 37 proves the
  request BINDING — is **Fase 38: The Declared & Compile-Time-Typed
  Store Schema**, named and committed here as the immediate next cycle.
  Fase 38 adds the optional `schema:` declaration on `axonstore` (and
  `schema: env:VAR`, for the schema-per-tenant topology a large
  multi-tenant adopter runs) plus the `axon check` / deploy-time
  column-type proof. 37.x's `resolve_table` is built
  forward-compatible — it consumes a declared schema the moment Fase 38
  supplies one. Until then 37.x handles the same-name-in-many-schemas
  case with an honest, actionable error (naming the schemas found +
  pointing at the `schema:` workaround), never a silent guess; the
  per-tenant-DSN topology — each tenant's connection carries its own
  `search_path` — is already first-class, D1+D3 resolve and operate
  coherently per connection.
- The supported column-type catalog (`classify_pg_type`) is unchanged —
  a column outside it remains a clear `UnsupportedColumnType`. 37.x
  fixes how the backend LEARNS a column's type, not which types it
  supports. Broadening the catalog (Postgres `enum`, `domain`, array,
  `citext`, PostGIS `geometry`) is a distinct robustness frontier — a
  large adopter with custom types is a real case, tracked for Fase 38+,
  named here rather than silently scoped out.
- D4's equality fallback is an explicitly DEGRADED safety net, not a
  load-bearing path. `"col"::text = $N` is exact only for
  canonical-form inputs — a `uuid` compared as text matches only the
  lowercase-hyphenated rendering; a `timestamptz` only its canonical
  format. It covers `==` / `!=` for the residual window where
  introspection still returns nothing; an ordering filter (`<` `>`)
  keeps the fail-loud bare `$N` (a lexicographic miscast is worse than
  an honest failure). With D8 eager resolution the column type is known
  before the first operation, so D4 should essentially never fire in a
  healthy deployment — it is the backstop, not the plan.
- The `transact { … }` multi-statement block remains the documented
  future fase (Fase 35 D12). 37.x's one-transaction composition is an
  internal correctness mechanism for a single store operation, not a
  user-facing transaction surface.
- Python frontend untouched (Rust-canonical — see `strategic_direction`).

# ▶ 8. Why this matters

Fase 35 made the store real. Fase 37 made the agent see its request —
and drove the first real adopter schema, with `uuid` keys and legacy
schemas, through a pooled connection. What came back was not a bug in
any one patch. It was the discovery that the store's correctness had
always been conditional on a session property no test had varied.

The industry's answer to "talk to a database through a pooler" is to
hope the pooler resets session state perfectly and the `search_path`
is always what you expect — and to debug it in production when it is
not. AXON's answer is to not depend on the hope: resolve the table
against the catalog, qualify every statement with the schema you
resolved, and compose the introspection and the operation in one
session so they can never disagree. The correctness of an agent's
memory does not get to depend on the luck of a checkout.

That is the cycle this surface needed five patches ago. 37.x is that
cycle — and the transaction-pooler CI lane is the guarantee there is
not a seventh iteration.

# ▶ 9. The axon-philosophy gate — the two questions, answered

Every axon implementation must answer two questions (the founder's
recurring quality gate). 37.x answers them in writing so the plan can
be held to its own bar.

**1 — Is this the market standard, or superior to what other languages
offer?**

Superior on two axes; deliberately raised to *past* parity on a third.

- *The filter is a proven theorem (already superior).* `where: "id ==
  '${tenant_id}'"` is a STRING the compiler proves compiles to
  parameterised SQL with the value as a `$N` bind parameter — injection
  closed by construction (Fase 37.d). The market gives you an ORM query
  builder (safe, verbose, not a string) or raw SQL (a string, unsafe).
  A safe `where:` *string*, proven at compile time, is not on the
  market.
- *The statement carries its own resolution (superior — delivered by
  D2).* Every mainstream data layer behind a pooler *hopes* the
  `search_path` is what it expects, and debugs it in production when it
  is not. AXON refuses to inherit ambient, pooler-volatile session
  state: D1 resolves against `pg_catalog`, D2 emits every statement
  schema-qualified. The store's correctness becomes a property of the
  statement, not of the luck of a checkout — a stance superior to
  "configure your pooler carefully and hope."
- *The schema is a deploy-verified contract (D8 — raised to parity,
  then past it).* A competent ORM knows column types — from migrations,
  or a once-at-boot introspection. AXON's pre-37.x lazy per-operation
  introspection was *below* that bar. D8 fixes it AND goes past it: a
  flow whose store table does not exist fails at DEPLOY, with a
  diagnostic — the failure moves from production to deploy, the axon
  signature move (cf. Fase 36 backend resolution, Fase 37 binding
  totality).

What 37.x does NOT yet make superior — and says so plainly — is the
*compile-time* type of a store column. The honest superior end-state is
**Fase 38** (§7): the type-checker proving `where:` / `persist` /
`mutate` against a declared column schema. 37.x is the
runtime-and-deploy half; Fase 38 is the compile-time half. Both are
named; neither is hand-waved.

**2 — Minimum to run, or robust and complete for large, complex
adopters?**

Robust — explicitly engineered past the triggering adopter.

- *The triggering case* (one logical schema, behind a transaction
  pooler): D1+D2+D3 make it *deterministically* correct — not "works on
  the 13th smoke iteration," works on the first.
- *Schema migration during uptime* (a large adopter migrates
  constantly): D9 — the cache self-heals; a live `ALTER TABLE` evicts
  the stale entry and the next operation re-introspects. No
  stale-until-restart.
- *Scale — many tables, many DSNs, multi-tenant*: D9 — the cache is a
  capacity-bounded LRU, not an immortal unbounded map.
- *First-operation race / a missing table*: D8 — eager deploy-time
  resolution; the schema is verified before the first request, a
  missing table is caught at deploy.
- *Schema-per-tenant topology*: the per-tenant-DSN case is first-class
  today (D1+D3 resolve coherently per connection); the
  one-DSN-many-schemas case gets an honest, actionable error now and
  the `schema:` declaration in Fase 38 — named, not scoped out.
- *Long streaming retrieves behind the pooler*: D3 — the cursor's
  transaction is bounded by the `PauseUpstream` row cap, so a held
  pooler backend is time-bounded; no pool starvation.

The minimum-to-run version of this cycle is D1+D2 alone (the smoke
passes). 37.x ships D1–D9 because "the smoke passes" is not the bar.
"No seventh iteration, for any adopter" is.
