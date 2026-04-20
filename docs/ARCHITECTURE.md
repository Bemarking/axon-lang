# Axon Enterprise Architecture

## Overview

Axon Enterprise is the commercial edition built on top of Axon open source core. It adds:

1. **RBAC** — Role-Based Access Control with hierarchies
2. **SSO** — Single Sign-On (SAML 2.0, OAuth 2.0, OpenID Connect)
3. **Audit** — Compliance audit logging for all operations
4. **Metering** — Usage tracking and billing integration
5. **Studio** — Visual debugger for flow development
6. **Observability** — Advanced metrics and monitoring

## Module Structure

```
axon_enterprise/
├── rbac/           # Role-based access control
├── sso/            # Single sign-on providers
├── audit/          # Audit logging & compliance
├── metering/       # Usage metering & billing
├── studio/         # Visual debugger
└── observability/  # Metrics & monitoring
```

## Integration with Core

Axon Enterprise:
- Depends on `axon-lang` as core
- Syncs from public repository regularly
- Adds enterprise features as layers on top
- Maintains same runtime and API surface

## Database Schema

PostgreSQL tables:

- `roles` — RBAC role definitions
- `permissions` — Granular permissions
- `role_hierarchies` — Role inheritance
- `audit_events` — Audit log entries
- `usage_metrics` — Metering data points
- `billing_records` — Customer invoices
- `sso_sessions` — SSO session tracking
- `debugger_breakpoints` — Debugger state

## Deployment

- **Docker Compose**: Single-machine development
- **Kubernetes**: Multi-zone production
- **Terraform**: Infrastructure-as-Code (AWS/GCP/Azure)

## Security

- TLS 1.3 for all connections
- SAML 2.0 certificate validation
- OAuth 2.0 PKCE for mobile
- JWT tokens with short expiry
- Audit logging of all sensitive operations
- Database encryption at rest (Terraform)
