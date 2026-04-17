output "secret_arns" {
  description = "Map of provider → SM secret ARN for this tenant. Use to grant IAM access."
  value = {
    for provider, secret in aws_secretsmanager_secret.tenant_provider_key :
    provider => secret.arn
  }
}

output "secret_paths" {
  description = "Map of provider → SM secret path (name) for this tenant."
  value = {
    for provider, secret in aws_secretsmanager_secret.tenant_provider_key :
    provider => secret.name
  }
}

output "tenant_id" {
  description = "The tenant_id this module was invoked for."
  value       = var.tenant_id
}

output "tenant_secret_prefix" {
  description = "SM path prefix for all secrets of this tenant."
  value       = "axon/tenants/${var.tenant_id}"
}
