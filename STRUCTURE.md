# Axon Enterprise — Folder Structure Overview

This document describes the organization of the `axon-enterprise` repository as of **v1.3.0** (2026-04-30). It is the canonical map of "where does X live"; if a path here disagrees with the filesystem, the filesystem is authoritative — please open a PR to correct this doc.

## Directory hierarchy

```
axon-enterprise/
├── axon_enterprise/                    # Main Python package — 20 enterprise modules
│   ├── __init__.py                     # Package version (1.3.0)
│   │
│   ├── identity/                       # User accounts, MFA, password security
│   │   ├── models.py                   # User, Credential, MFADevice
│   │   ├── service.py                  # IdentityService (signup, login, MFA enrol)
│   │   ├── password.py                 # Argon2id hashing + zxcvbn strength + HIBP
│   │   └── totp.py                     # RFC 6238 TOTP for MFA
│   │
│   ├── rbac/                           # Role-Based Access Control
│   │   ├── models.py                   # Role, Permission, RoleHierarchy
│   │   ├── service.py                  # RBACService
│   │   └── middleware.py               # Per-handler permission enforcement
│   │
│   ├── sso/                            # Single Sign-On
│   │   ├── saml.py                     # SAML 2.0 (Okta, Azure AD, Ping)
│   │   ├── oauth.py                    # OAuth 2.0 (generic)
│   │   └── oidc.py                     # OpenID Connect (Google, Microsoft, Auth0)
│   │
│   ├── jwt_issuer/                     # Tenant JWT signing + JWKS
│   │   ├── service.py                  # Sign / verify / rotate keys
│   │   ├── jwks.py                     # JWKS endpoint serialisation
│   │   └── models.py                   # JWTSigningKey
│   │
│   ├── api_keys/                       # Tenant-scoped API key issuance
│   │   ├── service.py                  # Issue / scope / rotate / revoke
│   │   └── models.py                   # APIKey, APIKeyScope
│   │
│   ├── invitations/                    # Tenant invitation flow
│   │   ├── service.py                  # Token issue + email + redeem
│   │   └── models.py                   # Invitation
│   │
│   ├── audit/                          # Immutable audit trail
│   │   ├── events.py                   # AuditEvent + EventType enum
│   │   ├── canonical.py                # Canonical hashing for tamper detection
│   │   ├── adapters.py                 # In-memory / Postgres / S3 sink
│   │   └── service.py                  # AuditService
│   │
│   ├── compliance/                     # Regulatory framework catalogue
│   │   ├── catalog.py                  # GDPR / CCPA / SOX / HIPAA / GLBA / PCI-DSS
│   │   ├── residency.py                # Data-residency middleware
│   │   └── service.py                  # ComplianceService
│   │
│   ├── crypto/                         # Centralised crypto primitives
│   │   ├── envelope.py                 # AEAD envelope encryption
│   │   ├── kdf.py                      # Argon2id / HKDF
│   │   └── signing.py                  # HMAC-SHA256, Ed25519
│   │
│   ├── secrets/                        # Tenant secrets store
│   │   ├── service.py                  # SecretsService
│   │   ├── adapters/
│   │   │   ├── memory.py               # In-process (dev/test only)
│   │   │   ├── vault.py                # HashiCorp Vault
│   │   │   ├── aws_secrets.py          # AWS Secrets Manager
│   │   │   └── azure_keyvault.py       # Azure Key Vault
│   │   └── models.py                   # Secret, SecretReference
│   │
│   ├── metering/                       # Usage tracking + Stripe billing
│   │   ├── models.py                   # UsageMetric, BillingRecord
│   │   ├── collector.py                # MeteringCollector
│   │   ├── billing.py                  # Stripe invoice draft generator
│   │   └── webhook.py                  # Stripe webhook handler
│   │
│   ├── observability/                  # Prometheus + OTel + structlog
│   │   ├── metrics.py                  # Counters / gauges / histograms
│   │   ├── tracing.py                  # OpenTelemetry spans
│   │   └── logging.py                  # structlog config
│   │
│   ├── replay/                         # ReplayLog Postgres adapter (Fase 11.c)
│   │   ├── postgres.py                 # PostgresReplayLog implements axon::ReplayLog trait
│   │   ├── executor.py                 # ReplayExecutor
│   │   └── models.py                   # ReplayToken row
│   │
│   ├── cognitive_states/               # PEM state persistence (Fase 11.d)
│   │   ├── postgres.py                 # PostgresPersistenceBackend
│   │   ├── encryption.py               # Envelope encryption per state
│   │   └── models.py                   # CognitiveState row
│   │
│   ├── studio/                         # Visual debugger
│   │   └── debugger.py                 # FlowDebugger (breakpoints + snapshots)
│   │
│   ├── tenant/                         # Request-scoped tenant propagation
│   │   └── context.py                  # TenantContext + ContextVar
│   │                                   # (Python mirror of axon-rs/src/tenant.rs)
│   │
│   ├── http/                           # HTTP API surface (Starlette + Uvicorn)
│   │   ├── api/
│   │   │   ├── admin.py                # /api/v1/admin/*
│   │   │   ├── portal.py               # /api/v1/portal/*
│   │   │   └── primitives.py           # /api/v1/primitives (Fase 11 discovery)
│   │   ├── middleware/
│   │   │   ├── tenant_extractor.py     # JWT → TenantContext
│   │   │   ├── rate_limit.py
│   │   │   └── cors.py
│   │   └── webhooks/
│   │       └── stripe.py               # Stripe → metering pipeline
│   │
│   ├── cli/                            # Operator CLI (Typer)
│   │   ├── tenants.py                  # tenant create/list/suspend
│   │   ├── audit.py                    # audit query/export
│   │   └── replay.py                   # replay execute <token>
│   │
│   ├── db/                             # SQLAlchemy async foundation
│   │   ├── base.py                     # Declarative Base
│   │   ├── session.py                  # AsyncSession + connection pool
│   │   └── models/                     # Cross-cutting model imports
│   │
│   └── config/                         # Pydantic Settings loader
│       └── settings.py                 # Env-driven configuration
│
├── alembic/                            # Postgres migrations
│   ├── env.py
│   ├── script.py.mako
│   └── versions/                       # 12 migrations (chronological)
│       ├── 001_baseline_foundation.py
│       ├── 002_identity_core.py
│       ├── 003_rbac_production.py
│       ├── 004_sso_configurations.py
│       ├── 005_jwt_signing_keys.py
│       ├── 006_tenant_secrets.py
│       ├── 007_audit_events.py
│       ├── 008_metering.py
│       ├── 009_tenant_api_keys.py
│       ├── 010_compliance.py
│       ├── 011_replay_tokens.py
│       └── 012_cognitive_states.py
│
├── alembic.ini                         # Alembic config (DB URL via env)
│
├── infrastructure/                     # Deployment artefacts
│   ├── docker/                         # docker-compose for local dev
│   │   ├── docker-compose.yml
│   │   └── Dockerfile
│   │
│   ├── kubernetes/                     # K8s manifests + Helm
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   ├── ingress.yaml
│   │   ├── postgres-statefulset.yaml
│   │   ├── configmap.yaml
│   │   ├── secrets-template.yaml
│   │   ├── persistent-volumes.yaml
│   │   └── kustomization.yaml
│   │
│   ├── terraform/                      # IaC (AWS by default)
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   ├── vpc.tf
│   │   ├── database.tf                 # PostgreSQL RDS
│   │   ├── compute.tf                  # ECS / EC2
│   │   └── iam.tf
│   │
│   └── aws/                            # Cloud-specific configs
│       └── iam/                        # IAM roles + policies
│
├── tests/                              # pytest suite (asyncio + testcontainers)
│   ├── identity/                       # Unit tests per module — mirrors axon_enterprise/
│   ├── rbac/
│   ├── jwt_issuer/
│   ├── api_keys/
│   ├── invitations/
│   ├── audit/
│   ├── compliance/
│   ├── crypto/
│   ├── metering/
│   ├── observability/
│   ├── cognitive_states/
│   ├── http/                           # Includes http/webhooks/ Stripe tests
│   ├── config/
│   ├── db/
│   ├── load/                           # k6 / locust load tests
│   └── enterprise_integration/         # Cross-module integration suite
│
├── docs/                               # 16 architecture + ops guides
│   ├── ARCHITECTURE.md                 # System design + module boundaries
│   ├── IDENTITY.md                     # Users, password security, MFA
│   ├── RBAC.md                         # Role-based access control
│   ├── SSO.md                          # Single sign-on
│   ├── JWT.md                          # JWT signing + JWKS + rotation
│   ├── AUDIT.md                        # Immutable audit trail
│   ├── COMPLIANCE.md                   # Regulatory frameworks
│   ├── SECRETS.md                      # Secrets store + cloud adapters
│   ├── METERING.md                     # Usage + billing pipeline
│   ├── OBSERVABILITY.md                # Prometheus / OTel / structlog
│   ├── ADMIN_API_AND_CLI.md            # Operator surface
│   ├── PORTAL_API.md                   # Tenant-facing portal
│   ├── DATABASE.md                     # Postgres schema + Alembic
│   ├── DEPLOYMENT.md                   # Docker / K8s / Terraform
│   ├── SECURITY_AUDIT.md               # Last security review (v1.2.0)
│   └── THREAT_MODEL.md                 # STRIDE + adversarial scenarios
│
├── pyproject.toml                      # name = "axon-enterprise", version = "1.3.0"
├── Dockerfile.enterprise               # Production container image
├── README.md                           # Top-level project README
├── STRUCTURE.md                        # This file
└── LICENSE.commercial                  # Bemarking AI proprietary licence
```

## Module responsibilities

### Identity, access, and authentication

| Module | Role |
|---|---|
| `identity/` | User accounts, Argon2id password hashing, RFC 6238 TOTP MFA, HIBP password breach checks, zxcvbn strength scoring. |
| `rbac/` | Hierarchical roles, fine-grained `resource:action` permissions, built-in roles (Admin / Developer / Viewer), HTTP middleware. |
| `sso/` | SAML 2.0, OAuth 2.0, OpenID Connect — provisioning + session lifecycle. |
| `jwt_issuer/` | Per-tenant JWT signing keys with rotation, JWKS endpoint, downstream verification. |
| `api_keys/` | Tenant-scoped API keys with scoped permissions, rotation, revocation. |
| `invitations/` | Email-token-based invitation redemption flow. |
| `tenant/` | Request-scoped tenant propagation via `ContextVar` (the Python mirror of Rust's `tokio::task_local!` in `axon-rs/src/tenant.rs`). Surfaces `require_tenant()` so accidental cross-tenant writes fail loudly. |

### Compliance, audit, and crypto

| Module | Role |
|---|---|
| `audit/` | Immutable audit trail with canonical event hashing for tamper detection. Pluggable sinks (in-memory, Postgres, S3). |
| `compliance/` | Closed catalogue of regulatory authorisations (GDPR / CCPA / SOX / HIPAA / GLBA / PCI-DSS). Drives data-residency middleware and the `@legal_basis` annotations consumed by `axon-lang`. |
| `crypto/` | Centralised primitives: AEAD envelope encryption, HMAC-SHA256, Ed25519, KDF (Argon2id / HKDF). |
| `secrets/` | Tenant-scoped secrets store with adapters for HashiCorp Vault, AWS Secrets Manager, and Azure Key Vault. |

### Operations and observability

| Module | Role |
|---|---|
| `metering/` | Usage tracking (flow executions, LLM tokens in/out, storage GB-hours, compute minutes). Stripe webhook-driven billing draft generator. |
| `observability/` | Prometheus metrics export, OpenTelemetry tracing, `structlog`-based structured logging. |
| `replay/` | `PostgresReplayLog` implements the `axon::ReplayLog` trait from Fase 11.c. Re-executes any flow from a canonical token. |
| `cognitive_states/` | `PostgresPersistenceBackend` implements the Fase 11.d backend trait. Q32.32 fixed-point density-matrix encoding so PEM state round-trips bit-identical across WebSocket reconnects. |
| `studio/` | Visual flow debugger: breakpoints, step-into / step-over, execution snapshots, variable inspection. |

### Platform infrastructure

| Module | Role |
|---|---|
| `http/` | Starlette routers (`/api/v1/admin/*`, `/api/v1/portal/*`, `/api/v1/primitives`), tenant extractor middleware, Stripe webhook handlers. |
| `cli/` | Operator CLI (`axon-enterprise <command>`, Typer-based) for tenant provisioning, audit queries, replay execution. |
| `db/` | SQLAlchemy async declarative base, session factory, connection pool tuning. |
| `config/` | Pydantic Settings loader with environment-driven overrides. |

## Synchronisation with `axon-lang`

`axon-enterprise` consumes `axon-lang` strictly as a **published Python and Rust dependency**, not as a code fork. There is **no git-level merge** between the two repos — they have completely independent histories.

```
axon-lang (public)
   │
   │ released to PyPI as axon-lang
   │ released to crates.io as axon-lang
   │
   ▼
axon-enterprise (private)
   ├── pyproject.toml: axon-lang>=1.5.1
   └── consumes the Rust runtime via the published crate
```

When a new `axon-lang` release lands, the integration step is:

```bash
# In ../axon-lang/  → cut the release, push to PyPI + crates.io.
# Then:
cd ../axon-enterprise
# Bump the pin in pyproject.toml: axon-lang>=X.Y.Z
# Bump axon-enterprise SemVer (minor for additive features that surface
# new axon-lang capability through the platform; patch for transparent
# upgrades).
git commit -am "release(vX.Y.Z): integrate axon-lang X.Y.Z — <highlight>"
git push origin master
```

> **Anti-pattern (do not do):** `git merge upstream/master` from axon-lang into axon-enterprise. The histories are unrelated; `git` will refuse without `--allow-unrelated-histories`, and even with it the cross-tree conflicts are intractable. The dependency pin **is** the sync mechanism.

## Development workflow

1. **Feature work**: scope changes to one module under `axon_enterprise/<module>/`. New cross-cutting concerns get a new top-level submodule rather than spreading into existing ones.
2. **Tests**: unit tests under `tests/<module>/`, integration tests under `tests/enterprise_integration/`, load tests under `tests/load/`. Use `testcontainers[postgres]` for Postgres-backed integration tests so CI does not depend on a long-lived DB.
3. **Migrations**: every schema change ships with a new Alembic file under `alembic/versions/` named `NNN_<concern>.py`. Migrations are **forward-only** in production — never edit a published migration; ship a follow-up.
4. **Documentation**: keep the matching `docs/<TOPIC>.md` in sync. The README and this STRUCTURE.md are refreshed at every minor release.
5. **Commit messages**: `<type>(<scope>): <subject>` per conventional-commits. Use `feat(<module>):`, `fix(<module>):`, `refactor(<module>):`, `release(vX.Y.Z): …` for the version-bump commit.
6. **Push**: `git push origin master` from this repo. **Never push to a cross-repo `enterprise` remote on the axon-lang side** — that is a legacy artefact and breaks GitHub Actions on the receiving repo (see `axon-lang`'s `development_dual_remote_strategy.md` memory note).

## Best practices

- **Stateless processes**: all state lives in PostgreSQL or external secrets stores; in-process state is a cache at most.
- **Tenant scoping**: every request goes through `tenant/context.py` extraction; downstream services call `require_tenant()` rather than reading the JWT directly.
- **Configuration**: environment variables via `config/settings.py`. No hard-coded secrets, no hard-coded URLs.
- **Logging**: structured logging only (`structlog`). Audit-relevant operations emit through `audit/` for the immutable trail; debug logs go through `observability/logging.py`.
- **Migrations**: generate via `alembic revision --autogenerate -m "<message>"` then **review the diff** before committing — autogen catches schema drift but does not always pick the right downgrade path.
- **Testing**: integration tests run before every production deploy. Load suite (`tests/load/`) runs on a release-candidate basis, not per-commit.

## Key differences from `axon-lang`

| Aspect | `axon-lang` (public, MIT) | `axon-enterprise` (private, commercial) |
|---|---|---|
| **Repository** | https://github.com/Bemarking/axon-lang | https://github.com/Bemarking/axon-enterprise |
| **Distribution** | PyPI: `axon-lang` · crates.io: `axon-lang` | Internal pip + container image |
| **Identity** | None | `identity/` (Argon2id + MFA + HIBP) |
| **RBAC** | None | `rbac/` |
| **SSO** | None | `sso/` (SAML / OAuth / OIDC) |
| **JWT issuance** | Verification only (Fase 10.e) | `jwt_issuer/` issues + rotates per-tenant keys |
| **Secrets store** | Local env vars only | `secrets/` with Vault / AWS / Azure adapters |
| **Audit trail** | Basic logging | Immutable trail with canonical hashing |
| **Compliance** | `legal_basis` catalogue (compile-time) | Runtime enforcement + residency middleware |
| **Metering / billing** | None | `metering/` + Stripe pipeline |
| **Replay / state persistence** | Trait + in-memory impl | Postgres backend implementations |
| **Studio debugger** | None | `studio/` |
| **Multi-tenant** | Single-tenant | Multi-tenant native (every layer is tenant-scoped) |
| **Database** | None required | PostgreSQL 14+ with 12 Alembic migrations |
| **Deployment** | `pip install` / `cargo install` | Docker + K8s + Terraform IaC |

---

**Version:** 1.3.0
**Last Updated:** 2026-04-30
