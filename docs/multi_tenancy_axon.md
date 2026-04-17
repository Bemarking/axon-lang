# Multi-Tenancy + Secrets Management — Axon Enterprise

## Estado del plan

| Fase | Nombre | Estado |
|------|--------|--------|
| M1 | Tenant Identity | 🔄 En progreso |
| M2 | Data Isolation (PostgreSQL RLS) | ⏳ Pendiente |
| M3 | Secrets per Tenant (AWS Secrets Manager) | ⏳ Pendiente |
| M4 | Backend Isolation (circuit breakers + metering) | ⏳ Pendiente |
| M5 | Terraform — onboarding de tenants | ⏳ Pendiente |

---

## Arquitectura objetivo

```
Request entrante
      │
      ▼
TenantExtractor middleware
  → extrae tenant_id del JWT o X-Tenant-ID header
  → inyecta TenantContext en request extensions
      │
      ▼
Auth middleware (RBAC existente)
  → valida rol dentro del tenant
      │
      ├──► Handler Rust
      │         │
      │         ├──► Storage (PostgreSQL + RLS)
      │         │     SET axon.current_tenant = tenant_id
      │         │     → Postgres filtra solo, bulletproof
      │         │
      │         └──► TenantSecretsClient
      │               → cache TTL 5min
      │               → AWS Secrets Manager: axon/tenants/{id}/provider_key
      │               → fallback a key global de Axon
      │
      └──► ResilientBackend[(tenant_id, provider)]
            → circuit breaker aislado por tenant
            → metering: cost_tracking con tenant_id
```

---

## M1 — Tenant Identity

**Objetivo:** cada request sabe a qué tenant pertenece.

### Archivos nuevos
- `axon-rs/migrations/003_add_tenants.sql` — tabla `tenants`
- `axon-rs/migrations/004_add_tenant_id.sql` — columna `tenant_id` en las 12 tablas existentes
- `axon-rs/src/tenant.rs` — `TenantContext`, `TenantExtractor` middleware, `TenantPlan` enum

### Cambios a existentes
- `axon-rs/src/storage.rs` — campo `tenant_id: String` en todos los row types
- `axon-rs/src/axon_server.rs` — registrar `TenantExtractor` en el router Axum

### Contrato del middleware
```
Header X-Tenant-ID: {tenant_id}    → TenantContext { tenant_id, plan }
Header Authorization: Bearer {jwt} → extrae claim "tenant_id" del payload JWT
Sin header                         → tenant_id = "default" (retrocompatibilidad)
```

### Tabla tenants
```sql
CREATE TABLE tenants (
    tenant_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    plan        TEXT NOT NULL DEFAULT 'starter',  -- starter | pro | enterprise
    status      TEXT NOT NULL DEFAULT 'active',   -- active | suspended | deleted
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO tenants (tenant_id, name, plan) VALUES ('default', 'Default Tenant', 'enterprise');
```

---

## M2 — Data Isolation (PostgreSQL RLS)

**Objetivo:** imposible leer datos cross-tenant, incluso con bug en Rust.

### Patrón
```sql
ALTER TABLE traces ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON traces
    USING (tenant_id = current_setting('axon.current_tenant', true));
```

### Cambios requeridos
- `axon-rs/migrations/005_enable_rls.sql` — RLS en las 12 tablas
- `axon-rs/src/db_pool.rs` — inyectar `SET axon.current_tenant = $1` al sacar conexión del pool
- `axon-rs/src/storage_postgres.rs` — todas las queries incluyen `tenant_id` en WHERE/INSERT

---

## M3 — Secrets per Tenant (AWS Secrets Manager)

**Objetivo:** cada tenant tiene sus propias LLM API keys, nunca en Postgres ni logs.

### Convención de paths
```
axon/tenants/{tenant_id}/anthropic_api_key
axon/tenants/{tenant_id}/openai_api_key
axon/tenants/{tenant_id}/gemini_api_key
axon/tenants/{tenant_id}/openrouter_api_key
axon/tenants/{tenant_id}/groq_api_key
```

### Cadena de resolución
1. Cache en memoria `(tenant_id, provider)` con TTL 5 minutos
2. AWS Secrets Manager path del tenant
3. Fallback a key global de Axon (env var)

### Archivos nuevos
- `axon-rs/src/tenant_secrets.rs` — `TenantSecretsClient` con cache + AWS SDK

### Decisión: AWS SM vs Vault
- **V1 (este plan):** AWS Secrets Manager — ya provisionado, IAM integrado, costo bajo
- **V2 (futuro):** HashiCorp Vault — dynamic secrets, rotación automática, multi-cloud

---

## M4 — Backend Isolation

**Objetivo:** un tenant no afecta a otro; base para billing.

### Cambios
- `ResilientBackend`: circuit breakers indexados por `(tenant_id, provider)` en vez de solo `provider`
- Rate limiter: cuota configurable en tabla `tenants` (requests/min, tokens/día)
- `cost_tracking` table: ya existe, solo necesita `tenant_id` (cubierto por M1)

---

## M5 — Terraform

**Objetivo:** onboarding de nuevos tenants sin intervención manual.

### Entregables
- `infrastructure/terraform/modules/tenant/` — crea paths SM para un tenant
- `infrastructure/scripts/onboard_tenant.sh` — crea tenant en DB + secretos vacíos + API key inicial
- Evaluar upgrade RDS de `t3.micro` a `t3.small` + Multi-AZ para carga multi-tenant real

---

## Routing Git para este plan

Todos los commits de M1–M5 son enterprise-only:

```bash
git push origin master && git push enterprise master
```

Prefijo de commits: `feat(enterprise): ...`
