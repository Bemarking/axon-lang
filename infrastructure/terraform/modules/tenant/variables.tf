variable "tenant_id" {
  description = "Unique tenant identifier (slug format, e.g. 'example-tenant')"
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$", var.tenant_id))
    error_message = "tenant_id must be lowercase alphanumeric with hyphens, 2–63 chars."
  }
}

variable "tenant_name" {
  description = "Human-readable tenant name (stored as SM tag)"
  type        = string
}

variable "plan" {
  description = "Subscription plan: starter | pro | enterprise"
  type        = string
  default     = "starter"

  validation {
    condition     = contains(["starter", "pro", "enterprise"], var.plan)
    error_message = "plan must be starter, pro, or enterprise."
  }
}

variable "providers_to_provision" {
  description = "List of LLM provider keys to create SM paths for"
  type        = set(string)
  default     = ["anthropic", "openai", "gemini", "openrouter", "groq"]
}

variable "environment" {
  description = "Deployment environment (prod | staging | dev)"
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "Project name prefix used for naming AWS resources"
  type        = string
  default     = "axon"
}

variable "aws_region" {
  description = "AWS region where secrets are created"
  type        = string
  default     = "us-east-1"
}

variable "recovery_window_in_days" {
  description = "SM secret recovery window (0 = force-delete, 7–30 = soft-delete)"
  type        = number
  default     = 7
}

variable "tags" {
  description = "Additional AWS tags to apply to all tenant resources"
  type        = map(string)
  default     = {}
}
