# Deployment Guide

## Quick Start (Docker Compose)

For development and testing:

```bash
cd infrastructure/docker
docker-compose up -d
```

Access:
- Axon Server: http://localhost:8000
- pgAdmin: http://localhost:5050

## Production Deployment (Kubernetes)

### Prerequisites
- Kubernetes 1.24+
- kubectl configured
- Cert-manager installed

### Deploy

```bash
kubectl apply -f infrastructure/kubernetes/
```

### Configuration

Edit `infrastructure/kubernetes/configmap.yaml`:

```yaml
AXON_RBAC_ENABLED: "true"
AXON_SSO_PROVIDER: "saml"
AXON_SSO_SAML_IDP_URL: "https://idp.example.com"
AXON_AUDIT_ENABLED: "true"
AXON_METERING_ENABLED: "true"
DATABASE_URL: "postgresql://user:pass@postgres:5432/axon"
```

### Secrets

Create secrets for sensitive data:

```bash
kubectl create secret generic axon-enterprise-secrets \
  --from-literal=saml-certificate=<cert> \
  --from-literal=saml-private-key=<key> \
  --from-literal=sso-client-secret=<secret>
```

## Infrastructure-as-Code (Terraform)

For cloud deployments (AWS/GCP/Azure):

```bash
cd infrastructure/terraform
terraform init
terraform plan -out=plan.tfplan
terraform apply plan.tfplan
```

Configure in `terraform.tfvars`:
```hcl
environment = "prod"
region      = "us-east-1"
instance_type = "t3.large"
postgres_version = "16"
backup_retention_days = 30
```

## Environment Variables

### Core
- `DATABASE_URL` — PostgreSQL connection string
- `REDIS_URL` — Redis connection string
- `LOG_LEVEL` — info, debug, warn, error

### RBAC
- `AXON_RBAC_ENABLED` — Enable RBAC (default: true)

### SSO
- `AXON_SSO_PROVIDER` — saml, oauth, oidc
- `AXON_SSO_SAML_IDP_URL` — SAML IdP endpoint
- `AXON_SSO_SAML_CERTIFICATE` — SAML certificate

### Audit
- `AXON_AUDIT_ENABLED` — Enable audit logging (default: true)
- `AXON_AUDIT_RETENTION_DAYS` — Days to retain logs (default: 730)

### Metering
- `AXON_METERING_ENABLED` — Enable metering (default: true)
- `AXON_BILLING_STRIPE_KEY` — Stripe API key (if using Stripe)

## Database Migrations

Migrations run automatically on server startup.

To manually run:

```bash
alembic upgrade head
```

To create new migration:

```bash
alembic revision --autogenerate -m "Add new table"
alembic upgrade head
```

## Health Checks

Kubernetes uses liveness and readiness probes:

```bash
# Liveness probe
curl http://localhost:8000/health

# Readiness probe
curl http://localhost:8000/ready
```

## Scaling

Horizontal scaling considerations:

1. **Stateless servers**: All state in PostgreSQL/Redis
2. **Session affinity**: Not required
3. **Database**: Single PostgreSQL with replication
4. **Redis**: Redis Cluster for high availability

### Example Kubernetes HPA

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: axon-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: axon-server
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

## Monitoring

### Prometheus Metrics

Exposed on `/metrics`:
- `axon_flow_executions_total` — Total flow executions
- `axon_llm_tokens_total` — Total tokens consumed
- `axon_api_latency_ms` — API latency
- `axon_database_connections` — Active DB connections

### Logging

Structured JSON logging to stdout:

```bash
docker logs axon-server | jq '.'
```

Export to logging service (DataDog, CloudWatch, etc.)

## Backup & Recovery

### Database Backup

```bash
# Manual backup
pg_dump postgresql://user:pass@localhost/axon > backup.sql

# Restore
psql postgresql://user:pass@localhost/axon < backup.sql
```

### Kubernetes Backup

Use Velero for cluster backups:

```bash
velero backup create axon-backup
velero restore create --from-backup axon-backup
```

## Troubleshooting

### Server won't start
- Check `DATABASE_URL` is valid
- Verify PostgreSQL is running: `psql $DATABASE_URL -c "SELECT 1"`
- Check logs: `docker logs axon-server`

### High latency
- Check database query performance: `EXPLAIN ANALYZE`
- Monitor Redis: `redis-cli INFO`
- Scale horizontally: add more Axon pods

### Audit logs missing
- Verify `AXON_AUDIT_ENABLED=true`
- Check database: `SELECT COUNT(*) FROM audit_events`

### SSO not working
- Validate SAML certificate: `openssl x509 -in cert.pem -text -noout`
- Check IdP connectivity: `curl $IDP_URL`
- Review logs for SAML validation errors
