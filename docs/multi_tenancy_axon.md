# Multi-Tenancy + Secrets Management — Axon Enterprise

## Estado del plan

### Plano de datos — Rust runtime (axon-lang)

| Fase | Nombre | Estado |
|------|--------|--------|
| M1 | Tenant Identity | ✅ Completo |
| M2 | Data Isolation (PostgreSQL RLS) | ✅ Completo |
| M3 | Secrets per Tenant (AWS Secrets Manager) | ✅ Completo |
| M4 | Backend Isolation (circuit breakers + metering) | ✅ Completo |
| M5 | Terraform — onboarding de tenants | ✅ Completo |

### Plano de control — Python (axon-enterprise v1.1.0)

| Fase | Nombre | Estado |
|------|--------|--------|
| 10.a | Persistence Foundation (SQLAlchemy 2 async + Alembic + RLS hookup) | ✅ Completo |
| 10.b | Identity Core (Users, Argon2id, TOTP, sessions, memberships) | ✅ Completo |
| 10.c | RBAC Production-Grade (persisted, tenant-scoped, hierarchy, enforcement) | ✅ Completo |
| 10.d | SSO Real (OIDC + SAML con verificación de firma) | ✅ Completo |
| 10.e | JWT Issuer + JWKS rotation (cierra el gap "no signature verification" de Rust) | ✅ Completo |
| 10.f | Secrets Service (API per-tenant, escribe a AWS SM, audit integrado) | ⏳ Pendiente |
| 10.g | Audit Hash-Chain (append-only + stitch a ESK provenance_chain) | ⏳ Pendiente |
| 10.h | Metering + Quota Enforcement (pricing plans, Stripe, rate limiting) | ⏳ Pendiente |
| 10.i | Observability Wiring (Prometheus per-tenant, OTel con tenant baggage, structured logs) | ⏳ Pendiente |
| 10.j | Admin API + CLI (tenant CRUD, user mgmt, key rotation, suspension) | ⏳ Pendiente |
| 10.k | Tenant Self-Service Portal API (invitaciones, SSO config, API keys) | ⏳ Pendiente |
| 10.l | Compliance Tooling (GDPR export JSONL, right-to-erasure, data residency) | ⏳ Pendiente |
| 10.m | Testing + Security Audit (cross-tenant isolation, load, threat model) | ⏳ Pendiente |

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
axon/tenants/{tenant_id}/kimi_api_key
axon/tenants/{tenant_id}/glm_api_key
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
- `infrastructure/terraform/modules/tenant/` — crea paths SM para un tenant (for_each sobre providers)
- `infrastructure/scripts/onboard_tenant.sh` — crea tenant en DB + secretos vacíos + API key inicial
- RDS upgrade: `db.t3.micro` → `db.t3.small`, `multi_az = true` (decisión documentada en variables.tf)
- `infrastructure/terraform/iam.tf` — Task Role ahora tiene permiso `axon/tenants/*` en SM (requerido por TenantSecretsClient)

### Decisión RDS
| Dimensión | Antes | Después |
|-----------|-------|---------|
| Instancia | db.t3.micro (1 GB) | db.t3.small (2 GB) |
| Multi-AZ | false | true |
| Motivo | Free tier / dev | SLA 99.9% multi-tenant; RLS agrega overhead por transacción |
| Siguiente umbral | — | db.t3.medium cuando tenants > 20 o p99 > 200 ms |

---

---

## Fase 10 — Enterprise Control Plane (Python / axon-enterprise v1.1.0)

### Por qué existe esta fase

M1–M5 completaron el **plano de datos** en el runtime Rust: extracción de tenant por request, RLS en Postgres, secrets aislados en AWS SM, circuit breakers per-(tenant, provider), y Terraform para onboarding de infra. Eso hace que una request *ya pateada* sea segura y aislada.

Lo que falta es el **plano de control** — el conjunto de servicios que provisionan tenants, gestionan usuarios, enforzan RBAC, emiten JWTs firmados, guardan secretos, corren auditoría append-only, facturan, y exponen un portal administrativo. Hoy `axon_enterprise/` es *scaffolding con TODOs*: dataclasses sin persistencia, SSO con `return None`, audit en `list` Python, RBAC in-memory sin tenant scope, métricas sin backend.

Fase 10 construye ese control plane de forma **production-grade desde el primer commit** — sin "por ahora", sin "lo mínimo", sin stubs. Cada sub-fase cierra uno de los gaps identificados en la auditoría de v1.0.0 y deja código apto para un primer cliente enterprise real.

### Arquitectura objetivo (Python ↔ Rust)

```
┌────────────────────── Plano de control (Python / axon-enterprise) ──────────────────────┐
│                                                                                         │
│   Admin CLI ──┐                                                                         │
│   Admin API ──┼─► TenantService ──► Postgres (tenants, users, roles, memberships)       │
│   Portal API ─┘                         │                                               │
│                                         │                                               │
│   SSO Router ──► OIDCProvider / SAMLProvider ─► validación firma ─► User/Membership     │
│        │                                                                                │
│        ▼                                                                                │
│   JWTIssuer ──► firma RS256 con llave KMS ──► { sub, tenant_id, roles, exp, jti }       │
│        │                                                                                │
│        ▼                                                                                │
│   SecretsService ──► write AWS SM path axon/tenants/{id}/{key} ──► emite audit event    │
│                                                                                         │
│   AuditService ──► append-only table + hash chain (SHA-256 anterior) ──► ESK stitch     │
│                                                                                         │
│   MeteringService ──► pricing_plan × usage ──► Stripe invoice ──► quota enforcement     │
│                                                                                         │
└─────────────────────────────────────┬───────────────────────────────────────────────────┘
                                      │ shared Postgres  (RLS enforced)
                                      │ shared AWS Secrets Manager
                                      │ JWKS served at /.well-known/jwks.json
                                      ▼
┌────────────────────── Plano de datos (Rust / axon-lang) ────────────────────────────────┐
│                                                                                         │
│   TenantExtractor ──► verifica firma JWT contra JWKS ──► TenantContext                  │
│   PostgresBackend ──► SET axon.current_tenant = $id ──► RLS lo filtra                   │
│   TenantSecretsClient ──► cache + AWS SM path convention                                │
│   ResilientBackend[(tenant, provider)] ──► circuit breaker aislado                      │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

**Principio:** Python escribe, Rust lee. Ambos comparten Postgres (con RLS) y AWS Secrets Manager. JWTs emitidos por Python, verificados por Rust contra JWKS público.

---

### 10.a — Persistence Foundation

**Estado:** ✅ Completo (2026-04-21) — **Depende de:** M1, M2 (completos)

**Shipped commits (axon-enterprise):**
- `58e5cb6` feat(fase-10.a): persistence foundation — config, tenant, db layer
- `4133e96` feat(fase-10.a): Alembic scaffold + baseline migration
- `cdd7492` test(fase-10.a): unit + integration suite for the persistence foundation
- `5c40c28` docs(fase-10.a): DATABASE.md operator guide

**Archivos producidos:**
- `axon_enterprise/config/{__init__.py, settings.py}` — pydantic-settings tree con validadores production-safety
- `axon_enterprise/tenant/{__init__.py, context.py}` — TenantContext + ContextVar (Python analogue de `tokio::task_local!`)
- `axon_enterprise/db/{__init__.py, base.py, engine.py, session.py, rls_policies.py}` — fundación completa
- `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/20260421_0000_001_baseline_foundation.py`
- `tests/{conftest.py, tenant/, config/, db/}` — suite unit + integration con testcontainers
- `docs/DATABASE.md` — operator guide (roles, migrations, RLS, pool tuning)

**Delta vs plan original:** + `SoftDeleteMixin`, + `admin_bypass_policy_sql` helper, + `full_policy_set_sql` convenience (reduce boilerplate en sub-fases 10.b+), + `psycopg[binary]` como fallback sync para Alembic offline mode, + `structlog` cableado en engine para slow-query logging.

**Objetivo:** fundación de persistencia async con RLS participativa. Todas las sub-fases siguientes construyen encima.

**Archivos nuevos (axon-enterprise):**
- `axon_enterprise/db/engine.py` — async engine (asyncpg), connection pool con `pool_pre_ping`, tuning per-plan
- `axon_enterprise/db/session.py` — `AsyncSessionLocal`, dependency `get_session(tenant_ctx)` que emite `SET LOCAL axon.current_tenant = :tid` antes de yield
- `axon_enterprise/db/base.py` — `DeclarativeBase` + `TimestampMixin` + `TenantScopedMixin` (FK + índice)
- `axon_enterprise/db/rls_policies.py` — helpers para declarar policies uniformes
- `alembic.ini`, `alembic/env.py`, `alembic/versions/001_initial.py`

**Decisiones clave:**
| Decisión | Elegido | Por qué |
|---|---|---|
| Driver | `asyncpg` | perf + async nativo; psycopg2 descartado |
| ORM | SQLAlchemy 2.x async | estándar, compatible con Alembic, evita split brain con ORMs menores |
| Migrations | Alembic con autogenerate + review manual | nunca autoapply en prod; cada migration es un PR |
| RLS setting | `axon.current_tenant` | **mismo nombre que Rust** (M2) — comparten la variable GUC |
| Session scope | Una por request HTTP | simplifica tx handling y error rollback |
| Connection pool | 10 min / 50 max por instancia | tuning inicial; ajustar con métricas de p99 |

**Criterios de aceptación:**
- Test de integración: query sin setear `axon.current_tenant` → RLS rechaza
- Test: query con tenant A NO retorna filas de tenant B aunque se haya declarado WHERE incorrecto
- Test: rollback de tx deja tenant setting limpio para el próximo checkout
- `alembic upgrade head` corre limpio contra schema vacío
- `alembic downgrade base` revierte sin errores

**Tracked commits:** _(pendiente)_

---

### 10.b — Identity Core

**Estado:** ✅ Completo (2026-04-21) — **Depende de:** 10.a

**Shipped commits (axon-enterprise):**
- `68299b8` feat(fase-10.b): envelope crypto + settings extension
- `e590155` feat(fase-10.b): identity core — users, memberships, sessions, auth
- `e88e4cc` test(fase-10.b): unit + integration suite for crypto and identity
- `9dc54b1` docs(fase-10.b): IDENTITY.md operator guide

**Archivos producidos:**
- `axon_enterprise/crypto/{__init__.py, envelope.py, local_envelope.py, kms_envelope.py}` — envelope encryption con interfaz + 2 backends (Fernet+HKDF local, AWS KMS GenerateDataKey prod)
- `axon_enterprise/identity/{__init__.py, errors.py, password.py, password_policy.py, totp.py, lockout.py, sessions.py, auth.py, models.py}` — servicios completos
- `axon_enterprise/config/settings.py` extendido: `EnvelopeSettings`, `IdentitySettings`, validator production-safety (rechaza envelope=local en prod)
- `alembic/versions/20260421_0100_002_identity_core.py` — migration con citext + pgcrypto + 3 tablas + RLS
- `tests/crypto/test_local_envelope.py` (10 casos)
- `tests/identity/{test_password, test_password_policy, test_totp, test_lockout, test_sessions_unit}.py` (28 casos unit, no Docker)
- `tests/identity/{test_auth_integration, test_rls_memberships}.py` (14 casos integration con testcontainers)
- `tests/conftest.py` refactor: fixtures de Postgres compartidas entre db/identity/audit/metering futuros
- `docs/IDENTITY.md` — operator guide

**Decisiones cerradas (preguntas abiertas de la sesión anterior):**
- Argon2id params: `t=3, m=64 MiB, p=4` como default (OWASP 2024 mid) — overrideable a 128 MiB vía env. Razón: balance entre starter-tier containers (1 GB RAM) y enterprise-tier. No usar 128 MiB por defecto degrada latencia de login en starters.
- TOTP secrets se cifran con envelope desde 10.b (no diferido a 10.f). Backend dual: `local` para dev (Fernet+HKDF), `kms` para prod (GenerateDataKey con EncryptionContext=AAD). Production validator en Settings rechaza `backend=local` cuando `env=production`.

**Delta vs plan original:** + `User.password_algo` column (track algo per-row para migrations entre hashing algos), + partial unique index en `invitation_token_hash` (solo no-NULL), + `Session.rotated_to_session_id` FK (chain-linking para forensics), + `Session.sequence` BigInt (replay detection), + `burn_equivalent_time()` para timing parity en login, + HIBP fails-open en network errors (no bloquea registros si upstream caído).

**Objetivo:** entidad User de verdad, hashing moderno, 2FA, sessions, pertenencia tenant (un user puede estar en varios tenants con roles distintos).

**Modelo de datos:**
```sql
CREATE TABLE users (
    user_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email          CITEXT UNIQUE NOT NULL,
    password_hash  TEXT,                            -- null si SSO-only
    password_algo  TEXT NOT NULL DEFAULT 'argon2id',
    totp_secret_encrypted BYTEA,                    -- envelope encrypted (KMS)
    totp_enabled   BOOLEAN NOT NULL DEFAULT FALSE,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    status         TEXT NOT NULL DEFAULT 'active',  -- active | locked | deleted
    failed_logins  SMALLINT NOT NULL DEFAULT 0,
    locked_until   TIMESTAMPTZ,
    last_login_at  TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE tenant_memberships (
    tenant_id      TEXT NOT NULL REFERENCES tenants(tenant_id),
    user_id        UUID NOT NULL REFERENCES users(user_id),
    invited_by     UUID REFERENCES users(user_id),
    invited_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    joined_at     TIMESTAMPTZ,
    status         TEXT NOT NULL DEFAULT 'active',  -- invited | active | suspended
    PRIMARY KEY (tenant_id, user_id)
);

CREATE TABLE sessions (
    session_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(user_id),
    tenant_id      TEXT NOT NULL REFERENCES tenants(tenant_id),
    refresh_token_hash BYTEA NOT NULL,              -- SHA-256 del refresh token (no el token crudo)
    user_agent     TEXT,
    ip_address     INET,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at     TIMESTAMPTZ NOT NULL,
    revoked_at     TIMESTAMPTZ
);
```

**Decisiones de seguridad:**
| Ítem | Elegido | Razón |
|---|---|---|
| Password hash | **Argon2id** (argon2-cffi), `time_cost=3, memory_cost=64 MiB, parallelism=4` | OWASP 2024 recommendation; bcrypt no resiste GPUs modernas |
| TOTP | `pyotp` + secret de 160 bits envelope-encriptado con KMS | RFC 6238 estándar, compatible con Authenticator apps |
| Password policy | min 12 chars, zxcvbn score ≥ 3, HIBP check async | balance usabilidad/seguridad |
| Lockout | 5 fallos = lock 15min, 10 fallos = lock 1h, 20 = lock indefinido | defensa contra brute-force |
| Refresh tokens | 64 bytes random, hash SHA-256 en DB, rotación en cada uso | limita ventana si BD se compromete |
| Sesión | 24h inactividad / 30d max | balance ergonomía/seguridad para enterprise |

**Criterios de aceptación:**
- Test: password hash re-verifica con `argon2.PasswordHasher.verify`
- Test: `needs_rehash()` detecta parámetros viejos y re-hashea en login
- Test: TOTP genera código compatible con Google Authenticator
- Test: refresh token no puede reusarse (rotación obligatoria)
- Test: 5 fallos consecutivos bloquea la cuenta

---

### 10.c — RBAC Production-Grade

**Estado:** ✅ Completo (2026-04-21) — **Depende de:** 10.a, 10.b

**Shipped commits (axon-enterprise):**
- `c8b1010` feat(fase-10.c): PrincipalContext — authenticated actor propagation
- `16c89c1` feat(fase-10.c): RBAC production-grade — persisted, hierarchical, tenant-scoped
- `a1bc247` test(fase-10.c): unit + integration suite for RBAC production
- `c8e21b2` docs(fase-10.c): rewrite RBAC.md for the production-grade subsystem

**Archivos producidos:**
- `axon_enterprise/identity/principal.py` — `PrincipalContext` + `CURRENT_PRINCIPAL` ContextVar
- `axon_enterprise/rbac/{__init__.py, models.py, service.py, permissions.py, seed.py, enforce.py, errors.py}` — reemplazo completo del scaffolding v1.0.0
- `alembic/versions/20260421_0200_003_rbac_production.py` — 4 tablas + seed del catalog + RLS completo
- `tests/rbac/{test_permissions_catalog.py, test_service_integration.py, test_enforce.py}` — 29 casos (13 unit + 16 integration)
- `docs/RBAC.md` — rewrite completo con diagrama + SQL del CTE + guard rails

**Decisiones cerradas (preguntas abiertas de la sesión anterior):**
- **Catálogo exacto**: 32 permissions en 8 resources (tenant/user/role/flow/secret/audit/metering/observability). Seeded por migration 003 con `INSERT ... ON CONFLICT DO NOTHING` — agregar permissions es una migration nueva.
- **Rol owner**: creado per-tenant con TODOS los permissions (no un wildcard — enumerar explícitamente sobrevive additions al catálogo y hace auditorías determinísticas). Owner del tenant obtiene este rol en provisioning.
- **Granularidad de `flow:execute`**: coarse (por resource, no por flow individual). Si un tenant necesita per-flow scoping, se agrega `scope_pattern` column en role_permissions en una sub-fase futura; por ahora la granularidad actual cubre el 95% de los casos enterprise sin over-engineering.

**Delta vs plan original:** + `BuiltInRoleProtected` error type para prevenir delete de roles built-in, + `grant_permissions` bulk method con backfill (idempotent re-seed tras agregar permissions al catalog), + `require_permission` decorator parsea at decoration time (typos fallan at import, no at request), + `_assert_no_cycle` walk explícito además de la confianza en `UNION` del CTE (mejor error message y fail-fast en write path), + `parent_role_id` self-FK con `ON DELETE SET NULL` (borrar un parent no destruye los children).

**Objetivo:** reemplazar el RBAC in-memory de v1.0.0 por uno persistente, tenant-scoped, con jerarquía recursiva real y middleware que enforza permisos.

**Modelo:**
```sql
CREATE TABLE roles (
    role_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      TEXT NOT NULL REFERENCES tenants(tenant_id),  -- scoping crítico
    name           TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    is_built_in    BOOLEAN NOT NULL DEFAULT FALSE,
    parent_role_id UUID REFERENCES roles(role_id),               -- jerarquía recursiva
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, name)
);

CREATE TABLE permissions (
    permission_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource       TEXT NOT NULL,      -- "flow", "secret", "audit", "tenant", ...
    action         TEXT NOT NULL,      -- "read", "create", "delete", "execute", ...
    description    TEXT NOT NULL DEFAULT '',
    is_system      BOOLEAN NOT NULL DEFAULT FALSE,               -- seedeada por el sistema
    UNIQUE (resource, action)
);

CREATE TABLE role_permissions (
    role_id        UUID NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    permission_id  UUID NOT NULL REFERENCES permissions(permission_id),
    granted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE user_roles (
    user_id        UUID NOT NULL REFERENCES users(user_id),
    role_id        UUID NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    tenant_id      TEXT NOT NULL REFERENCES tenants(tenant_id),  -- denormalized para RLS
    assigned_by    UUID REFERENCES users(user_id),
    assigned_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id, tenant_id)
);
```

**Catálogo de permisos del sistema (seed):**

| Resource | Actions |
|---|---|
| `tenant` | `read`, `update`, `delete`, `suspend` |
| `user` | `invite`, `read`, `update`, `deactivate`, `impersonate` |
| `role` | `create`, `read`, `update`, `delete`, `assign` |
| `flow` | `create`, `read`, `update`, `delete`, `execute`, `deploy` |
| `secret` | `list`, `read`, `write`, `delete`, `rotate` |
| `audit` | `read`, `export` |
| `metering` | `read`, `export_invoice` |
| `observability` | `read_metrics`, `read_logs`, `read_traces` |

**Roles built-in (seed por tenant al crear):**
- `owner` → todos los permissions
- `admin` → todo excepto `tenant:delete`, `tenant:suspend`, `user:impersonate`
- `developer` → `flow:*`, `secret:read` (solo por ahora), `audit:read`, `observability:*`, `metering:read`
- `viewer` → solo `*:read` del resource

**Enforcement:**
- Decorator `@require_permission("secret:write")` para handlers HTTP
- Helper `rbac.check(user, tenant, "resource:action")` devuelve bool
- Resolución de permisos efectivos con **CTE recursiva en Postgres** — la jerarquía se resuelve en BD, no en Python (evita N+1 + walk infinito):
```sql
WITH RECURSIVE role_tree AS (
    SELECT role_id, parent_role_id FROM roles WHERE role_id = $1
    UNION
    SELECT r.role_id, r.parent_role_id FROM roles r JOIN role_tree rt ON r.role_id = rt.parent_role_id
)
SELECT DISTINCT p.resource, p.action FROM role_tree rt
  JOIN role_permissions rp ON rp.role_id = rt.role_id
  JOIN permissions p ON p.permission_id = rp.permission_id;
```

---

### 10.d — SSO Real (OIDC + SAML)

**Estado:** ✅ Completo (2026-04-21) — **Depende de:** 10.b, 10.c

**Shipped commits (axon-enterprise):**
- `3a849f7` feat(fase-10.d): SSO foundation — settings, errors, models, config store
- `ab2b1b2` feat(fase-10.d): OIDC + SAML providers + SsoService orchestrator
- `89b5e77` test(fase-10.d): unit + integration suite for SSO
- `591a5a8` docs(fase-10.d): rewrite SSO.md for the production-grade subsystem

**Archivos producidos:**
- `axon_enterprise/sso/{__init__.py, errors.py, models.py, configurations.py, state.py, rate_limit.py, mapper.py, service.py, saml_metadata.py}` — fundación + orquestador
- `axon_enterprise/sso/oidc.py` (rewrite) + `oidc_pkce.py`, `oidc_discovery.py`, `oidc_jwks.py`, `oidc_id_token.py` — OIDC completo
- `axon_enterprise/sso/saml.py` (rewrite) — python3-saml wrapper con replay defence
- `axon_enterprise/sso/oauth.py` **eliminado** (out of scope)
- `axon_enterprise/config/settings.py` extendido con `SsoSettings`
- `alembic/versions/20260421_0300_004_sso_configurations.py` — 3 tablas con RLS
- `tests/sso/{test_pkce, test_id_token, test_saml_metadata, test_rate_limit, test_config_integration}.py` — 34 casos (27 unit + 7 integration)
- `docs/SSO.md` rewrite completo con reveal-to-client matrix

**Decisiones cerradas (preguntas abiertas de la sesión anterior):**
- OIDC + SAML shippeados **juntos** en 10.d (no iterativo). SAML delega a python3-saml con lazy import — xmlsec no requerido en dev.
- `sso_configurations.config_encrypted` usa envelope del 10.b con AAD `{tenant_id, provider_type, purpose=sso_config}` — cohesivo con el patrón existente de TOTP secrets.
- `auto_provision_default=true` + rate limit 30/min/`(tenant, provider)` via `InMemoryRateLimiter`. Swap a Redis en 10.i cuando multi-replica.

**Delta vs plan original:** + `SsoAssertionSeen` tabla dedicada (UNIQUE constraint-based replay defence vs check-then-insert race), + `oidc_discovery` con stampede protection (asyncio.Lock + in-flight futures dedup), + `oidc_jwks` con force-refresh-on-kid-miss + `Cache-Control: no-cache` bypass, + `saml_metadata.py` pure-Python (no xmlsec en metadata time), + `role_map` additive-only (admin-granted roles sobreviven SSO login — strict mode diferido), + reveal-to-client matrix explícito en errors para que HTTP middleware no leakee info por timing/message distinction.

**Objetivo:** reemplazar los `return None` de v1.0.0 con SSO federado real. Soporta OIDC (Google Workspace, Azure AD, Okta) y SAML 2.0 (enterprise IdPs).

**OIDC — implementación completa:**
- Discovery: fetch y cache de `/.well-known/openid-configuration` (TTL 1h)
- State + nonce: generados con `secrets.token_urlsafe(32)`, persistidos por 10min, **binding a session cookie**
- Authorization URL con PKCE (S256 challenge, mandatorio para public clients)
- Token exchange + validación de ID token:
  - Firma: RS256/ES256 contra JWKS del issuer (cache con rotación forzada en kid miss)
  - Claims: `iss`, `aud`, `exp`, `nbf`, `iat`, `nonce` (match con el guardado)
  - Verificación de `email_verified=true`
- Mapping: `email` del ID token → upsert de `User`, creación de `TenantMembership` si acepta invite

**SAML 2.0 — implementación completa:**
- Metadata: `SPMetadata` generado + served en `/sso/saml/{tenant_id}/metadata.xml`
- AuthnRequest firmado con cert per-tenant (KMS-backed)
- Response validation via `python3-saml` (librería de OneLogin, auditada):
  - Firma XML (signed assertion y signed response)
  - Destination URL match
  - InResponseTo match con request emitido
  - NotBefore / NotOnOrAfter ventana
  - Audience restriction
- Mapping de atributos configurable per-tenant en tabla `sso_configurations`

**Tabla `sso_configurations`:**
```sql
CREATE TABLE sso_configurations (
    tenant_id      TEXT PRIMARY KEY REFERENCES tenants(tenant_id),
    provider_type  TEXT NOT NULL,                    -- 'oidc' | 'saml'
    config_encrypted BYTEA NOT NULL,                 -- envelope encrypted (KMS)
    attribute_map  JSONB NOT NULL DEFAULT '{}',
    auto_provision BOOLEAN NOT NULL DEFAULT FALSE,   -- crear user en primer login
    default_role_id UUID REFERENCES roles(role_id),  -- rol asignado si auto_provision
    enabled        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Criterios de aceptación:**
- Test E2E con mock OIDC server (custom, sin depender de IdP externo)
- Test: JWT con firma inválida es rechazado
- Test: nonce replay es rechazado
- Test: PKCE verifier mismatch es rechazado
- Test SAML: assertion sin firma es rechazada
- Test SAML: replay de assertion (misma `ID`) es rechazado

---

### 10.e — JWT Issuer + JWKS rotation

**Estado:** ✅ Completo (2026-04-21) — **Depende de:** 10.b, 10.d

**Shipped commits:**
- `axon-enterprise` `2743633` feat(fase-10.e): JwtIssuer + JWKS rotation + revocation
- `axon-enterprise` `514215b` test+docs(fase-10.e): unit + integration + JWT.md guide
- `axon-lang`  `ae44d44` feat(runtime): JWT signature verification — closes §Fase 10.e gap

**Archivos producidos (Python / axon-enterprise):**
- `axon_enterprise/jwt_issuer/{__init__.py, errors.py, models.py, signer.py, local_signer.py, kms_signer.py, key_management.py, jwks.py, issuer.py, revocation.py}`
- `axon_enterprise/config/settings.py` extendido con `JwtSettings` + production validator
- `alembic/versions/20260421_0400_005_jwt_signing_keys.py` — tablas + partial unique index one-active
- `tests/jwt_issuer/{test_local_signer, test_integration}.py` — 14 casos (7 unit + 7 integration)
- `docs/JWT.md` — operator guide

**Archivos producidos (Rust / axon-lang):**
- `axon-rs/src/jwt_verifier.rs` — JwtVerifier + JwksClient con cache TTL + rotation-on-miss
- `axon-rs/src/lib.rs` — módulo registrado
- `axon-rs/src/tenant.rs` — middleware ahora prefiere verified-JWT sobre X-Tenant-ID cuando `AXON_JWT_JWKS_URL` está set
- `axon-rs/Cargo.toml` + jsonwebtoken=9

**Decisiones cerradas (preguntas abiertas de la sesión anterior):**
- **Una sola llave KMS compartida entre tenants** — simplicidad operativa + clientes no necesitan pull-kid-por-tenant. Rotación c/90d mitiga el all-or-nothing revocation.
- **`kid` = SHA-256(SPKI DER)[:16]** (UUID-like opaque, 16 hex chars) — no revela cadencia de rotación ni creation time.
- **Redis para blacklist con Postgres fallback** — Redis para reads rápidos del verifier; Postgres siempre escribe (durabilidad). `is_revoked()` fail-closed: outage de Redis → fallthrough a Postgres, nunca silently permit.

**Delta vs plan original:** + Partial unique index `uq_jwt_signing_keys_one_active` (invariante "one active key" enforced at DB level, no a nivel de aplicación), + reserved-claims overwrite en `JwtIssuer.mint` (callers no pueden silently impersonar tenants via `extra_claims`), + `enforce` flag en Rust verifier (deployments pre-10.e siguen funcionando con legacy path; enterprise flip a enforce=true vía env var), + local + KMS signer comparten mismo kid derivation (migrar entre backends no rota el kid), + `JwksClient` del Rust reutiliza el patrón de 10.d OIDC (TTL + force-refresh-on-miss).

**Objetivo:** cierra el gap actual en `axon-rs/src/tenant.rs` donde el JWT se lee **sin verificar firma** (línea 100 de ese archivo: `Extracts tenant_id from a JWT payload without signature verification`). Emite JWTs firmados por Python, verificados por Rust contra JWKS público.

**Implementación:**
- Firma **RS256** (NO HS256 — asimétrica para que Rust verifique sin compartir secreto)
- Llave privada en **AWS KMS** (nunca sale del HSM); firma vía `kms:Sign` API
- Dos llaves activas rotadas cada 90 días; período de gracia 7 días donde ambas son válidas
- JWKS público servido en `/.well-known/jwks.json` con las **dos** `kid` activas
- Claims:
  ```json
  {
    "iss": "https://auth.bemarking.com",
    "sub": "user:{user_id}",
    "tenant_id": "{tenant_id}",      // consumido por Rust TenantExtractor
    "plan": "enterprise",
    "roles": ["admin", "developer"],
    "aud": "axon-api",
    "exp": 1234567890,
    "iat": 1234567880,
    "nbf": 1234567880,
    "jti": "{uuid}"
  }
  ```
- Revocación: `jti` blacklist en Redis (TTL = remaining exp)

**Cambios en axon-rs:**
- Añadir verificación de firma en `tenant_extractor_middleware` — fetchea JWKS (cache 10min), valida `iss`, `aud`, `exp`, firma
- La verificación es **obligatoria** cuando `ENFORCE_JWT_VERIFICATION=true` (default en prod)
- Mantener el modo legacy (solo extracción) para tests y dev con flag explícito

**Criterios:**
- Test: JWT firmado con kid rotada (pero dentro de la ventana de gracia) pasa
- Test: JWT con firma forjada (`alg=none`) es rechazado
- Test: JWT expirado es rechazado
- Test: JWT con `jti` en blacklist es rechazado
- Test end-to-end: Python emite → Rust verifica → handler recibe tenant_id

---

### 10.f — Secrets Service

**Estado:** ⏳ Pendiente — **Depende de:** 10.c

**Objetivo:** API REST para que el owner de cada tenant gestione sus secretos (API keys, webhooks, etc.) con audit completo, sin que nunca toquen BD en plaintext.

**API:**
```
POST   /api/v1/tenants/{tenant_id}/secrets
         Body: {"key": "openai_api_key", "value": "sk-...", "description": "..."}
         Permiso requerido: secret:write
         Acción: escribe a AWS SM path axon/tenants/{tenant_id}/openai_api_key
         Respuesta: 201 + { key, version_id, created_at } (value NO se retorna)

GET    /api/v1/tenants/{tenant_id}/secrets
         Permiso: secret:list
         Respuesta: [{ key, description, last_rotated_at, created_by }]
         (nunca retorna el value)

GET    /api/v1/tenants/{tenant_id}/secrets/{key}
         Permiso: secret:read
         Respuesta: 200 + { key, value, version_id }
         Auditoría: emite 'config:secret_access' antes de retornar

DELETE /api/v1/tenants/{tenant_id}/secrets/{key}
         Permiso: secret:delete
         Acción: schedule_deletion en AWS SM (7 días de ventana)

POST   /api/v1/tenants/{tenant_id}/secrets/{key}/rotate
         Permiso: secret:rotate
         Acción: nueva versión + versión anterior marcada AWSPREVIOUS
```

**Tabla metadata (los values viven en AWS SM, no en BD):**
```sql
CREATE TABLE tenant_secrets (
    tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id),
    key             TEXT NOT NULL,                                 -- "openai_api_key"
    aws_sm_arn      TEXT NOT NULL,                                 -- ARN para auditoría
    current_version TEXT NOT NULL,                                 -- AWSCURRENT version id
    description     TEXT NOT NULL DEFAULT '',
    created_by      UUID NOT NULL REFERENCES users(user_id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_rotated_at TIMESTAMPTZ,
    last_accessed_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, key)
);
```

**Decisiones:**
| Decisión | Elegido | Razón |
|---|---|---|
| Backend | AWS Secrets Manager (reutiliza M3) | ya provisionado por Terraform, Rust ya lo lee |
| Path convention | `axon/tenants/{id}/{key}` (sin cambios de M3) | evita dual code path |
| Caching | No en Python (cliente pega directo a AWS SM) | el caching de 5min vive en Rust `TenantSecretsClient` para lectura en runtime |
| Versioning | AWS SM nativo (`AWSCURRENT` / `AWSPREVIOUS`) | rollback en 1 API call |
| Audit | Emite `config:secret_access` en GET; `config:secret_write` en POST/rotate | siempre con user_id, tenant_id, key name (nunca value) |

---

### 10.g — Audit Hash-Chain

**Estado:** ⏳ Pendiente — **Depende de:** 10.a

**Objetivo:** audit log append-only con hash chain tamper-evident, stitched al `provenance_chain` que ya existe en ESK (axon-lang). Ningún evento puede ser modificado o borrado sin quebrar la cadena.

**Modelo:**
```sql
CREATE TABLE audit_events (
    event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id),
    event_type      TEXT NOT NULL,                 -- 'auth:login', 'secret:write', ...
    actor_user_id   UUID REFERENCES users(user_id),
    actor_email     TEXT,
    resource_type   TEXT NOT NULL,
    resource_id     TEXT,
    action          TEXT NOT NULL,
    status          TEXT NOT NULL,                 -- 'success' | 'failure' | 'denied'
    ip_address      INET,
    user_agent      TEXT,
    details         JSONB NOT NULL DEFAULT '{}',
    -- Hash chain
    prev_hash       BYTEA NOT NULL,                -- SHA-256 del evento anterior del tenant
    event_hash      BYTEA NOT NULL,                -- SHA-256 de este evento (incluye prev_hash)
    sequence_number BIGINT NOT NULL,               -- monotónico por tenant
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, sequence_number)
);

-- Append-only enforcement vía trigger
CREATE OR REPLACE FUNCTION audit_events_no_update_delete() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_events_prevent_update BEFORE UPDATE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_no_update_delete();

CREATE TRIGGER audit_events_prevent_delete BEFORE DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_no_update_delete();

-- Solo superuser puede bypass (para retención programada, auditada por CloudTrail)
```

**Hash computation:**
```python
event_hash = sha256(
    prev_hash
    || tenant_id
    || sequence_number.to_bytes(8, "big")
    || event_type
    || canonical_json({actor_user_id, resource_id, action, status, details, timestamp})
)
```

El primer evento de cada tenant usa `prev_hash = sha256(b"GENESIS:" + tenant_id)` (genesis determinístico).

**Stitch con ESK provenance_chain:**
Cuando se emite un evento crítico (`secret:write`, `tenant:delete`, `compliance:export`), también se registra una entrada en el `provenance_chain` del runtime ESK (axon-lang). El `event_hash` aquí y el `entry_hash` allá se referencian mutuamente — doble garantía para compliance SOC 2 / ISO 27001.

**Emisión automática:**
Cada servicio (TenantService, UserService, SecretsService, RBACService) toma un `AuditService` como dependency y emite el evento correspondiente en cada mutation.

**Verificación de integridad:**
`axon-enterprise audit verify --tenant {id}` recalcula la cadena entera y reporta cualquier divergencia. Se corre como cronjob diario.

---

### 10.h — Metering + Quota Enforcement

**Estado:** ⏳ Pendiente — **Depende de:** 10.a

**Objetivo:** metering real (con tenant_id, no organization_id), pricing plans, integración Stripe, y **enforcement** (rate limiting, not just tracking).

**Modelo:**
```sql
CREATE TABLE pricing_plans (
    plan_id         TEXT PRIMARY KEY,              -- 'starter' | 'pro' | 'enterprise'
    display_name    TEXT NOT NULL,
    monthly_base_cents INT NOT NULL,
    included_executions BIGINT NOT NULL,
    included_tokens BIGINT NOT NULL,
    included_storage_gb INT NOT NULL,
    overage_per_execution_cents INT NOT NULL,
    overage_per_1k_tokens_cents INT NOT NULL,
    overage_per_gb_storage_cents INT NOT NULL,
    rate_limit_rpm  INT NOT NULL,                   -- requests/min
    rate_limit_tpd  BIGINT NOT NULL,                -- tokens/day
    active          BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE usage_events (
    usage_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id),
    metric_type     TEXT NOT NULL,
    quantity        DOUBLE PRECISION NOT NULL,
    unit            TEXT NOT NULL,
    flow_id         UUID,
    provider        TEXT,                           -- 'anthropic' | 'openai' | ...
    metadata        JSONB NOT NULL DEFAULT '{}',
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON usage_events (tenant_id, recorded_at);

CREATE TABLE invoices (
    invoice_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id),
    period_start    TIMESTAMPTZ NOT NULL,
    period_end      TIMESTAMPTZ NOT NULL,
    line_items      JSONB NOT NULL,
    subtotal_cents  INT NOT NULL,
    tax_cents       INT NOT NULL,
    total_cents     INT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'draft',  -- draft | finalized | paid | void
    stripe_invoice_id TEXT,
    issued_at       TIMESTAMPTZ,
    due_at          TIMESTAMPTZ,
    paid_at         TIMESTAMPTZ
);
```

**Quota enforcement (rate limit):**
- Redis-based sliding window counter per `(tenant_id, metric)` con TTL = ventana
- En la request path (Rust) o en GraphQL/REST gateway (Python): si `current_count > limit`, retorna `429 Too Many Requests` con headers `X-RateLimit-*` + `Retry-After`
- Overages: **no bloquean**, se acumulan en `usage_events` y se facturan como overage al fin de período (salvo que el plan sea `hard_cap=true`)

**Stripe integration:**
- Webhook receiver en `/webhooks/stripe` — valida firma, procesa `invoice.payment_succeeded`, `customer.subscription.updated`
- `StripeService.issue_invoice(tenant, period)` crea el invoice en Stripe con line items por metric
- `StripeService.suspend_on_delinquency(tenant)` marca el tenant como `status='suspended'` si 3 facturas sin pagar; el Rust lo rechaza en el extractor

---

### 10.i — Observability Wiring

**Estado:** ⏳ Pendiente — **Depende de:** 10.a

**Objetivo:** cerrar los `# TODO: Send to metrics backend` de v1.0.0. Prometheus + OpenTelemetry + structured logs, todo con `tenant_id` como dimensión.

**Prometheus:**
- `/metrics` endpoint en el Python service, usando `prometheus_client.CollectorRegistry`
- Métricas base: `axon_requests_total{tenant,method,status}`, `axon_request_duration_seconds{tenant,endpoint}` (histogram), `axon_flows_executed_total{tenant,status}`, `axon_llm_tokens_total{tenant,provider}`, `axon_quota_hit_total{tenant,metric}`
- ServiceMonitor K8s manifest para scraping

**OpenTelemetry:**
- `opentelemetry-instrumentation-starlette` + `-sqlalchemy` + `-asyncpg` + `-httpx`
- `tenant_id` en **baggage** (propaga a spans hijos automáticamente)
- OTLP exporter hacia collector (configurable: Datadog, Grafana Cloud, Jaeger)
- Sampling tail-based para traces de error (100%) y success (10%)

**Structured logs:**
- `structlog` con JSON renderer
- Contextvars auto-injection: `tenant_id`, `user_id`, `request_id`, `trace_id`
- Niveles: `DEBUG` (dev only), `INFO` (default), `WARNING`, `ERROR`, `CRITICAL`
- Redacción automática de valores marcados `Secret[str]` (no leakea en logs)

---

### 10.j — Admin API + CLI

**Estado:** ⏳ Pendiente — **Depende de:** 10.b, 10.c, 10.f, 10.g

**Objetivo:** superficie administrativa para operators (internal) y tenant owners (external).

**Admin API — interno (protegido por mTLS o IP allowlist):**
```
POST   /admin/tenants              crear tenant + provisionar KMS + crear owner user
GET    /admin/tenants              listar todos los tenants (con filtros)
GET    /admin/tenants/{id}         detalle (uso, plan, status, owner)
PATCH  /admin/tenants/{id}         update (plan, status, name)
POST   /admin/tenants/{id}/suspend suspender (trigger manual de deuda, violación ToS)
POST   /admin/tenants/{id}/resume  reactivar
DELETE /admin/tenants/{id}         schedule deletion (retención 30d, luego purge)
POST   /admin/tenants/{id}/impersonate  genera JWT one-shot para soporte (auditado!)
GET    /admin/usage/metrics        system-wide metering
GET    /admin/audit/events         cross-tenant audit (para compliance interno)
```

**Admin CLI (`axon-enterprise` command):**
```bash
axon-enterprise tenant create --slug acme --plan enterprise --owner-email admin@acme.com
axon-enterprise tenant list --status active
axon-enterprise tenant suspend <slug> --reason "payment failed"
axon-enterprise user invite <tenant> --email dev@acme.com --role developer
axon-enterprise secret rotate <tenant> <key> --new-value-from-stdin
axon-enterprise audit verify <tenant>  # recalcula hash chain, reporta integridad
axon-enterprise migrate status         # estado de migraciones Alembic
```

Ambos comparten la misma `AdminService`; el CLI es un wrapper Typer sobre HTTP al Admin API local, o conexión directa a BD si se corre con `AXON_LOCAL_ADMIN=true`.

---

### 10.k — Tenant Self-Service Portal API

**Estado:** ⏳ Pendiente — **Depende de:** 10.c, 10.d, 10.f

**Objetivo:** endpoints para el owner de cada tenant — gestión sin intervención de soporte.

```
POST   /api/v1/tenant/users/invite          invitar usuario (email + rol)
GET    /api/v1/tenant/users                 listar miembros
DELETE /api/v1/tenant/users/{id}            revocar acceso
PATCH  /api/v1/tenant/users/{id}/roles      cambiar roles

GET    /api/v1/tenant/sso                   ver config SSO actual (redacted)
PUT    /api/v1/tenant/sso                   configurar OIDC/SAML
POST   /api/v1/tenant/sso/test              test de conexión contra IdP

GET    /api/v1/tenant/api-keys              listar (sin revelar secret)
POST   /api/v1/tenant/api-keys              crear (secret se retorna UNA vez)
DELETE /api/v1/tenant/api-keys/{id}         revocar

GET    /api/v1/tenant/usage                 dashboard de uso actual período
GET    /api/v1/tenant/invoices              historia de facturas
GET    /api/v1/tenant/invoices/{id}/pdf     PDF del invoice

POST   /api/v1/tenant/compliance/export     GDPR subject access request
POST   /api/v1/tenant/compliance/erase      right-to-erasure request
```

Toda request enforza `tenant_id` del JWT (no se puede cross-tenant aunque se ponga otro `{id}` en URL).

---

### 10.l — Compliance Tooling

**Estado:** ⏳ Pendiente — **Depende de:** 10.a, 10.g

**Objetivo:** cumplir GDPR / CCPA / SOC 2 sin ingeniería custom por cada request.

**GDPR Subject Access Request:**
- `POST /api/v1/tenant/compliance/export` con body `{user_email}` → scheduled job
- Query a todas las tablas con filter `user_id = ?` + `tenant_id` scoping
- Output: ZIP con JSON-per-table + hash chain snippet del audit log del usuario
- SLA: 30 días (GDPR Art. 12), pero típicamente < 1h

**Right to Erasure (Art. 17):**
- `POST /api/v1/tenant/compliance/erase` con body `{user_email, reason}`
- Soft delete inmediato (`user.status = 'erasure_pending'`)
- Background job purga PII después de 7 días (ventana para reversión legal)
- Audit events del usuario NO se borran (necesarios para compliance propio) pero se anonymizan: `user_email → 'erased-{hash}@axon.internal'`

**Data residency:**
- Column `tenants.data_region` ('us-east-1', 'eu-west-1', 'ap-southeast-1')
- Validación en middleware: si tenant.region != current region, redirect 308 al endpoint regional
- Deployment multi-region con Terraform per-región

**SOC 2 evidence:**
- Integración con el `EvidencePackager` que ya existe en ESK
- Endpoint `POST /admin/compliance/evidence-bundle` genera ZIP con: dossier, SBOM, provenance chain snippet, audit events del período, control statements — listo para auditor

---

### 10.m — Testing + Security Audit

**Estado:** ⏳ Pendiente — **Depende de:** 10.a–10.l

**Objetivo:** validar formalmente el aislamiento y resistencia del control plane.

**Cross-tenant isolation tests:**
- Matriz de endpoints × tenants: tenant A hace request a recurso de tenant B → debe devolver 404 (no 403, para evitar leakage de existencia)
- Fuzzing: `hypothesis` con `tenant_id` + payloads arbitrarios
- RLS bypass test: intento manual de `SET axon.current_tenant = 'B'` en sesión autenticada como tenant A

**Load tests:**
- `locust` con 1000 tenants simultáneos, cada uno con 10 users activos
- Escenarios: login flood, secret read burst, metering spike, audit write storm
- Métricas: p50/p99 latency per-tenant, isolation (un tenant saturado no debe degradar a otro)

**Threat model:**
- STRIDE por cada subsistema documentado en `docs/threat_model_axon_enterprise.md`
- Controles mapeados a OWASP ASVS v4 L3
- Pentesting externo (tercero) antes del GA de v1.1.0

**Security audit checklist:**
- [ ] CSP headers, HSTS, secure cookies
- [ ] No password/secret en logs (test con grep + redaction verification)
- [ ] JWT tokens rotados antes de retirarse
- [ ] RLS enabled en TODAS las tablas con `tenant_id`
- [ ] SQL injection fuzzed en cada handler
- [ ] Rate limiting real, no solo métrica
- [ ] Timing attacks: password verification usa `constant_time_compare`

---

## Log de decisiones

Las decisiones tomadas durante la ejecución de Fase 10 se registran aquí con fecha y contexto — para recuperar el estado mental en sesiones futuras.

| Fecha | Decisión | Contexto / alternativas consideradas |
|-------|----------|--------------------------------------|
| 2026-04-21 | Fase 10 se ejecuta en el repo `axon-enterprise` (no en axon-lang) | Separation of concerns: axon-lang es el runtime, axon-enterprise es el control plane comercial. |
| 2026-04-21 | Postgres compartido entre Python (Fase 10) y Rust (M1–M5), una sola BD | Evita dual source of truth. RLS funciona en ambos sentidos. Mismo `axon.current_tenant` GUC. |
| 2026-04-21 | JWTs firmados por Python RS256, verificados por Rust contra JWKS | Cierra el TODO "no signature verification" actual en Rust. KMS mantiene la llave privada en HSM. |
| 2026-04-21 | Audit hash chain stitched a ESK provenance_chain | Doble garantía de tamper-evidence; aprovecha el primitivo ya existente en axon-lang. |
| 2026-04-21 | 10.a: `FORCE ROW LEVEL SECURITY` en cada tabla tenant-scoped | Sin FORCE, el owner de la tabla (axon_app cuando actúe como creador) bypassaría RLS. FORCE aplica la política incluso al owner — defense in depth. |
| 2026-04-21 | 10.a: NULL guard en la policy — `current_setting(..., true) IS NOT NULL` | Un query sin GUC set devuelve 0 filas en lugar de todas. El comportamiento default de `current_setting(.., true)` sin NULL check permitiría `WHERE tenant_id = NULL` que no matchea nada, pero dejar la policy con esa ambigüedad era innecesariamente frágil. |
| 2026-04-21 | 10.a: Alembic usa `NullPool` durante migraciones | Un pool pool-recycle podría descartar la conexión mid-migration y perder `SET LOCAL`. |
| 2026-04-21 | 10.a: `TenantScopedMixin.__tablename__` genera índice compuesto `(tenant_id, created_at)` por defecto | Shape de query más común; mejora perf sin requerir declaración manual en cada modelo. |
| 2026-04-21 | 10.b: Envelope encryption con AAD serialised ordenado por clave | `{"a":"1","b":"2"}` produce byte-idéntico output regardless de dict insertion order — evita bugs si dict ordering cambia entre Python versions. |
| 2026-04-21 | 10.b: `users` table con RLS `FORCE` + `admin_bypass` (sin tenant_isolation) | Tabla global: un user puede estar en N tenants. Service layer enforza "este user pertenece a mi tenant" via `tenant_memberships` bajo `tenant_session`, luego abre `admin_session` para leer el user. RLS sin bypass sería imposible (necesitamos poder leer cross-tenant en paths privilegiados). |
| 2026-04-21 | 10.b: Refresh tokens 64 bytes random → SHA-256 hash persistido | Pérdida de BD no revela refresh tokens (attacker tendría hash sin preimage). SHA-256 (no HMAC) porque el hash no necesita secret-key property — el atacante con hash sigue sin poder forjar un token de 64 bytes. |
| 2026-04-21 | 10.b: Replay detection revoca TODA la chain para `(user_id, tenant_id)` | Si alguien presenta un token ya-rotado, OR es un attacker OR es un cliente legítimo con bug. Revocar ambos (forzando re-login) es el camino seguro — no podemos distinguir who's who sin metadata adicional. |
| 2026-04-21 | 10.b: HIBP k-anonymity con `Add-Padding: true` header + fails-open | Padding mitiga traffic analysis (response size revela hit/miss sin padding). Fails-open porque un outage de HIBP no debe bloquear registros legítimos — trade-off consciente en favor de availability sobre defense-in-depth absoluto. |
| 2026-04-21 | 10.c: `permissions` table es global sin RLS (read-only closed set) | Una tabla tenant-scoped significaría que cada tenant puede inventar permission strings que el código no enforza — security hole. Catalog cerrado ensure strings coinciden con `@require_permission` decorators. |
| 2026-04-21 | 10.c: Denormalized tenant_id en role_permissions + user_roles | Policy RLS puede aplicar directamente sin JOIN. JOIN-en-policy puede causar recursive policy evaluation (policy consulta tabla que tiene su propia policy que consulta la primera) — evitado. |
| 2026-04-21 | 10.c: Owner rol con TODOS los permissions enumerados (no wildcard) | Catalog growth → owner recibe los nuevos permissions automáticamente via re-run del seeder idempotent. Wildcard haría imposible auditar exactamente qué puede hacer owner en un point-in-time. |
| 2026-04-21 | 10.c: `@require_permission("x:y")` parsea at decoration time | Typos fallan at import (handler no se carga) en lugar de at request (handler loads pero nunca matchea). Elimina una clase entera de bugs silenciosos. |
| 2026-04-21 | 10.c: Cycle prevention doble — _assert_no_cycle + UNION en CTE | UNION dedupes cycles en read (queries terminan incluso con cycle smuggled). _assert_no_cycle at write-time da error message explícito ("would create cycle") — fail-fast > fail-silently. Defensa en profundidad. |
| 2026-04-21 | 10.c: BuiltInRoleProtected impide delete/rename de built-in roles | owner/admin/developer/viewer son contratos entre el sistema y los handlers — un handler que dice `@require_permission("tenant:read")` asume que "admin" rol existe y lo tiene. Renombrar o borrar un built-in rompe el contrato. |
| 2026-04-21 | 10.d: SAML replay defence via UNIQUE constraint en BD (no check-then-insert) | Check-then-insert tiene race window (dos requests simultáneos con mismo assertion_id pasan el check, luego uno falla el insert). UNIQUE constraint hace la concurrencia de Postgres hacer el trabajo — atomic by construction. |
| 2026-04-21 | 10.d: OIDC discovery con asyncio.Lock + in-flight futures dedup | N requests al mismo issuer en paralelo disparaban N HTTP fetches sin dedup. Con dedup solo 1 fetch + N coroutines esperan el mismo future. Reduce latencia P99 y carga en el IdP. |
| 2026-04-21 | 10.d: JWKS con force-refresh-on-kid-miss + Cache-Control: no-cache bypass | IdPs rotan llaves publicando la nueva kid minutos antes de usarla. Sin force-refresh, nuestro cache stale rechaza tokens legítimos firmados con kid nuevo. Bypass de Cache-Control es el segundo chance para CDN stale. |
| 2026-04-21 | 10.d: `role_map` es additive-only (no revoca) en SSO login | Admins pueden grantear roles extra out-of-band (ej. promover un user temporalmente). Si SSO login los revocara por no estar en el IdP, eso pisa la decision manual del admin. Strict sync diferido hasta compliance explicita. |
| 2026-04-21 | 10.d: Reveal-to-client matrix explícito en SsoError subclasses | Sin esto, HTTP middleware no sabe cuáles errors son safe to return vs cuáles deben collapsarse a 401 genérico. Leakear "nonce_mismatch" vs "state_invalid" permite a un attacker inferir qué parte del flow es el problema. |
| 2026-04-21 | 10.e: Partial unique index `WHERE status='active'` en jwt_signing_keys | Enforces "one active key" invariant at the DB level. Sin esto, un bug en app code podría insertar dos rows active y el issuer elegiría una arbitrariamente. CHECK constraints no expresan "only one row" — partial unique lo hace. |
| 2026-04-21 | 10.e: Reserved claims overwrite `extra_claims` en JwtIssuer.mint | Sin overwrite, un caller que pase `extra_claims={"tenant_id": "victim"}` silently impersonaría a otro tenant. Defensivo against programmer mistakes — callers pueden querer extend claims pero NUNCA sobrescribir iss/sub/aud/exp/iat/nbf/jti/tenant_id/roles. |
| 2026-04-21 | 10.e: kid = SHA-256(SPKI DER)[:16] compartido entre Local + KMS signer | Migrar operator de local → KMS (o vice-versa) NO rota el kid mientras el public key del KMS sea el mismo. JWTs minted antes de la migration siguen verificando post-migration. Deterministic kid > random. |
| 2026-04-21 | 10.e: Rust verifier con `enforce` flag + fallback legacy path | Pre-10.e deployments (incluyendo OSS/single-tenant) siguen funcionando sin `AXON_JWT_JWKS_URL` set — no breaking change. Enterprise deployments flip enforce=true via env, no code change. Gradual rollout vs hard cutover. |
| 2026-04-21 | 10.e: Redis + Postgres para revocation (fail-closed en Redis down) | Redis solo sería insuficiente: ephemeral, datos perdidos en restart. Postgres solo: too slow en hot path. Ambos: Postgres es source of truth, Redis acelera. Critical: `is_revoked()` falla-closed (Redis down → checa Postgres) — nunca silently permite un token revocado. |

---

## Open questions (a resolver antes de mergear cada sub-fase)

- **10.a:** ¿Connection pool per-tenant (aislamiento fuerte) o pool compartido con RLS (eficiente)? Hoy: pool compartido. Re-evaluar si un tenant saturado afecta p99 de otros.
- **10.d:** ¿Soportar múltiples IdPs por tenant (ej: OIDC + SAML simultáneos)? Hoy: uno por tenant. El DB schema lo soporta pero la UI/API asume uno.
- **10.f:** ¿Permitir per-user secrets (no solo per-tenant)? Caso de uso: el mismo tenant tiene varios devs con LLM accounts personales. Deferred a v1.2.
- **10.h:** ¿Prepaid (hard cap) vs postpaid (overage billed)? Hoy: configurable por plan. Starter = hard_cap, Pro/Enterprise = overage. Revisar después del primer cliente real.
- **10.l:** ¿Right-to-erasure borra audit events? Hoy: anonymize, no borrar. Legal debe confirmar que anonymization cumple Art. 17.

---

## Sesión actual — estado vivo

**Última actualización:** 2026-04-21

**Próxima sesión — pickup point:** arrancar **10.f (Secrets Service)** en el repo `axon-enterprise`.

**Decisiones cerradas en esta sesión (10.e):**
- Una sola llave KMS compartida entre tenants (no per-tenant) — simplicidad ops + rotación c/90d mitiga revocation al por mayor.
- `kid = SHA-256(SPKI DER)[:16]` — opaque, no revela cadencia de rotación.
- Partial unique index `uq_jwt_signing_keys_one_active` — invariante "one active" at DB level, no at app level.
- Redis (fast) + Postgres (durable) para `jti` blacklist; fail-closed en Redis outage.
- Rust verifier en mismo crate axon-rs — jsonwebtoken=9, hand-rolled error enum (no thiserror dep).
- Middleware Rust con `enforce` flag — pre-10.e deployments siguen funcionando (legacy path), enterprise flip via env var.

**Pre-requisitos para 10.f:**
- [x] 10.a + 10.b + 10.c + 10.d + 10.e completados
- [x] Envelope encryption disponible desde 10.b
- [x] M3 del plano Rust (AWS Secrets Manager per-tenant paths) ya implementado
- [x] RBAC con permissions `secret:{list,read,write,delete,rotate}` ya en catalog (10.c)
- [ ] Decidir scope de "secret read": ¿permission granular por secret key (`secret:read:openai_api_key`) o coarse (`secret:read`)? Propongo **coarse para 10.f, granular como feature opt-in**.
- [ ] Decidir retention de versiones AWS SM: default 30d vs 90d. Propongo **90d** — matches compliance windows típicos.
- [ ] Decidir audit event granularity — ¿emitir en CADA `secret:read` o solo en writes? Propongo **ambos** — reads enterprise deben ser auditados (SOC 2 CC.6.1 requires it).

**Sesión abierta en:**
- `axon-enterprise`: commits hasta `514215b` (JWT issuer + tests + docs)
- `axon-lang`:     commit `ae44d44` (Rust JWT verifier)
- Doc vivo actualizado en `axxon-constructor:docs/multi_tenancy_axon.md`

---

## Routing Git para este plan

### M1–M5 (Rust / axon-lang)

Commits en este repo (`axon-lang`), pusheados a ambos remotes:

```bash
git push origin master && git push enterprise master
```

Prefijo: `feat(enterprise): ...` cuando el cambio es enterprise-only; `feat(runtime): ...` cuando aplica al open-source también.

### Fase 10 (Python / axon-enterprise)

Commits en el repo `axon-enterprise` (sibling directory). Subir directo:

```bash
cd ../axon-enterprise
git push origin master
git tag v1.1.0-alpha.X && git push origin v1.1.0-alpha.X    # alpha per sub-fase
git tag v1.1.0 && git push origin v1.1.0                    # GA al terminar 10.m
```

Prefijo: `feat(fase-10.X): ...` donde X es la sub-fase (a, b, c, ...). El tag `v*` dispara el workflow `release.yml` que construye y publica la imagen a ECR (`axon/axon-enterprise:1.1.0`).
