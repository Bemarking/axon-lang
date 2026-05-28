# Upgrading from v1.x OSS `axon-rs` to v3.x — `axon_admin` + `axon_control` already populated

> **Audience:** operators of a deployment that ran the OSS `axon-rs`
> v1.x cycle (Fase 35-37 timeframe; the sqlx ledger lives in
> `public._sqlx_migrations` with versions 1-6) and now needs to
> bring the schema to v3.x canonical shape **without** dropping +
> recreating the schemas (data preservation MANDATORY).
>
> If you are upgrading from `axon-enterprise` v1.x (the commercial
> tier, not the OSS axon-rs), use
> [`UPGRADE_v1.x_TO_v3.0.0.md`](./UPGRADE_v1.x_TO_v3.0.0.md) instead
> — that path assumes the `axon_admin` + `axon_control` schemas were
> created at the v3.x canonical shape and `public.*` carries your
> legacy data. **This** runbook covers the inverse: your v1.x
> OSS-axon-rs cycle landed data **inside** `axon_admin` +
> `axon_control` with the early-version shape (no `vertical`/
> `region`/lifecycle columns; tables created without `FORCE ROW
> LEVEL SECURITY`).
>
> If you are upgrading from v2.x, use
> [`UPGRADE_v2.x_TO_v3.0.0.md`](./UPGRADE_v2.x_TO_v3.0.0.md) — v2.x →
> v3.x is purely additive (§Fase 49) and does not hit this cliff.
>
> **Total apply time:** ~10-30 minutes including verification. The
> actual DDL runs in under a minute; the diagnostic pre-flight + the
> post-flight `bootstrap` is what takes the rest.

---

## Why this runbook exists

The v1.x OSS `axon-rs` cycle created the `axon_admin` + `axon_control`
schemas with an early shape:

- `axon_admin.tenants` had **5 columns**: `tenant_id`, `name`, `plan`,
  `status`, `created_at`. The v3.x canonical shape adds **13 more**
  via migrations 017 + 018: `vertical`, `region`,
  `quota_budget_usd_monthly`, `metadata`, `created_by`, `updated_at`,
  `deleted_at`, `version`, `lifecycle_state`,
  `deletion_scheduled_at`, `deletion_grace_until`, `deletion_reason`,
  `deletion_requested_by`.
- `axon_control.users` was missing the `password_hash_encrypted BYTEA`
  column (migration 019, §Fase 44.c envelope encryption).
- The 18 tenant-scoped tables in `axon_control` (`tenant_memberships`,
  `sessions`, `roles`, `role_permissions`, `user_roles`,
  `sso_configurations`, `sso_states`, `secrets`,
  `tenant_subscriptions`, `usage_events`, `invoices`, `audit_events`,
  `compliance_requests`, `legal_holds`, `tenant_api_keys`,
  `cognitive_states`, `replay_tokens`, `flow_deployments`) were
  created without `ENABLE/FORCE ROW LEVEL SECURITY` + tenant
  isolation policies.
- The migration ledger lived in `public._sqlx_migrations` (the OSS
  axon-rs sqlx ledger) — invisible to the v3.x runner which uses
  `axon_control.schema_migrations`.

The v3.x bootstrap uses `CREATE TABLE IF NOT EXISTS` everywhere, so
running `axon-enterprise-server migrate up` on a v1.x-OSS-populated
DB silently skips every `CREATE TABLE` that already exists, leaves
the divergent column shapes in place, leaves RLS disabled, and
writes 21 new rows into the `axon_control.schema_migrations` ledger
that don't reflect the actual schema state. **Net result: a
runtime DB that LOOKS bootstrapped but is structurally broken** —
queries against missing columns 500, RLS isolation is off (CRITICAL
Supabase Advisors flag), and any future migration trusted to the
ledger is operating against a lie.

This runbook applies the upgrade SQL surgically: ADD COLUMN the
missing 13+1, ENABLE/FORCE RLS on the 18 tables, sync the ledger,
and emit operator-visible counts so the success state is verifiable
end-to-end.

---

## Pre-flight checklist (DO NOT SKIP)

### Step 0 — Backup MANDATORY

```bash
# Identify the role + URL the upgrade will run as.
export AXON_DB_URL='postgresql://<superuser-or-axon-admin-member>@<host>:5432/<db>'

# Snapshot the schemas + data. The custom-format dump is
# pg_restore-friendly and ~10x smaller than plain SQL.
pg_dump -Fc \
        -n axon_admin -n axon_control -n public \
        -f axon_pre_v3_oss_upgrade_$(date +%Y%m%d_%H%M%S).dump \
        "$AXON_DB_URL"
```

The dump MUST cover `axon_admin` + `axon_control` (the schemas
this upgrade modifies) plus `public` (because the
`public._sqlx_migrations` ledger is the only proof you were on
v1.x-OSS-axon-rs; we don't touch `public` but losing the ledger
forfeits forensic ability).

Verify the dump is restorable on a scratch instance before
proceeding (`pg_restore --list axon_pre_v3_oss_upgrade_*.dump |
head -20`).

### Step 1 — Diagnostic inventory (the 7 queries)

Run these against the production DB (as the same role
`axon-enterprise-server` will use, OR as a superuser — they're
SELECT-only):

#### Query 1.1 — Migration ledger state

```sql
SELECT
  (SELECT count(*) FROM information_schema.tables
     WHERE table_schema='axon_control' AND table_name='schema_migrations')
  AS v3x_ledger_exists,
  (SELECT count(*) FROM information_schema.tables
     WHERE table_schema='public' AND table_name='_sqlx_migrations')
  AS v1x_ledger_exists;

-- If v1x_ledger_exists=1, this confirms the v1.x-OSS-axon-rs origin.
-- Inspect the actual ledger entries:
SELECT version, description, success, execution_time
  FROM public._sqlx_migrations
  ORDER BY version;
-- Expected (per the Fase 35-37 OSS cycle): 6 rows, version range 1-6,
-- all success=true.
```

#### Query 1.2 — `axon_admin.tenants` column inventory

```sql
SELECT column_name, data_type, is_nullable, column_default
  FROM information_schema.columns
  WHERE table_schema='axon_admin' AND table_name='tenants'
  ORDER BY ordinal_position;

-- v3.x canonical: 18 columns total (5 baseline + 8 from 017 + 5 from 018).
-- v1.x-OSS-axon-rs: 5 baseline only.
-- If your row count is 5, you have exactly the gap this runbook closes.
-- If your row count is 6-17, you have a partial v1.x state — the upgrade
-- SQL handles it idempotently (every ADD COLUMN is IF NOT EXISTS).
```

#### Query 1.3 — `axon_control.users.password_hash_encrypted` check

```sql
SELECT count(*) AS column_exists
  FROM information_schema.columns
  WHERE table_schema='axon_control' AND table_name='users'
    AND column_name='password_hash_encrypted';
-- 0 → migration 019 will fire on apply; 1 → already at v2.4.0+ shape.
```

#### Query 1.4 — RLS state matrix

```sql
SELECT n.nspname AS schema,
       c.relname AS table,
       c.relrowsecurity AS rls_enabled,
       c.relforcerowsecurity AS rls_forced,
       (SELECT count(*) FROM pg_policies p
          WHERE p.schemaname=n.nspname AND p.tablename=c.relname)
       AS policies_count
  FROM pg_class c
  JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname IN ('axon_admin','axon_control')
    AND c.relkind='r'
  ORDER BY n.nspname, c.relname;

-- v3.x canonical end-state:
--   * 18 axon_control tables: rls_enabled=t, rls_forced=t, policies_count=2.
--   * 6 globals (axon_admin.tenants, axon_admin.shredded_tenants, users,
--     permissions, jwt_signing_keys, pricing_plans): rls_enabled=f.
-- v1.x-OSS-axon-rs: ALL 22-24 tables with rls_enabled=f, policies_count=0.
-- This is the CRITICAL gap Supabase Advisors flag.
```

#### Query 1.5 — Row inventory (data preservation pre-flight)

```sql
WITH inventory AS (
  SELECT 'axon_admin.tenants'              AS table_name, count(*) AS rows FROM axon_admin.tenants
  UNION ALL SELECT 'axon_control.users',                count(*) FROM axon_control.users
  UNION ALL SELECT 'axon_control.tenant_memberships',  count(*) FROM axon_control.tenant_memberships
  UNION ALL SELECT 'axon_control.tenant_api_keys',     count(*) FROM axon_control.tenant_api_keys
  UNION ALL SELECT 'axon_control.usage_events',        count(*) FROM axon_control.usage_events
  UNION ALL SELECT 'axon_control.audit_events',        count(*) FROM axon_control.audit_events
  UNION ALL SELECT 'axon_control.sessions',            count(*) FROM axon_control.sessions
)
SELECT * FROM inventory WHERE rows > 0 ORDER BY rows DESC;
```

Record these counts. **Post-flight you'll re-run the same query and
confirm every count is unchanged.** The upgrade SQL does not INSERT
or UPDATE row data (other than the schema_migrations ledger); any
discrepancy is a red flag.

#### Query 1.6 — Multi-tenant pollution check

```sql
SELECT 'axon_control.tenant_memberships' AS source, count(DISTINCT tenant_id) AS distinct_tenants
  FROM axon_control.tenant_memberships
UNION ALL
SELECT 'axon_control.usage_events', count(DISTINCT tenant_id)
  FROM axon_control.usage_events
UNION ALL
SELECT 'axon_control.tenant_api_keys', count(DISTINCT tenant_id)
  FROM axon_control.tenant_api_keys
UNION ALL
SELECT 'axon_admin.tenants', count(*) FROM axon_admin.tenants
ORDER BY source;

-- Every tenant-scoped count should be ≤ axon_admin.tenants count.
-- If a tenant-scoped count is GREATER, it means rows with tenant_id
-- not in axon_admin.tenants exist (the v1.x cycle ran without RLS
-- enforcement, so cross-tenant pollution was structurally possible).
-- POST-RLS-ENABLEMENT, those polluted rows become "invisible" to
-- tenant-scoped queries but still occupy disk + appear in admin-
-- bypass scans. Decide BEFORE running the upgrade whether to:
--   (a) accept the pollution as historical noise (they'll be
--       admin-only-visible after RLS),
--   (b) clean up via DELETE before the upgrade (operator decision),
--   (c) re-tenant via UPDATE before the upgrade (operator decision).
```

#### Query 1.7 — Application-role inventory

```sql
SELECT current_user,
       current_setting('is_superuser'),
       pg_has_role(current_user, 'axon_admin', 'MEMBER') AS member_of_axon_admin;

-- If member_of_axon_admin=false AND current_user is the role
-- `AXON_DB_URL` will use post-upgrade → after RLS is enabled,
-- every query against the 18 tenant-scoped tables silently returns
-- ZERO ROWS. Fix BEFORE running the upgrade SQL:
--   GRANT axon_admin TO <your-app-role>;
-- The axon_admin role is created by the upgrade SQL §0 if absent;
-- the GRANT requires a superuser session.
```

Capture the outputs of all 7 queries. They're the operator's
ground-truth state. If anything in 1.5-1.7 looks unexpected, halt
and inspect before applying the upgrade SQL.

### Step 2 — Maintenance window prerequisites

- **Drain traffic.** The upgrade SQL takes the schema-modify locks
  on `axon_admin.tenants` for the duration of §2-3 (~5-10 seconds
  on small DBs, ~30-60 seconds on DBs with 1M+ tenants). Concurrent
  v1.x writes during this window can deadlock or return unexpected
  errors. Stop your `axon-enterprise-server` (or v1.x equivalent)
  before applying.
- **Verify the `axon_admin` role grant.** Per Query 1.7, ensure the
  role you'll use for `AXON_DB_URL` post-upgrade is a member of
  `axon_admin`:
  ```sql
  -- As a superuser:
  GRANT axon_admin TO <your-app-role>;
  ```
- **Confirm `pgcrypto` + `citext` extensions are installed** (Kivi
  audit confirmed they are on Supabase out-of-the-box; non-Supabase
  adopters may need `CREATE EXTENSION IF NOT EXISTS pgcrypto;
  CREATE EXTENSION IF NOT EXISTS citext;` first).

---

## Upgrade procedure

### Step 3 — Apply [`upgrade_v1_oss_axon_rs.sql`](./upgrade_v1_oss_axon_rs.sql)

The artifact lives next to this runbook. Apply it as a superuser
(needed for `CREATE ROLE` in §0 and `ALTER ... ENABLE ROW LEVEL
SECURITY` ownership preconditions) OR as the connecting role IF
it has the required privileges.

```bash
# Adjust the URL to your project. Supabase projects: use the
# session-mode pooler URL (5432, NOT 6543) with the postgres.<ref>
# username format (v3.0.2+ handles the literal dot; pre-v3.0.2 needs
# %2E URL-encoding per docs/SELF_HOSTING_QUICKSTART.md Supabase note).
export AXON_DB_URL='postgresql://postgres.<project-ref>:<pw>@<region>.pooler.supabase.com:5432/postgres'

psql "$AXON_DB_URL" -f docs/upgrade_v1_oss_axon_rs.sql 2>&1 | tee upgrade.log
```

The script will:

1. Bootstrap `axon_admin` BYPASSRLS role if absent (§0).
2. Ensure schemas + ledger table (§1).
3. ALTER TABLE `axon_admin.tenants` ADD COLUMN × 13 + 4 indexes +
   2 CHECK constraints + 1 function + 1 trigger (§2-3).
4. ALTER TABLE `axon_control.users` ADD COLUMN
   `password_hash_encrypted BYTEA` (§4).
5. CREATE TABLE `axon_admin.shredded_tenants` + index (§3).
6. ENABLE/FORCE RLS + 2 policies on each of the 18 tenant-scoped
   tables in `axon_control` (§5, 108 statements in one
   transaction).
7. INSERT 21 canonical migration names into
   `axon_control.schema_migrations` (§6).
8. Emit RAISE NOTICE post-condition report (§7).

Inspect the tail of `upgrade.log` — you should see the §7
post-condition report with these values:

```
NOTICE:  =====================================================================
NOTICE:  axon-enterprise v1.x → v3.x upgrade — post-condition report
NOTICE:  =====================================================================
NOTICE:  axon_admin role present: t  (expected: t)
NOTICE:  axon_control.schema_migrations rows: 21  (expected: >= 21)
NOTICE:  axon_control tables with FORCE RLS: 18  (expected: >= 18)
NOTICE:  axon_admin.tenants column count: 18  (expected: >= 18)
NOTICE:  =====================================================================
NOTICE:  Next step: GRANT axon_admin TO <your-app-role>;
NOTICE:  Then:     `axon-enterprise-server bootstrap --platform-owner-email <addr>`
NOTICE:  See:      docs/UPGRADE_v1.x_OSS_AXON_RS_TO_v3.x.md
NOTICE:  =====================================================================
```

If any count diverges, halt and consult the [fix matrix below](#post-flight-fix-matrix).

### Step 4 — Post-flight verification

#### Verify 4.1 — re-run the row inventory from Query 1.5

Every count should be identical to Step 1. **If any count changed,
investigate immediately** — the upgrade SQL does not modify row
data outside the schema_migrations ledger.

#### Verify 4.2 — re-run the RLS matrix from Query 1.4

Every `axon_control` tenant-scoped table should now show
`rls_enabled=t, rls_forced=t, policies_count=2`. The 6 globals
(`axon_admin.tenants`, `axon_admin.shredded_tenants`, `users`,
`permissions`, `jwt_signing_keys`, `pricing_plans`) stay
`rls_enabled=f` by design.

#### Verify 4.3 — `axon_admin.tenants` column inventory

Re-run Query 1.2. The new column count is 18 (was 5 in the v1.x
state). The 13 new columns (`vertical`, `region`,
`quota_budget_usd_monthly`, `metadata`, `created_by`, `updated_at`,
`deleted_at`, `version`, `lifecycle_state`,
`deletion_scheduled_at`, `deletion_grace_until`, `deletion_reason`,
`deletion_requested_by`) should all be present with their canonical
defaults backfilled on existing rows.

#### Verify 4.4 — application-role bypass

```sql
SET ROLE <your-app-role>;
SELECT count(*) FROM axon_control.tenant_memberships;
RESET ROLE;
```

The count should match the pre-upgrade inventory (Query 1.5). If
it's 0 and the pre-upgrade inventory had rows, the connecting role
is NOT a member of `axon_admin` and RLS is silently filtering
everything. Fix:

```sql
-- As superuser:
GRANT axon_admin TO <your-app-role>;
```

Then re-run Verify 4.4.

### Step 5 — Start v3.x server + bootstrap platform owner

The upgrade SQL stamped the ledger with all 21 migration names, so
`axon-enterprise-server migrate up` against this DB is a clean
no-op. The bootstrap subcommand additionally seeds `pricing_plans`
(5 BUILT_IN_PLANS), `permissions` (42 SYSTEM_PERMISSIONS), built-in
roles for the default tenant, and provisions the platform owner
(magic-link token printed to stdout):

```bash
docker run --rm \
  --env AXON_DB_URL="$AXON_DB_URL" \
  --env-file your-axon.env \
  --network host \
  <your-registry>/axon-enterprise:3.0.6 \
  axon-enterprise bootstrap --platform-owner-email <addr>
```

Expected output:

```
axon-enterprise bootstrap: already up to date (slug=default, 21/21 migrations)
  ✓ db_roundtrip
  ✓ migration_ledger — 21 migrations applied
  ✓ default_tenant_present — default tenant slug="default"
  ✓ shredded_tenants_registry — 0 shredded rows
  ✓ default_tenant_rbac_seeded — 4 role(s) for tenant "default"

platform owner provisioned:
  email     : <addr>
  user_id   : <uuid>
  tenant_id : default
  magic_link: <base64url-encoded 32-byte token>
  expires_at: <unix-ms> (Unix ms; 24h TTL — capture it now)
```

Capture the magic-link token. Then redeem via `POST /api/v1/auth/invite/accept`
(v3.0.4+ — see `docs/PORTAL_API.md:85-93`).

### Step 6 — Smoke-test the upgraded DB

```bash
# 1. Healthchecks.
curl http://<your-host>:8420/healthz   # 200 OK
curl http://<your-host>:8420/readyz    # 200 OK — bootstrap status: ok

# 2. Confirm the platform owner can log in (post-redemption).
curl -X POST http://<your-host>:8420/token \
  -H "Content-Type: application/json" \
  -d '{"email":"<addr>","password":"<post-redeem-password>","tenant_id":"default"}'
# Expected: 200 OK with access_token + refresh_token.

# 3. Confirm flow deploy works (the v3.0.6 ::uuid fix in place).
curl -X POST http://<your-host>:8420/api/v1/tenant/flows \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"flow_slug":"smoke","source_text":"<<your .axon source>>"}'
# Expected: 200 OK with deployment_id.

# 4. Confirm the docker logs are clean (no flow.persistence_failed lines).
docker logs <container> 2>&1 | grep flow.persistence | wc -l
# Expected: 0.
```

---

## Post-flight fix matrix

### Symptom: §7 post-condition report shows `axon_admin role present: f`

The role creation in §0 silently failed (probably ran as a
non-superuser without `CREATE ROLE` privilege). Re-run §0 as a
superuser:

```sql
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'axon_admin') THEN
    CREATE ROLE axon_admin NOLOGIN BYPASSRLS;
  END IF;
END $$;
```

Then re-run the rest of `upgrade_v1_oss_axon_rs.sql` (every other
section is idempotent).

### Symptom: §7 shows `axon_control.schema_migrations rows: < 21`

Some `INSERT` in §6 failed. Common cause: the ledger table doesn't
exist yet (the upgrade SQL §1 should have created it; verify the
schema was reachable). Re-run §1 + §6:

```sql
CREATE SCHEMA IF NOT EXISTS axon_control;
CREATE TABLE IF NOT EXISTS axon_control.schema_migrations (
  name TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Re-apply §6 (all 21 INSERTs are ON CONFLICT DO NOTHING).
```

### Symptom: §7 shows `tables with FORCE RLS: < 18`

A subset of the 18 RLS-enablement blocks failed mid-transaction. The
§5 BEGIN/COMMIT scope means a partial failure rolled back ALL 18.
Re-run §5 in isolation; if a specific table fails, the error
message identifies the offending table. Common cause: the table
doesn't exist (it was never created by v1.x). In that case, run the
canonical v3.x `CREATE TABLE` for the missing table via:

```bash
docker run --rm \
  --env AXON_DB_URL="$AXON_DB_URL" \
  <your-registry>/axon-enterprise:3.0.6 \
  axon-enterprise migrate up
```

This runs every v3.x migration that hasn't been ledger-stamped yet
(though after §6 of this upgrade, every migration IS stamped — so
this only triggers if §6 was incomplete). Note: in that case,
the v3.x migrate runs against unprotected tables, which is
acceptable as a recovery path (operator-supervised maintenance
window, drained traffic).

### Symptom: app queries return 0 rows after upgrade

Almost certainly the connecting role is NOT a member of `axon_admin`.
RLS is filtering everything. Verify with Query 1.7 + apply:

```sql
GRANT axon_admin TO <your-app-role>;
```

See [`docs/DATABASE.md#troubleshooting-rls-rejections-on-flow_deployments`](./DATABASE.md#troubleshooting-rls-rejections-on-flow_deployments)
for the broader troubleshooting recipe.

### Symptom: `axon-enterprise bootstrap` fails with `owner role not seeded for the default tenant`

You're on v3.0.2 or earlier. The §49.j bootstrap RBAC seed gap is
fixed in v3.0.3+. Pull `:3.0.3` (or later) and re-run. If you must
stay on v3.0.2 for some reason, the operational workaround is to
manually seed `axon_control.permissions` + `axon_control.roles` for
the default tenant (the canonical content lives in
`crates/saas-rbac/src/catalog.rs::SYSTEM_PERMISSIONS` +
`builtin_role_permissions`).

### Symptom: `POST /api/v1/tenant/flows` fails with `flow.persistence_failed`

You're on v3.0.0-v3.0.5 and `axon_admin` membership isn't granted
to your app role (per [v3.0.5 observability hardening](./RELEASE_NOTES_v3.0.5.md)).
Capture the underlying sqlx error from stderr (`docker logs |
grep flow.persistence`), confirm the role state, and fix per
above. v3.0.6 ships the `::uuid` cast that closes the
related-but-different bug Kivi diagnosed.

---

## Honest enumeration — what this runbook does NOT cover

- **Seeding `pricing_plans`, `permissions`, built-in roles.** The
  `bootstrap` subcommand in step 5 handles these (§Fase 49.j). This
  runbook focuses on the schema upgrade only.
- **Partial v1.x states.** If your v1.x deployment hand-applied SQL
  patches that diverge from the canonical OSS axon-rs migrations,
  the column-add-only path in §2-3 may not be sufficient. Diagnose
  via Query 1.2 and add custom `ALTER TABLE` statements as needed
  before applying the canonical SQL.
- **`public.*` legacy schema.** Whatever your v1.x deployment stored
  outside `axon_admin` + `axon_control` (Supabase auth, your own
  app tables, etc.) is left untouched. The
  `public.axon_current_tenant()` function (if you created one for
  Supabase RLS interop) continues to work as-is — the v3.x server
  sets `SET LOCAL axon.current_tenant` via `begin_tenant_tx`
  matching exactly the GUC the helper reads.
- **Migration 020 + 021 (`flow_deployments` + NOTIFY trigger).**
  The canonical SQL ENABLEs RLS on `flow_deployments` and stamps
  the ledger, but does NOT issue the `CREATE TABLE` for the
  `flow_deployments` table itself (Kivi audit confirmed the table
  already exists from the v1.x cycle; future adopters whose v1.x
  pre-dates §Fase 49 may need to run `axon-enterprise migrate up`
  AFTER this script to create the table, then re-run §5+§6 to
  apply RLS + ledger).
- **`axon-enterprise migrate from-v1` CLI subcommand.** A future
  v3.1.0 candidate (Path B in the Kivi correspondence) will
  wrap this SQL in a binary subcommand with autonomous detection
  + structured report. Until then, the manual `psql` apply is the
  canonical path.

---

## Source of truth + drift gates

Every SQL statement in `upgrade_v1_oss_axon_rs.sql` was mechanically
transcribed from these canonical Rust sources:

| SQL section | Rust source |
|---|---|
| §0 axon_admin role | [`crates/serverd/src/migrations.rs::BOOTSTRAP_ROLE`](../crates/serverd/src/migrations.rs) |
| §1 ledger DDL | [`crates/serverd/src/migrations.rs::LEDGER_DDL`](../crates/serverd/src/migrations.rs) |
| §2-3 axon_admin.tenants ALTER | [`crates/saas-persistence/src/migrations.rs::tenant_lifecycle_migrations`](../crates/saas-persistence/src/migrations.rs) (017+018) |
| §4 users.password_hash_encrypted | [`crates/saas-persistence/src/migrations.rs::password_envelope_migrations`](../crates/saas-persistence/src/migrations.rs) (019) |
| §5 RLS enablement | [`crates/saas-db/src/rls.rs::full_policy_set_sql`](../crates/saas-db/src/rls.rs) × 18 tenant-scoped tables |
| §6 ledger sync | [`crates/serverd/src/migrations.rs::all_migrations`](../crates/serverd/src/migrations.rs) name list |

Three drift gates in
[`crates/saas-cli/src/docs_drift.rs`](../crates/saas-cli/src/docs_drift.rs)
pin this artifact against the canonical Rust sources:

1. `upgrade_v1_oss_sql_inserts_every_canonical_migration_name` —
   asserts every name in `all_migrations()` appears as an INSERT
   into `axon_control.schema_migrations` in the SQL.
2. `upgrade_v1_oss_sql_rls_enables_every_tenant_scoped_table` —
   asserts every table in the canonical 18-table list has the
   6-statement RLS block in the SQL.
3. `upgrade_v1_oss_sql_alter_tenants_adds_every_017_018_column` —
   asserts every `ADD COLUMN IF NOT EXISTS` from migrations 017 +
   018 source has a counterpart in the upgrade SQL.

A future migration edit that adds a column / table / migration
without updating the upgrade SQL fails the gate at
`cargo test --workspace` time, before the artifact diverges
silently.

---

— Bemarking AI · `support@bemarking.com.co`
