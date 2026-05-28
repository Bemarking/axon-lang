# axon-enterprise v1.29.3 — catch-up to axon-lang 1.38.4 (IDENTITY end-to-end at compile time)

Patch catch-up bundling **axon-lang v1.38.4** (Fase 38.x.d — IDENTITY end-to-end at compile time). axon-lang dep pin: `>=1.38.3` → `>=1.38.4`. axon-frontend Rust crate dep transitively `0.19.1` → `0.19.2`.

## What enterprise tenants inherit (Fase 38.x.d)

v1.38.3 plumbed `identity: bool` through the AST + manifest + introspect OUTPUT — but no `.axon` declaration form could SET the field non-false, AND the type-checker silently skipped forms (b) `manifest_ref` + (c) `env_var` at compile time. v1.38.4 makes T801-T805 + T803 CONSUME the field from EVERY declaration form.

### 5 D-letters

| D-letter | Guarantee |
|---|---|
| **D1** | Inline parser accepts `identity` keyword: `schema { id: BigInt primary_key identity not_null }` now compiles. Position-independent like `primary_key`/`not_null`/`unique`. Statically enforced by §4 grep §-assertion |
| **D2** | New `TypeChecker::with_manifest(&Program, &Manifest)` constructor — additive. `register_declarations` populates `store_inline_column_sets` for ALL THREE forms when a manifest is supplied |
| **D3** | `axon check --schemas-dir <path>` CLI flag (env var `AXON_SCHEMAS_DIR`). Mirror of `axon serve --schemas-dir` from Fase 38.j |
| **D4** | Form (c) env_var first-match resolution mirrors the deploy-time `declared_columns_for`: exact `<env_var>.<store_name>` first, then suffix-scan `*.<store_name>` |
| **D5** | **Absolute backwards-compat.** Without `--schemas-dir`, no manifest is loaded; forms (b)/(c) silently skip exactly as in v1.38.3 |

## Vertical inheritance — transparent

Enterprise tenants on regulated verticals inherit the contract (no per-tenant code change required):

- 🏥 **HIPAA Safe Harbor + 21 CFR Part 11 §11.10(e)** clinical PHI stores using `id BIGINT GENERATED ALWAYS AS IDENTITY` can declare it inline (`schema { id: BigInt primary_key identity not_null }`) OR via `--schemas-dir`-loaded manifest; T803 no longer false-positives; T801 + T802 + T804 keep firing on every column reference.
- ⚖️ **FRE 502 + Upjohn / Hickman + ABA Rule 1.6** legal stores with IDENTITY-keyed privilege logs get the same closure.
- 💰 **BSA / OFAC / MiFID II** AML fintech stores with IDENTITY-keyed transaction ledgers inherit identically.
- 🏛 **FedRAMP AU-2 + AC-3** government stores using IDENTITY primary keys on `audit_event_log` keep the SDLC-control TypedColumn surface intact.

## Migration steps

For existing v1.29.2 deployments:

1. Upgrade axon-lang to `>=1.38.4` (PyPI + crates.io live).
2. Pull the v1.29.3 image:
   ```sh
   docker pull 908489016816.dkr.ecr.us-east-1.amazonaws.com/axon/axon-enterprise:v1.29.3
   ```
3. **For inline IDENTITY** — adopters can now write:
   ```axon
   axonstore chat_history {
       backend: postgresql
       schema {
           id: BigInt primary_key identity not_null
           tenant_id: Uuid not_null
           content: Text not_null
       }
   }
   ```
4. **For manifest-based IDENTITY** — run `axon check` with the flag:
   ```sh
   axon check src/flow.axon --schemas-dir ./schemas
   ```
   T801-T805 + T803 now fire compile-time against the manifest's `identity: true` columns.

## Files changed (lean catch-up — same shape as every catch-up since v1.9.0)

- `pyproject.toml`: version `1.29.2` → `1.29.3`; dep pin `axon-lang>=1.38.3` → `>=1.38.4`
- `axon_enterprise/__init__.py`: `__version__ = "1.29.2"` → `"1.29.3"`

## Same-day chain (4 patches, 1 minor cycle)

| Patch | axon-lang | axon-enterprise |
|---|---|---|
| Fase 38 (parent) | v1.38.0 | v1.29.0 |
| Fase 38.x.a | v1.38.1 | bundled into v1.29.1 |
| Fase 38.x.b | v1.38.2 | v1.29.1 |
| Fase 38.x.c | v1.38.3 | v1.29.2 |
| Fase 38.x.d | v1.38.4 | **v1.29.3 (this release)** |

## Standing rule honored

Per founder directive 2026-05-20 — *"todo cambio, avance, todo, debe recibirlo axon enterprise. para que todos los adopters rust reciban. hay que hacerlo siempre."* — every axon-lang release ships an axon-enterprise catch-up.

## Cross-links

- 📋 [Fase 38.x.d plan vivo](https://github.com/Bemarking/axon-lang/blob/master/docs/fase/fase_38xd_identity_end_to_end.md)
- 📖 [axon-lang v1.38.4 GitHub Release](https://github.com/Bemarking/axon-lang/releases/tag/v1.38.4)
- 📖 [axon-enterprise v1.29.2 GitHub Release](https://github.com/Bemarking/axon-enterprise/releases/tag/v1.29.2) — Fase 38.x.c parent

🤖 Generated with [Claude Code](https://claude.com/claude-code)
