---
title: "Plan vivo: Fase 38.x.b — Admin schema isolation (axon's tenants table moves to `axon_admin.tenants`)"
status: ⏳ OPEN 2026-05-20 — sub-fases drafted, awaiting D-letter ratification + execution.
owner: AXON Language + Enterprise Team
created: 2026-05-20
target: |
  axon-lang **v1.38.2** (PATCH — bug fix; axon-frontend stays 0.19.0)
  axon-enterprise **v1.29.1** (catch-up + the 57-ref FK relocation + alembic migration 013)
depends_on: |
  Fase 38.x.a CLOSED 2026-05-20 (Pooler-coherent Transactions Contract,
  v1.38.1). 38.x.b is the SECOND of the two kivi-smoke-16 reports to be
  closed; the first (sqlx prepared-statement collision behind transaction-
  mode poolers) shipped in v1.38.1.
charter_class: |
  SPLIT — touches axon-lang OSS (one migration file in `axon-rs/migrations/`)
  AND axon-enterprise (~57 references across SQLAlchemy FK declarations,
  raw SQL strings, an alembic precondition, and the cross-schema FK mixin).

# ▶ 1. The kivi smoke 16 third finding (2026-05-20)

> *"(Pre-existente, no bloqueante de este smoke) La migración admin
> «AXON Enterprise: Tenant Identity (M1)» choca con cualquier adopter
> que ya tenga un `tenants` legacy de schema distinto — falla
> `column "plan" does not exist` y axon cae a memoria. Las admin
> tables deberían vivir en un schema dedicado (`axon_admin.tenants`
> o similar), no en `public` desnudo."*

The kivi adopter explicitly labelled this *pre-existing* and *not
blocking* the smoke. v1.38.1's release notes acknowledged it. 38.x.b
closes it.

# ▶ 2. Root cause + the design choice

The OSS migration `axon-rs/migrations/003_add_tenants.sql` (named in its
header comment "AXON Enterprise: Tenant Identity (M1)" — a 2026-04
artifact from when the OSS / enterprise boundary was less crisp)
created `tenants` in the **default schema** (typically `public`) with
`CREATE TABLE IF NOT EXISTS tenants (…)`. That's a collision risk
against any adopter who already has `public.tenants` with a different
column shape: the CREATE skips, axon's readers later SELECT a column
that doesn't exist, and the runtime degrades.

The robust design isolates axon's admin tables into their own schema:

- `axon_admin.tenants` — the new canonical home for axon's tenant
  identity table
- `axon_admin` schema as a namespace for every future axon-owned admin
  table (future migrations 004+ land here; never in `public`)
- The OSS migration becomes adopter-defensive: it creates `axon_admin`,
  creates the new `axon_admin.tenants`, COPIES rows from
  `public.tenants` IF and ONLY IF the legacy table has axon's column
  shape (detected via `information_schema.columns` lookup of the
  `plan` column — the unique-to-axon marker), then leaves
  `public.tenants` UNTOUCHED so the adopter still owns whatever they
  had

Enterprise's 57 references to `public.tenants` (FK CASCADE rules, raw
SQL CRUD, the cross-schema `TenantScopedMixin`) atomically move to
`axon_admin.tenants` via:

- a new alembic migration `013_relocate_tenants_to_axon_admin.py` that
  drops every FK pointing at `public.tenants`, copies any remaining
  axon-owned data, swaps the FK targets to `axon_admin.tenants`, and
  recreates each FK with its original CASCADE/RESTRICT semantics
  preserved
- a global source-replace `public.tenants` → `axon_admin.tenants`
  across every Python module (FK declarations, raw SQL strings,
  comments)
- the alembic baseline `001` precondition assertion updated from
  `public.tenants` to `axon_admin.tenants`

# ▶ 3. The Admin Schema Isolation Contract (four D-letters)

**D1 — `axon_admin` is the canonical namespace for axon-owned admin
tables.** Every present and future migration in axon-rs creates its
tables in `axon_admin`. `public` is OWNED BY THE ADOPTER — axon
NEVER writes to a table the adopter could plausibly have. Enforced by
a grep §-assertion in the new anchor test.

**D2 — Idempotent, non-destructive migration from legacy
`public.tenants`.** v1.38.2's M1 detects axon-owned `public.tenants`
(via the `plan` column existence) and COPIES rows into
`axon_admin.tenants` with `ON CONFLICT DO NOTHING`. It NEVER drops
`public.tenants` — the adopter may still need it for application
RLS / app logic / their own consumers.

**D3 — Enterprise FK relocation is ATOMIC within one alembic
migration.** The new `013_relocate_tenants_to_axon_admin.py` runs as
ONE transaction: drop all FKs → copy any remaining data → swap target
→ recreate FKs. A rollback rebuilds the legacy state.

**D4 — Absolute backwards-compat for the kivi report class.** A fresh
adopter who has NEVER deployed axon and has THEIR own `public.tenants`
sees axon land its admin table in `axon_admin.tenants`, completely
sidestepping the collision. The `column "plan" does not exist` failure
mode is structurally closed.

# ▶ 4. Sub-fases (38.x.b.1 — single coordinated cycle, two crates)

| Sub-fase | What | D-letters | Status |
|---|---|---|---|
| **38.x.b.1** | `axon-rs/migrations/003_add_tenants.sql` — create `axon_admin` schema, create `axon_admin.tenants`, idempotent COPY from `public.tenants` if axon-owned (detected via `information_schema.columns` of the `plan` column), seed `default` tenant into the new canonical home. | D1, D2, D4 | ⏳ |
| **38.x.b.2** | axon-enterprise: update every `public.tenants` reference (~57) to `axon_admin.tenants`. Touches: 10+ SQLAlchemy `ForeignKey(...)` declarations, ~5 raw SQL strings in CLI / HTTP handlers, the `TenantScopedMixin` in `db/base.py`, the residency lookup, docs. | D3 | ⏳ |
| **38.x.b.3** | New alembic migration `013_relocate_tenants_to_axon_admin.py` (the atomic FK swap) — drops each enterprise FK that points at `public.tenants.tenant_id`, recreates it pointing at `axon_admin.tenants.tenant_id` with the same `ondelete` / `onupdate` semantics. Idempotent (skips if FK is already at the new target). | D3 | ⏳ |
| **38.x.b.4** | Update alembic baseline `001_baseline_foundation.py` precondition: was `assert public.tenants exists`; becomes `assert axon_admin.tenants OR public.tenants exists` (accept BOTH for one release cycle so fresh installs from 1.38.2+ + legacy adopters not yet on alembic 013 both succeed). | D3 | ⏳ |
| **38.x.b.5** | Coordinated release: axon-lang v1.38.2 (axon-rs only, no axon-frontend bump) + axon-enterprise v1.29.1 (catches up + ships alembic 013 + source-replace + precondition update). | — | ⏳ |

# ▶ 5. The grep §-assertion (D1 static enforcement)

The Fase 38.x.a anchor test (`fase38x_a_pooler_prepared_statement_regression.rs`)
already established a grep §-assertion model: a `§4` test walks the
source tree and asserts every `sqlx::query` carries `.persistent(false)`.

38.x.b extends with: every future migration file under
`axon-rs/migrations/` that creates tables MUST create them in
`axon_admin` (or another non-`public` schema explicitly owned by axon).
A new `§6_d1_admin_schema_namespace` assertion catches a regression
where someone slips a `CREATE TABLE IF NOT EXISTS foo (...)` in a
future migration.

# ▶ 6. What is intentionally NOT in v1.38.2 / v1.29.1

- **Removal of `public.tenants` for fresh installs.** The legacy table
  STAYS as-is for one full minor cycle (v1.38.2 → v1.40.0) so adopters
  with their own consumers of `public.tenants` (RLS grants, BI tools,
  custom apps) don't break overnight. v1.40.0 will introduce a
  deprecation tracing warning; v2.0.0 may drop axon's COPY into the
  legacy table entirely.
- **Rename of `tenants` to a different name (e.g. `axon_tenants`).**
  Just relocating to a new schema is sufficient. A name change adds
  burden without adopter value.
- **Migration of OTHER admin tables.** Only `tenants` is migrated in
  38.x.b because that's the only one kivi reported a collision on.
  Future fases can move `cognitive_states`, `replay_tokens`, `audit_events`
  etc. into `axon_admin` if a similar collision report arrives.

# ▶ 7. The trigger sources

- 2026-05-20 — kivi adopter smoke 16, third finding ("Pre-existente,
  no bloqueante de este smoke").
- Founder framing 2026-05-20 — "axon es un lenguaje para el mundo;
  con axon se deben poder crear agentes multitenant" — multitenant
  adopters cannot have axon's admin tables colliding with their
  application schema. The fix is foundational, not optional.

Closed when axon-lang v1.38.2 + axon-enterprise v1.29.1 are both live
cross-stack.
