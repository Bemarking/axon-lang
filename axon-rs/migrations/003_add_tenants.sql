-- AXON Enterprise: Tenant Identity (M1) — schema-isolated edition (v1.38.2+)
--
-- §Fase 38.x.b (D1, D2, D4) — axon's tenant identity table now lives in
-- a dedicated `axon_admin` schema. Pre-v1.38.2 this table was created
-- in the default search-path schema (typically `public`), which
-- collided with adopter-owned `public.tenants` tables that had a
-- different column shape — falsely passing `CREATE TABLE IF NOT EXISTS`
-- and then failing at the first SELECT with `column "plan" does not
-- exist`. v1.38.2 fixes this structurally: axon-owned admin tables
-- live in `axon_admin`, never in `public`.
--
-- Migration semantics:
--
--   - Idempotent: rerunning is a no-op once `axon_admin.tenants` is
--     populated.
--   - Non-destructive: `public.tenants` is NEVER dropped, even when it
--     contains axon-owned data that has been copied across. The
--     adopter may still have RLS grants, app FKs, or custom consumers
--     pointing at it; we don't presume to clean up.
--   - Defensive: data COPY from legacy `public.tenants` runs ONLY if
--     the legacy table has BOTH `plan` AND `status` columns (axon's
--     unique markers). A table that lacks either is the adopter's own
--     — left untouched.

-- ── §D1 — the axon_admin namespace ───────────────────────────────────
CREATE SCHEMA IF NOT EXISTS axon_admin AUTHORIZATION CURRENT_USER;

COMMENT ON SCHEMA axon_admin IS
    'AXON-owned admin namespace (Fase 38.x.b, v1.38.2+). Tables here are '
    'created and managed by axon-rs migrations. Adopters MUST NOT modify '
    'this schema directly; FK references from application code are '
    'discouraged — use the Admin API or capabilities-based reads instead.';

-- ── §D1 — the canonical tenants table ────────────────────────────────
CREATE TABLE IF NOT EXISTS axon_admin.tenants (
    tenant_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    plan        TEXT NOT NULL DEFAULT 'starter',   -- starter | pro | enterprise
    status      TEXT NOT NULL DEFAULT 'active',    -- active | suspended | deleted
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_axon_admin_tenants_status ON axon_admin.tenants (status);
CREATE INDEX IF NOT EXISTS idx_axon_admin_tenants_plan   ON axon_admin.tenants (plan);

-- ── §D2 — idempotent COPY from legacy public.tenants if axon-owned ───
-- Detection: the legacy `public.tenants` exists AND has both `plan`
-- AND `status` columns (axon's unique markers; an adopter table
-- rarely has both with these exact names).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'tenants'
          AND column_name = 'plan'
    ) AND EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'tenants'
          AND column_name = 'status'
    ) THEN
        -- The legacy table has axon's shape — safe to copy.
        EXECUTE
            'INSERT INTO axon_admin.tenants ' ||
            '    (tenant_id, name, plan, status, created_at, updated_at) ' ||
            'SELECT tenant_id, name, plan, status, created_at, updated_at ' ||
            'FROM public.tenants ' ||
            'ON CONFLICT (tenant_id) DO NOTHING';
        -- IMPORTANT: do NOT drop public.tenants. The adopter may still
        -- need it for RLS grants / app FKs / their own readers.
        -- A future Fase 39+ may introduce a deprecation warning when
        -- axon detects writes still going to public.tenants.
    END IF;
END
$$;

-- ── §D2 — seed the default tenant into the new canonical home ────────
INSERT INTO axon_admin.tenants (tenant_id, name, plan, status)
VALUES ('default', 'Default Tenant', 'enterprise', 'active')
ON CONFLICT (tenant_id) DO NOTHING;
