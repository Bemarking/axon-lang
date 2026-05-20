---
title: "Plan vivo: Fase 38.x.d — IDENTITY end-to-end at COMPILE TIME (closing the v1.38.3 surface-only gap)"
status: ⏳ OPEN 2026-05-20 — adopter follow-up to v1.38.3 same-day.
owner: AXON Language + Runtime Team
created: 2026-05-20
target: |
  axon-lang **v1.38.4** (PATCH — bug fix; inline parser keyword + type-checker manifest consumption)
  axon-frontend **0.19.2** (additive parser surface + new TypeChecker constructor)
  axon-enterprise **v1.29.3** (catch-up per standing-rule; lean — dep-pin only)
depends_on: |
  Fase 38.x.c CLOSED 2026-05-20 (IDENTITY Column Recognition surface;
  v1.38.3). 38.x.d closes the architectural gap the adopter pointed at
  the moment v1.38.3 shipped: the `identity: bool` field is plumbed
  through `IntrospectionRow`, `ManifestColumn`, `StoreColumn`,
  `DeclaredColumn`, `IRStoreColumn` — but the field is set ONLY by
  introspect (the output surface). NO declaration form in `.axon`
  source can produce a non-false value, AND the type-checker doesn't
  consume the manifest's value for forms (b)/(c).

charter_class: |
  OSS end to end. Lives in `axon-frontend/src/parser.rs` (D1) +
  `axon-frontend/src/type_checker.rs` (D2) + `axon-rs/src/main.rs`
  (D3 — the CLI flag). Pure runtime substrate, vertical-agnostic.

# ▶ 1. The adopter's verdict on v1.38.3 (2026-05-20)

> *"Aunque el store introspect emite `"identity":true`. El fix de
> 1.38.3 surfó la propiedad en introspect (output), pero T803 todavía
> es un chequeo estático que sólo lee el schema declarado en el .axon
> — no consulta el introspect/pg_catalog. El gap está medio cerrado:
> la recognition llegó al output, no al type-checker."*

Spot-on. v1.38.3 made `axon store introspect` emit `identity: true`
into the manifest. But:

- An adopter who hand-writes `schema { id: BigInt primary_key identity }`
  inline gets a **PARSE ERROR** at the `identity` token. The inline
  parser's constraint-match arms cover `primary_key`, `auto_increment`,
  `not_null`, `unique`, `default` — and falls into `_ => break` for
  anything else.
- An adopter who writes `schema: "public.chat_history"` (form b
  manifest reference) sees the type-checker **silently skip** the
  proof for that store. Line 425-436 of `type_checker.rs` is explicit:
  *"Forms (b)/(c) need filesystem context (38.h/38.j) and are silently
  skipped at this layer — the deploy-time D8 (38.f) is their gate."*

Both gaps mean `identity: true` on a manifest never reaches T803 at
compile time. The recognition is in the OUTPUT, not the INPUT.

# ▶ 2. Architectural picture: three declaration forms, three plumbing routes

axon's `axonstore` declaration has three forms (D1 of Fase 38):

| Form | Source syntax | Where columns live | TypeChecker access (pre-v1.38.4) |
|---|---|---|---|
| (a) inline | `schema { id: BigInt identity }` | `StoreColumn` list in AST | DIRECT — `store_inline_column_sets` populated at `register_declarations` |
| (b) manifest_ref | `schema: "public.chat_history"` | `.axon-schema.json` on disk | SILENT SKIP (no filesystem context) |
| (c) env_var | `schema: env:TENANT_SCHEMA` | manifest entry resolved at runtime | SILENT SKIP (same reason) |

v1.38.4 closes BOTH the (a) parse-time hole AND the (b)/(c)
type-check-time hole — leaving the `axonstore` surface symmetric: any
declaration form can carry IDENTITY semantics, and the type-checker
proves T801-T805 + T803 against it.

# ▶ 3. The IDENTITY-End-to-End Contract — five D-letters

**D1 — inline parser accepts `identity` keyword.** The constraint
match arm in `parser.rs::parse_store_schema_declaration` gains
`"identity" => { col.identity = true; self.advance(); }`. Position-
independent like every other constraint; can co-occur with
`primary_key`, `not_null`, etc. **Statically enforced** by §4 grep
§-assertion in the new anchor.

**D2 — TypeChecker accepts an optional manifest.** New constructor
`TypeChecker::with_manifest(manifest: &Manifest)` (additive — the
existing `TypeChecker::new()` keeps working unchanged). When a
manifest is supplied AND a declaration uses form (b) `manifest_ref`,
`register_declarations` looks up the qualified name in the manifest,
converts the `ManifestStore` to a `ColumnSet` via `from_manifest_store`
(already exists from 38.d), and inserts it into
`store_inline_column_sets` the same way inline schemas do. The
type-checker code paths downstream (run_38d_where_proof,
run_38e_persist_proof, run_38e_mutate_proof) need NO change — they
read from the same HashMap.

**D3 — `axon check --schemas-dir <path>` CLI flag.** The Rust `axon`
binary's `check` subcommand gains the flag (mirror of `axon serve
--schemas-dir` from Fase 38.j). When set, the CLI runs
`load_and_merge_manifests(path)` and passes the result to
`TypeChecker::with_manifest`. Without the flag, behavior is
byte-identical to v1.38.3.

**D4 — form (c) env_var also honors the manifest.** `register_declarations`
extends to form (c): when the schema is `EnvVar { var, .. }` AND a
manifest is supplied, use the existing 38.d first-match heuristic
(`<env_var_name>.<store_name>` first, then any `*.<store_name>`) to
resolve the lookup. The runtime env-var resolution (Fase 38.f's D3)
is unchanged — D4 here only adds the compile-time lookup mirror.

**D5 — Absolute backwards-compat.** Without `--schemas-dir`, no
manifest is loaded; forms (b)/(c) silently skip at compile time
exactly as in v1.38.3. Inline schemas without `identity` keyword
behave exactly as before. Existing manifests with no `identity` key
parse with `identity = false` (D5 of 38.x.c carries through). No
adopter on v1.38.3 sees a behavioral change unless they opt in.

# ▶ 4. Sub-fases (38.x.d.1 — single-cycle patch)

| Sub-fase | What | D-letters | Status |
|---|---|---|---|
| **38.x.d.1** | `axon-frontend/src/parser.rs` — add `"identity"` arm to the constraint loop. Python parser stays at v1.33 surface per Rust-canonical directive. | D1 | ⏳ |
| **38.x.d.2** | `axon-frontend/src/type_checker.rs` — new `TypeChecker::with_manifest(&Manifest)` constructor. `register_declarations` extended to populate `store_inline_column_sets` for forms (b)/(c) when manifest is supplied. | D2, D4 | ⏳ |
| **38.x.d.3** | `axon-rs/src/main.rs` — extend the `check` subcommand with `--schemas-dir <path>` flag. Load manifests via `load_and_merge_manifests` and pass to TypeChecker. | D3 | ⏳ |
| **38.x.d.4** | New anchor `axon-rs/tests/fase38xd_identity_compile_time_proof.rs` — 5 §-assertions: §1 inline `identity` parses + T803 skips, §2 form (b) manifest_ref with `identity:true` → T803 skips, §3 form (b) without manifest → silent skip (D5 backwards-compat), §4 STATIC grep — parser constraint arm includes `"identity"`, §5 form (c) env_var with manifest → T803 skips. | D1, D2, D4, D5 | ⏳ |
| **38.x.d.5** | Coordinated patch release axon-lang **v1.38.4** + axon-frontend **0.19.2** (additive parser keyword + additive TypeChecker API). axon-enterprise **v1.29.3** catch-up per the standing rule. | — | ⏳ |

# ▶ 5. What is intentionally NOT in v1.38.4

- **Python parser surface for `identity` keyword.** Per founder
  directive *"todo encaminado a ser 100% Rust + C, 0 Python"* — Python
  frontend stays at v1.33 surface. Adopters using the Rust binary
  (which is what `axon/axon-enterprise:vX.Y.Z` ships) get the full
  surface. Python frontend continues to parse `identity` as a parse
  error — adopters using the Python frontend can use `auto_increment`
  as a stopgap (T803 already skips it).
- **Runtime evaluation of `GENERATED ALWAYS` rejection at T802.**
  Postgres rejects `INSERT INTO t(id) VALUES (...)` server-side when
  `id` is `GENERATED ALWAYS AS IDENTITY` (without `OVERRIDING SYSTEM
  VALUE`). A compile-time T802 arm rejecting this is a future
  38.x.e candidate; the `attidentity` 'a' vs 'd' distinction is
  preserved in `IntrospectionRow` (38.x.c) for that follow-up.
- **`axon check --schemas-dir` Python parity.** The Python `axon
  check` CLI doesn't consume manifests today; this stays the same.

# ▶ 6. The trigger source

- 2026-05-20 — kivi adopter response to v1.38.3:
  *"El gap está medio cerrado: la recognition llegó al output, no al
  type-checker."*
- Founder principle: *"Seguimos avanzando en hacer de axon un lenguaje
  sólido, completo y sofisticado."* — half-closed gaps are not
  acceptable.

Closed when axon-lang v1.38.4 + axon-enterprise v1.29.3 are both
live cross-stack.
