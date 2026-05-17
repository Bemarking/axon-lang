---
title: "Plan vivo: Fase 21 — Integration Surface for axon-enterprise SaaS sabor"
status: SHIPPED 2026-05-07 — 21.a–21.k completas; axon-enterprise v1.8.0 publicado (PR #8 merged en `d9833d1`, tag `v1.8.0` pushed, GitHub Release https://github.com/Bemarking/axon-enterprise/releases/tag/v1.8.0); 79/79 tests verdes en `tests/discovery/`; cero breaking changes (additive only); axon-lang permanece v1.15.0 (no language change)
owner: AXON Enterprise Team
created: 2026-05-06
updated: 2026-05-06
target: axon-enterprise v1.8.0 (separate release; axon-lang permanece en v1.15.0 — esta fase no toca el lenguaje OSS)
depends_on: Fase 20 SHIPPED (Production Shield Runtime + plugin registry maduros; superficie estable que ahora hay que exponer)
---

## ▶ Status snapshot (2026-05-06 — DRAFTED)

| Sub-phase | Status | Tests target | Module(s) / Notes |
|---|---|---|---|
| 21.a OIDC Discovery (`.well-known/openid-configuration`) | ✅ SHIPPED | 9 (8 + 1 bonus) verdes | `axon_enterprise/http/discovery/oidc.py` + mount en `app.py` |
| 21.b OAuth Authorization Server Metadata (RFC 8414) | ✅ SHIPPED | 8 (6 + 2 bonus) verdes | `axon_enterprise/http/discovery/oauth.py` + mount en `app.py` + cross-doc consistency test |
| 21.c Tenant-scoped integration context endpoint | ✅ SHIPPED (v1) | 12/12 verdes | `axon_enterprise/http/api/integration_context.py` + Mount en `build_api_router`; v1 ships static surface (tenant_id, plan, auth params, discovery URLs, version); per-tenant rate_limits / feature_flags / vertical_packs / shield categories quedan deferred a slice 21.c.2 cuando existan los modelos de datos |
| 21.d Capability advertisement (`.well-known/axon-capabilities.json`) | ✅ SHIPPED | 11/11 verdes (10 + 1 bonus) | `axon_enterprise/http/discovery/capabilities.py` + helpers extracted to `discovery/_helpers.py` (also refactored 21.a/b/c to use them); honest probes (axon-lang version via `importlib.metadata`, SSO via `SsoProviderType` enum, Shield via `axon.runtime.shield_scanners.default_registry.known()`); fields → `null` on probe failure |
| 21.e OpenAPI 3.x publication (`/openapi.json` + `/docs` + `/redoc`) | ✅ SHIPPED | 8/8 verdes (5 target + 3 bonus) | `axon_enterprise/http/discovery/openapi.py` + `docs_ui.py`; **hand-built spec** (Starlette no auto-genera, sin agregar FastAPI/apispec dep); full schemas para 5 endpoints Fase 21 + tag stubs para Auth/SSO/Tenant/Webhooks/Admin; Swagger UI + ReDoc desde CDN unpkg/jsdelivr (versiones pinneadas); negative test "endpoints públicos NO declaran security" para evitar SDK auth-injection accidental |
| 21.f Health/status surface formalization | ✅ SHIPPED | 6/6 verdes | `axon_enterprise/http/discovery/version.py` + mounts en `app.py`; **`/livez` = alias mount del mismo handler que `/healthz`** (k8s-modern naming sin duplicar lógica — comment explicando por qué); `/version` nuevo con `axon_enterprise_version`, `axon_lang_installed_version`, `python_version`, `build_sha` (env var), `build_date` (env var); regression tests para `/healthz`; readyz no testado unit (necesita DB live, lo cubre integration suite preexistente) |
| 21.g Drift gate: discovery ≡ reality | ✅ SHIPPED | 9/9 verdes (7 target + 2 bonus) | `tests/discovery/test_discovery_drift_gate.py` (nuevo, 9 tests pure-builder, sin HTTP/DB); chequea: OpenAPI documenta cada Fase 21 path, `$ref` integrity + zero orphan schemas, OIDC ⇄ OAuth shared fields byte-identical, capabilities ⇄ Shield registry exact match, capabilities ⇄ SsoProviderType enum, capabilities.discovery_endpoints ⇄ published well-known set, **no internal leakage** (ALB/S3/internal env strings) en ninguno de los 5 docs públicos, schema_versions semver-shaped, axon-lang version coherente entre capabilities + version |
| 21.h Observability: discovery hits + integration patterns | ✅ SHIPPED | 6/6 verdes (4 target + 2 bonus) | `axon_enterprise/http/discovery/observability.py` (3 Prom metrics en `default_registry`, 2 wrapper decorators, UA classifier, IP /24 anonymizer); wrappers aplicados a los 6 discovery routes en `app.py` + integration_context route; **privacy discipline verificada**: test confirma que raw UA, full IP, y bearer tokens NUNCA aparecen en logs; tests cubren happy path + 304 status differentiation + UA classifier 12 cases + IP /24 v4 + /48 v6 |
| 21.i Adopter Integration Guide (`docs/INTEGRATION_GUIDE.md`) | ✅ SHIPPED | doc-only | `axon-enterprise/docs/INTEGRATION_GUIDE.md` nuevo (~280 líneas, 11 secciones: TL;DR + bootstrap + auth + integration-context + capabilities + health + cache + ETag + endpoint reference + versioning + where-to-ask); cross-link agregado al top de `docs/PORTAL_API.md`; ejemplos curl + Python (PyJWT, httpx); **single env var contract** explícitamente documentado; sección "What we deliberately do not expose" recodifica la lección "no kitchen door" en doc-form |
| 21.j Contract tests adopter↔server (golden vectors) | ✅ SHIPPED | 10/10 verdes (8 target + 2 bonus) | `tests/discovery/test_discovery_contracts.py` + 6 goldens checked-in en `tests/discovery/golden/`; **6 snapshot tests** (OIDC/OAuth/capabilities/openapi/version/integration-context) con normalización de volátiles (`axon_enterprise_version`, `axon_lang_installed_version`, `python_version`, `build_sha`/`build_date`, `info.version`); **3 schema-compliance tests** (`openapi-spec-validator` valida 3.1.0 oficial; `jsonschema` valida OIDC + RFC 8414 mandatory fields); **third-party parse compat** con `authlib.AuthorizationServerMetadata.validate()`; auto-create-on-missing pattern: golden no existe → primer run lo crea + skip; runs siguientes comparan; regen deliberado vía `rm <golden> && pytest`; `pyproject.toml [dev]` actualizado con jsonschema + openapi-spec-validator + authlib |
| 21.k Coordinated v1.8.0 release commit + tag | ✅ SHIPPED | release | branch `release/enterprise-v1.8.0` → commit `7f4df36` (+5036/-5 across 33 files) → PR #8 merged (`d9833d1` merge commit en master) → tag annotated `v1.8.0` creado en merge commit + pushed → GitHub Release https://github.com/Bemarking/axon-enterprise/releases/tag/v1.8.0 publicado con notas completas; remote branch auto-deleted vía `gh pr merge --delete-branch`; local back to master en sync |

**Acceptance metrics target:**

- **≥66 nuevos tests** distribuidos: 8 OIDC + 6 OAuth + 12 tenant context + 10 capabilities + 5 openapi + 6 health + 7 drift + 4 obs + 8 contract.
- **`.well-known/openid-configuration` parseable por cualquier librería OIDC standard** (validado contra `jwt`, `authlib`, `oidc-client-js` en tests de contrato).
- **Drift gate falla** si el discovery doc declara endpoints/issuer/audience/jwks_uri que no coinciden con la app real montada.
- **Adopter Integration Guide** documenta el flujo end-to-end en ≤2 pantallas: el adopter setea **una** env var (`AXON_API_BASE`), llama discovery en boot, y obtiene todo el resto.
- **Cero filtración de internals** en el doc público: no aparecen ALB hostnames, S3 bucket names, ni nombres de environment internos. Lo público es público (issuer, audience, jwks_uri vía DNS estable); lo interno permanece interno.
- **OSS / ENTERPRISE / SPLIT classification honored**: todas las sub-fases son **ENTERPRISE-only** porque axon-lang OSS no tiene HTTP surface que exponer. La consistencia con el charter se valida en CI.

## How to apply (post-SHIPPED)

Cuando el usuario o un adopter pregunte "¿cómo me integro con axon-enterprise?", "¿dónde está el JWKS?", "¿cuál es el audience de mi tenant?", "¿qué primitivas tengo disponibles en mi instalación?" — la respuesta es: **leé `https://<axon-base>/.well-known/openid-configuration` y `/.well-known/axon-capabilities.json` desde tu cliente. Tu único secret de configuración es `AXON_API_BASE`. Lo demás se descubre.** Esta fase elimina cualquier handover de valores hardcoded entre Bemarking y un adopter para integración. Para introspección post-auth (rate limits, primitivas habilitadas, retención de audit), `GET /api/v1/tenant/me/integration-context` con el JWT del tenant.

---

# FASE 21 — INTEGRATION SURFACE FOR AXON-ENTERPRISE SaaS SABOR

> Living document, single source of truth for the phase. Reading only this file is enough to know where we are and what comes next.

---

## 1. TL;DR (resume in 30 seconds)

- **What:** axon-enterprise como sabor servicio HTTP del lenguaje gana una superficie de integración self-discoverable, estándar (OIDC + OAuth + OpenAPI), introspeccionable post-auth, y verificada por drift gate. Cualquier consumer (tenant, dashboard, herramienta SRE, SDK third-party) descubre los parámetros de conexión sin handover humano y sin que axon filtre internals de despliegue.
- **Why:** Un lenguaje en sabor enterprise que requiere fricción humana o conocimiento de internals (ALB hostnames, S3 buckets, magic strings) para integrarse es, en ese aspecto, inmaduro. axon-enterprise apunta a adopters de muy alto nivel — la madurez de la superficie de integración es prerequisito de credibilidad de producto, no add-on. El estándar OIDC Connect Discovery 1.0 + RFC 8414 (OAuth Authorization Server Metadata) son lo que cualquier consumer enterprise espera por default.
- **OSS / ENTERPRISE / SPLIT split:** **100% ENTERPRISE.** axon-lang OSS es lenguaje + runtime + crates — no expone HTTP. La superficie de integración es feature exclusiva del sabor SaaS de axon-enterprise. La Integration Guide menciona conceptos OSS (estructura de Shield, capabilities, etc.) pero no requiere cambios al repo OSS.
- **Robustness target:** ship contract tests con golden vectors del discovery doc; drift gate que falle CI si discovery declara algo que no existe; observability que muestre patrones de integración de adopters (qué clientes consumen discovery, frecuencia, errores). Producción-completo desde día uno.

---

## 2. Audit findings — qué carencia tiene v1.7.0

Inspección empírica de axon-enterprise v1.7.0:

| Concern | Pre-Fase-21 state | Risk |
|---|---|---|
| No hay `/.well-known/openid-configuration` | Solo `/.well-known/jwks.json` está mounted ([app.py:100](../axon-enterprise/axon_enterprise/http/app.py#L100)). El issuer + audience + signing alg + endpoints viven en `settings.py` y solo son visibles a operadores con acceso al config. | Cualquier OIDC client (la mayoría) espera el documento de discovery por convención. Su ausencia obliga a configuración manual de cada parámetro per-adopter — handover humano de valores que el server ya conoce. |
| No hay OAuth Authorization Server Metadata (RFC 8414) | No expuesto. | Clientes OAuth no-OIDC (machine-to-machine, mTLS, client_credentials) no tienen discovery estándar. Mismo problema que el anterior pero para clientes no-user-facing. |
| No hay introspección tenant-scoped post-auth | El tenant autenticado no puede consultar "¿qué tengo configurado?" — no sabe sus rate limits, primitivas habilitadas, retention de audit, feature flags activos. | Adopter no puede construir dashboard interno mostrando su consumo / límites / config. Cualquier introspección requiere contactar a Bemarking o leer la documentación. |
| No hay capability advertisement axon-específico | Las primitivas, strategies, scanners disponibles en una instalación no son introspeccionables. Versión, schema versions, feature flags solo viven en código + docs. | Adopter / SDK no puede adaptarse dinámicamente a la versión del server. Compatibility matrix se documenta a mano y se desactualiza. |
| OpenAPI no publicado | Starlette/FastAPI puede generar OpenAPI automáticamente; no está habilitado o no está expuesto en una ruta pública estable. | Adopters generan clientes a mano o con specs incompletos. Tooling estándar (Postman, Insomnia, Stoplight, generadores OpenAPI) queda fuera. |
| Health surface incompleto | `/healthz` existe; no es claro si hay `/readyz` distinto, ni `/livez`, ni `/version`. | Orchestradores (k8s, Nomad, ECS), load balancers, y dashboards de observabilidad esperan los 3-4 endpoints estándar. Sin eso, healthchecks son ad-hoc. |
| Sin drift gate sobre discovery | No hay test que asegure que lo que el discovery doc declara (endpoints, issuer, audience) coincide con la app real montada. | Cualquier refactor que renombre un endpoint o cambie audience podría desincronizar discovery del runtime, llevando a adopters a configurarse contra valores fantasma. |
| Sin observability de integration patterns | No hay logs/metrics estructurados sobre qué adopters consultan discovery, con qué frecuencia, qué errores reciben. | Bemarking SRE no puede detectar adopters con problemas de integración hasta que abren ticket. Reactivo por default. |

**Severidad uniforme**: cada item es un **product maturity concern** del sabor enterprise. v1.7.0 es honesto sobre lo que ya envió (Production Shield + vertical R&D); Fase 21 cierra el gap entre "el producto funciona" y "el producto se integra como un producto enterprise serio".

---

## 3. Architecture — la superficie de integración como contrato del producto

### 3.1 Discovery layer (well-known endpoints)

Tres documentos públicos, sin auth, en el namespace `/.well-known/`:

```
GET /.well-known/openid-configuration        → OIDC Connect Discovery 1.0
GET /.well-known/oauth-authorization-server  → RFC 8414
GET /.well-known/axon-capabilities.json      → axon-specific capability advertisement
GET /.well-known/jwks.json                   → ya existe (firmas RSA del issuer)
```

**OIDC discovery doc** (`openid-configuration`):

```json
{
  "issuer": "https://api.axon.bemarking.com",
  "authorization_endpoint": "https://api.axon.bemarking.com/api/v1/sso/oidc/initiate",
  "token_endpoint": "https://api.axon.bemarking.com/api/v1/auth/login",
  "jwks_uri": "https://api.axon.bemarking.com/.well-known/jwks.json",
  "response_types_supported": ["id_token", "code"],
  "subject_types_supported": ["public"],
  "id_token_signing_alg_values_supported": ["RS256"],
  "scopes_supported": ["openid", "profile", "email", "tenant"],
  "claims_supported": ["sub", "iss", "aud", "exp", "iat", "tenant_id", "email", "user_id"],
  "audience_supported": ["axon-api"],
  "axon_enterprise_version": "1.8.0",
  "axon_discovery_schema_version": "1.0"
}
```

**OAuth Authorization Server Metadata** (RFC 8414): superset relacionado, incluye `grant_types_supported`, `token_endpoint_auth_methods_supported`, `revocation_endpoint`, `introspection_endpoint`. Cubre M2M / client_credentials.

**Axon capabilities advertisement** (custom, axon-namespaced):

```json
{
  "axon_enterprise_version": "1.8.0",
  "axon_lang_compatible_versions": [">=1.13.0", "<2.0.0"],
  "primitives_enabled": ["Flow", "Step", "Shield", "Hibernate", "Drill", "Trail", "Par", "Pix", "Lambda"],
  "shield_strategies_enabled": ["pattern", "classifier", "dual_llm", "canary", "perplexity", "ensemble"],
  "shield_categories_enabled": ["prompt_injection", "jailbreak", "data_exfil", "pii_leak", "toxicity", "bias", "hallucination", "code_injection", "social_engineering", "model_theft", "training_poisoning", "capability_validate"],
  "vertical_packs_loaded": ["hipaa", "legal_privilege", "fintech_aml"],
  "sso_providers": ["oidc", "saml"],
  "audit_retention_days_default": 365,
  "rate_limits_default": {"requests_per_minute": 600, "burst": 100},
  "schema_versions": {"primitives": "1.0", "shield": "1.0", "audit_event": "1.0"}
}
```

Esto es lo que un SDK consulta para auto-configurarse y un dashboard adopter para mostrar "qué viene incluido en mi instalación".

### 3.2 Tenant introspection layer (post-auth)

**`GET /api/v1/tenant/me/integration-context`** — auth: bearer JWT del tenant.

```json
{
  "tenant_id": "<uuid>",
  "tenant_slug": "<adopter-slug>",
  "audience": "axon-api",
  "expected_issuer": "https://api.axon.bemarking.com",
  "rate_limits": {"requests_per_minute": 600, "burst": 100, "current_usage_pct": 12.4},
  "primitives_allowed": ["Flow", "Step", "Shield", "Hibernate", "Drill", "Trail", "Par", "Pix", "Lambda"],
  "shield_categories_required": ["prompt_injection", "pii_leak"],
  "shield_categories_optional": ["bias", "toxicity"],
  "vertical_packs_subscribed": ["hipaa"],
  "audit_retention_days": 2555,
  "feature_flags": {"federated_execution": false, "byok_signing_keys": true},
  "sso_configured": true,
  "sso_provider": "oidc",
  "discovery_doc_url": "https://api.axon.bemarking.com/.well-known/openid-configuration",
  "capabilities_doc_url": "https://api.axon.bemarking.com/.well-known/axon-capabilities.json"
}
```

Esto permite que un adopter construya su dashboard interno sin tener que pedirle a Bemarking sus valores de configuración. Single source of truth: el server.

### 3.3 OpenAPI publication

Starlette + Pydantic ya tienen la mayoría del trabajo hecho. Habilitamos:

```
GET /openapi.json  → spec OpenAPI 3.x completo (Portal API + Admin API + webhooks)
GET /docs          → Swagger UI rendered
GET /redoc         → ReDoc rendered (alternativa)
```

Enriquecido con:
- `info.x-axon-discovery`: link al openid-configuration
- `securitySchemes`: bearer JWT con link al jwks
- Tags: `Auth`, `Tenant`, `SSO`, `Webhooks`, `Discovery`, `Admin`
- Operations annotated con example requests/responses

### 3.4 Health / status surface

Estandarizar 4 endpoints (3 si `livez ≡ healthz`):

```
GET /healthz   → "is the process alive" — devuelve 200 si server arrancó
GET /readyz    → "can the process serve traffic" — checks DB conn + JWKS load + downstream deps
GET /livez     → liveness probe (k8s convention) — más estricto que healthz
GET /version   → JSON: {axon_enterprise_version, axon_lang_required, build_sha, build_date}
```

`/healthz` y `/readyz` ya existen ([app.py](../axon-enterprise/axon_enterprise/http/app.py)). Esta sub-fase formaliza el contrato + agrega `/version` y eventualmente `/livez` distinto.

### 3.5 Drift gate (discovery ≡ reality)

Test a nivel CI que:

1. Construye la app con `build_app()`.
2. Genera el discovery doc esperado a partir de `settings` + routes mounted.
3. Hace `GET /.well-known/openid-configuration` contra la app de test.
4. Compara serializado: si difieren, falla CI con diff explícito.
5. Mismo patrón para OAuth metadata + capabilities + OpenAPI tags vs routes mounted.

Reusa el patrón de [tests/test_fase19_drift_gate.py](../axon-enterprise/tests/...) y [tests/test_fase20_drift_gate.py](../axon-enterprise/tests/...) — mismo discipline.

### 3.6 Observability hooks

Cada hit a discovery emite un structured log event:

```json
{"event": "discovery.fetched", "doc": "openid-configuration", "ua_class": "browser|sdk|cli|unknown", "remote_ip_class_b": "203.0.113.0/24", "status": 200, "ms": 4.2}
```

Métricas Prometheus:
- `axon_discovery_requests_total{doc="openid-configuration",status="200"}`
- `axon_discovery_request_duration_seconds{doc="..."}`
- `axon_tenant_integration_context_requests_total{tenant_slug="...",status="..."}`

Sin PII. UA fingerprint (no full UA) para inferir clase de cliente. IP a clase B para detectar adopters mal configurados sin doxearlos.

### 3.7 Versioning + Cache-Control

- `axon_discovery_schema_version` semver en cada doc — cuando agreguemos campos no-breaking, bump minor; breaking → bump major + notice + deprecation window.
- `Cache-Control: public, max-age=300` en discovery + capabilities (5 min, alineado con JWKS lifespan).
- `ETag` derivado del hash SHA-256 del cuerpo, soporta `If-None-Match` → 304.

---

## 4. Sub-fases — desglose, dependencies, classification

| # | Title | Classification | Depends on | Approximate scope |
|---|---|---|---|---|
| 21.a | OIDC Discovery endpoint | ENTERPRISE | — | endpoint + serializer + 8 tests + Cache-Control + ETag |
| 21.b | OAuth Authorization Server Metadata | ENTERPRISE | 21.a | endpoint + 6 tests |
| 21.c | Tenant integration-context endpoint | ENTERPRISE | — | endpoint + auth + 12 tests (positive, negative, RLS, rate limit visibility) |
| 21.d | Capability advertisement | ENTERPRISE | 21.a | endpoint + capability registry introspection + 10 tests |
| 21.e | OpenAPI publication + render | ENTERPRISE | — | habilitar generation + custom enrichment + 5 tests |
| 21.f | Health/status surface formalization | ENTERPRISE | — | `/version` nuevo + `/livez` nuevo (si aplica) + 6 tests |
| 21.g | Drift gate discovery ≡ reality | ENTERPRISE | 21.a, 21.b, 21.d, 21.e | 7 tests (uno por doc, uno por consistency cross-doc) |
| 21.h | Observability: discovery + integration-context hits | ENTERPRISE | 21.a, 21.c | structured events + Prometheus metrics + 4 tests |
| 21.i | Adopter Integration Guide | ENTERPRISE (docs) | 21.a–21.h | `docs/INTEGRATION_GUIDE.md` nuevo + actualización de `PORTAL_API.md` |
| 21.j | Contract tests adopter↔server (golden vectors) | ENTERPRISE | 21.a–21.f | snapshot tests con vectores fijos para detectar regressions de wire format |
| 21.k | Coordinated v1.8.0 release commit + tag | ENTERPRISE | 21.a–21.j | bump-my-version, PR, merge, tag con refspec mapping (per release workflow) |

---

## 5. Decisions (D1–Dn)

**D1 — Standards adoption: OIDC Connect Discovery 1.0 + RFC 8414 simultaneous**

We publish both `/.well-known/openid-configuration` (OIDC) and `/.well-known/oauth-authorization-server` (RFC 8414) — they overlap but cover different client populations (OIDC for user-facing flows, OAuth metadata for M2M). Adopters consume whichever their lib expects. No custom protocol invented; if a future spec evolves (e.g., OAuth 2.1), we add the new doc and deprecate the old gracefully.

**D2 — Audience model exposure**

Discovery declara `audience_supported` como array (single element today: el server-wide audience configured). Per-tenant audience model es una posible evolución; cuando llegue, el array crece sin breaking. Tenant-scoped audience visible en `/api/v1/tenant/me/integration-context`.

**D3 — Tenant introspection scope**

`/api/v1/tenant/me/integration-context` devuelve solo lo que ESE tenant tiene/puede. RLS strict — un tenant nunca ve config de otro. El endpoint reusa el AuthMiddleware existente; no inventa modelo de auth nuevo.

**D4 — Capability advertisement vs OpenAPI overlap**

Mantenemos ambos por separado. **OpenAPI** describe la API surface (endpoints, schemas, auth). **Axon capabilities** describe conceptos del lenguaje (qué primitivas, qué strategies, qué vertical packs, qué schema versions). Son ortogonales y un client puede consumir uno sin el otro.

**D5 — Drift gate enforcement (CI gating)**

El drift gate de discovery es **bloqueante en CI**. Si discovery declara `audience: "axon-api"` y settings tiene `audience: "different"`, CI rojo. Mismo discipline que portal_routes_catalog drift gate (Fase 18+) y shield drift gate (Fase 20.j). Esto previene desync silenciosa entre runtime y advertised surface.

**D6 — Discovery doc versioning + cache**

Cada doc lleva `*_schema_version` semver. `Cache-Control: public, max-age=300` (5 min) alineado con JWKS lifespan. ETag SHA-256. Schema version bump minor en cambios no-breaking; major + deprecation notice (90 días warning en `meta.deprecations`) en breaking.

**D7 — Observability privacy discipline**

Logs de discovery hits NO incluyen full UA, NO incluyen IP completa, NO incluyen tokens. Solo: UA class (heurística simple), IP a clase B (`203.0.113.0/24`), status, latency. Detectar patrones agregados; nunca trackear adopters individualmente.

**D8 — SDK auto-discovery (defer to future fase)**

Esta fase expone la superficie. La consumption side (SDKs en Python/TS/Rust que auto-descubran en init) es separada — Fase 22+ candidate. Razón: probar la superficie con consumers reales primero, después invertir en ergonomía SDK con feedback de uso real.

**D9 — Sin breaking changes a la Portal API existente**

Fase 21 SOLO agrega endpoints nuevos. NO renombra, deprecata, ni cambia formato de los endpoints actuales (`/api/v1/auth/*`, `/api/v1/tenant/*`, `/api/v1/sso/*`). Compatibilidad backward total. v1.8.0 es minor bump (additive features), no major.

**D10 — DNS estable como prerequisito operativo (no parte de esta fase)**

Esta fase asume que axon-enterprise se sirve detrás de un nombre DNS estable (ej. `api.axon.bemarking.com`) con TLS. Si la instalación de staging actualmente usa hostname feo de ALB, eso es trabajo de **infra ops** (Route 53 + ACM cert + listener HTTPS), no de Fase 21. Documentamos la asunción pero no implementamos infra cambios.

---

## 6. Tests target — ≥66 nuevos

| Suite | File (proposed) | Tests | Coverage |
|---|---|---|---|
| OIDC discovery | `tests/discovery/test_oidc_configuration.py` | 8 | endpoint shape, headers, Cache-Control, ETag, schema validation, 404 negative, parse with `authlib`, parse with `python-jose` |
| OAuth metadata | `tests/discovery/test_oauth_metadata.py` | 6 | RFC 8414 compliance, fields presence, parse compatibility |
| Tenant integration context | `tests/api/test_integration_context.py` | 12 | happy path, no-auth 401, wrong tenant 403 (RLS), rate limit fields, primitive list, audit retention, vertical packs, schema validation, request id propagation, ETag, idempotent reads, multi-tenant isolation |
| Capabilities | `tests/discovery/test_capabilities.py` | 10 | shape, version sync vs `__version__`, strategies enabled match registry, vertical packs match installed, schema versions present, no PII leak, ETag, Cache-Control, deprecation field present, axon-lang compat |
| OpenAPI | `tests/discovery/test_openapi_publication.py` | 5 | spec parses (OpenAPI Validator), all routes covered, security schemes correct, tags coherent, swagger UI loads |
| Health/status | `tests/health/test_health_surface.py` | 6 | healthz 200 always, readyz 503 when DB down, livez behavior, version JSON shape, version bumps with `__version__`, all probes have low overhead |
| Drift gate | `tests/discovery/test_discovery_drift_gate.py` | 7 | discovery vs settings, OAuth vs OIDC consistency, capabilities vs registries, OpenAPI tags vs routes, version cross-coherence, no leaked internals (no ALB hostnames, no S3 names), schema version monotonic |
| Observability | `tests/observability/test_discovery_obs.py` | 4 | log emission shape, no PII, metric increments, UA classification heuristic |
| Contract / golden vectors | `tests/discovery/test_discovery_contracts.py` | 8 | snapshot OIDC, snapshot OAuth, snapshot capabilities, version bumps require snapshot regen (anti-accident), parse with 4 different OIDC libs, parse with 2 OAuth libs |

**Total**: 66 nuevos. Más cualquiera que surja durante implementación.

---

## 7. Drift gate / charter compliance

Además del drift gate sobre discovery (sub-fase 21.g), añadimos un **charter compliance test**:

```python
def test_fase21_classification_compliance():
    """Asegura que ningún archivo nuevo de Fase 21 viva en axon-lang OSS.
    Toda esta fase es ENTERPRISE-only."""
    forbidden_patterns = [
        "axon/runtime/discovery",
        "axon/http",
    ]
    for pattern in forbidden_patterns:
        assert not Path(pattern).exists(), \
            f"Fase 21 es ENTERPRISE-only; nada debe vivir en {pattern}"
```

Y un **purity gate** sobre el contenido del discovery doc:

```python
def test_fase21_no_internal_leakage():
    """Discovery docs públicos NO deben filtrar internals de despliegue.
    No ALB hostnames, no S3 bucket names, no environment names internos."""
    doc = client.get("/.well-known/openid-configuration").json()
    for value in _flatten_strings(doc):
        assert "elb.amazonaws.com" not in value
        assert ".s3.amazonaws.com" not in value
        assert "staging-internal" not in value
        assert "axon-prod-alb" not in value
    # Mismo check para oauth-authorization-server y axon-capabilities
```

Esto materializa la lección: el discovery debe exponer **nombres estables del producto**, nunca infraestructura subyacente.

---

## 8. Ship target

- **axon-enterprise v1.8.0** — minor bump (feature add, no breaking).
- **axon-lang permanece en v1.15.0** — esta fase no toca el repo OSS.
- **Release workflow**: per [memoria axon-enterprise release workflow](../memory/reference_enterprise_release_workflow.md) — branch off enterprise/master, bump 2 files (pyproject + `__version__`), PR + merge + tag con refspec mapping `enterprise/v1.8.0:refs/tags/v1.8.0`.
- **No requiere release coordinado de axon-lang** (a diferencia de Fase 20 que fue cross-stack).
- **Docs**: `docs/INTEGRATION_GUIDE.md` se ubica en axon-enterprise/docs/; `PORTAL_API.md` se actualiza con sección "Discovery" referenciando el nuevo doc.

---

## 9. Out of scope (para esta fase)

Estas son ideas adyacentes que **no** entran en Fase 21 — quedan para fases futuras o para discusión:

- **mTLS client cert auth** — alternativa a JWT para adopters de muy alta seguridad. Fase 22+ candidate.
- **Per-tenant audience model** — hoy audience es server-wide. Si llega un adopter que requiere isolation por audience, fase aparte.
- **Webhook signing key discovery** — `.well-known/webhook-signing-keys.json` para adopters que reciban webhooks de axon. Fase webhooks-related.
- **Operator status page** — surface tipo statuspage.io con uptime, incidentes, maintenance windows. Fase ops-related.
- **SDK packages auto-discovery helpers** — librerías Python/TS/Rust que consuman discovery automáticamente en init. Fase 22+ (después de validar la superficie con consumers manuales reales).
- **GraphQL endpoint introspection** — si un día axon expone GraphQL, su introspection es discovery natural. No aplica hoy.
- **Cambios a la Portal API existente** — D9 lo ratifica: solo additive.

---

## 10. Summary table — 30-second decision support

| Question | Answer |
|---|---|
| ¿Es esto urgente? | **Sí.** Es prerequisite de credibilidad enterprise frente a adopters de alto nivel. Marker: la próxima conversación de integración con un adopter debería ser "pegá `AXON_API_BASE` y leé discovery", no "te paso 5 valores por handover". |
| ¿Toca axon-lang OSS? | **No.** 100% enterprise. axon-lang permanece en v1.15.0. |
| ¿Rompe algo existente? | **No.** Solo additive. v1.8.0 minor bump. D9 lo prohíbe explícitamente. |
| ¿Cuánto código nuevo? | Estimado ~1.5k LOC (Python) + ~66 tests + 1 doc nuevo + actualizaciones a `PORTAL_API.md`. |
| ¿Qué desbloquea? | Onboarding adopter sin handover humano; SDKs auto-configurables; dashboards adopter-side; observability de patrones de integración; eliminación de la deuda "tenant repo conoce internals de axon". |
| ¿Cuál es el primer commit? | 21.a — OIDC Discovery endpoint + 8 tests + Cache-Control + ETag. Baseline mínimo con el cual el resto encadena. |

---

**Próximo paso operacional**: confirmar prioridad vs otras iniciativas en backlog, asignar owner del primer commit (21.a), y arrancar.
