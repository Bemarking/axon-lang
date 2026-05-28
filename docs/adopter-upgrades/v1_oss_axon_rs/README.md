# `axon-rs` v1.x → v3.x — operator upgrade artifacts (public mirror)

> This directory carries the upgrade artifacts for adopters running the
> OSS `axon-rs` v1.x cycle (Fase 35–37, sqlx ledger lives in
> `public._sqlx_migrations` with versions 1–6) who need to bring their
> `axon_admin` + `axon_control` schemas up to the v3.x canonical shape
> without dropping + recreating.
>
> **Why this lives in the `axon-lang` public repo, not the commercial
> `axon-enterprise` source:** the artifacts are 100% adopter-agnostic
> (zero adopter-specific configuration, zero secrets, zero EULA-licensed
> code). The schema mechanics they describe (`axon_admin` +
> `axon_control` table shape, RLS policies, migration-ledger sync) are
> the **interface contract** between adopters and the runtime — exactly
> the surface that belongs to the language documentation, not to the
> commercial product source.

## Files

| File | Purpose | Bytes |
|---|---|---|
| [`upgrade_v1_oss_axon_rs.sql`](./upgrade_v1_oss_axon_rs.sql) | Canonical idempotent SQL: 7 sections (axon_admin role bootstrap → ledger DDL → 13 ALTER TABLE ADD COLUMN on `axon_admin.tenants` → password_hash_encrypted ADD COLUMN on `axon_control.users` → 108-statement RLS-enablement block on 18 tenant-scoped tables → 21-row ledger sync ON CONFLICT DO NOTHING → RAISE NOTICE post-condition report). | 30 575 |
| [`UPGRADE_v1.x_OSS_AXON_RS_TO_v3.x.md`](./UPGRADE_v1.x_OSS_AXON_RS_TO_v3.x.md) | Operator runbook: pre-flight backup MANDATORY + 7 diagnostic queries + traffic-drain + role-grant precondition; upgrade procedure with expected RAISE NOTICE output; post-flight verification 4 checks; fix matrix 5 failure modes with recovery; honest deferred enumeration; source-of-truth table mapping each SQL section to canonical Rust source. | 24 771 |

## Canonical location + drift gates

The **canonical home** for these artifacts is the
`axon-enterprise` repository (commercial, EULA-licensed, private)
under `docs/upgrade_v1_oss_axon_rs.sql` +
`docs/UPGRADE_v1.x_OSS_AXON_RS_TO_v3.x.md`. Three drift gates in
`crates/saas-cli/src/docs_drift.rs` pin the SQL artifact against the
canonical Rust migration sources at `cargo test --workspace` time:

- `upgrade_v1_oss_sql_inserts_every_canonical_migration_name` — every
  migration name in `all_migrations()` must appear as an INSERT.
- `upgrade_v1_oss_sql_rls_enables_every_tenant_scoped_table` — every
  tenant-scoped table in the `.chain(rls(...))` call sites must have
  the 6-statement RLS block.
- `upgrade_v1_oss_sql_alter_tenants_adds_every_017_018_019_column` —
  every `ADD COLUMN IF NOT EXISTS` from migrations 017/018/019 must
  appear in the SQL.

This public mirror is **byte-identical to the canonical** at the time
of last sync. Verify with:

```bash
sha256sum docs/adopter-upgrades/v1_oss_axon_rs/upgrade_v1_oss_axon_rs.sql
# expected: 98d67c8980d56d5a2234cfc0fdd56e076a2522555e316d29f1324b37daf4551c

sha256sum docs/adopter-upgrades/v1_oss_axon_rs/UPGRADE_v1.x_OSS_AXON_RS_TO_v3.x.md
# expected: 533b2cd7dd44fa63021d7fd992c4893506f0c36277d3034e0e8b4422c9bde9cc
```

If you find a divergence between the mirror and any canonical version
the runbook documents, the canonical is the source of truth — file an
issue at https://github.com/Bemarking/axon-lang/issues so we can re-sync.

## Why we publish the public mirror

The OSS `axon-rs` v1.x cycle (~Fase 35–37, late 2025 / early 2026) was
distributed via crates.io as `axon-rs` — adopters who installed it,
shipped to production against managed Postgres (Supabase, RDS, Cloud
SQL), and want to move to v3.x today need this upgrade SQL regardless
of whether they're moving to a commercial axon-enterprise tier or
just keeping their schema converged with current OSS shape.

The runbook explicitly handles the cases where:
- Migrations created `axon_admin` + `axon_control` schemas but with
  divergent early-shape (the `vertical` / `region` / `lifecycle_state`
  columns were added in §Fase 42.a + 42.c which post-date the v1.x
  cycle).
- The 18 tenant-scoped tables were created without `FORCE ROW LEVEL
  SECURITY` (the v1.x cycle pre-dates §Fase 40.f RLS hardening) —
  Supabase Advisors correctly flag this as **CRITICAL**.
- The `axon_control.schema_migrations` ledger is empty even though
  `public._sqlx_migrations` shows 6 applied versions.

## Versioning

These artifacts target the v3.x canonical schema (21 migrations as of
`axon-enterprise` v3.0.6, 2026-05-27). When a new migration lands in
v3.1.x+ that affects schemas v1.x adopters already created, the drift
gates in `axon-enterprise` fail at test time + the canonical artifact
gets a bump + this mirror gets re-synced.

## License

The artifacts are AGPL-3.0-or-later (matching the `axon-lang` repo
license). They are pure SQL + markdown documentation — no
`axon-enterprise` commercial code is included.

— Bemarking AI · `support@bemarking.com.co`
