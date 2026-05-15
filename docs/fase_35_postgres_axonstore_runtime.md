---
title: "Plan vivo: Fase 35 — Postgres-backed axonstore runtime (the data plane the language already declares)"
status: 🚀 PROPOSED 2026-05-15 — D1–D13 pending founder bloque ratification. Triggered by the kivi-enterprise adopter gap report 2026-05-15 ("el runtime Rust ignora `axonstore { backend: postgresql }`"), verified true cross-path against the source.
owner: AXON Runtime + Backends Team
created: 2026-05-15
target: axon-lang v1.30.0 (minor — the `axonstore { backend: postgresql }` declaration becomes load-bearing at runtime: `retrieve` / `persist` / `mutate` / `purge` against a postgresql-backed store execute real SQL instead of routing to the session key-value store)
depends_on: Fase 34 SHIPPED v1.29.0 + v1.29.1 (Tools as stream-producers; the streaming dispatcher is the production hot path). Fase 33.z SHIPPED v1.27.0 (the dispatcher IS the production path — so wiring the store backend into `flow_dispatcher` reaches production traffic). `sqlx` (postgres feature) is already an axon-rs dependency; `axon-rs/src/db_pool.rs` + `storage_postgres.rs` + `migrations.rs` already establish the `PgPool` conventions to follow.
charter_class: OSS — every adopter that declares `axonstore { backend: postgresql }` gets a real SQL data plane. The capability is adopter-agnostic; no vertical-specific content. axon-enterprise inherits via the v1.30.0 catch-up (35.k).

pillars: |
  MATHEMATICS — The `axonstore` declaration is a categorical statement: the store IS the table (the Python reference impl names this the "Univalence A ≃ B" / HoTT schema-isomorphism — `CREATE TABLE ↔ IRStoreSchema`). `retrieve from S where φ` is the relational selection σ_φ(S); `persist` is a tuple insertion; `mutate` an update; `purge` a deletion. Today the Rust runtime reinterprets all four as key-value `get`/`put` on a `__store_<name>_<key>` namespace — categorically a DIFFERENT structure (a finite map, not a relation). Fase 35 corrects the morphism: a postgresql-backed `axonstore` denotes the actual relation, and the four operations denote the four relational-algebra operations against it.

  LOGIC — Store resolution is a total function over a closed catalog. Every `IRRetrieveStep` / `IRPersistStep` / `IRMutateStep` / `IRPurgeStep` carries a `store_name`; that name resolves against `IRProgram.axonstore_specs` to exactly one `IRAxonStore` or to the implicit in-memory default. `IRAxonStore.backend` is a closed catalog `{in_memory, postgresql}`. There is no third path, no silent fallback: a declared-but-unresolvable store, or an unknown backend slug, is an error — never a quiet KV lookup that looks like success.

  PHILOSOPHY — The language honors its own declarations. An adopter writes `axonstore tenants { backend: postgresql connection: "env:DATABASE_URL" }` and the runtime does what the words say. The pre-35 state — the declaration parses into `IRAxonStore` but the runtime never reads it — is the same class of defect as the SSE gap (Fase 30–34) and the webhook-HMAC gap (v1.29.1): a capability the language lets you DECLARE but the server silently does not HONOR. A language that compiles a lie is worse than one that rejects it.

  COMPUTING — A real data plane is the floor for building AI applications on axon. An agent flow that reads tenant rows, writes audit records, updates session state — that is most production AI software. `retrieve from tenants` that silently returns a key-value lookup by step-name instead of the tenant table is a divergence that deploys clean and corrupts at runtime. Closing it is what lets axon power "todo tipo de aplicaciones impulsadas por AI".

---

## ▶ 1. The trigger — verified adopter gap report

The kivi-enterprise adopter (migrating from the Python server to the Rust server to obtain the Fase 30–34 SSE algebraic-effects surface) filed a gap report 2026-05-15. **Verified true, file-by-file, and broader than the report claims:**

| Claim | Verification |
|---|---|
| The frontend parses the postgresql store | ✅ `axon-frontend/src/ir_nodes.rs:1286` — `IRAxonStore { name, backend, connection, confidence_floor, isolation, on_breach }`; `IRProgram.axonstore_specs: Vec<IRAxonStore>` (line 35). `axonstore X { backend: postgresql, connection: ... }` → `IRAxonStore` with `backend == "postgresql"`. |
| The sync runner ignores it | ✅ `axon-rs/src/runner.rs` has **0** references to `IRAxonStore` / `axonstore_specs` / `axonstore`. `execute_real`'s session-memory interception (~line 1139) routes `persist`/`retrieve`/`mutate`/`purge` to `session.*` (the scoped KV store), keyed by `step_name`. |
| **The streaming dispatcher ALSO ignores it** (not in the report) | ✅ `axon-rs/src/flow_dispatcher/wire_integrations.rs` — `persist_to_store` / `retrieve_from_store` / `mutate_store` / `purge_from_store` are pure key-value ops against `ctx.let_bindings` with `__store_<name>_<key>` keys. Zero SQL, zero `IRAxonStore`. The docstrings say verbatim *"OSS default … Enterprise overrides route to Postgres / Redis"*. **The gap is in BOTH execution paths.** |
| Python has a reference impl | ✅ `axon/runtime/store_backends/postgresql_backend.py` (376 LOC, `PostgreSQLStoreBackend`) + `sqlite_backend.py` + `filter_parser.py` (310 LOC, `build_pg_where` — parameterized) + `store_dispatcher.py` (497 LOC). |

It is a **runtime-parity gap**: the table-backed store model exists in the Python runtime and is absent from the Rust runtime. The Rust server compiles and deploys a flow that declares a postgresql store, then executes its `retrieve`/`persist` against an in-memory key-value map — a silent divergence.

## ▶ 2. The architectural arc — why this matters

axon-lang ships TWO HTTP servers — the Python `axon serve` server and the Rust `axon-rs` server. The Fase 30–34 cycles built the SSE algebraic-effects surface, the dispatcher, the wire-format adapter, tools-as-stream-producers — **in the Rust server**. Adopters migrating to the Rust server for that surface (kivi-enterprise is the first) discover that the Rust server, while ahead on streaming, is **behind on the data plane**: the Python server's `PostgreSQLStoreBackend` was never ported.

Migrating to the Rust server today therefore trades "no SSE" for "no data plane". Fase 35 closes the second half so the migration is whole: the Rust server gains the real `axonstore` data plane the Python server already has, and the Rust server becomes the single, complete production surface.

This is the **fourth instance of the same defect class** the project has been systematically closing — a declarable-but-not-wired capability:

- Fase 30–34 — `transport: sse` / algebraic stream effects → wired.
- v1.29.1 — webhook `compute_signature` documented HMAC-SHA256, was FNV-64 → fixed.
- v1.20.2 — `Dockerfile.enterprise` fetched the Rust binary then clobbered it → fixed.
- **Fase 35 — `axonstore { backend: postgresql }` parses but the runtime ignores it → this cycle.**

## ▶ 3. The model — `axonstore` IS the table

The reference (`PostgreSQLStoreBackend`) realizes a clean isomorphism. Fase 35 ports it to the Rust runtime via `sqlx`:

| `axon` source | Relational denotation | Rust runtime (Fase 35) |
|---|---|---|
| `axonstore S { backend: postgresql connection: C }` | the relation `S` reachable at `C` | a `PgPool` keyed by the resolved DSN |
| `retrieve from S where φ as r` | `r := σ_φ(S)` | `SELECT * FROM "S" WHERE <φ→parameterized>` → rows → JSON-safe value bound to `r` |
| `persist into S { c1: v1, … }` | `S := S ∪ {(v1,…)}` | `INSERT INTO "S" (c1,…) VALUES ($1,…) RETURNING *` |
| `mutate S where φ { c: v }` | `S := update_φ(S, c↦v)` | `UPDATE "S" SET c=$1 WHERE <φ→parameterized>` |
| `purge from S where φ` | `S := S \ σ_φ(S)` | `DELETE FROM "S" WHERE <φ→parameterized>` |

Where `<φ→parameterized>` is the closed-catalog filter compiler: column names regex-validated `[a-zA-Z_]\w*`, operators whitelisted `{=, !=, >, >=, <, <=, LIKE}`, every value bound as `$N` — no user value ever interpolated into the SQL string.

## ▶ 4. D-letters proposed (D1–D13) — pending founder bloque ratification

- **D1 — `axonstore { backend: postgresql }` is honored at runtime.** When a flow executes `retrieve` / `persist` / `mutate` / `purge` against a store whose resolved `IRAxonStore.backend == "postgresql"`, the Rust runtime executes real SQL against the declared `connection` — NOT the session/`let_bindings` key-value path.

- **D2 — Store resolution is a total function over a closed catalog.** Every store-op IR node's `store_name` resolves against `IRProgram.axonstore_specs`. `backend` is the closed catalog `{in_memory, postgresql}` (the implicit default is `in_memory`). A `store_name` that names no `IRAxonStore` AND is not a legacy implicit store, or an `IRAxonStore` with an unknown `backend` slug, surfaces a named error — never a silent KV lookup.

- **D3 — Zero regression on the key-value path (absolute).** A flow that uses only in-memory / default stores behaves **byte-identically** to pre-35 on BOTH execution paths. The SQL path is entered if and only if a matching `IRAxonStore` has `backend == "postgresql"`. This is kivi's explicit acceptance criterion and is non-negotiable.

- **D4 — Every WHERE clause is parameterized — SQL-injection-proof by construction.** The `where "<expr>"` predicate is parsed into a closed-catalog `FilterCondition` AST and rendered with `$1, $2, …` bind placeholders. Column identifiers are regex-validated; operators are whitelist-validated; values are ALWAYS bound parameters. No code path interpolates a user-supplied value into a SQL string. A `where` expression that fails to parse is a named error, not a degraded query.

- **D5 — Cross-stack runtime parity (Python ↔ Rust).** For the same store + operation + where-expression, the Rust backend emits the SAME SQL structure and exhibits the SAME observable behavior as Python's `PostgreSQLStoreBackend`. A shared corpus drift gate locks `build_pg_where` ≡ the Rust filter compiler.

- **D6 — Connection resolution: `connection: "env:VAR"` + literal DSN.** `IRAxonStore.connection` with an `env:` prefix resolves the named environment variable at runtime; any other value is treated as a literal DSN. A missing/empty env var surfaces a clear named error identifying the store and the variable — never a panic, never a silent fall-back to the KV path.

- **D7 — Both execution paths honored identically.** The sync runner (`runner.rs::execute_server_flow` → `execute_real`) AND the streaming dispatcher (`flow_dispatcher::wire_integrations`) route postgresql-backed store ops through the SAME `PostgresStoreBackend`. No path divergence — the Fase 30–34 lesson (a capability wired in one path and dormant in the other) is not repeated.

- **D8 — Connection pooling + lifecycle.** Exactly one `sqlx::PgPool` is created per distinct resolved DSN, lazily on first use, with bounded min/max connections, and reused across operations within a flow and across flows. Pool acquisition / construction failures surface as typed errors.

- **D9 — Honest failure surface.** Every failure mode — connection refused, authentication, missing table, SQL error, malformed where-expression, type-mapping failure — surfaces as a typed, named error carrying an adopter-facing diagnostic. No panic. No silent empty result that masks a failed query (an empty `SELECT` result and a failed `SELECT` are distinct observable outcomes).

- **D10 — Schema-absence is an honest, documented scope boundary.** `IRAxonStore` carries `backend` + `connection` but NOT the column schema. v1.30.0 therefore operates against **existing** tables — `query` / `insert` / `mutate` / `purge`. It does NOT emit `CREATE TABLE` DDL (`initialize`), `ALTER TABLE` (`migrate`), or `CREATE INDEX`. Those require the column definitions in the IR; extending `IRAxonStore` with the schema + shipping DDL is an explicit follow-on (35.x / Fase 36), documented in the adopter docs as a known boundary — not a silent omission.

- **D11 — Transaction discipline (single-statement autocommit in v1.30.0).** Each `retrieve` / `persist` / `mutate` / `purge` runs as one autocommit statement. The Python reference's multi-statement transaction surface (`begin_transaction` / `commit` / `rollback` with linear-logic tokens) binds to a future `transact { … }` block and is out of v1.30.0 scope — documented.

- **D12 — Production-grade D12 fuzz.** New `axon-rs/tests/fase35_fuzz.rs` (hand-rolled Knuth/MMIX LCG, no external dep): the filter compiler is total + never panics on arbitrary byte input; no input produces an unparameterized value (SQL-injection resistance is a fuzzed invariant, not just a unit test); operator/column closed-catalog rejection is total; store resolution is total.

- **D13 — Real-Postgres integration tests (the robustness floor).** Integration tests run `retrieve` / `persist` / `mutate` / `purge` end-to-end against a **real Postgres instance** (a Docker container the test harness spins up, mirroring the `fase33_d` axum-mock-server pattern but for a DB). Real rows, real SQL, real round-trips — not mocks. The implementation is proven against an actual database before it ships.

## ▶ 5. Sub-fase shape — sequenced execution

Topologically sequenced. 35.a anchors the gap. 35.b–d build the backend bottom-up (filter compiler → SQL backend → store registry). 35.e–f wire the two execution paths. 35.g–i are the robustness gates (fuzz, real-DB integration, cross-stack). 35.j is docs. 35.k is release.

| Sub-phase | Scope | LOC target | Status | Description |
|---|---|---|---|---|
| **35.a** | Diagnostic anchor + plan ratification | ~350 | ⏳ pending bloque | New `axon-rs/tests/fase35_a_axonstore_gap_diagnostic.rs` capturing the CURRENT behavior as the snapshot baseline: a flow with `axonstore S { backend: postgresql }` + `retrieve from S` routes to the KV path (the pre-35 wire/result shape, pinned). The anchor every 35.b–k sub-fase preserves or deliberately inverts. Founder D1–D13 ratification. |
| **35.b** | Filter compiler — `where`-expr → parameterized SQL | ~600 | ⏳ pending bloque | New `axon-rs/src/store/filter.rs` — faithful Rust port of `filter_parser.py`: tokenizer + parser → closed-catalog `FilterCondition { column, op, value }` AST → `build_pg_where(expr, param_offset) -> (clause, Vec<SqlValue>)` with `$N` placeholders. Closed operator catalog `{=, !=, >, >=, <, <=, LIKE}`; column regex `[a-zA-Z_]\w*`; typed value parsing (int/float/bool/null/string). Pure, no I/O — exhaustively unit-tested. D4 + D5 anchored here. |
| **35.c** | `PostgresStoreBackend` — the SQL backend | ~700 | ⏳ pending bloque | New `axon-rs/src/store/postgres_backend.rs` — `PostgresStoreBackend` over `sqlx::PgPool`: `query` (`SELECT * … WHERE`), `insert` (`INSERT … RETURNING *`), `mutate` (`UPDATE … SET … WHERE`), `purge` (`DELETE … WHERE`). `env:`-prefix DSN resolution; lazy bounded pool (D8); pg-row → JSON-safe value mapping (UUID / TIMESTAMPTZ / NUMERIC → JSON-stable strings — pre-empting the exact monkey-patches the kivi adopter reported needing on the Python side); typed `StoreError` surface (D9). |
| **35.d** | Store registry + backend dispatch | ~400 | ⏳ pending bloque | New `axon-rs/src/store/registry.rs` — `StoreRegistry` built from `IRProgram.axonstore_specs`: resolves `store_name` → `IRAxonStore`; closed-catalog `backend` dispatch (`postgresql` → `PostgresStoreBackend`, `in_memory`/absent → existing KV path); per-DSN `PgPool` cache. D2 + D3 dispatch decision lives here — the single chokepoint that decides SQL-vs-KV. |
| **35.d.1** | `sqlite` backend (catalog completeness) | ~400 | ⏳ optional bloque | Python ships `sqlite_backend.py`; the closed `backend` catalog is honestly `{in_memory, postgresql, sqlite}`. 35.d.1 ports the sqlite backend so the catalog is complete cross-stack. **Scoping question for ratification:** include in v1.30.0, or defer (catalog stays `{in_memory, postgresql}` for v1.30.0 with sqlite as a documented follow-on)? |
| **35.e** | Wire into the sync runner | ~450 | ⏳ pending bloque | `runner.rs` — `execute_server_flow` (which has `&IRProgram`) builds the `StoreRegistry` + threads it into `execute_real`; the session-memory interception consults the registry: postgresql store → `PostgresStoreBackend`, else → the current `session.*` path unchanged (D3). |
| **35.f** | Wire into the streaming dispatcher | ~450 | ⏳ pending bloque | `flow_dispatcher/wire_integrations.rs` — `persist_to_store` / `retrieve_from_store` / `mutate_store` / `purge_from_store` consult the `StoreRegistry` (threaded via `DispatchCtx`); postgresql → SQL, else → the `let_bindings` KV path unchanged (D3 + D7). This is the production hot path (Fase 33.z). |
| **35.g** | D12 fuzz | ~600 | ⏳ pending bloque | New `axon-rs/tests/fase35_fuzz.rs` — hand-rolled LCG: filter-compiler totality + never-panic on arbitrary input; SQL-injection-resistance invariant (no input → unparameterized value); operator/column closed-catalog rejection totality; store-resolution totality; pg-row → value mapping totality. |
| **35.h** | Real-Postgres integration tests | ~700 | ⏳ pending bloque | New `axon-rs/tests/fase35_h_postgres_integration.rs` — spins up a real Postgres (Docker container via the test harness), creates fixture tables, runs `retrieve`/`persist`/`mutate`/`purge` end-to-end through the runtime, asserts real rows. The D13 robustness floor. |
| **35.i** | Cross-stack parity drift gate | ~450 | ⏳ pending bloque | New `axon-rs/tests/fase35_i_cross_stack_filter.rs` + `tests/test_fase35_i_cross_stack_filter.py` — a shared corpus of `(where-expr → expected clause + params)` hardcoded byte-identical in both stacks; drift in Rust `build_pg_where` or Python `build_pg_where` fails both gates. D5. |
| **35.j** | Adopter docs | ~700 | ⏳ pending | New `docs/ADOPTER_AXONSTORE.md` — the `axonstore` reference: the `backend` catalog, `connection` resolution, the `where` filter grammar, the four operations, the D10/D11 honest scope boundaries (no DDL, single-statement autocommit). New `docs/MIGRATION_v1.30.md` scenario recipes. |
| **35.k** | Release v1.30.0 cross-stack + axon-enterprise catch-up | release | ⏳ pending | bump-my-version minor 1.29.1 → 1.30.0 across the 6 file entries; axon-frontend version TBD (likely unchanged — Fase 35 is runtime-only unless D10's IR-schema extension lands, which it does not in v1.30.0). crates.io + PyPI + GitHub Release. axon-enterprise catch-up consuming axon-lang 1.30.0. |

**Total target: ~6 200 LOC + the real-Postgres integration harness + the cross-stack drift gate + D12 fuzz. Cross-stack Python+Rust. D3 zero-regression absolute.**

## ▶ 6. Open scoping questions for the ratification bloque

1. **`sqlite` backend (35.d.1)** — in v1.30.0, or deferred? Python ships it; including it makes the `backend` catalog complete cross-stack. Deferring keeps v1.30.0 tighter (`{in_memory, postgresql}`).
2. **DDL / schema (D10)** — confirmed out of v1.30.0 (the IR has no schema). The follow-on that extends `IRAxonStore` with the column schema + ships `CREATE TABLE` — Fase 36, or a 35.x within this cycle?
3. **`transact { … }` block (D11)** — confirmed out of v1.30.0. The multi-statement transaction surface is a future fase.
4. **Value model** — `retrieve … as r` binds `r`. The runtime's binding values are strings; rows serialize to JSON. Confirm: a multi-row `SELECT` binds a JSON array; a single-row, a JSON object — or always an array? (Python `query` always returns a list.)

---

*This plan vivo is the Fase 35 source of truth. Sub-fase status flips ⏳ → ✅ SHIPPED at landing. D-letter text is frozen on founder bloque ratification.*
