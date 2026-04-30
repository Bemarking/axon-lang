# Axon Enterprise Edition

**Axon Enterprise v1.3.0 — Commercial platform built on the AXON cognitive language**

Primer Lenguaje de Programación AI Native Cognitivo Formal. Enterprise platform with production-grade identity, compliance, metering, and operational primitives for multi-tenant SaaS deployments — built **on top of** the open-source [`axon-lang`](https://github.com/Bemarking/axon-lang) compiler/runtime.

## What's new in v1.3.0

Integrated **`axon-lang>=1.5.1`** which closes Fase 13.f.2 — the native Rust `TypedEventBus` runtime now has full parity with the Python reference. Adopters running on the platform's Rust runtime get end-to-end typed channels with the same guarantees the Python interpreter offers:

- **QoS×5** dispatch: `at_most_once` / `at_least_once` / `exactly_once` / `broadcast` / `queue` (per-channel `tokio::sync::mpsc`)
- **Lifetime tracking**: affine / linear / persistent
- **π-calculus mobility**: second-order `Channel<Channel<T>>` (paper §3.2)
- **Capability extrusion** via shield-mediated `publish` (D8), one-shot `discover`
- **ESK-aware compliance predicate hook** for production wiring

Previously, enterprise deployments hit a Rust-side execution gap — the frontend parsed and type-checked the new channel surface but the Rust runtime had no executor for it. v1.3.0 closes that.

## Compatibility matrix

| `axon-enterprise` | requires `axon-lang` | Highlight |
|---|---|---|
| **1.3.0** (current) | `>=1.5.1` | **Fase 13.f.2** — typed channels Rust runtime parity |
| 1.2.x | `>=1.4.0` | Fase 11 Trust catalog + LegalBasis + OTS + `/api/v1/primitives` discovery endpoint |
| 1.1.x | `>=1.3.0` | Fase 10 Enterprise Control Plane GA |
| 1.0.0 | `>=1.0.0` | Initial GA |

The two products track **independent SemVer trains**. Cross-stack sync happens through the `axon-lang` PyPI / crates.io dependency pin in `pyproject.toml`, never through git tag mirroring.

## Key features

### Identity & access control

- **`rbac/`** — Role-Based Access Control with hierarchical roles, fine-grained `resource:action` permissions, built-in roles (Admin / Developer / Viewer).
- **`identity/`** — User accounts, password hashing (Argon2id), TOTP MFA (RFC 6238), HIBP k-anonymity password breach checks.
- **`sso/`** — Single Sign-On: SAML 2.0 (Okta, Azure AD, Ping), OAuth 2.0, OpenID Connect (Google, Microsoft, Auth0).
- **`jwt_issuer/`** — Tenant-scoped JWT signing with key rotation, JWKS endpoint for downstream verification.
- **`api_keys/`** — Tenant API keys with scoped permissions, rotation, and revocation.
- **`invitations/`** — Tenant-scoped invitation flow with email tokens.

### Compliance, audit, and crypto

- **`audit/`** — Immutable audit trail with canonical event hashing; pluggable adapters (in-memory, Postgres, S3 sink). Surfaces every privileged operation.
- **`compliance/`** — Closed catalogue of regulatory authorisations (GDPR / CCPA / SOX / HIPAA / GLBA / PCI-DSS) enforced via residency middleware + HTTP tooling. Powers `@legal_basis` annotations downstream in `axon-lang`.
- **`crypto/`** — Centralised crypto primitives (HMAC-SHA256, Ed25519, envelope encryption for at-rest sensitive data).
- **`secrets/`** — Tenant-scoped secrets store with HashiCorp Vault / AWS Secrets Manager / Azure Key Vault adapters.

### Operations & observability

- **`metering/`** — Usage tracking (flow executions, LLM tokens in/out, storage, compute hours). Stripe webhook-driven billing pipeline.
- **`observability/`** — Prometheus metrics export, distributed tracing (OpenTelemetry), structured logging (`structlog`).
- **`replay/`** — `ReplayLog` Postgres adapter implementing the `axon-lang` Fase 11.c trait. Lets the platform re-execute any flow from a canonical token.
- **`cognitive_states/`** — Stateful PEM persistence over WebSocket reconnects (Q32.32 fixed-point density-matrix encoding for bit-identical round-trips). Implements the `axon-lang` Fase 11.d `PersistenceBackend` trait.
- **`studio/`** — Visual debugger for Axon flows: breakpoints, step-into / step-over, execution snapshots, variable inspection.
- **`tenant/`** — Request-scoped tenant propagation. Mirrors `axon-rs/src/tenant.rs` so the Python control plane and the Rust data plane share one mental model (`TenantContext` carried via `ContextVar` — Python analogue of `tokio::task_local!`).

### Platform infrastructure

- **`http/`** — HTTP API layer: `/api/v1/admin/*`, `/api/v1/portal/*`, `/api/v1/primitives` (discovery — Fase 11), tenant extractor middleware, Stripe webhook handlers.
- **`cli/`** — Operator CLI (`axon-enterprise <command>`) for tenant provisioning, role inspection, audit queries, replay execution.
- **`db/`** — SQLAlchemy async base classes, session management, connection pooling. Alembic migrations under `alembic/versions/`.
- **`config/`** — Settings loader (Pydantic Settings), environment-driven overrides.

## Folder structure

```
axon-enterprise/
├── axon_enterprise/                # Python package (enterprise features)
│   ├── rbac/                       # Role-Based Access Control
│   ├── identity/                   # User accounts, MFA, password security
│   ├── sso/                        # SAML / OAuth / OIDC
│   ├── jwt_issuer/                 # Tenant JWT signing + JWKS
│   ├── api_keys/                   # Scoped API key issuance
│   ├── invitations/                # Tenant invitation flow
│   ├── audit/                      # Immutable audit trail
│   ├── compliance/                 # Regulatory framework catalogue
│   ├── crypto/                     # Centralised crypto primitives
│   ├── secrets/                    # Vault / Secrets Manager adapters
│   ├── metering/                   # Usage tracking + Stripe billing
│   ├── observability/              # Prometheus + OTel + structlog
│   ├── replay/                     # ReplayLog Postgres adapter
│   ├── cognitive_states/           # PEM state persistence (Fase 11.d)
│   ├── studio/                     # Visual flow debugger
│   ├── tenant/                     # Request-scoped tenant context
│   ├── http/                       # API routers + middleware + webhooks
│   ├── cli/                        # Operator CLI (Typer)
│   ├── db/                         # SQLAlchemy async base
│   └── config/                     # Pydantic Settings loader
│
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/                   # 12 migrations: foundation → cognitive_states
│
├── infrastructure/
│   ├── docker/                     # docker-compose for local dev
│   ├── kubernetes/                 # K8s manifests + Helm
│   ├── terraform/                  # IaC (AWS by default)
│   └── aws/                        # AWS-specific configs (ECR, RDS, etc.)
│
├── docs/                           # 16 architecture + ops guides (see below)
├── tests/                          # pytest suite (unit + integration with testcontainers)
├── Dockerfile.enterprise           # Production container image
├── pyproject.toml                  # name = "axon-enterprise", version = "1.3.0"
├── STRUCTURE.md                    # Detailed folder map
└── LICENSE.commercial              # Bemarking AI proprietary license
```

## Installation

```bash
pip install axon-enterprise[all]
# pulls in axon-lang>=1.5.1 automatically
```

Optional extras: `[aws]`, `[gcp]`, `[datadog]`, `[stripe]`, `[dev]`. See `pyproject.toml`.

## Quick start

### Local development (Docker Compose)

```bash
cd infrastructure/docker
docker-compose up -d
```

Services:

- **Axon server**: http://localhost:8000
- **PostgreSQL**: `localhost:5432`
- **Redis**: `localhost:6379`
- **pgAdmin**: http://localhost:5050

Run database migrations:

```bash
alembic upgrade head
```

### Production (Kubernetes)

```bash
# Prerequisites — cert-manager for TLS
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml

# Deploy axon-enterprise
kubectl apply -f infrastructure/kubernetes/
```

### Infrastructure as Code (Terraform / AWS)

```bash
cd infrastructure/terraform
terraform init
terraform plan -var-file=production.tfvars
terraform apply -var-file=production.tfvars
```

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the full deployment matrix.

## Usage examples

### RBAC

```python
from axon_enterprise.rbac import RBACService

rbac = RBACService(session)
developer = await rbac.get_role_by_name("developer")
deploy_perm = await rbac.create_permission("flow", "deploy", "Deploy flows")
await rbac.grant_permission(developer.id, deploy_perm.id)
allowed = await rbac.check_permission(user_id, "flow", "deploy")
```

### SSO (SAML 2.0)

```python
from axon_enterprise.sso import SAMLProvider

saml = SAMLProvider(config)
login_url = await saml.initiate_sso(tenant_id="acme")
user_data = await saml.handle_assertion(saml_response)
```

### Audit logging

```python
from axon_enterprise.audit import AuditLogger, EventType

audit = AuditLogger(session)
await audit.log_event(
    event_type=EventType.FLOW_DEPLOY,
    actor_email="alice@example.com",
    resource_type="flow",
    resource_id=flow_id,
    metadata={"version": "v3"},
)
```

### Usage metering & billing

```python
from axon_enterprise.metering import MeteringCollector

collector = MeteringCollector(session)
await collector.record_flow_execution(tenant_id, flow_id)
await collector.record_llm_tokens(tenant_id, tokens_in=1500, tokens_out=500)

record = await collector.create_billing_record(tenant_id, period_start, period_end)
# → emits a Stripe-compatible invoice draft
```

### Typed channels on the Rust runtime (NEW in v1.3.0)

```python
# Compile-time: declarative channel + producer/consumer
# (axon-lang surface — works on both Python and Rust runtimes)
from axon import Lexer, Parser, IRGenerator

source = """
shield PublicBroker { compliance: PCI_DSS }

channel OrdersCreated {
    message: Order
    qos: at_least_once
    lifetime: affine
    shield: PublicBroker
}

flow create_order(o: Order) -> () {
    emit OrdersCreated(o)
    publish OrdersCreated within PublicBroker
}
"""

ir = IRGenerator().generate(Parser(Lexer(source).tokenize()).parse())

# Runtime (Python — TypedEventBus reference):
from axon.runtime.channels.typed import TypedEventBus
bus = TypedEventBus.from_ir_program(ir)
await bus.emit("OrdersCreated", order_payload)
cap = await bus.publish("OrdersCreated", shield="PublicBroker")
handle = await bus.discover(cap)
```

For the Rust runtime equivalent, the platform's HTTP layer routes execution to `axon-lang`'s native `axon::runtime::channels::typed::TypedEventBus` with byte-identical guarantees. See [axon-lang on crates.io](https://crates.io/crates/axon-lang).

## Documentation

| Doc | Topic |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System design, module boundaries, request lifecycle |
| [`docs/IDENTITY.md`](docs/IDENTITY.md) | Users, password security, MFA |
| [`docs/RBAC.md`](docs/RBAC.md) | Role-based access control |
| [`docs/SSO.md`](docs/SSO.md) | Single sign-on (SAML / OAuth / OIDC) |
| [`docs/JWT.md`](docs/JWT.md) | JWT signing, JWKS, key rotation |
| [`docs/AUDIT.md`](docs/AUDIT.md) | Immutable audit trail + canonical hashing |
| [`docs/COMPLIANCE.md`](docs/COMPLIANCE.md) | Regulatory frameworks + residency middleware |
| [`docs/SECRETS.md`](docs/SECRETS.md) | Tenant secrets store + cloud adapters |
| [`docs/METERING.md`](docs/METERING.md) | Usage tracking + billing pipeline |
| [`docs/OBSERVABILITY.md`](docs/OBSERVABILITY.md) | Prometheus + OpenTelemetry + structlog |
| [`docs/ADMIN_API_AND_CLI.md`](docs/ADMIN_API_AND_CLI.md) | Operator surface (HTTP + CLI) |
| [`docs/PORTAL_API.md`](docs/PORTAL_API.md) | Tenant-facing portal endpoints |
| [`docs/DATABASE.md`](docs/DATABASE.md) | Postgres schema + Alembic migrations |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Docker / K8s / Terraform |
| [`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md) | Security review (last: v1.2.0) |
| [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) | STRIDE + adversarial scenarios |

## License

**Commercial License** — Bemarking AI S.A.S. proprietary software. All rights reserved. See [`LICENSE.commercial`](LICENSE.commercial).

## Support

- **Email**: support@bemarking.com.co
- **Docs portal**: https://docs.bemarking.com/enterprise

## Cross-references

- Open-source core: https://github.com/Bemarking/axon-lang
- `axon-lang` on PyPI: https://pypi.org/project/axon-lang/
- `axon-lang` on crates.io: https://crates.io/crates/axon-lang

---

**Version:** 1.3.0
**Last Updated:** 2026-04-30
**Status:** Production
