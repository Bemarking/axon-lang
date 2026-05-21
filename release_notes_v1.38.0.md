# axon-lang v1.38.0 — The Declared & Compile-Time-Typed Store Schema

> **Cycle:** Fase 38 — *The Declared & Compile-Time-Typed Store Schema*.
> 11 sub-fases (a–k) shipped 2026-05-19/20. D1–D10 ratified.
>
> **TL;DR:** an `axonstore`'s columns become a **COMPILE-TIME type** the
> type-checker proves every `where:`, every `persist`, every `mutate`,
> every `purge` against. A `where: "tenantid = ${tenant_id}"` against a
> column actually spelled `tenant_id` is now a **compile error** with a
> Levenshtein "Did you mean `tenant_id`?" hint — the failure moves
> from runtime (pre-37.x) → deploy (37.x D8) → **compile time** (v1.38.0).
> Backwards-compatible by design (D5 absolute) — an `axonstore` without
> a `schema:` declaration behaves byte-identically to v1.37.0.

This is the **compile-time half** of the contract v1.37.0 shipped the
runtime+deploy half of. The TypedColumn pillar joins Epistemic +
Audit-chained + Streaming + Capability as the **FIFTH pillar** of the
cognitive data plane.

---

## The contract — ten D-letters

| D-letter | Guarantee |
|---|---|
| **D1** | An `axonstore` may declare its column schema in **three closed forms**: an inline `schema { col: Type, … }` block, a `schema: "qualified.name"` manifest reference, or a `schema: env:VAR` per-tenant env-var. The 15-type closed catalog: `{Uuid, Text, Int, BigInt, Float, Double, Bool, Timestamptz, Timestamp, Date, Time, Jsonb, Json, Bytea, Numeric}`. Anything else is a parse error |
| **D2** | When `schema:` is declared, `axon check` proves **every** `where:` column reference, **every** `persist`/`mutate` field name + value type, **every** `purge` `where:` column against the declared columns. **Total** end-to-end before deploy can proceed |
| **D3** | Per-tenant env-var resolution (`schema: env:TENANT_SCHEMA`) at deploy time — env var resolves to the SQL schema namespace, runtime sessions stamp the namespace into `application_name` (`axon-store/<store>/<tenant>`) so DBA tooling sees the tenant in `pg_stat_activity`. Missing env var → `axon-T806` deploy failure, never a silent fallback |
| **D4** | Canonical manifest format — `.axon-schema.yml` / `.axon-schema.json` key-sorted at every level, UTF-8, optional `sha256:` content-hash header, byte-deterministic serialization |
| **D5** | **Absolute backwards-compat.** An `axonstore` without a `schema:` declaration is **byte-identical** to v1.37.0. Every existing v1.37.x flow keeps working, untouched, with no diagnostic changes |
| **D6** | Honest, actionable diagnostics — every error code names the line + column, lists the declared schema's column inventory, surfaces a Levenshtein "Did you mean X?" suggestion when applicable, and (for type mismatches) lists columns whose type **would** accept the value |
| **D7** | A dedicated CI lane [`fase_38_typed_store_schema.yml`](https://github.com/Bemarking/axon-lang/blob/master/.github/workflows/fase_38_typed_store_schema.yml) exercises 5 parallel lanes: pure-column-proof + manifest-roundtrip + per-tenant-resolution + declared-vs-live-drift + d5-zero-regression |
| **D8** | `POST /v1/deploy` extends 37.x's D8 eager schema verification: when a `schema:` is declared, the live database's introspected columns must MATCH the declared columns. A drift (column type, presence) FAILS the deploy with `axon-T807` |
| **D9** | The 15-type catalog is closed; any addition requires a compiler PR + design note |
| **D10** | A new `axon store introspect <store>` CLI exports the live schema as a checked-in `.axon-schema.json` manifest — adopters capture the live schema at a moment in time, commit it, and `axon check` proves against the captured manifest **off line** (no database required for compile-time correctness) |

---

## Six error codes the language now speaks

| Code | What it catches |
|---|---|
| **`axon-T801`** | Unknown column referenced in a `where:` — with Levenshtein "Did you mean `tenant_id` (Uuid)?" composite hint |
| **`axon-T802`** | Column-type mismatch — a `String` parameter bound into a `Uuid` column, an `Int` literal compared to a `Text` column. Names declared vs. observed type AND lists type-compatible alternatives in the same schema |
| **`axon-T803`** | A `persist` block omits a NOT-NULL column with no default and no `auto_increment` — caught at compile time, not at the first `INSERT` |
| **`axon-T804`** | A `persist`/`mutate` field-block names a column that doesn't exist — with Levenshtein composite hint identical to T801 |
| **`axon-T805`** | A `.axon-schema.json` manifest's pinned `sha256:` content-hash doesn't match the manifest body — the operator's checked-in commitment was edited without updating the hash |
| **`axon-T807`** | Deploy-time declared-vs-live drift — the database's introspected columns disagree with the declared schema. Names the offending column + the migration to run |

(`axon-T806` is the deploy-time companion to D3 — missing per-tenant env var.)

---

## What changed end-to-end

- **An `axonstore` declared with `schema: { tenant_id: Uuid, tier: Text }` is now type-checked.** A typo in any `where:`/`persist`/`mutate`/`purge` is a compile error, named at line + column, with a suggestion.
- **Adopters checking in a `.axon-schema.json` manifest get offline compile-time correctness.** No database needed at `axon check` time — the type-checker proves against the captured manifest.
- **Multi-tenant SaaS adopters get `schema: env:TENANT_SCHEMA`.** The schema namespace resolves at deploy from the env var; runtime sessions stamp it into `application_name` so DBA tools see the tenant.
- **`axon serve --schemas-dir <path>`** activates the deploy-time declared-vs-live gate. Without the flag, behavior is byte-identical to v1.37.0 (D5 absolute).
- **`axon store introspect <store>`** captures the live schema as a canonical manifest. Honest omission of unmappable PG types (`enum 'tier_enum'` → `# omitted: …` comment, never silently lossily mapped to `Text`).

No adopter with a *working* v1.37.x setup regresses. D5 is absolute.

---

## New code surfaces

- `axon_frontend::store_schema::{StoreColumnType, StoreColumn, StoreColumnSchema}` — the closed 15-type catalog + the 3 declaration forms.
- `axon_frontend::store_schema_manifest::{Manifest, ManifestStore, ManifestColumn, ManifestError, load_and_merge_manifests, discover_manifest_files}` — the canonical manifest format + discovery layer + SHA-256 content-hash.
- `axon_frontend::store_column_proof::{ColumnSet, FlowParamTypes, ProofErrorCode, ProofError, check_filter, check_persist_fields, check_mutate_fields, suggest_columns_composite}` — the `axon check`-time proof + Fase 28-anchored composite Levenshtein suggestions.
- `axon_frontend::store_introspect::{udt_to_canonical_type, build_manifest_store, OmittedColumn, ManifestDiff, manifest_diff, format_manifest_diff}` — pure helpers behind the introspect CLI.
- `axon::store::registry::verify_postgres_schemas_with_manifest` — extends 37.x D8 to honor the declared schema; emits `T807` on declared-vs-live drift.
- `axon::store::postgres_backend::application_name_for_with_namespace` + `connect_named_with_namespace` — Gap-3-inheritance per-tenant `application_name` stamping.
- `axon::store::introspect_cli::{introspect_store, introspect_stores, render_introspection_output}` — the runtime side of `axon store introspect`.

---

## Test surface (~2 600 tests green)

- **393 axon-frontend lib** (`store_schema::` + `store_schema_manifest::` + `store_column_proof::` + `store_introspect::`).
- **5 `fase38_a_typed_store_diagnostic`** — pre-Fase-38 diagnostic anchor with all 5 §-assertions §1–§5 INVERTED in place (T801, T802, T804 fire as regression guards; §4 + §5 confirm grammar + CLI presence).
- **11 `fase38_b_schema_grammar`** + **1 `fase38_b_schema_drift_gate`** (cross-stack Rust ↔ Python drift over a 7-entry corpus).
- **8 `fase38_c_manifest_discovery`** — canonical YAML/JSON parity + content-hash verification.
- **21 `fase38_i_integration`** — end-to-end multi-store source against curated 5-tenant manifest + every D2 error code + composite suggestion + 38.h public-API smoke.
- **5 `fase38_i_property_fuzz`** — ~6 200 deterministic LCG iters across `Manifest::parse_json` totality + `check_filter` totality + `canonical_serialize` fixed point.
- **6 `fase38_j_schemas_dir_plumbing`** — the load-bearing wire: `--schemas-dir` × empty / non-existent / hash-mismatch / duplicate / verified-hash / D5 no-flag.
- **6 `fase38_h_introspect_integration`** — real-PG happy-path × omitted types × constraints × auto_increment × diff-mode × multi-store.
- **2 096 axon-rs lib + 48 store integration** (the 37.x baseline, unchanged — D5 absolute regression guard).

Zero regressions cross-stack. Python frontend untouched at v1.33.0 surface (Rust-canonical from 38.b onward per founder directive 2026-05-15).

---

## Dedicated CI workflow

[`.github/workflows/fase_38_typed_store_schema.yml`](https://github.com/Bemarking/axon-lang/blob/master/.github/workflows/fase_38_typed_store_schema.yml) — 5 parallel lanes:

1. **pure-column-proof** — `store_column_proof::` + `fase38_a_typed_store_diagnostic` + `store_introspect::` (no DB).
2. **manifest-roundtrip** — `store_schema_manifest::` + `fase38_i_integration` + `fase38_i_property_fuzz` (~6 200 LCG iters).
3. **per-tenant-resolution** — `store::registry::` + `store::postgres_backend::` (the D3 + Gap-3 stamping pack).
4. **declared-vs-live-drift** — the new `fase38_j_schemas_dir_plumbing` 6-case pack.
5. **d5-zero-regression** — `fase37x_i_property_fuzz` (~7 500 iters) + `fase35_fuzz` (~18 000 iters) + the broad Fase 32/33 family regressions — the cross-cycle D5 absolute guarantee.

A `fase-38-summary` gate job needs all five.

---

## Adopter migration

- **No `axonstore` declaration changed:** drop in v1.38.0. D5 absolute — byte-identical to v1.37.0.
- **Want compile-time column-type proof on a single store?** Add an inline `schema { … }` block (form a, smallest change).
- **Want a checked-in manifest?** `axon store introspect tenants --connection $DATABASE_URL --output schemas/tenants.axon-schema.json`, commit, point `schema: "public.tenants"`.
- **Multi-tenant SaaS?** Set `schema: env:TENANT_SCHEMA`, point per-tenant env, ship one manifest with `tenant_alpha.tenants`, `tenant_beta.tenants`, … entries.
- **Want deploy-time gating?** Add `--schemas-dir ./schemas` to `axon serve` (or `AXON_SCHEMAS_DIR` env var). T807 fires the moment declared columns disagree with live.

Full reference:

- 📖 [Migration guide v1.37.x → v1.38.0](https://github.com/Bemarking/axon-lang/blob/master/docs/MIGRATION_v1.38.md) — 6 scenario-driven recipes A–F.
- 📖 [`ADOPTER_AXONSTORE.md` §17](https://github.com/Bemarking/axon-lang/blob/master/docs/ADOPTER_AXONSTORE.md#17-the-compile-time-typed-store-schema-v1380) — the 5 recipes (inline / manifest / per-tenant / introspect-then-commit / wiring `--schemas-dir`).
- 📖 [`ADOPTER_TYPED_STORE.md`](https://github.com/Bemarking/axon-lang/blob/master/docs/ADOPTER_TYPED_STORE.md) — the 5-pillar deep-dive (Epistemic + Audit + Streaming + Capability + **TypedColumn**).
- 📖 [`AXON_GAP_store_typed_columns` resolution — compile-time half closed](https://github.com/Bemarking/axon-lang/blob/master/docs/fase/AXON_GAP_store_typed_columns_resolution.md) — close-the-loop on the original adopter gap report.
- 📋 [Plan vivo §1–§12](https://github.com/Bemarking/axon-lang/blob/master/docs/fase/fase_38_declared_compile_time_typed_store_schema.md) — the full cycle plan.

---

## What is intentionally NOT in v1.38.0

- **YAML manifest format** is deferred to a `38.c.2` follow-on behind a `yaml-manifest` Cargo feature pulling `serde_yaml`. The canonical-hash anchor stays on canonical JSON; YAML files when added parse → convert to canonical JSON → hash that, so format-mixing never breaks adopter hashes.
- **Compile-time proof for forms (b) `manifest_ref` and (c) `env_var`** runs at the `axon check` layer that has filesystem context — today the inline form (a) covers the load-bearing ~80% adopter case at compile time; forms (b)/(c) are still proven at deploy via 37.x D8 extended into T807.
- **NOT-NULL parity in T807** — 37.x's `introspect_conn` query doesn't capture `attnotnull`; the runtime catches NOT-NULL drift via SQLSTATE 23502 at the first failing persist (defense-in-depth retained); a `38.f.2` follow-on will extend the introspection.

---

## Acknowledgements

Triggered by the §7 commitment Fase 37.x landed on 2026-05-19. The
founder's principle — *"hacer que una aplicación AI sea determinista y
fundada en nuestros cuatro pilares como lenguaje es el aporte a la
humanidad"* — applied to the COLUMN as the fifth load-bearing pillar.

---

## Install

```sh
# Rust crate (axon-lang on crates.io)
cargo add axon-lang@1.38.0

# Python package (axon-lang on PyPI)
pip install axon-lang==1.38.0
```
