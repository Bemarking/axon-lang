-- AXON Enterprise: Tenant Identity (M1)
-- Creates the tenants table as the root entity for multi-tenancy.

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    plan        TEXT NOT NULL DEFAULT 'starter',   -- starter | pro | enterprise
    status      TEXT NOT NULL DEFAULT 'active',    -- active | suspended | deleted
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tenants_status ON tenants (status);
CREATE INDEX IF NOT EXISTS idx_tenants_plan   ON tenants (plan);

-- Seed the default tenant for backwards-compatibility with single-tenant deployments.
INSERT INTO tenants (tenant_id, name, plan, status)
VALUES ('default', 'Default Tenant', 'enterprise', 'active')
ON CONFLICT (tenant_id) DO NOTHING;
