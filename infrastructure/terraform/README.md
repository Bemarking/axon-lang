# Terraform Infrastructure

Infrastructure-as-Code for Axon Enterprise deployment on AWS/GCP/Azure.

## Modules

- `vpc/` — Virtual Private Cloud setup
- `database/` — PostgreSQL RDS with backup
- `compute/` — Compute instances for Axon server
- `networking/` — Load balancer, security groups
- `iam/` — IAM roles for RBAC and service accounts
- `monitoring/` — CloudWatch/Datadog integration
- `storage/` — S3/GCS for audit logs and exports

## Usage

```bash
terraform init
terraform plan
terraform apply
```

## Variables

See `terraform.tfvars.example` for configuration:
- `environment` — dev, staging, prod
- `region` — AWS/GCP region
- `instance_type` — Compute instance size
- `postgres_version` — PostgreSQL version
- `backup_retention_days` — Backup retention period
