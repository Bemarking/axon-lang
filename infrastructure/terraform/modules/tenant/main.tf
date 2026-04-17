# Axon Enterprise — Per-Tenant AWS Secrets Manager Provisioning
#
# Creates one SM secret per (tenant, provider) pair following the path
# convention expected by TenantSecretsClient (M3):
#
#   axon/tenants/{tenant_id}/{provider}_api_key
#
# Secrets are initialized with an empty placeholder. The actual API keys
# are populated manually by the tenant or via the onboard_tenant.sh script.
# Rotation is out of scope for V1 (HashiCorp Vault considered for V2).

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }
}

locals {
  # Canonical secret path expected by TenantSecretsClient.get_api_key()
  secret_path = "axon/tenants/${var.tenant_id}"

  common_tags = merge(var.tags, {
    TenantId    = var.tenant_id
    TenantName  = var.tenant_name
    TenantPlan  = var.plan
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

# One SM secret per provider — created for every entry in providers_to_provision.
resource "aws_secretsmanager_secret" "tenant_provider_key" {
  for_each = var.providers_to_provision

  name                    = "${local.secret_path}/${each.key}_api_key"
  description             = "LLM API key for tenant '${var.tenant_id}' — provider '${each.key}'"
  recovery_window_in_days = var.recovery_window_in_days

  tags = merge(local.common_tags, {
    Provider = each.key
    Name     = "axon-tenant-${var.tenant_id}-${each.key}-api-key"
  })
}

# Initialize every secret with an empty placeholder.
# Actual keys are set by the tenant (self-serve) or by onboard_tenant.sh.
resource "aws_secretsmanager_secret_version" "tenant_provider_key" {
  for_each = var.providers_to_provision

  secret_id     = aws_secretsmanager_secret.tenant_provider_key[each.key].id
  secret_string = ""

  # Allow external updates (e.g. the tenant setting their real key) without
  # triggering a Terraform plan diff. lifecycle ignores the value after creation.
  lifecycle {
    ignore_changes = [secret_string]
  }
}
