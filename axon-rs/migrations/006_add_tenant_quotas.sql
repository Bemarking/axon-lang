-- AXON Enterprise: Per-Tenant Quota Columns (M4)
--
-- Adds configurable rate-limit columns to the tenants table so operators
-- can override per-plan defaults without a code deploy.
--
-- Defaults mirror the in-memory TenantQuotas constants in rate_limiter.rs:
--   starter    →  60 req/min,   100_000 tokens/day
--   pro        → 300 req/min, 1_000_000 tokens/day
--   enterprise → 2000 req/min, unlimited (NULL = no cap)

ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS requests_per_min  INTEGER  DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS tokens_per_day    BIGINT   DEFAULT NULL;

COMMENT ON COLUMN tenants.requests_per_min IS
    'Per-minute request quota override. NULL = use plan default.';

COMMENT ON COLUMN tenants.tokens_per_day IS
    'Daily token quota override. NULL = use plan default (enterprise = unlimited).';

-- Seed per-plan defaults for the built-in "default" tenant
UPDATE tenants
SET    requests_per_min = 2000,
       tokens_per_day   = NULL   -- NULL = unlimited for enterprise
WHERE  tenant_id = 'default';
