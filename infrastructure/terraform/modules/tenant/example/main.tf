# Example: provision Kivi KAS as the first Axon Enterprise tenant.
#
# Run from the root infrastructure/terraform/ directory:
#   terraform workspace new kivi-kas  (optional: per-tenant workspace)
#   terraform apply -target=module.tenant_kivi_kas
#
# Or inline in the root main.tf for a fully declarative multi-tenant inventory.

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

module "tenant_kivi_kas" {
  source = "../"

  tenant_id   = "kivi-kas"
  tenant_name = "Kivi KAS"
  plan        = "enterprise"
  environment = "prod"
  project_name = "axon"
  aws_region  = "us-east-1"

  # Provision all five standard providers
  providers_to_provision = ["anthropic", "openai", "gemini", "openrouter", "groq"]

  tags = {
    CustomerContact = "ops@kivi.com"
    SLATier         = "enterprise"
  }
}

output "kivi_kas_secret_arns" {
  description = "SM ARNs for all Kivi KAS LLM secrets"
  value       = module.tenant_kivi_kas.secret_arns
  sensitive   = true
}

output "kivi_kas_secret_prefix" {
  description = "SM path prefix for Kivi KAS"
  value       = module.tenant_kivi_kas.tenant_secret_prefix
}
