output "alb_dns_name" {
  description = "DNS name del Application Load Balancer (acceso público)"
  value       = aws_lb.axon.dns_name
}

output "alb_url" {
  description = "URL pública del ALB para acceder al servidor"
  value       = "http://${aws_lb.axon.dns_name}"
}

output "alb_arn" {
  description = "ARN del Application Load Balancer"
  value       = aws_lb.axon.arn
}

output "ecr_rust_server_url" {
  description = "URL del repositorio ECR para la imagen axon-server (Rust)"
  value       = aws_ecr_repository.axon_server.repository_url
}

output "ecr_enterprise_url" {
  description = "URL del repositorio ECR para la imagen axon-enterprise (Python)"
  value       = aws_ecr_repository.axon_enterprise.repository_url
}

output "rds_endpoint" {
  description = "Endpoint del RDS PostgreSQL (accesible solo desde VPC)"
  value       = aws_db_instance.axon.endpoint
  sensitive   = true
}

output "rds_address" {
  description = "Dirección IP del RDS (hostname sin puerto)"
  value       = aws_db_instance.axon.address
  sensitive   = true
}

output "rds_port" {
  description = "Puerto del RDS PostgreSQL"
  value       = aws_db_instance.axon.port
}

output "rds_database_name" {
  description = "Nombre de la base de datos PostgreSQL"
  value       = aws_db_instance.axon.db_name
}

output "rds_username" {
  description = "Usuario master de RDS"
  value       = aws_db_instance.axon.username
  sensitive   = true
}

output "ecs_cluster_name" {
  description = "Nombre del cluster ECS"
  value       = aws_ecs_cluster.axon.name
}

output "ecs_cluster_arn" {
  description = "ARN del cluster ECS"
  value       = aws_ecs_cluster.axon.arn
}

output "ecs_service_name" {
  description = "Nombre del servicio ECS"
  value       = aws_ecs_service.axon.name
}

output "ecs_task_definition_arn" {
  description = "ARN de la definición del task ECS"
  value       = aws_ecs_task_definition.axon.arn
}

output "vpc_id" {
  description = "ID de la VPC"
  value       = aws_vpc.axon.id
}

output "vpc_cidr" {
  description = "CIDR block de la VPC"
  value       = aws_vpc.axon.cidr_block
}

output "public_subnet_ids" {
  description = "IDs de las subnets públicas"
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "IDs de las subnets privadas"
  value       = aws_subnet.private[*].id
}

output "nat_gateway_ip" {
  description = "Dirección IP pública del NAT Gateway"
  value       = aws_eip.nat.public_ip
}

output "secrets_manager_database_url_arn" {
  description = "ARN del secret DATABASE_URL en Secrets Manager"
  value       = aws_secretsmanager_secret.database_url.arn
}

output "secrets_manager_auth_token_arn" {
  description = "ARN del secret AXON_AUTH_TOKEN en Secrets Manager"
  value       = aws_secretsmanager_secret.axon_auth_token.arn
}

output "aws_account_id" {
  description = "ID de la cuenta AWS"
  value       = data.aws_caller_identity.current.account_id
}

output "cloudwatch_log_group_rust" {
  description = "Nombre del CloudWatch Log Group para axon-server"
  value       = aws_cloudwatch_log_group.axon_server.name
}

output "cloudwatch_log_group_enterprise" {
  description = "Nombre del CloudWatch Log Group para axon-enterprise"
  value       = aws_cloudwatch_log_group.axon_enterprise.name
}
