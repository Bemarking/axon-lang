-- AXON Enterprise: Add tenant_id to all runtime tables (M1)
-- Every row is now scoped to a tenant. Default value = 'default' for
-- backwards-compatibility with existing single-tenant deployments.

ALTER TABLE traces
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'
        REFERENCES tenants(tenant_id);

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'
        REFERENCES tenants(tenant_id);

ALTER TABLE daemons
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'
        REFERENCES tenants(tenant_id);

ALTER TABLE audit_log
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'
        REFERENCES tenants(tenant_id);

ALTER TABLE axon_stores
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'
        REFERENCES tenants(tenant_id);

ALTER TABLE dataspaces
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'
        REFERENCES tenants(tenant_id);

ALTER TABLE hibernations
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'
        REFERENCES tenants(tenant_id);

ALTER TABLE event_history
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'
        REFERENCES tenants(tenant_id);

ALTER TABLE execution_cache
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'
        REFERENCES tenants(tenant_id);

ALTER TABLE cost_tracking
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'
        REFERENCES tenants(tenant_id);

ALTER TABLE schedules
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'
        REFERENCES tenants(tenant_id);

ALTER TABLE backend_registry
    ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'
        REFERENCES tenants(tenant_id);

-- Performance indexes for tenant-scoped queries on the most-queried tables.
CREATE INDEX IF NOT EXISTS idx_traces_tenant          ON traces          (tenant_id);
CREATE INDEX IF NOT EXISTS idx_sessions_tenant        ON sessions        (tenant_id);
CREATE INDEX IF NOT EXISTS idx_daemons_tenant         ON daemons         (tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_tenant       ON audit_log       (tenant_id);
CREATE INDEX IF NOT EXISTS idx_axon_stores_tenant     ON axon_stores     (tenant_id);
CREATE INDEX IF NOT EXISTS idx_dataspaces_tenant      ON dataspaces      (tenant_id);
CREATE INDEX IF NOT EXISTS idx_hibernations_tenant    ON hibernations    (tenant_id);
CREATE INDEX IF NOT EXISTS idx_event_history_tenant   ON event_history   (tenant_id);
CREATE INDEX IF NOT EXISTS idx_execution_cache_tenant ON execution_cache (tenant_id);
CREATE INDEX IF NOT EXISTS idx_cost_tracking_tenant   ON cost_tracking   (tenant_id);
CREATE INDEX IF NOT EXISTS idx_schedules_tenant       ON schedules       (tenant_id);
CREATE INDEX IF NOT EXISTS idx_backend_registry_tenant ON backend_registry (tenant_id);
