# Kubernetes Deployment

Kubernetes manifests for deploying Axon Enterprise edition.

## Structure

- `deployment.yaml` — Axon server deployment
- `service.yaml` — Kubernetes service configuration
- `ingress.yaml` — Ingress for external access
- `postgres-statefulset.yaml` — PostgreSQL stateful set
- `configmap.yaml` — Configuration for enterprise features
- `secrets-template.yaml` — Template for secrets (RBAC, SSO, billing keys)
- `persistent-volumes.yaml` — Persistent volume claims for data
- `kustomization.yaml` — Kustomize base for multi-environment deployments

## Prerequisites

- Kubernetes 1.24+
- kubectl configured
- PostgreSQL operator (or external PostgreSQL)
- Cert-manager for SSL

## Deployment

```bash
kubectl apply -f kubernetes/
```

## Configuration

See `configmap.yaml` for environment variables:
- `AXON_RBAC_ENABLED` — Enable RBAC
- `AXON_SSO_PROVIDER` — SSO provider (saml, oauth, oidc)
- `AXON_AUDIT_ENABLED` — Enable audit logging
- `AXON_METERING_ENABLED` — Enable usage metering
