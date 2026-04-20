# Example: provision a sample tenant using the Axon Enterprise tenant module.
#
# Run from the root infrastructure/terraform/ directory:
#   terraform workspace new example-tenant  (optional: per-tenant workspace)
#   terraform apply -target=module.tenant_example
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

module "tenant_example" {
  source = "../"

  tenant_id    = "example-tenant"
  tenant_name  = "Example Tenant"
  plan         = "enterprise"
  environment  = "prod"
  project_name = "axon"
  aws_region   = "us-east-1"

  # Provision all five standard providers
  providers_to_provision = ["anthropic", "openai", "gemini", "openrouter", "groq"]

  tags = {
    CustomerContact = "ops@example.com"
    SLATier         = "enterprise"
  }
}

output "example_tenant_secret_arns" {
  description = "SM ARNs for all tenant LLM secrets"
  value       = module.tenant_example.secret_arns
  sensitive   = true
}

output "example_tenant_secret_prefix" {
  description = "SM path prefix for the example tenant"
  value       = module.tenant_example.tenant_secret_prefix
}
