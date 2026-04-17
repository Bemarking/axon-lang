variable "aws_region" {
  description = "AWS region para todos los recursos"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Nombre del entorno (prod, staging, dev)"
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["prod", "staging", "dev"], var.environment)
    error_message = "El entorno debe ser prod, staging o dev."
  }
}

variable "project_name" {
  description = "Nombre del proyecto (prefijo para nombres de recursos)"
  type        = string
  default     = "axon"
}

# ============================================================================
# Configuración de recursos de compute (Fargate)
# ============================================================================

variable "rust_server_cpu" {
  description = "CPU units para el container Rust (1 vCPU = 1024 units)"
  type        = number
  default     = 1024  # 1 vCPU
}

variable "rust_server_memory_mb" {
  description = "Memoria en MB para el container Rust"
  type        = number
  default     = 2048  # 2 GB
}

variable "python_sidecar_cpu" {
  description = "CPU units para el sidecar Python (0.25 vCPU = 256 units)"
  type        = number
  default     = 256
}

variable "python_sidecar_memory_mb" {
  description = "Memoria en MB para el sidecar Python"
  type        = number
  default     = 512
}

# Task-level totals
# Fargate requiere que cpu/memory del task sea >= suma de containers
# Valores válidos de Fargate: 256, 512, 1024, 2048, 4096
variable "task_cpu" {
  description = "CPU total del task Fargate (debe ser >= suma de containers)"
  type        = number
  default     = 2048  # Válido en Fargate (1024 Rust + 256 Python + headroom)
}

variable "task_memory_mb" {
  description = "Memoria total del task Fargate (debe ser >= suma de containers)"
  type        = number
  default     = 4096  # Válido en Fargate (2048 Rust + 512 Python + headroom)
}

variable "ecs_desired_count" {
  description = "Número deseado de tasks ECS ejecutándose"
  type        = number
  default     = 2
}

# ============================================================================
# Configuración de RDS PostgreSQL
# ============================================================================

variable "rds_instance_class" {
  description = "Clase de instancia RDS. Actual: db.t3.micro (free tier). Upgrade a db.t3.small cuando se actualice el plan AWS."
  type        = string
  default     = "db.t3.micro"
  # M5 evaluation (PENDIENTE): db.t3.micro → db.t3.small cuando se active paid tier
  # Rationale: multi-tenant RLS adds per-row SET LOCAL calls on every transaction.
  # db.t3.micro (1 GB RAM) may show shared_buffer pressure under concurrent tenants.
  # db.t3.small (2 GB RAM) gives ~500 MB shared_buffers — target for early prod.
  # ACTION: upgrade AWS account plan, then change default to "db.t3.small".
  # Next threshold: db.t3.medium when active tenants > 20 or p99 latency > 200ms.
}

variable "rds_multi_az" {
  description = "Habilitar Multi-AZ en RDS. Requiere paid AWS tier. Mantener false en free tier."
  type        = bool
  default     = false
  # M5 evaluation (PENDIENTE): enable cuando se active paid tier
  # Rationale: Axon Enterprise SaaS must meet 99.9% uptime SLA for early adopters
  # (Kivi KAS). Single-AZ RDS has no failover; an AZ outage means full downtime.
  # Cost delta: ~$35/month for db.t3.small Multi-AZ vs $17/month single-AZ.
  # ACTION: set to true after upgrading AWS account and instance class.
}

variable "rds_allocated_storage_gb" {
  description = "Almacenamiento inicial de RDS en GB"
  type        = number
  default     = 20
}

variable "rds_max_allocated_storage_gb" {
  description = "Almacenamiento máximo autoscaling en RDS"
  type        = number
  default     = 100
}

variable "rds_db_name" {
  description = "Nombre de la base de datos PostgreSQL"
  type        = string
  default     = "axon"
}

variable "rds_username" {
  description = "Usuario master para acceder a RDS"
  type        = string
  default     = "axon_admin"
  sensitive   = true
}

variable "rds_backup_retention_days" {
  description = "Días para retener backups automáticos (Free Tier máximo: 1)"
  type        = number
  default     = 1
}

# ============================================================================
# Configuración de networking (VPC)
# ============================================================================

variable "vpc_cidr" {
  description = "CIDR block de la VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "enable_nat_gateway" {
  description = "Habilitar NAT Gateway para acceso outbound desde private subnets"
  type        = bool
  default     = true
}
