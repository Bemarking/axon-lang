# axon-enterprise v1.29.2 — catch-up to axon-lang 1.38.3 (IDENTITY Column Recognition)

Patch catch-up bundling **axon-lang v1.38.3** (Fase 38.x.c — IDENTITY Column Recognition). axon-lang dep pin: `>=1.38.2` → `>=1.38.3`. axon-frontend Rust crate dep transitively `0.19.0` → `0.19.1`.

## What enterprise tenants inherit

axon's `axon store introspect` + the compile-time T803 NOT-NULL-omission proof now correctly recognize `GENERATED ALWAYS/BY DEFAULT AS IDENTITY` columns via `pg_attribute.attidentity`. Pre-v1.38.3 these columns triggered false-positive T803 errors that forced adopters to delete the column from the manifest entirely — silencing every other proof (T801, T802, T804) for the column.

### 5 D-letters

| D-letter | Guarantee |
|---|---|
| **D1** | `pg_attribute.attidentity` is a first-class introspection field — deep query SELECTs `a.attidentity::text AS identity_kind`. **Statically enforced** by `§4` grep §-assertion in the new fase38xc anchor |
| **D2** | `identity: bool` is a first-class manifest + AST field — `StoreColumn` / `ManifestColumn` / `DeclaredColumn` / `IRStoreColumn` all carry it |
| **D3** | T803 treats `identity: true` as safely omittable — `has_default = !default_value.is_empty() \|\| auto_increment \|\| identity` |
| **D4** | `auto_increment` semantics unchanged. SERIAL (via `nextval` default) emits `auto_increment: true`; IDENTITY (via `attidentity`) emits `identity: true`. The two SQL surfaces stay DISTINCT |
| **D5** | **Absolute backwards-compat** — v1.38.2 manifests parse + serialize byte-identical |

## Vertical inheritance — transparent (no per-tenant change required)

- 🏥 **HIPAA Safe Harbor + 21 CFR Part 11 §11.10(e)** clinical PHI stores using `id BIGINT GENERATED ALWAYS AS IDENTITY` for sequenced records no longer trigger T803 false positives; the `persist into patient_records` block stays scoped to PHI columns; Pillar V TypedColumn proofs hold end-to-end.
- ⚖️ **FRE 502 + Upjohn / Hickman** legal stores with IDENTITY-keyed `privilege_log` entries get the same closure; T801 + T802 + T804 fire correctly on every column reference (the column no longer disappears from the manifest to silence T803).
- 💰 **BSA / OFAC / MiFID II** AML stores with IDENTITY-keyed `transaction_ledger` entries inherit identically.
- 🏛 **FedRAMP AU-2 + AC-3** government stores using IDENTITY primary keys on `audit_event_log` keep the SDLC-control TypedColumn surface intact.

## Migration

For existing v1.29.1 deployments:

1. Upgrade axon-lang to `>=1.38.3` (PyPI + crates.io live).
2. Pull the v1.29.2 image:
   ```sh
   docker pull 908489016816.dkr.ecr.us-east-1.amazonaws.com/axon/axon-enterprise:v1.29.2
   ```
3. **Re-run `axon store introspect`** against IDENTITY-bearing tables to refresh manifests with `"identity": true`:
   ```sh
   axon store introspect chat_history \
       --connection $DATABASE_URL \
       --output schemas/chat_history.json
   ```
4. Old manifests still parse (D5) but T803 keeps firing until the manifest is refreshed.

Fresh installs against axon-lang v1.38.3+ get the identity recognition automatically.

## Files changed (lean catch-up — same shape as every catch-up since v1.9.0)

- `pyproject.toml`: version `1.29.1` → `1.29.2`; dep pin `axon-lang>=1.38.2` → `>=1.38.3`
- `axon_enterprise/__init__.py`: `__version__ = "1.29.1"` → `"1.29.2"`

## Standing rule honored

Per founder directive 2026-05-20 — *"todo cambio, avance, todo, debe recibirlo axon enterprise. para que todos los adopters rust reciban. hay que hacerlo siempre."* — every axon-lang release ships an axon-enterprise catch-up so Rust adopters consuming the Docker image receive every change end-to-end. v1.38.3 shipped earlier today without an enterprise catch-up by mistake; v1.29.2 closes the gap.

## Cross-links

- 📋 [Fase 38.x.c plan vivo](https://github.com/Bemarking/axon-lang/blob/master/docs/fase/fase_38xc_identity_recognition.md)
- 📖 [axon-lang v1.38.3 GitHub Release](https://github.com/Bemarking/axon-lang/releases/tag/v1.38.3)
- 📖 [axon-enterprise v1.29.1 GitHub Release](https://github.com/Bemarking/axon-enterprise/releases/tag/v1.29.1) — Fase 38.x.b parent

## Same-day chain

| Patch | axon-lang | axon-enterprise |
|---|---|---|
| Fase 38.x.a | v1.38.1 | (bundled into v1.29.1) |
| Fase 38.x.b | v1.38.2 | v1.29.1 (18-FK relocation + alembic 013) |
| Fase 38.x.c | v1.38.3 | **v1.29.2 (this release)** |

🤖 Generated with [Claude Code](https://claude.com/claude-code)
