-- AXON Enterprise: Row-Level Security — Data Isolation (M2)
--
-- Guarantees that no query, regardless of application-layer bugs, can ever
-- return rows belonging to a different tenant.
--
-- Mechanism: every storage method opens a transaction and executes
--   SET LOCAL axon.current_tenant = '<tenant_id>'
-- before any DML. Postgres evaluates the RLS policy against this setting for
-- every row touched in that transaction.
--
-- IMPORTANT: The database role used by the application must NOT be a superuser.
-- Superusers bypass RLS by default. Use a dedicated app role:
--   CREATE ROLE axon_app LOGIN PASSWORD '...' NOSUPERUSER;
--   GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO axon_app;

-- ── Step 1: Fix UNIQUE / PK constraints for composite tenant isolation ─────────
--
-- Tables with TEXT name as primary key must use (tenant_id, name) as the
-- composite PK so two tenants can have resources with the same name.

-- traces: UNIQUE(trace_id) → UNIQUE(tenant_id, trace_id)
ALTER TABLE traces DROP CONSTRAINT IF EXISTS traces_trace_id_key;
ALTER TABLE traces ADD CONSTRAINT traces_tenant_trace_id_key
    UNIQUE (tenant_id, trace_id);

-- sessions: UNIQUE(scope, key) → UNIQUE(tenant_id, scope, key)
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_scope_key_key;
ALTER TABLE sessions ADD CONSTRAINT sessions_tenant_scope_key_key
    UNIQUE (tenant_id, scope, key);

-- daemons: PRIMARY KEY (name) → PRIMARY KEY (tenant_id, name)
ALTER TABLE daemons DROP CONSTRAINT IF EXISTS daemons_pkey;
ALTER TABLE daemons ADD PRIMARY KEY (tenant_id, name);

-- axon_stores: PRIMARY KEY (name) → PRIMARY KEY (tenant_id, name)
ALTER TABLE axon_stores DROP CONSTRAINT IF EXISTS axon_stores_pkey;
ALTER TABLE axon_stores ADD PRIMARY KEY (tenant_id, name);

-- dataspaces: PRIMARY KEY (name) → PRIMARY KEY (tenant_id, name)
ALTER TABLE dataspaces DROP CONSTRAINT IF EXISTS dataspaces_pkey;
ALTER TABLE dataspaces ADD PRIMARY KEY (tenant_id, name);

-- hibernations: PRIMARY KEY (id) → PRIMARY KEY (tenant_id, id)
ALTER TABLE hibernations DROP CONSTRAINT IF EXISTS hibernations_pkey;
ALTER TABLE hibernations ADD PRIMARY KEY (tenant_id, id);

-- schedules: PRIMARY KEY (name) → PRIMARY KEY (tenant_id, name)
ALTER TABLE schedules DROP CONSTRAINT IF EXISTS schedules_pkey;
ALTER TABLE schedules ADD PRIMARY KEY (tenant_id, name);

-- backend_registry: PRIMARY KEY (name) → PRIMARY KEY (tenant_id, name)
ALTER TABLE backend_registry DROP CONSTRAINT IF EXISTS backend_registry_pkey;
ALTER TABLE backend_registry ADD PRIMARY KEY (tenant_id, name);

-- execution_cache: UNIQUE(cache_key) → UNIQUE(tenant_id, cache_key)
ALTER TABLE execution_cache DROP CONSTRAINT IF EXISTS execution_cache_cache_key_key;
ALTER TABLE execution_cache ADD CONSTRAINT execution_cache_tenant_cache_key_key
    UNIQUE (tenant_id, cache_key);

-- ── Step 2: Enable RLS on all 12 runtime tables ────────────────────────────────
--
-- RLS is disabled by default even when policies exist. Enabling it here activates
-- the isolation guarantee at the database level.

ALTER TABLE traces           ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions         ENABLE ROW LEVEL SECURITY;
ALTER TABLE daemons          ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log        ENABLE ROW LEVEL SECURITY;
ALTER TABLE axon_stores      ENABLE ROW LEVEL SECURITY;
ALTER TABLE dataspaces       ENABLE ROW LEVEL SECURITY;
ALTER TABLE hibernations     ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_history    ENABLE ROW LEVEL SECURITY;
ALTER TABLE execution_cache  ENABLE ROW LEVEL SECURITY;
ALTER TABLE cost_tracking    ENABLE ROW LEVEL SECURITY;
ALTER TABLE schedules        ENABLE ROW LEVEL SECURITY;
ALTER TABLE backend_registry ENABLE ROW LEVEL SECURITY;

-- ── Step 3: Create isolation policies ─────────────────────────────────────────
--
-- Policy expression:
--   COALESCE(NULLIF(current_setting('axon.current_tenant', true), ''), 'default')
--
-- This means:
--   - current_setting returns NULL if not set (due to the `true` missing-ok flag)
--   - NULLIF converts empty string to NULL as well
--   - COALESCE falls back to 'default' when neither header nor JWT tenant is set
--   - This ensures open-source / single-tenant installs work without any config

CREATE OR REPLACE FUNCTION axon_current_tenant() RETURNS TEXT AS $$
  SELECT COALESCE(NULLIF(current_setting('axon.current_tenant', true), ''), 'default');
$$ LANGUAGE SQL STABLE SECURITY DEFINER;

-- USING: filters rows on SELECT / UPDATE / DELETE
-- WITH CHECK: validates rows on INSERT / UPDATE
-- Both must match the tenant so cross-tenant writes are also blocked.

CREATE POLICY tenant_isolation ON traces
    USING     (tenant_id = axon_current_tenant())
    WITH CHECK (tenant_id = axon_current_tenant());

CREATE POLICY tenant_isolation ON sessions
    USING     (tenant_id = axon_current_tenant())
    WITH CHECK (tenant_id = axon_current_tenant());

CREATE POLICY tenant_isolation ON daemons
    USING     (tenant_id = axon_current_tenant())
    WITH CHECK (tenant_id = axon_current_tenant());

CREATE POLICY tenant_isolation ON audit_log
    USING     (tenant_id = axon_current_tenant())
    WITH CHECK (tenant_id = axon_current_tenant());

CREATE POLICY tenant_isolation ON axon_stores
    USING     (tenant_id = axon_current_tenant())
    WITH CHECK (tenant_id = axon_current_tenant());

CREATE POLICY tenant_isolation ON dataspaces
    USING     (tenant_id = axon_current_tenant())
    WITH CHECK (tenant_id = axon_current_tenant());

CREATE POLICY tenant_isolation ON hibernations
    USING     (tenant_id = axon_current_tenant())
    WITH CHECK (tenant_id = axon_current_tenant());

CREATE POLICY tenant_isolation ON event_history
    USING     (tenant_id = axon_current_tenant())
    WITH CHECK (tenant_id = axon_current_tenant());

CREATE POLICY tenant_isolation ON execution_cache
    USING     (tenant_id = axon_current_tenant())
    WITH CHECK (tenant_id = axon_current_tenant());

CREATE POLICY tenant_isolation ON cost_tracking
    USING     (tenant_id = axon_current_tenant())
    WITH CHECK (tenant_id = axon_current_tenant());

CREATE POLICY tenant_isolation ON schedules
    USING     (tenant_id = axon_current_tenant())
    WITH CHECK (tenant_id = axon_current_tenant());

CREATE POLICY tenant_isolation ON backend_registry
    USING     (tenant_id = axon_current_tenant())
    WITH CHECK (tenant_id = axon_current_tenant());

-- tenants table itself is NOT RLS-protected — it is an admin/system table.
-- Access to it is controlled by application-layer auth (Admin role only).
