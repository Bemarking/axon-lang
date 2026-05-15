---
title: "Plan vivo: Fase 35 — axonstore as a cognitive data plane (the persistent relation no other language has)"
status: 🚀 PROPOSED 2026-05-15 (reframed from the industry-standard port to the axon-native vision per founder directive) — D1–D14 pending bloque ratification. Triggered by the kivi-enterprise gap report 2026-05-15, verified true; reframed because a faithful Postgres-ORM port would only EQUAL the market, and axon exists to surpass it.
owner: AXON Runtime + Backends Team
created: 2026-05-15
target: axon-lang v1.30.0 (minor — `axonstore` becomes a load-bearing runtime primitive: a persistent relation that is epistemically typed, audit-chained by construction, streamable, and capability-secured)
depends_on: Fase 34 SHIPPED v1.29.x (the `unified_stream_handler` + `Stream<ToolChunk>` surface — Pillar III routes through it). Fase 33.z SHIPPED v1.27.0 (the dispatcher is the production path). ESK Fase 6 (the epistemic lattice — Pillar I). Fase 16 / `esk::provenance` (HMAC-Merkle audit chains — Pillar II). Fase 32.g `auth_scope` + Fase 11/13 trust + capability types (Pillar IV). `sqlx` (postgres) + `axon-rs/src/db_pool.rs` already establish the `PgPool` substrate.
charter_class: OSS — every adopter that declares an `axonstore` gets the cognitive data plane. Adopter-agnostic; no vertical content. The OSS audit chain uses OSS crypto (`sha2`/`hmac` + axon-csys pure-C); axon-enterprise overrides Pillar II's crypto with the FIPS-validated + mmap tamper-evident kernel (`axon-csys-enterprise`) via the charter's SPLIT discipline. axon-enterprise inherits the base via the v1.30.0 catch-up (35.n).
strategic_direction: This cycle is built **Rust-canonical**. Per the founder directive 2026-05-15 — *"todo encaminado a ser 100% Rust + C, 0 Python"* — the Rust implementation IS the canonical `axonstore` runtime. The Python `axon/runtime/store_backends/` modules are the historical reference this cycle learns from, but they are frozen: no new Python store work, no Python↔Rust parity infrastructure is built (a permanent cross-stack drift gate would deepen exactly the coupling the project is retiring). The Python store backends are on the eventual deprecation path.

pillars: |
  MATHEMATICS — A relation `R` is not just a set of tuples. axon's `axonstore` is a relation enriched, ORTHOGONALLY, in four dimensions the relational model never carried: (1) an EPISTEMIC grading — each tuple sits somewhere in the lattice ⊥ ⊑ doubt ⊑ speculate ⊑ believe ⊑ know; (2) a TEMPORAL-INTEGRITY structure — the mutation history is a Merkle-chained sequence, a free monoid of deltas with a verifiable fold; (3) an ALGEBRAIC-EFFECT structure — selection σ_φ(R) is a coinductive `Stream`, not an eager set; (4) a CAPABILITY structure — access to `R` is a typed permission in the linear/affine sense. The faithful-ORM port realizes only the bare relation. Fase 35 realizes the enriched object — which is a genuinely new mathematical structure, not present in SQLAlchemy / Prisma / Diesel / sqlx, because those have no epistemic lattice, no algebraic-effect calculus, no capability types to enrich WITH.

  LOGIC — The four enrichments are not bolt-ons; they are axon SYSTEMS the store JOINS. axon already HAS the epistemic lattice (ESK, Fase 6), the HMAC-Merkle audit chain (Fase 16 / `esk::provenance`), the algebraic-effect streaming runtime (`unified_stream_handler`, Fase 34), and capability/trust types (Fase 11/13/32). No new invention is required — the `axonstore` simply becomes the PERSISTENT-DATA member of each system. The reason no other language can copy this is not cleverness; it is that no other language has the four systems to join.

  PHILOSOPHY — The language honors its own declarations — ALL of them. `IRAxonStore` carries `confidence_floor` and `on_breach` fields that the runtime has always ignored, exactly as it ignored `backend`. A Fase 35 that honored `backend` while leaving `confidence_floor`/`on_breach` inert would close one instance of the defect and ship the next. The reframed Fase 35 honors every field the declaration carries — and makes the declaration MEAN something the market cannot offer.

  COMPUTING — axon's purpose is to be the default language for building AI applications and agents. An agent's persistent memory is the substrate of its cognition: what it believes, how sure it is, what it is allowed to read, and a tamper-evident record of how its world changed. A plain table answers none of those. The cognitive data plane answers all four — as language primitives, verified, with zero adopter bolt-on. That is the floor for "the default language for AI software".

---

## ▶ 1. The trigger + the reframe

The kivi-enterprise adopter filed a gap report 2026-05-15: the Rust runtime ignores `axonstore { backend: postgresql }`. **Verified true** (file-by-file; the gap is in BOTH the sync runner `runner.rs` AND the streaming dispatcher `flow_dispatcher/wire_integrations.rs` — both route `retrieve`/`persist`/`mutate`/`purge` to a key-value store, never SQL). The Python runtime has a `PostgreSQLStoreBackend` reference; the Rust runtime has nothing.

The first draft of this plan proposed the obvious fix: a faithful Rust port of the Python backend — `PgPool` + parameterized CRUD. **That draft was correct and would have closed the gap — and it would only have made axon EQUAL the market.** "Map a store declaration to a table and do CRUD with a parameterized WHERE" is what every ORM does.

The reframe: `axonstore` is not a table. The proof is in the language's own IR — `IRAxonStore` carries `confidence_floor: Option<f64>` and `on_breach: String`, fields the language designers placed there and the runtime never honored. They are the language saying, in its own type, that a store was always meant to be a *cognitive* object. Fase 35 builds that object.

## ▶ 2. The model — the four enrichments

A normal store is `Relation`. The axon `axonstore` is `Relation` enriched in four orthogonal dimensions, each by JOINING an axon system that already exists:

### Pillar I — Epistemic (the store joins the ESK lattice)

Every tuple in an `axonstore` has an epistemic grade. Data does not enter the world `true` — it enters `Untrusted` (⊥) and is *elevated* by reasoning. This is already how ℰMCP-sourced data (`EpistemicTaint`) and LLM-streamed tokens (`EpistemicGradient`) are treated. The `axonstore` joins that discipline:

- A row produced by `retrieve from S` is born `Untrusted` — a downstream `shield` / `know` / reasoning step must elevate it before it is trusted. A `retrieve` result is NOT a fact; it is a claim.
- `confidence_floor: f` on the store is enforced: `retrieve` filters or flags tuples whose stored confidence is below `f`.
- `persist into S` of a value below the store's `confidence_floor`, or of an un-elevated `Untrusted` value, is a typed error — you cannot quietly write doubt into a believed store.

No ORM has the concept "this row has a confidence and a trust level". axon does — the store joins it.

### Pillar II — Audit-chained by construction (the store joins the Fase 16 / ESK provenance chain)

Every `persist` / `mutate` / `purge` appends a delta to a tamper-evident, **HMAC-Merkle-chained** mutation log. The chain's crypto is the OSS `sha2`/`hmac` path (axon-enterprise overrides with the FIPS-validated + mmap kernel from `axon-csys-enterprise`, per the SPLIT charter — and the C kernels are the "Rust + C" half of the stack).

- The store's complete mutation history is an independently verifiable Merkle sequence — regulatory replay (PCI DSS Req 10, FedRAMP AU-2, 21 CFR Part 11 §11.10, FRE 502) as a *language primitive*, not an event-sourcing framework the adopter bolts on.
- `on_breach: String` is honored: when chain verification detects tampering, the declared policy fires (`halt` / `quarantine` / `alert`).

The market answer is CDC + audit triggers + an event store, integrated by hand. axon's `axonstore` gives a tamper-evident mutation chain for free.

### Pillar III — `retrieve` is a `Stream<Row>` (the store joins the Fase 34 algebraic-effect surface)

`retrieve from S where φ` is the coinductive selection — a `Stream<Row>` drained through the **same `unified_stream_handler` Fase 34 shipped**. A large result set is not materialized; rows flow with a declared `BackpressurePolicy`, cancel-aware (D5 cancel-into-body).

- A pg-backed `axonstore` is, structurally, a first-class stream producer — unified with `Tool::stream()` and the four streaming-effect disjunctions.
- `retrieve from huge_table` does not OOM the agent; it streams, exactly like an LLM token stream, through one drain loop.

The market answer is cursors and manual pagination. axon's is the algebraic-effect stream it already has.

### Pillar IV — Capability-typed access (the store joins the trust / capability type system)

`retrieve` / `persist` / `mutate` / `purge` against `S` require the executing flow to hold a capability for `S`. The **type-checker enforces it** — store access is a typed permission, not an app-code `if tenant_id == …` the developer must remember.

- Data isolation (the tenant-isolation audit found it lives entirely in app code) becomes a *language guarantee*: a flow without the capability cannot, by construction, read the store.
- This joins Fase 32.g auth scopes, Fase 11/13 trust types + capability extrusion.

The market answer is row-level-security policies + app-layer scoping. axon's is a capability type the compiler checks.

## ▶ 3. Why this is the market-surpassing object

| Concern | Industry standard (ORM / query builder) | axon `axonstore` (Fase 35) |
|---|---|---|
| A retrieved row is… | a fact | a *claim* — born `Untrusted`, must be elevated (Pillar I) |
| Mutation history | bolt-on: CDC / triggers / event store | a verifiable HMAC-Merkle chain, by construction (Pillar II) |
| Large result sets | manual cursors / pagination | a backpressured, cancel-aware `Stream<Row>` (Pillar III) |
| Access control | RLS policies + app-layer `tenant_id` checks | a capability the type-checker enforces (Pillar IV) |
| Why others can't copy it | — | they have no epistemic lattice, no algebraic-effect calculus, no audit-chain primitive, no capability types to enrich a relation WITH |

## ▶ 4. D-letters proposed (D1–D14) — pending founder bloque ratification

**The substrate (D1–D7) — the relation must be real before it can be enriched:**

- **D1 — `axonstore { backend: postgresql }` honored at runtime.** `retrieve`/`persist`/`mutate`/`purge` against a postgresql-backed store execute real SQL against the declared `connection` — not the key-value path.

- **D2 — Store resolution is a total function over a closed catalog.** Every store-op IR node's `store_name` resolves against `IRProgram.axonstore_specs`. `backend ∈ {in_memory, postgresql}` (closed; `in_memory` is the implicit default). Unknown backend or unresolvable store → a named error, never a silent KV lookup.

- **D3 — Zero regression on the key-value path (absolute).** A flow using only in-memory/default stores behaves byte-identically to pre-35 on BOTH execution paths. The SQL path is entered iff a matching `IRAxonStore` has `backend == "postgresql"`. kivi's explicit acceptance criterion; non-negotiable.

- **D4 — Every WHERE clause is parameterized — SQL-injection-proof by construction.** `where "<expr>"` parses into a closed-catalog `FilterCondition` AST (column regex `[a-zA-Z_]\w*`; operators whitelisted `{=,!=,>,>=,<,<=,LIKE}`; values typed) and renders with `$N` bind placeholders. No code path interpolates a user value into SQL.

- **D5 — Both execution paths honored identically.** The sync runner (`runner.rs`) AND the streaming dispatcher (`flow_dispatcher::wire_integrations`) route postgresql-backed ops through the SAME backend. No path divergence — the SSE-gap lesson is not repeated.

- **D6 — Connection resolution: `connection: "env:VAR"` + literal DSN.** `env:`-prefixed values resolve the named environment variable; other values are literal DSNs. Missing env var → a clear named error, never a panic, never a silent KV fallback.

- **D7 — Pooling + honest typed failure surface.** One `sqlx::PgPool` per distinct resolved DSN, lazy, bounded, reused. Every failure (connect, auth, missing table, SQL error, malformed where-expr, type mapping) → a typed named error. No panic; no silent empty result masking a failed query.

**The four enrichments (D8–D11) — the axon-native object:**

- **D8 — Pillar I, Epistemic data plane.** Every tuple from `retrieve` is born `Untrusted` (⊥) in the ESK lattice. `confidence_floor` is enforced at `retrieve` (sub-floor tuples filtered/flagged) and at `persist` (writing an un-elevated or sub-floor value is a typed error). The `axonstore` is a participant in axon's epistemic discipline, not an opaque byte store.

- **D9 — Pillar II, Audit-chained by construction.** Every `persist`/`mutate`/`purge` appends a delta to a tamper-evident HMAC-Merkle mutation chain (OSS `sha2`/`hmac` crypto; enterprise overrides with the FIPS + mmap C kernel). The chain is independently verifiable. `on_breach` is honored on tamper detection. Regulatory replay is a primitive, not a framework.

- **D10 — Pillar III, `retrieve` is a `Stream<Row>`.** Result sets drain through the Fase 34 `unified_stream_handler` with a `BackpressurePolicy`, cancel-aware. A pg-backed `axonstore` is a first-class stream producer, unified with the algebraic-effect surface — large `retrieve` never materializes eagerly.

- **D11 — Pillar IV, Capability-typed store access.** `retrieve`/`persist`/`mutate`/`purge` against `S` require a capability for `S`, enforced by the type-checker (compile-time) and re-checked at runtime. Data isolation becomes a language guarantee. Joins Fase 32.g auth scopes + Fase 11/13 trust/capability types.

**Honest scope + robustness (D12–D14):**

- **D12 — Schema-absence + transaction scope are honest, documented boundaries.** `IRAxonStore` carries no column schema → v1.30.0 operates against existing tables (no `CREATE TABLE`/`migrate`/`CREATE INDEX` DDL — needs an IR schema extension, a documented follow-on). Each op is single-statement autocommit; the multi-statement `transact { … }` block is a documented future fase. Boundaries are stated in the adopter docs, not silently omitted.

- **D13 — Production-grade D12 fuzz.** `axon-rs/tests/fase35_fuzz.rs` (hand-rolled LCG): filter compiler totality + never-panic; SQL-injection-resistance as a fuzzed invariant (no input → unparameterized value); closed-catalog operator/column rejection totality; epistemic-grade assignment totality; audit-chain integrity under arbitrary delta sequences; store-resolution totality.

- **D14 — Real-Postgres integration tests (the robustness floor).** `axon-rs/tests/fase35_*_postgres_integration.rs` exercises all four pillars end-to-end against a REAL Postgres (Docker container spun up by the harness): real rows, real `confidence_floor` filtering, real audit-chain Merkle verification, real `Stream<Row>` backpressure, real capability gating. Not mocks. The implementation is proven against an actual database before it ships.

## ▶ 5. Sub-fase shape — sequenced execution

Substrate first (35.a–f) — the relation must be real before it is enriched. Then the four pillars (35.g–j), each joining an existing axon system. Then the robustness gates (35.k–l), docs (35.m), release (35.n).

| Sub-phase | Scope | LOC target | Status | Description |
|---|---|---|---|---|
| **35.a** | Diagnostic anchor + four-pillar architecture spec | ~450 | ⏳ pending bloque | `axon-rs/tests/fase35_a_axonstore_gap_diagnostic.rs` pins the CURRENT behavior (pg-store `retrieve` → KV) as the snapshot baseline. The architecture spec for the four enrichments + their join points into ESK / `esk::provenance` / `unified_stream` / `auth_scope`. Founder D1–D14 ratification. |
| **35.b** | Filter compiler — `where`-expr → parameterized SQL | ~600 | ⏳ pending bloque | New `axon-rs/src/store/filter.rs` — tokenizer + parser → closed-catalog `FilterCondition` AST → `build_pg_where(expr, offset) -> (clause, Vec<SqlValue>)` with `$N` placeholders. Pure, no I/O, exhaustively unit-tested. D4. |
| **35.c** | `PostgresStoreBackend` — SQL substrate | ~750 | ⏳ pending bloque | New `axon-rs/src/store/postgres_backend.rs` — `query`/`insert`/`mutate`/`purge` over `sqlx::PgPool`; `env:` DSN resolution; lazy bounded pool; pg-row → JSON-safe value mapping (UUID/TIMESTAMPTZ/NUMERIC — pre-empting the kivi-reported Python monkey-patches); typed `StoreError`. D6 + D7. |
| **35.d** | `StoreRegistry` + closed-catalog dispatch | ~450 | ⏳ pending bloque | New `axon-rs/src/store/registry.rs` — built from `IRProgram.axonstore_specs`; resolves `store_name` → `IRAxonStore`; closed `backend` dispatch (`postgresql` → SQL backend, else → KV path); per-DSN pool cache. D2 + D3 — the single SQL-vs-KV chokepoint. |
| **35.e** | Wire into the sync runner | ~450 | ⏳ pending bloque | `runner.rs` — `execute_server_flow` builds the `StoreRegistry` + threads it into `execute_real`; the session-memory interception consults it. KV path byte-unchanged (D3). |
| **35.f** | Wire into the streaming dispatcher | ~450 | ⏳ pending bloque | `flow_dispatcher/wire_integrations.rs` — `persist_to_store`/`retrieve_from_store`/`mutate_store`/`purge_from_store` consult the registry (threaded via `DispatchCtx`). Production hot path. D3 + D5. |
| **35.g** | **Pillar I — Epistemic data plane** | ~900 | ⏳ pending bloque | New `axon-rs/src/store/epistemic.rs` — `retrieve` tuples born `Untrusted` in the ESK lattice; `confidence_floor` enforced at `retrieve` (filter/flag) + `persist` (sub-floor / un-elevated write → typed error). Joins ESK Fase 6 (`esk/`). D8. |
| **35.h** | **Pillar II — Audit-chained mutations** | ~1000 | ⏳ pending bloque | New `axon-rs/src/store/audit_chain.rs` — every `persist`/`mutate`/`purge` appends an HMAC-Merkle delta; independent chain verification; `on_breach` policy enforcement. Crypto via `sha2`/`hmac` (OSS) — enterprise overrides with the `axon-csys-enterprise` FIPS + mmap C kernel. D9. |
| **35.i** | **Pillar III — `retrieve` as `Stream<Row>`** | ~750 | ⏳ pending bloque | New `axon-rs/src/store/row_stream.rs` — `retrieve` produces a `Stream<Row>` drained through the Fase 34 `unified_stream_handler` with a `BackpressurePolicy`, cancel-aware. The pg `axonstore` becomes a first-class stream producer. D10. |
| **35.j** | **Pillar IV — Capability-typed store access** | ~850 | ⏳ pending bloque | `axon-frontend` type-checker — store access requires a capability (compile-time); `axon-rs` runtime re-check. Joins Fase 32.g `auth_scope` + Fase 11/13 trust/capability types. D11. |
| **35.k** | D12 fuzz | ~700 | ⏳ pending bloque | `axon-rs/tests/fase35_fuzz.rs` — hand-rolled LCG: filter totality + SQL-injection-resistance invariant + closed-catalog rejection + epistemic-grade totality + audit-chain integrity + resolution totality. D13. |
| **35.l** | Real-Postgres integration tests | ~900 | ⏳ pending bloque | `axon-rs/tests/fase35_l_postgres_integration.rs` — a real Postgres (Docker container); all four pillars exercised end-to-end: real rows, real `confidence_floor` filter, real Merkle verification, real `Stream<Row>` backpressure, real capability gate. D14. |
| **35.m** | Adopter docs | ~800 | ⏳ pending | New `docs/ADOPTER_AXONSTORE.md` — the cognitive data plane reference: the four pillars, the `backend`/`connection` catalog, the `where` grammar, the D12 honest scope boundaries. New `docs/MIGRATION_v1.30.md`. |
| **35.n** | Release v1.30.0 cross-stack + axon-enterprise catch-up | release | ⏳ pending | bump-my-version minor 1.29.1 → 1.30.0; crates.io + PyPI + GitHub Release; axon-enterprise catch-up (inherits the base; the enterprise Pillar-II crypto override ships in the enterprise vertical track). |

**Total target: ~10 000 LOC + the real-Postgres integration harness + D12 fuzz. Built Rust-canonical (the strategic direction — 0 Python). D3 zero-regression absolute.**

## ▶ 6. Open scoping questions for the ratification bloque

1. **Pillar sequencing.** All four pillars (35.g–j) in v1.30.0 — or substrate + a subset in v1.30.0, the rest in v1.30.x? Recommendation: all four — the substrate alone is the "industry-standard" version the founder explicitly rejected; the pillars ARE Fase 35.
2. **`confidence_floor` storage (Pillar I).** A row's stored confidence — a reserved `_confidence` column convention, or a sidecar metadata table? Affects the schema contract with the adopter's existing tables.
3. **Audit-chain storage (Pillar II).** The Merkle chain — a sidecar table in the same Postgres, or the existing `audit_trail` store? And: is `on_breach` a closed catalog `{halt, quarantine, alert}`?
4. **Capability grammar (Pillar IV).** Does the store capability reuse the Fase 32.g `requires: [slug]` grammar, or a new `axonstore S { capability: <slug> }` field on the declaration?
5. **`sqlite` backend.** Python ships `sqlite_backend.py`. Include a Rust `sqlite` backend in the closed catalog for v1.30.0, or keep `{in_memory, postgresql}` and add sqlite later?

---

*This plan vivo is the Fase 35 source of truth. Built Rust-canonical per the 0-Python strategic direction. Sub-fase status flips ⏳ → ✅ SHIPPED at landing. D-letter text is frozen on founder bloque ratification.*
