# Axon Enterprise — Folder Structure Overview

This document describes the organization of the axon-enterprise repository.

## Directory Hierarchy

```
axon-enterprise/
├── axon_enterprise/                    # Main Python package (enterprise features)
│   ├── __init__.py                     # Package initialization
│   │
│   ├── rbac/                           # Role-Based Access Control
│   │   ├── __init__.py
│   │   ├── models.py                   # Role, Permission, RoleHierarchy
│   │   ├── service.py                  # RBACService with CRUD operations
│   │   └── middleware.py               # HTTP middleware for permission checks
│   │
│   ├── sso/                            # Single Sign-On (Authentication)
│   │   ├── __init__.py
│   │   ├── saml.py                     # SAML 2.0 provider (Okta, Azure AD, etc.)
│   │   ├── oauth.py                    # OAuth 2.0 provider (generic)
│   │   └── oidc.py                     # OpenID Connect provider (Google, Microsoft)
│   │
│   ├── audit/                          # Audit Logging & Compliance
│   │   ├── __init__.py
│   │   ├── events.py                   # AuditEvent model, EventType enum
│   │   └── logger.py                   # AuditLogger service
│   │
│   ├── metering/                       # Usage Metering & Billing
│   │   ├── __init__.py
│   │   ├── models.py                   # UsageMetric, BillingRecord
│   │   └── collector.py                # MeteringCollector service
│   │
│   ├── studio/                         # Visual Debugger
│   │   ├── __init__.py
│   │   └── debugger.py                 # FlowDebugger with breakpoints/snapshots
│   │
│   └── observability/                  # Advanced Observability & Metrics
│       ├── __init__.py
│       └── metrics.py                  # MetricsCollector (counters, gauges, histograms)
│
├── infrastructure/                     # Deployment & Infrastructure
│   ├── kubernetes/                     # Kubernetes manifests for production
│   │   ├── deployment.yaml             # Axon server deployment
│   │   ├── service.yaml                # Kubernetes service
│   │   ├── ingress.yaml                # Ingress for external access
│   │   ├── postgres-statefulset.yaml   # PostgreSQL database
│   │   ├── configmap.yaml              # Environment configuration
│   │   ├── secrets-template.yaml       # Secrets template (RBAC, SSO keys)
│   │   ├── persistent-volumes.yaml     # Storage configuration
│   │   ├── kustomization.yaml          # Kustomize overlays
│   │   └── README.md                   # Kubernetes deployment guide
│   │
│   ├── terraform/                      # Infrastructure-as-Code (AWS/GCP/Azure)
│   │   ├── main.tf                     # Main configuration
│   │   ├── variables.tf                # Variable definitions
│   │   ├── outputs.tf                  # Outputs
│   │   ├── vpc.tf                      # VPC/networking
│   │   ├── database.tf                 # PostgreSQL RDS
│   │   ├── compute.tf                  # Compute instances
│   │   ├── iam.tf                      # IAM roles & policies
│   │   ├── terraform.tfvars.example    # Example variables
│   │   └── README.md                   # Terraform deployment guide
│   │
│   └── docker/                         # Docker & Docker Compose
│       ├── docker-compose.yml          # Multi-container setup (dev/test)
│       ├── Dockerfile                  # Axon server image
│       └── README.md                   # Docker deployment guide
│
├── tests/                              # Test suite
│   ├── test_rbac.py                    # RBAC unit tests
│   ├── test_sso.py                     # SSO provider tests
│   ├── test_audit.py                   # Audit logging tests
│   ├── test_metering.py                # Metering & billing tests
│   ├── test_studio.py                  # Debugger tests
│   ├── test_observability.py           # Metrics tests
│   └── enterprise_integration/         # Integration tests
│       ├── test_end_to_end.py
│       ├── test_rbac_sso_flow.py       # RBAC + SSO integration
│       └── test_metering_billing.py    # Metering + billing flow
│
├── docs/                               # Documentation
│   ├── ARCHITECTURE.md                 # System design & module overview
│   ├── RBAC.md                         # RBAC concepts & usage guide
│   ├── SSO.md                          # SSO configuration & setup
│   ├── AUDIT.md                        # Audit logging & compliance
│   ├── METERING.md                     # Metering, billing, pricing
│   └── DEPLOYMENT.md                   # Deployment guides (Docker, K8s, Terraform)
│
├── pyproject.toml                      # Python project configuration & dependencies
├── README.md                           # Main project README
├── STRUCTURE.md                        # This file — folder structure guide
└── LICENSE.commercial                  # Commercial license agreement
```

## Module Responsibilities

### `axon_enterprise.rbac`
**Role-Based Access Control**
- Manages roles, permissions, and hierarchies
- Enforces access control at handler level
- Tracks permission assignments
- Supports custom roles beyond built-in ones

### `axon_enterprise.sso`
**Single Sign-On**
- Integrates with enterprise identity providers
- Supports SAML 2.0, OAuth 2.0, OpenID Connect
- Handles authentication and user provisioning
- Manages session lifecycle

### `axon_enterprise.audit`
**Audit Logging**
- Records all security-relevant operations
- Generates immutable audit trails
- Supports compliance reporting (GDPR, SOC 2, HIPAA)
- Queries and filtering for forensics

### `axon_enterprise.metering`
**Usage Tracking & Billing**
- Collects usage metrics (executions, tokens, storage)
- Aggregates metrics for billing periods
- Generates invoices
- Integrates with payment processors (Stripe, custom)

### `axon_enterprise.studio`
**Visual Debugger**
- Sets and manages breakpoints
- Captures execution snapshots
- Provides step-into/step-over controls
- Inspects variables and stack traces

### `axon_enterprise.observability`
**Advanced Metrics**
- Collects counters, gauges, histograms
- Exports to Prometheus/Grafana
- Tracks flow latency, token usage, errors
- Feeds into monitoring dashboards

## Synchronization with axon-lang

This repository always stays **ahead** of the public `axon-lang`:

```
axon-lang (public)
    ↓ (merge)
axon-enterprise (private)
    ↓ (add features)
axon-enterprise + RBAC + SSO + Audit + Metering
```

To sync from upstream:
```bash
git remote add upstream git@github.com:Bemarking/axon-lang.git
git fetch upstream
git merge upstream/master
```

## Development Workflow

1. **Feature development**: Create features in `axon_enterprise/` modules
2. **Testing**: Unit tests in `tests/`, integration tests in `tests/enterprise_integration/`
3. **Documentation**: Update `docs/` modules as needed
4. **Deployment**: Update infrastructure in `infrastructure/` folder
5. **Commit**: Use `feat(enterprise):` prefix for commits with enterprise features
6. **Push**: Use `push-smart.sh` or `git push enterprise master`

## Best Practices

- **Separation of Concerns**: Each module handles one enterprise feature (RBAC, SSO, etc.)
- **Stateless Design**: All state lives in PostgreSQL, not in-memory
- **Configuration**: Use environment variables, not hardcoded values
- **Logging**: Use structured logging for audit trails
- **Testing**: Integration tests before production deployment
- **Documentation**: Keep docs in sync with code changes

## Key Differences from axon-lang

| Aspect | axon-lang | axon-enterprise |
|--------|-----------|-----------------|
| **Repository** | Public (GitHub) | Private (GitHub) |
| **License** | MIT | Commercial |
| **RBAC** | No | Yes (module) |
| **SSO** | No | Yes (SAML/OAuth/OIDC) |
| **Audit** | Basic logging | Full audit trail |
| **Metering** | No | Yes (multi-tenant billing) |
| **Studio** | No | Yes (visual debugger) |
| **Advanced Metrics** | No | Yes (Prometheus) |
| **Multi-tenant** | Single-tenant | Multi-tenant ready |
| **Compliance** | Basic | GDPR/SOC2/HIPAA ready |

---

**Version:** 1.0.0  
**Last Updated:** 2026-04-15
