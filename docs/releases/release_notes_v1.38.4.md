# axon-lang v1.38.4 — IDENTITY end-to-end at compile time (Fase 38.x.d)

> **Cycle:** Fase 38.x.d — *IDENTITY end-to-end at compile time*. Fourth patch in the v1.38.x adopter-report closure chain (v1.38.1 → v1.38.4 in <10 hours). D1–D5 ratified.
>
> **TL;DR:** v1.38.3 plumbed `identity: bool` through the AST + manifest + introspect OUTPUT — but no `.axon` declaration form could SET the field non-false, AND the type-checker silently skipped forms (b) `manifest_ref` + (c) `env_var` at compile time. **v1.38.4 makes T801-T805 + T803 consume `identity` from EVERY declaration form.** Adopters can now declare `id: BigInt primary_key identity not_null` inline OR point at a manifest with `axon check --schemas-dir <path>` — either way, the proof runs.

---

## The adopter's verdict on v1.38.3 (2026-05-20)

> *"Aunque el store introspect emite `"identity":true`. El fix de 1.38.3 surfó la propiedad en introspect (output), pero T803 todavía es un chequeo estático que sólo lee el schema declarado en el .axon — no consulta el introspect/pg_catalog. El gap está medio cerrado: la recognition llegó al output, no al type-checker."*

Spot-on. Two architectural gaps remained after v1.38.3:

1. **Inline parser didn't accept `identity` keyword.** Adopters who hand-wrote `schema { id: BigInt primary_key identity }` got a parse error at the `identity` token.
2. **TypeChecker silently skipped forms (b)/(c).** Even with `identity: true` in the manifest, `schema: "public.chat_history"` (form b) and `schema: env:TENANT_SCHEMA` (form c) never reached T803 at compile time — the type-checker only consulted inline column blocks.

v1.38.4 closes both. The `identity` field is now setable from every declaration form, AND consumed by every proof code path.

## The contract — 5 D-letters

| D-letter | Guarantee |
|---|---|
| **D1** | Inline parser accepts `identity` keyword in `schema { col: Type identity }` blocks. Position-independent like `primary_key`/`not_null`/`unique`. **Statically enforced** by §4 grep §-assertion in the new anchor |
| **D2** | New `TypeChecker::with_manifest(&Program, &Manifest)` constructor — additive (existing `::new()` keeps working). `register_declarations` populates `store_inline_column_sets` for ALL THREE forms when manifest is supplied: form (a) inline → unchanged; form (b) `manifest_ref` → `manifest.lookup(qualified_name)`; form (c) `env_var` → first-match heuristic. Proof code paths read uniformly from the same HashMap — zero downstream code change |
| **D3** | `axon check --schemas-dir <path>` CLI flag (env var `AXON_SCHEMAS_DIR`). Mirror of `axon serve --schemas-dir` from Fase 38.j. Loads + merges every `.axon-schema.json` under the path and feeds the result to `TypeChecker::with_manifest`. **Without the flag**, behavior byte-identical to v1.38.3 |
| **D4** | Form (c) env_var resolution mirrors the deploy-time `declared_columns_for` (Fase 38.f): exact `<env_var>.<store_name>` first, then suffix-scan `*.<store_name>` fallback. Compile-time check sees the same ColumnSet deploy-time check would |
| **D5** | **Absolute backwards-compat.** Without `--schemas-dir`, no manifest loads; forms (b)/(c) silently skip exactly as v1.38.3. Inline schemas without `identity` keyword behave exactly as before |

## What you'll see post-upgrade

### Inline schema with `identity` keyword

```axon
axonstore chat_history {
    backend: postgresql
    connection: "env:DATABASE_URL"
    schema {
        id: BigInt primary_key identity not_null
        tenant_id: Uuid not_null
        content: Text not_null
    }
}

flow Insert(tid: Uuid, msg: Text) -> Text {
    persist into chat_history { tenant_id: "${tid}" content: "${msg}" }
    // ↑ T803 does NOT fire on omitted `id` — it's `identity: true`
}
```

`axon check` compiles green. The `id` column stays in the manifest so T801 + T802 + T804 keep firing on every future reference.

### Manifest reference + `axon check --schemas-dir`

```axon
axonstore chat_history {
    backend: postgresql
    connection: "env:DATABASE_URL"
    schema: "public.chat_history"
}
```

```sh
# Introspect once to capture the schema (refreshes identity:true onto IDENTITY columns):
axon store introspect chat_history --connection $DATABASE_URL --output schemas/chat_history.json

# Compile-time proof now consults the manifest:
axon check src/flow.axon --schemas-dir ./schemas
```

T801-T805 + T803 fire compile-time against the manifest's declared columns — including the IDENTITY semantics from v1.38.3.

### Backwards-compat path (no opt-in)

```sh
# No --schemas-dir flag → v1.38.3 behavior preserved:
axon check src/flow.axon
# Forms (b)/(c) silently skip; T807 at deploy still catches declared-vs-live drift.
```

## Test surface (zero regressions)

- **2 096** axon-rs lib tests green (identical baseline to v1.38.3)
- **6** new `fase38xd_identity_compile_time_proof` §-assertions:
  - §1 D1 inline `identity` keyword parses + sets `identity=true` (+ negative control: non-identity columns default to `false`)
  - §2 D2 form (b) manifest_ref with `identity:true` → T803 skips
  - §3 D5 form (b) without manifest → silent skip (backwards-compat)
  - §4 D1 STATIC grep — parser constraint arm includes `"identity"`
  - §5 D4 form (c) env_var with manifest first-match → T803 skips
- **9/9** fase38xc (38.x.c invariants intact)
- **6/6** fase38x_a (38.x.a + 38.x.b invariants intact)
- **5/5** fase37x_a, 6/6 fase37x_i_property_fuzz, 6/6 fase35_fuzz, 6/6 fase38_j

## What is intentionally NOT in v1.38.4

- **Python parser surface for `identity` keyword.** Per founder directive *"todo encaminado a ser 100% Rust + C, 0 Python"* — Python frontend stays at v1.33 surface. Adopters using the Rust binary (which is what `axon/axon-enterprise:vX.Y.Z` ships) get the full surface.
- **Python `axon check --schemas-dir` parity.** Python doesn't consume manifests today.
- **T802 rejection of values INTO `GENERATED ALWAYS` columns.** The `attidentity` 'a' vs 'd' distinction is preserved in `IntrospectionRow` for a future 38.x.e arm.

## Same-day chain summary (v1.38.x kivi smoke-16 closure)

| Patch | Cycle | Closure |
|---|---|---|
| **v1.38.1** | Fase 38.x.a | Pooler-coherent transactions + observability |
| **v1.38.2** | Fase 38.x.b | Admin schema isolation + enterprise FK relocation |
| **v1.38.3** | Fase 38.x.c | IDENTITY recognition (output surface) |
| **v1.38.4** | Fase 38.x.d | IDENTITY end-to-end at compile time (this release) |

Four patches, four contracts, one same-day adopter-report closure cycle. The Pillar V TypedColumn promise — every adopter dimension proven before a request is served — now holds for IDENTITY columns across ALL THREE `schema:` declaration forms.

## Cross-links

- 📋 [Plan vivo Fase 38.x.d](https://github.com/Bemarking/axon-lang/blob/master/docs/fase/fase_38xd_identity_end_to_end.md)
- 📖 [v1.38.1](https://github.com/Bemarking/axon-lang/releases/tag/v1.38.1) — Pooler-coherent Transactions
- 📖 [v1.38.2](https://github.com/Bemarking/axon-lang/releases/tag/v1.38.2) — Admin Schema Isolation
- 📖 [v1.38.3](https://github.com/Bemarking/axon-lang/releases/tag/v1.38.3) — IDENTITY surface

## Standing rule honored

Per founder directive 2026-05-20: every axon-lang release ships an axon-enterprise catch-up. **axon-enterprise v1.29.3 ships next** with the dep pin advance.

## Acknowledgements

Founder framing 2026-05-20:
> *"Seguimos avanzando en hacer de axon un lenguaje sólido, completo y sofisticado."*

Half-closed gaps are not acceptable. v1.38.4 closes the gap end-to-end.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
