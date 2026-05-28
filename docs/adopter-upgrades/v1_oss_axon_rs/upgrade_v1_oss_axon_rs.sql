-- =====================================================================
-- axon-enterprise — v1.x OSS-axon-rs → v3.x upgrade SQL (§Fase 49.n)
-- =====================================================================
--
-- Audience: operators of an `axon_admin` + `axon_control` schema set
-- populated by the OSS `axon-rs` v1.x cycle (Fase 35-37 timeframe;
-- ledger lives in `public._sqlx_migrations`, version range 1-6) who
-- need to bring their schema up to the v3.x canonical shape WITHOUT
-- destructive drop+recreate.
--
-- See `docs/UPGRADE_v1.x_OSS_AXON_RS_TO_v3.x.md` for the operator
-- runbook (pre-flight diagnostics, post-flight verification, fix
-- matrix). This file is the artifact the runbook applies; running
-- this file alone WITHOUT the runbook's pre-flight checklist is a
-- footgun (backup MANDATORY before any DDL on a production DB).
--
-- Scope (Path A.minimum):
--   1. Bootstrap `axon_admin` BYPASSRLS role if missing.
--   2. ALTER TABLE axon_admin.tenants ADD COLUMN IF NOT EXISTS … × 13
--      (the columns migrations 017 + 018 would have added but
--      `CREATE TABLE IF NOT EXISTS` silently skipped).
--   3. tenants_vertical_catalog_check + tenants_lifecycle_state_check
--      CHECK constraints (DO-block-guarded so re-runs are no-op).
--   4. tenants_bump_version_trigger function + trigger.
--   5. 4 ix_tenants_* helper indexes.
--   6. ALTER TABLE axon_control.users ADD COLUMN password_hash_encrypted
--      (migration 019).
--   7. CREATE TABLE IF NOT EXISTS axon_admin.shredded_tenants + index
--      (migration 018 §D2 cryptographic-shredding registry).
--   8. RLS enablement for 18 tenant-scoped tables in axon_control:
--      18 × 6 statements = 108 statements (ENABLE + FORCE + DROP
--      POLICY tenant_isolation + CREATE POLICY tenant_isolation +
--      DROP POLICY admin_bypass + CREATE POLICY admin_bypass).
--   9. Ledger sync: 21 INSERT INTO axon_control.schema_migrations
--      (name) VALUES (…) ON CONFLICT DO NOTHING — so subsequent
--      `axon-enterprise-server migrate up` against the upgraded DB
--      is a clean no-op.
--  10. Post-condition RAISE NOTICE counts so the operator sees the
--      expected end-state.
--
-- Out of scope (Path A.complete + Path B — future §49.n.2+):
--   - CREATE TABLE IF NOT EXISTS safety-belt for tables Kivi has but
--     a hypothetical future v1.x adopter might not. v1.x DID create
--     all 22 axon_* tables; only 7 ended up with rows, but all are
--     present. Future adopters with PARTIAL v1.x state get covered
--     by Path A.complete.
--   - Seeding `pricing_plans` (5 BUILT_IN_PLANS) + `permissions` (42
--     SYSTEM_PERMISSIONS) + built-in roles. Bootstrap subcommand
--     (§42.e + §49.j) seeds these on first run AFTER this upgrade
--     completes. Sequence: `apply this upgrade.sql` → `axon-enterprise
--     bootstrap --platform-owner-email <addr>` → all good.
--   - `axon-enterprise migrate from-v1` CLI subcommand (Path B).
--     Future v3.1.0 candidate.
--
-- Idempotency: every DDL uses `IF NOT EXISTS` / `IF EXISTS` /
-- `ON CONFLICT DO NOTHING` / DO-block existence guards. Running this
-- file twice is a no-op.
--
-- Transaction discipline: the file emits each domain as a separate
-- BEGIN/COMMIT so a partial failure has a clear rollback boundary.
-- A single mega-transaction would lock the entire `axon_admin` +
-- `axon_control` schema set for the duration; bounded domain blocks
-- keep lock-contention windows short.
--
-- Anti-enumeration: zero data manipulation. ZERO INSERT into rows
-- (other than the ledger sync). Existing data in `axon_admin.tenants`,
-- `axon_control.users`, `tenant_memberships`, `tenant_api_keys`,
-- `usage_events`, etc. is left exactly as-is.
--
-- RLS safety: the RLS-enablement block (§8) DOES NOT change the
-- connecting user. If the user is NOT a member of `axon_admin`, every
-- subsequent query against the 18 tenant-scoped tables WILL return
-- zero rows until `GRANT axon_admin TO <your-app-role>` is executed.
-- The runbook §post-flight calls this out explicitly. See
-- `docs/DATABASE.md#troubleshooting-rls-rejections-on-flow_deployments`
-- for the role-grant fix recipe.
--
-- Source of truth: every SQL statement here was mechanically
-- transcribed from the corresponding Rust `*_migrations()` function
-- in `crates/saas-persistence/src/migrations.rs`, `crates/saas-db/
-- src/rls.rs`, etc. Three drift gates in
-- `crates/saas-cli/src/docs_drift.rs` pin this file against the
-- canonical Rust source so a future migration edit fails the gate
-- before this file diverges silently.
--
-- =====================================================================
-- §0 — Precondition: axon_admin BYPASSRLS role
-- =====================================================================
-- Verbatim from `crates/serverd/src/migrations.rs:155-160`:
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'axon_admin') THEN
    CREATE ROLE axon_admin NOLOGIN BYPASSRLS;
    RAISE NOTICE 'axon_admin role created (NOLOGIN BYPASSRLS)';
  ELSE
    RAISE NOTICE 'axon_admin role already exists — skipped';
  END IF;
END $$;

-- =====================================================================
-- §1 — Ensure schemas + ledger table (idempotent)
-- =====================================================================
CREATE SCHEMA IF NOT EXISTS axon_admin;
CREATE SCHEMA IF NOT EXISTS axon_control;

CREATE TABLE IF NOT EXISTS axon_control.schema_migrations (
  name TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =====================================================================
-- §2 — Migration 017: axon_admin.tenants schema upgrade
--     (8 ADD COLUMN + 3 indexes + 1 CHECK + 1 function + 1 trigger)
-- =====================================================================
BEGIN;

ALTER TABLE axon_admin.tenants
  ADD COLUMN IF NOT EXISTS vertical TEXT NOT NULL DEFAULT 'generic';

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'tenants_vertical_catalog_check'
  ) THEN
    ALTER TABLE axon_admin.tenants
      ADD CONSTRAINT tenants_vertical_catalog_check
      CHECK (vertical IN (
        'generic', 'hipaa', 'gdpr', 'pci_dss', 'sox', 'soc2',
        'fedramp', 'gxp', 'fisma', 'legal', 'fintech', 'government'
      ));
  END IF;
END $$;

ALTER TABLE axon_admin.tenants
  ADD COLUMN IF NOT EXISTS region TEXT NOT NULL DEFAULT 'global';

ALTER TABLE axon_admin.tenants
  ADD COLUMN IF NOT EXISTS quota_budget_usd_monthly NUMERIC(12,2)
    NOT NULL DEFAULT 0;

ALTER TABLE axon_admin.tenants
  ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE axon_admin.tenants
  ADD COLUMN IF NOT EXISTS created_by TEXT;

ALTER TABLE axon_admin.tenants
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE axon_admin.tenants
  ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

ALTER TABLE axon_admin.tenants
  ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS ix_tenants_vertical ON axon_admin.tenants (vertical);
CREATE INDEX IF NOT EXISTS ix_tenants_status   ON axon_admin.tenants (status);
CREATE INDEX IF NOT EXISTS ix_tenants_deleted_at ON axon_admin.tenants (deleted_at)
  WHERE deleted_at IS NOT NULL;

CREATE OR REPLACE FUNCTION axon_admin.tenants_bump_version_trigger()
  RETURNS TRIGGER AS $$
  BEGIN
    NEW.version = OLD.version + 1;
    NEW.updated_at = now();
    RETURN NEW;
  END;
  $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tenants_bump_version ON axon_admin.tenants;
CREATE TRIGGER tenants_bump_version
  BEFORE UPDATE ON axon_admin.tenants
  FOR EACH ROW
  EXECUTE FUNCTION axon_admin.tenants_bump_version_trigger();

COMMIT;

-- =====================================================================
-- §3 — Migration 018: tenant lifecycle state machine
--     (5 ADD COLUMN + 1 CHECK + 1 partial index + 1 CREATE TABLE +
--      1 index on shredded_tenants)
-- =====================================================================
BEGIN;

ALTER TABLE axon_admin.tenants
  ADD COLUMN IF NOT EXISTS lifecycle_state TEXT NOT NULL DEFAULT 'active';

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'tenants_lifecycle_state_catalog_check'
  ) THEN
    ALTER TABLE axon_admin.tenants
      ADD CONSTRAINT tenants_lifecycle_state_catalog_check
      CHECK (lifecycle_state IN (
        'active', 'pending_deletion', 'soft_deleted', 'hard_deleted'
      ));
  END IF;
END $$;

ALTER TABLE axon_admin.tenants
  ADD COLUMN IF NOT EXISTS deletion_scheduled_at TIMESTAMPTZ;
ALTER TABLE axon_admin.tenants
  ADD COLUMN IF NOT EXISTS deletion_grace_until TIMESTAMPTZ;
ALTER TABLE axon_admin.tenants
  ADD COLUMN IF NOT EXISTS deletion_reason TEXT;
ALTER TABLE axon_admin.tenants
  ADD COLUMN IF NOT EXISTS deletion_requested_by TEXT;

CREATE INDEX IF NOT EXISTS ix_tenants_lifecycle_sweeper
  ON axon_admin.tenants (lifecycle_state, deletion_grace_until)
  WHERE lifecycle_state IN ('pending_deletion', 'soft_deleted');

CREATE TABLE IF NOT EXISTS axon_admin.shredded_tenants (
  tenant_id   TEXT PRIMARY KEY,
  shredded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  shredded_by TEXT,
  reason      TEXT
);
CREATE INDEX IF NOT EXISTS ix_shredded_tenants_shredded_at
  ON axon_admin.shredded_tenants (shredded_at);

COMMIT;

-- =====================================================================
-- §4 — Migration 019: password-hash envelope encryption
--     (1 ADD COLUMN on axon_control.users)
-- =====================================================================
BEGIN;

ALTER TABLE axon_control.users
  ADD COLUMN IF NOT EXISTS password_hash_encrypted BYTEA;

COMMIT;

-- =====================================================================
-- §5 — RLS enablement: the CRITICAL fix
-- =====================================================================
-- Every tenant-scoped table in `axon_control` gets the canonical 6
-- statements: ENABLE + FORCE RLS + DROP/CREATE tenant_isolation +
-- DROP/CREATE admin_bypass. The OSS axon-rs v1.x cycle created the
-- table shells without RLS — Supabase Advisors correctly flag this
-- as CRITICAL on adopter projects. The 18 tenant-scoped tables
-- (mechanically extracted from the `rls(table)` calls in domain
-- migration sources):
--
--   spine 002:   tenant_memberships, sessions
--   spine 003:   roles, role_permissions, user_roles
--   spine 005:   sso_configurations, sso_states
--   spine 006:   secrets
--   metering 008: tenant_subscriptions
--   metering 009: usage_events
--   metering 010: invoices
--   audit 011:    audit_events
--   compliance 012: compliance_requests
--   compliance 013: legal_holds
--   access 014:   tenant_api_keys
--   cognition 015: cognitive_states
--   cognition 016: replay_tokens
--   flow_deployments 020: flow_deployments
--
-- 18 tables × 6 statements = 108 statements. Wrapped in one BEGIN/
-- COMMIT because RLS-enablement contention is shorter than schema-
-- alter contention; an interrupted block leaves a partial mix of
-- enabled/disabled tables which is observable + recoverable.
--
-- Per `crates/saas-db/src/rls.rs::full_policy_set_sql`, the tenant
-- column is `tenant_id` and the admin role is `axon_admin` for every
-- table.

BEGIN;

-- tenant_memberships (002)
ALTER TABLE "axon_control"."tenant_memberships" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."tenant_memberships" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."tenant_memberships";
CREATE POLICY tenant_isolation ON "axon_control"."tenant_memberships" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."tenant_memberships";
CREATE POLICY admin_bypass ON "axon_control"."tenant_memberships" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

-- sessions (002)
ALTER TABLE "axon_control"."sessions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."sessions" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."sessions";
CREATE POLICY tenant_isolation ON "axon_control"."sessions" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."sessions";
CREATE POLICY admin_bypass ON "axon_control"."sessions" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

-- roles (003)
ALTER TABLE "axon_control"."roles" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."roles" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."roles";
CREATE POLICY tenant_isolation ON "axon_control"."roles" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."roles";
CREATE POLICY admin_bypass ON "axon_control"."roles" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

-- role_permissions (003)
ALTER TABLE "axon_control"."role_permissions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."role_permissions" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."role_permissions";
CREATE POLICY tenant_isolation ON "axon_control"."role_permissions" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."role_permissions";
CREATE POLICY admin_bypass ON "axon_control"."role_permissions" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

-- user_roles (003)
ALTER TABLE "axon_control"."user_roles" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."user_roles" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."user_roles";
CREATE POLICY tenant_isolation ON "axon_control"."user_roles" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."user_roles";
CREATE POLICY admin_bypass ON "axon_control"."user_roles" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

-- sso_configurations (005)
ALTER TABLE "axon_control"."sso_configurations" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."sso_configurations" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."sso_configurations";
CREATE POLICY tenant_isolation ON "axon_control"."sso_configurations" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."sso_configurations";
CREATE POLICY admin_bypass ON "axon_control"."sso_configurations" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

-- sso_states (005)
ALTER TABLE "axon_control"."sso_states" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."sso_states" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."sso_states";
CREATE POLICY tenant_isolation ON "axon_control"."sso_states" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."sso_states";
CREATE POLICY admin_bypass ON "axon_control"."sso_states" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

-- secrets (006)
ALTER TABLE "axon_control"."secrets" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."secrets" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."secrets";
CREATE POLICY tenant_isolation ON "axon_control"."secrets" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."secrets";
CREATE POLICY admin_bypass ON "axon_control"."secrets" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

-- tenant_subscriptions (008)
ALTER TABLE "axon_control"."tenant_subscriptions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."tenant_subscriptions" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."tenant_subscriptions";
CREATE POLICY tenant_isolation ON "axon_control"."tenant_subscriptions" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."tenant_subscriptions";
CREATE POLICY admin_bypass ON "axon_control"."tenant_subscriptions" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

-- usage_events (009)
ALTER TABLE "axon_control"."usage_events" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."usage_events" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."usage_events";
CREATE POLICY tenant_isolation ON "axon_control"."usage_events" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."usage_events";
CREATE POLICY admin_bypass ON "axon_control"."usage_events" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

-- invoices (010)
ALTER TABLE "axon_control"."invoices" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."invoices" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."invoices";
CREATE POLICY tenant_isolation ON "axon_control"."invoices" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."invoices";
CREATE POLICY admin_bypass ON "axon_control"."invoices" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

-- audit_events (011)
ALTER TABLE "axon_control"."audit_events" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."audit_events" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."audit_events";
CREATE POLICY tenant_isolation ON "axon_control"."audit_events" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."audit_events";
CREATE POLICY admin_bypass ON "axon_control"."audit_events" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

-- compliance_requests (012)
ALTER TABLE "axon_control"."compliance_requests" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."compliance_requests" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."compliance_requests";
CREATE POLICY tenant_isolation ON "axon_control"."compliance_requests" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."compliance_requests";
CREATE POLICY admin_bypass ON "axon_control"."compliance_requests" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

-- legal_holds (013)
ALTER TABLE "axon_control"."legal_holds" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."legal_holds" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."legal_holds";
CREATE POLICY tenant_isolation ON "axon_control"."legal_holds" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."legal_holds";
CREATE POLICY admin_bypass ON "axon_control"."legal_holds" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

-- tenant_api_keys (014)
ALTER TABLE "axon_control"."tenant_api_keys" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."tenant_api_keys" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."tenant_api_keys";
CREATE POLICY tenant_isolation ON "axon_control"."tenant_api_keys" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."tenant_api_keys";
CREATE POLICY admin_bypass ON "axon_control"."tenant_api_keys" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

-- cognitive_states (015)
ALTER TABLE "axon_control"."cognitive_states" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."cognitive_states" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."cognitive_states";
CREATE POLICY tenant_isolation ON "axon_control"."cognitive_states" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."cognitive_states";
CREATE POLICY admin_bypass ON "axon_control"."cognitive_states" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

-- replay_tokens (016)
ALTER TABLE "axon_control"."replay_tokens" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."replay_tokens" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."replay_tokens";
CREATE POLICY tenant_isolation ON "axon_control"."replay_tokens" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."replay_tokens";
CREATE POLICY admin_bypass ON "axon_control"."replay_tokens" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

-- flow_deployments (020)
ALTER TABLE "axon_control"."flow_deployments" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "axon_control"."flow_deployments" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON "axon_control"."flow_deployments";
CREATE POLICY tenant_isolation ON "axon_control"."flow_deployments" FOR ALL USING (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL) WITH CHECK (tenant_id = current_setting('axon.current_tenant', true) AND current_setting('axon.current_tenant', true) IS NOT NULL);
DROP POLICY IF EXISTS admin_bypass ON "axon_control"."flow_deployments";
CREATE POLICY admin_bypass ON "axon_control"."flow_deployments" FOR ALL TO axon_admin USING (true) WITH CHECK (true);

COMMIT;

-- =====================================================================
-- §6 — Ledger sync: stamp every canonical v3.x migration as applied
-- =====================================================================
-- After this block, `axon-enterprise-server migrate up` against this
-- DB is a clean no-op (every name already in the ledger). All 21
-- canonical names from `crates/serverd/src/migrations.rs::all_migrations`.
-- ON CONFLICT DO NOTHING keeps the block idempotent.

BEGIN;

INSERT INTO axon_control.schema_migrations (name) VALUES ('001_baseline')                       ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('002_identity')                       ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('003_rbac')                           ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('004_jwt_signing_keys')               ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('005_sso')                            ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('006_secrets')                        ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('007_pricing_plans')                  ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('008_tenant_subscriptions')           ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('009_usage_events')                   ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('010_invoices')                       ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('011_audit_events')                   ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('012_compliance_requests')            ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('013_legal_holds')                    ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('014_tenant_api_keys')                ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('015_cognitive_states')               ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('016_replay_tokens')                  ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('017_tenant_schema_upgrade')          ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('018_tenant_lifecycle_state_machine') ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('019_password_hash_envelope')         ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('020_flow_deployments')               ON CONFLICT DO NOTHING;
INSERT INTO axon_control.schema_migrations (name) VALUES ('021_flow_deployments_notify')        ON CONFLICT DO NOTHING;

COMMIT;

-- =====================================================================
-- §7 — Post-condition: emit operator-visible counts
-- =====================================================================
-- These RAISE NOTICE lines print to the operator's psql session so
-- they see the expected end-state without running follow-up queries.
-- All four counts should match the expected values on a successful
-- run; mismatch indicates partial failure + the runbook §post-flight
-- has the diagnosis matrix.

DO $$
DECLARE
  v_ledger_count INTEGER;
  v_rls_enabled_count INTEGER;
  v_tenants_columns INTEGER;
  v_role_exists BOOLEAN;
BEGIN
  SELECT COUNT(*) INTO v_ledger_count FROM axon_control.schema_migrations;
  SELECT COUNT(*) INTO v_rls_enabled_count
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'axon_control'
      AND c.relrowsecurity = true
      AND c.relforcerowsecurity = true;
  SELECT COUNT(*) INTO v_tenants_columns
    FROM information_schema.columns
    WHERE table_schema = 'axon_admin' AND table_name = 'tenants';
  SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = 'axon_admin') INTO v_role_exists;

  RAISE NOTICE '=====================================================================';
  RAISE NOTICE 'axon-enterprise v1.x → v3.x upgrade — post-condition report';
  RAISE NOTICE '=====================================================================';
  RAISE NOTICE 'axon_admin role present: %  (expected: t)', v_role_exists;
  RAISE NOTICE 'axon_control.schema_migrations rows: %  (expected: >= 21)', v_ledger_count;
  RAISE NOTICE 'axon_control tables with FORCE RLS: %  (expected: >= 18)', v_rls_enabled_count;
  RAISE NOTICE 'axon_admin.tenants column count: %  (expected: >= 18)', v_tenants_columns;
  RAISE NOTICE '=====================================================================';
  RAISE NOTICE 'Next step: GRANT axon_admin TO <your-app-role>;';
  RAISE NOTICE 'Then:     `axon-enterprise-server bootstrap --platform-owner-email <addr>`';
  RAISE NOTICE 'See:      docs/UPGRADE_v1.x_OSS_AXON_RS_TO_v3.x.md';
  RAISE NOTICE '=====================================================================';
END $$;
