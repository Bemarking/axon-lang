# axon-lang v1.38.2 — Admin Schema Isolation Contract (Fase 38.x.b)

> **Cycle:** Fase 38.x.b — *Admin Schema Isolation Contract*.
> Companion to Fase 38.x.a (v1.38.1, Pooler-coherent Transactions).
> Both shipped 2026-05-20 in response to the kivi adopter's three
> smoke-16 findings. D1–D4 ratified.
>
> **TL;DR:** axon's admin `tenants` table previously lived in the
> default search-path schema (typically `public`), where it collided
> with adopter-owned `public.tenants` tables of different shape —
> producing `column "plan" does not exist` at the first runtime SELECT
> and causing axon-enterprise to degrade to its in-memory fallback.
> v1.38.2 isolates axon's admin tables into a dedicated `axon_admin`
> schema. **Backwards-compatible** (D4): the legacy `public.tenants`
> table is never dropped; if it has axon's shape, rows are
> idempotently copied into the new canonical home.

---

## The third kivi finding

> *"(Pre-existente, no bloqueante de este smoke) La migración admin
> «AXON Enterprise: Tenant Identity (M1)» choca con cualquier adopter
> que ya tenga un `tenants` legacy de schema distinto — falla
> `column "plan" does not exist` y axon cae a memoria. Las admin
> tables deberían vivir en un schema dedicado (`axon_admin.tenants`
> o similar), no en `public` desnudo."*

v1.38.2 closes the third report. The first (`sqlx_s_N` prepared
statement collision) shipped in v1.38.1; the second (observability of
in-transaction introspection failures) shipped alongside in v1.38.1
via D3. This release closes the schema-isolation hole.

## The contract — four D-letters

| D-letter | Guarantee |
|---|---|
| **D1** | `axon_admin` is the canonical namespace for axon-owned admin tables. The M1 migration (`axon-rs/migrations/003_add_tenants.sql`) creates `axon_admin.tenants` + the `axon_admin` schema itself. **Statically enforced** by the new §6 anchor in `fase38x_a_pooler_prepared_statement_regression.rs`: any future migration that creates `tenants` outside `axon_admin` turns the test RED |
| **D2** | **Idempotent, non-destructive migration** from legacy `public.tenants`. Detection: BOTH `plan` AND `status` columns must exist (axon's unique markers). On match, rows are copied with `ON CONFLICT DO NOTHING`. The legacy table is **NEVER dropped** — the adopter may have RLS grants, FKs, custom readers pointing at it |
| **D3** | Atomic FK relocation in axon-enterprise v1.29.1 (next release): 57 references to `public.tenants` across SQLAlchemy ForeignKey declarations, raw SQL strings, `TenantScopedMixin`, and CLI/HTTP handlers move to `axon_admin.tenants` in one alembic migration with CASCADE/RESTRICT semantics preserved |
| **D4** | **Absolute backwards-compat** for the kivi collision class. A fresh adopter who has THEIR own `public.tenants` sees axon land in `axon_admin.tenants`, completely sidestepping the collision |

## What changed in v1.38.2

The single file `axon-rs/migrations/003_add_tenants.sql` was rewritten
from:

```sql
CREATE TABLE IF NOT EXISTS tenants ( … );
INSERT INTO tenants … VALUES ('default', …);
```

to:

```sql
CREATE SCHEMA IF NOT EXISTS axon_admin AUTHORIZATION CURRENT_USER;
CREATE TABLE IF NOT EXISTS axon_admin.tenants ( … );
DO $$
BEGIN
    IF /* legacy public.tenants has axon's shape */ THEN
        INSERT INTO axon_admin.tenants
        SELECT … FROM public.tenants
        ON CONFLICT (tenant_id) DO NOTHING;
    END IF;
END
$$;
INSERT INTO axon_admin.tenants … VALUES ('default', …) ON CONFLICT DO NOTHING;
```

Plus the new `§6_d1_kivi_tenants_collision_class_closed` static
§-assertion in the diagnostic anchor.

## What changed in axon-enterprise v1.29.1 (next)

- 57 source references `public.tenants` → `axon_admin.tenants`
- New alembic migration `013_relocate_tenants_to_axon_admin.py` —
  atomic FK swap (drop legacy FKs, recreate at new target,
  CASCADE/RESTRICT preserved)
- alembic `001_baseline_foundation.py` precondition updated to accept
  EITHER `axon_admin.tenants` OR `public.tenants` (one-cycle
  transition window)

## What is intentionally NOT in v1.38.2

- **Removal of `public.tenants` from the OSS M1 migration path.**
  Even fresh installs leave the legacy table absent — but if a
  pre-existing `public.tenants` is present, it remains. v1.38.2 is
  purely additive.
- **Migration of OTHER axon-owned admin tables** (`traces`, `sessions`,
  `daemons`, `audit_log`, …) to `axon_admin`. Only `tenants` was the
  kivi-reported collision class; future Fase 39+ may broaden on
  demand.

## Migration

**No code change needed for adopters.** v1.38.2 ships purely as an
additive M1 migration: existing axon deployments will see
`axon_admin.tenants` appear on their next migration run, with their
data copied across if axon-owned.

**For axon-enterprise adopters:** wait for v1.29.1 (next; ships
shortly with the 57-ref FK relocation + alembic 013).

```sh
cargo add axon-lang@1.38.2
pip install axon-lang==1.38.2
```

## Test surface

- **2 096** axon-rs lib tests green (identical baseline to v1.38.1)
- **6** `fase38x_a` §-assertions (NEW §6 added):
  - §1 — kivi smoke 16 collision symptom corpus pin
  - §2 — zero silent `Err(_)` swallows
  - §3 — every D3 `tracing::warn!` carries `error = %e`
  - §4 — STATIC INVARIANT: every `sqlx::query` carries `.persistent(false)`
  - §5 — D2 `after_release(DEALLOCATE ALL)` installation + meta-invariant
  - **§6 (NEW)** — D1 STATIC INVARIANT: `tenants` MUST be created in `axon_admin`

Zero regressions cross-stack.

## Cross-links

- 📋 [Plan vivo Fase 38.x.b](https://github.com/Bemarking/axon-lang/blob/master/docs/fase/fase_38xb_admin_schema_isolation.md) — the full D1–D4 contract + sub-fase ladder + scope statement
- 📋 [Plan vivo Fase 38.x.a](https://github.com/Bemarking/axon-lang/blob/master/docs/fase/fase_38x_pooler_transactions.md) — the Pooler-coherent Transactions Contract (v1.38.1)
- 📖 [v1.38.1 GitHub Release](https://github.com/Bemarking/axon-lang/releases/tag/v1.38.1) — closed the first two kivi findings

## Acknowledgements

Closed same day as the kivi smoke 16 report. Three findings, three
contracts, two patches (v1.38.1 + v1.38.2). The Pillar V cognitive
data plane is whole again.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
