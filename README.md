# Axon Enterprise Edition

**Axon v1.0.0 — Commercial Edition with RBAC, SSO, Audit, and Metering**

Primer Lenguaje de Programación AI Native Cognitivo Formal. Enterprise edition with production-grade security, compliance, and billing features for SaaS deployments.

## Key Features

### 🔐 RBAC (Role-Based Access Control)
- Hierarchical role management
- Fine-grained permissions (resource:action)
- Built-in roles: Admin, Developer, Viewer
- Custom role creation

### 🔑 SSO (Single Sign-On)
- SAML 2.0 support (Okta, Azure AD, Ping)
- OAuth 2.0 for generic providers
- OpenID Connect (Google, Microsoft, Auth0)
- Secure session management with JWT

### 📊 Audit Logging & Compliance
- Immutable audit trail for all operations
- GDPR, SOC 2, HIPAA compliance ready
- Granular event tracking
- Compliance reporting

### 💰 Usage Metering & Billing
- Flow execution tracking
- LLM token metering
- Storage and compute hours
- Billing integration (Stripe, custom)
- Multi-tenant cost allocation

### 🐛 Studio (Visual Debugger)
- Step-into/step-over debugging
- Breakpoint management
- Real-time state inspection
- Flow execution snapshots

### 📈 Advanced Observability
- Prometheus metrics export
- Distributed tracing
- Custom metrics collection
- Performance monitoring

## Folder Structure

```
axon-enterprise/
├── axon_enterprise/              # Python package
│   ├── __init__.py
│   ├── rbac/                    # Role-Based Access Control
│   │   ├── models.py            # Role, Permission, RoleHierarchy
│   │   ├── service.py           # RBACService
│   │   └── middleware.py
│   ├── sso/                     # Single Sign-On
│   │   ├── saml.py              # SAML 2.0 provider
│   │   ├── oauth.py             # OAuth 2.0 provider
│   │   └── oidc.py              # OpenID Connect provider
│   ├── audit/                   # Audit Logging
│   │   ├── events.py            # AuditEvent, EventType
│   │   └── logger.py            # AuditLogger service
│   ├── metering/                # Usage Metering & Billing
│   │   ├── models.py            # UsageMetric, BillingRecord
│   │   └── collector.py         # MeteringCollector service
│   ├── studio/                  # Visual Debugger
│   │   └── debugger.py          # FlowDebugger
│   └── observability/           # Advanced Observability
│       └── metrics.py           # MetricsCollector
├── infrastructure/
│   ├── kubernetes/              # Kubernetes manifests
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   ├── configmap.yaml
│   │   └── README.md
│   ├── terraform/               # Infrastructure as Code
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── README.md
│   └── docker/
│       ├── docker-compose.yml
│       └── Dockerfile
├── tests/
│   ├── test_rbac.py
│   ├── test_sso.py
│   ├── test_audit.py
│   ├── test_metering.py
│   └── enterprise_integration/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── RBAC.md
│   ├── SSO.md
│   ├── AUDIT.md
│   ├── METERING.md
│   └── DEPLOYMENT.md
├── pyproject.toml
└── LICENSE.commercial
```

## Quick Start

### Development (Docker Compose)

```bash
cd infrastructure/docker
docker-compose up -d
```

Then:
- Axon Server: http://localhost:8000
- PostgreSQL: localhost:5432
- Redis: localhost:6379
- pgAdmin: http://localhost:5050

### Production (Kubernetes)

```bash
# Prerequisites
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml

# Deploy Axon Enterprise
kubectl apply -f infrastructure/kubernetes/
```

### Installation

```bash
pip install axon-enterprise[all]
```

## Usage Examples

### RBAC

```python
from axon_enterprise.rbac import RBACService

rbac = RBACService()

# Get built-in developer role
developer = rbac.get_role_by_name("developer")

# Create custom permission
deploy_perm = rbac.create_permission("flow", "deploy", "Deploy flows")

# Grant permission
rbac.grant_permission(developer.id, deploy_perm.id)

# Check permission
has_access = rbac.check_permission(developer.id, deploy_perm.id)
```

### SSO Integration

```python
from axon_enterprise.sso import SAMLProvider

saml = SAMLProvider(config)
login_url = await saml.initiate_sso()
user_data = await saml.handle_assertion(saml_response)
```

### Audit Logging

```python
from axon_enterprise.audit import AuditLogger, EventType

audit = AuditLogger()
audit.log_event(
    event_type=EventType.FLOW_DEPLOY,
    user_email="alice@example.com",
    resource_type="flow",
    resource_id=flow_id,
)
```

### Usage Metering

```python
from axon_enterprise.metering import MeteringCollector, MetricType

collector = MeteringCollector()
collector.record_flow_execution(org_id, flow_id)
collector.record_llm_tokens(org_id, tokens_in=1500, tokens_out=500)

# Generate billing
record = collector.create_billing_record(org_id, start, end)
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — System design and module structure
- [RBAC Guide](docs/RBAC.md) — Role-based access control
- [SSO Setup](docs/SSO.md) — Single sign-on configuration
- [Audit Logging](docs/AUDIT.md) — Compliance and audit trails
- [Metering & Billing](docs/METERING.md) — Usage tracking and invoicing
- [Deployment](docs/DEPLOYMENT.md) — Docker, Kubernetes, Terraform

## License

**Commercial License**

This is Bemarking AI S.A.S. proprietary software. All rights reserved.

See [LICENSE.commercial](LICENSE.commercial) for details.

## Support

For enterprise support and questions:
- Email: support@bemarking.com.co
- Docs: https://docs.bemarking.com/enterprise

---

**Version:** 1.0.0  
**Last Updated:** 2026-04-15  
**Status:** Production
